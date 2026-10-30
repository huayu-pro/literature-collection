#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""下载计划生成器：消费 cnki_scan.py 产出的 html_whitelist.json / no_html.json。

背景：v1.3 里 html_whitelist.json 与 no_html.json 是零消费者的中间产物——
cnki_scan.py 写了它们，之后没有任何脚本读，G4 的通道选择全靠 agent 回看 JSON 手判，
判漏一篇就按错的通道白跑一趟（PDF 通道对无原版的文献必然失败）。
本脚本是它们的消费者：把「哪条走 HTML、哪条走 PDF、哪条没入口」落成一张可执行的计划表。

同时把 no_html.json 的条目接进「未获取全文」的原因链（v1.3 里这批条目在
未获取全文.md 里只能显示「未登记原因」）：写 raw/download_plan.csv 之外，
还写 raw/no_html_reasons.json 供 build_index.py 读取填补原因。

硬性纪律：只依据 cnki_scan 已记录的 has_html / has_pdf 判定；SKILL.md 硬规则 2 要求
「两次确认」——本脚本只认第一次（结果页），详情页二次确认的结果用 --confirm 传入，
不做任何猜测式补全。

用法：
    /usr/bin/python3 scripts/plan_download.py "<工作目录>" --json
    /usr/bin/python3 scripts/plan_download.py "<工作目录>" --records raw/records.json \
        --whitelist raw/html_whitelist.json --no-html raw/no_html.json
    /usr/bin/python3 scripts/plan_download.py "<工作目录>" --confirm detail_probe.json

退出码：0 成功；64 参数/文件错误；65 计划为空（无可用记录）。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

PLAN_COLUMNS = ["rid", "title", "channel", "url", "reason", "detail_confirmed"]
# 计划产物名（写进 raw/，供 G4 执行与 build_index 消费原因链）
PLAN_NAME = "download_plan.csv"
REASON_NAME = "no_html_reasons.json"

CHANNEL_HTML = "HTML"
CHANNEL_PDF = "PDF"
CHANNEL_NONE = "NONE"

# 与 reason_codes.py 的规范枚举保持一致（这里不 import，避免脚本目录被当包依赖；
# 值不匹配时 verify_delivery 的台账/原因 lint 会红）
REASON_NO_HTML = "no_html"
REASON_NO_PDF = "no_pdf"


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"JSON 解析失败（{p.name}）：{exc}", file=sys.stderr)
        sys.exit(64)


def as_records(data):
    if isinstance(data, dict):
        data = data.get("records") or data.get("rows") or []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def main():
    ap = argparse.ArgumentParser(description="按 HTML 白名单生成下载计划")
    ap.add_argument("workdir", help="运行时工作目录")
    ap.add_argument("--records", default="", help="默认 <workdir>/raw/records.json")
    ap.add_argument("--whitelist", default="", help="默认 <workdir>/raw/html_whitelist.json")
    ap.add_argument("--no-html", default="", help="默认 <workdir>/raw/no_html.json")
    ap.add_argument("--confirm", default="",
                    help="详情页二次确认结果 JSON：[{rid, has_html}] 或 {details:[...]}")
    ap.add_argument("--out", default="", help="计划输出路径，默认 <workdir>/raw/download_plan.csv")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser()
    if not wd.is_dir():
        print(f"工作目录不存在：{wd}", file=sys.stderr)
        sys.exit(64)
    raw = wd / "raw"

    rp = Path(args.records) if args.records else raw / "records.json"
    wp = Path(args.whitelist) if args.whitelist else raw / "html_whitelist.json"
    np = Path(args.no_html) if args.no_html else raw / "no_html.json"

    records = as_records(load_json(rp, None))
    if not records:
        # 退到 cnki_records.json：cnki_scan 单跑时 records.json 还没合并
        records = as_records(load_json(raw / "cnki_records.json", None))
    if not records:
        print(f"没有题录可用：{rp}（或 raw/cnki_records.json）", file=sys.stderr)
        sys.exit(65)

    whitelist = load_json(wp, None)
    no_html = load_json(np, None)
    if whitelist is None and no_html is None:
        print(f"没有白名单输入：{wp} 与 {np} 都不存在；先跑 cnki_scan.py", file=sys.stderr)
        sys.exit(64)

    html_rids = {str(r.get("rid") or "").strip() for r in as_records(whitelist)}
    whitelist_url = {str(r.get("rid") or "").strip(): (r.get("href") or r.get("url") or "")
                     for r in as_records(whitelist)}
    no_html_url = {str(r.get("rid") or "").strip(): (r.get("href") or r.get("url") or "")
                   for r in as_records(no_html)}

    # 详情页二次确认：只接受「显式声明无 HTML」的去升级，不接受反向（无 HTML → HTML）
    confirm = {}
    if args.confirm:
        for r in as_records(load_json(args.confirm, [])):
            rid = str(r.get("rid") or "").strip()
            if rid:
                confirm[rid] = bool(r.get("has_html"))

    rows, reason_rows = [], []
    for rec in records:
        rid = str(rec.get("rid") or "").strip()
        if not rid:
            continue
        url = str(rec.get("url") or "").strip()
        has_html = bool(rec.get("has_html"))
        has_pdf = bool(rec.get("has_pdf"))
        if rid not in html_rids and rid not in no_html_url and not has_html:
            # whitelist/no_html 都是空的且记录没标 has_html：按 SKILL.md 口径标待确认，不猜
            channel, reason = CHANNEL_NONE, REASON_NO_HTML
            confirmed = ""
        elif has_html or rid in html_rids:
            if confirm.get(rid) is False:
                channel, reason = CHANNEL_PDF if has_pdf else CHANNEL_NONE, (
                    "" if has_pdf else REASON_NO_PDF)
                confirmed = "详情页确认无 HTML"
            else:
                channel, reason = CHANNEL_HTML, ""
                confirmed = "已确认" if rid in confirm else "结果页（待详情页二次确认）"
        elif has_pdf:
            channel, reason = CHANNEL_PDF, ""
            confirmed = "结果页标「原版阅读」"
        else:
            channel, reason = CHANNEL_NONE, REASON_NO_HTML
            confirmed = "结果页两次均无入口"
        rows.append({
            "rid": rid,
            "title": str(rec.get("title") or ""),
            "channel": channel,
            "url": url or whitelist_url.get(rid, "") or no_html_url.get(rid, ""),
            "reason": reason,
            "detail_confirmed": confirmed,
        })
        if channel == CHANNEL_NONE:
            reason_rows.append({"rid": rid, "reason": reason,
                                "detail": confirmed or "结果页无 HTML 入口"})

    if not rows:
        print("没有可计划的记录", file=sys.stderr)
        sys.exit(65)

    raw.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else raw / PLAN_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PLAN_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    rf = raw / REASON_NAME
    rf.write_text(json.dumps(reason_rows, ensure_ascii=False, indent=1), encoding="utf-8")

    counts = {c: sum(1 for r in rows if r["channel"] == c) for c in
              (CHANNEL_HTML, CHANNEL_PDF, CHANNEL_NONE)}
    stats = {"planned": len(rows), "html": counts[CHANNEL_HTML], "pdf": counts[CHANNEL_PDF],
             "none": counts[CHANNEL_NONE], "plan": str(out), "reasons": str(rf),
             "no_html_reasons": len(reason_rows)}
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"✓ 下载计划 {len(rows)} 条 → {out}")
        print(f"  HTML {counts[CHANNEL_HTML]} / PDF {counts[CHANNEL_PDF]} / 无入口 {counts[CHANNEL_NONE]}")
        print(f"  无入口条目已登记原因 → {rf}（build_index 会填进 未获取全文.md）")
        if counts[CHANNEL_HTML]:
            print("  HTML 通道仍需详情页二次确认；二次结果用 --confirm 回传重跑")
    sys.exit(0)


if __name__ == "__main__":
    main()
