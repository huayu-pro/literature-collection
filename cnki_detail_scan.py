#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""知网详情页字段补抓合并：detail JSON → records.json。

背景：cnki_scan.py 只抓结果页行（标题/作者/被引/下载），题录导出的
关键词/摘要/卷/期/页码/ISSN/CN/机构 只有详情页才有——没有这些字段，
文献题录.txt 的 K1/AB/IS/vo/OP/SN/CN/AD 全是空白行。

合并策略：只补 records.json 里的空字段，已有值一律不覆盖（真源优先）；
匹配键按 rid → url → title 归一依次尝试。每次合并写 raw/detail_log.csv。

用法：
    /usr/bin/python3 scripts/cnki_detail_scan.py detail.json --records raw/records.json
    /usr/bin/python3 scripts/cnki_detail_scan.py detail.json --records raw/records.json --out raw/records.new.json

detail.json 形态（单条/数组/{"details":[...]} 均可，字段名宽松）：
    [{"rid":"C0001","keywords":["数字治理"],"abstract":"…","volume":"20","issue":"2",
      "pages":"12-25","issn":"1006-0863","cn":"23-1405/D","institution":"清华大学公共管理学院"}]

退出码：0 成功（含部分未匹配，warning）；65 输入错误；66 一条都没匹配上。
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from unicodedata import normalize as unicodedata_normalize

# 允许补抓的字段（detail 里的其他键忽略，防把 rid/platform 等身份键冲掉）
MERGEABLE = ("keywords", "abstract", "volume", "issue", "pages", "issn", "cn",
             "institution", "doi", "url", "authors", "author", "source", "year", "title")
ALIASES = {"author": "authors", "journal": "source", "keyword": "keywords", "affiliation": "institution"}


def norm_title(value):
    v = unicodedata_normalize("NFKC", value or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", v)


def flat(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ";".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def load_details(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"JSON 解析失败：{exc}", file=sys.stderr)
        sys.exit(65)
    if isinstance(data, dict):
        data = data.get("details") or data.get("rows") or [data]
    if not isinstance(data, list) or not data:
        print("detail.json 必须是对象数组或 {details:[...]}", file=sys.stderr)
        sys.exit(65)
    clean = [{ALIASES.get(k, k): v for k, v in d.items()} for d in data if isinstance(d, dict)]
    if not clean:
        print("detail.json 里没有对象行", file=sys.stderr)
        sys.exit(65)
    return clean


def rid_index(records):
    """rid → 记录；重复 rid 全部收集，供 match_record fail fast。

    v1.3 的 match_record 遇到重复 rid 返回第一条（first-wins）：同一 rid 挂两篇不同
    文献时，补抓的关键词/摘要永远只上到第一条，第二条静默缺字段——等题录导出发现
    K1/AB 是空行时，已经不知道哪一條被跳过了。
    """
    by_rid = {}
    for rec in records:
        rid = str(rec.get("rid") or "").strip()
        if not rid:
            continue
        by_rid.setdefault(rid, []).append(rec)
    return by_rid


def match_record(detail, records, by_rid=None):
    """rid → url → 篇名归一，依次找同一条文献；rid 撞车（多篇同名不同内容）直接退出。"""
    by_rid = by_rid if by_rid is not None else rid_index(records)
    rid = flat(detail.get("rid"))
    if rid:
        hits = by_rid.get(rid, [])
        if len(hits) > 1:
            titles = " / ".join(sorted({str(h.get("title") or "")[:24] for h in hits}))
            print(f"records 里 rid={rid} 有 {len(hits)} 条记录，无法判断补给哪一条（{titles}）；"
                  f"先跑 dedupe.py 或为不同文献重编 rid 再补字段，不做 first-wins 猜测",
                  file=sys.stderr)
            sys.exit(65)
        if hits:
            return hits[0]
    url = flat(detail.get("url"))
    if url:
        for rec in records:
            if flat(rec.get("url")) == url:
                return rec
    key = norm_title(detail.get("title"))
    if key:
        for rec in records:
            if norm_title(rec.get("title")) == key:
                return rec
    return None


def main():
    ap = argparse.ArgumentParser(description="知网详情页字段补抓合并")
    ap.add_argument("detail", help="bsk evaluate 抓的详情页 JSON")
    ap.add_argument("--records", required=True, help="records.json（默认原地更新）")
    ap.add_argument("--out", default="", help="写到别处而不动 records.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    details = load_details(args.detail)
    rp = Path(args.records)
    if not rp.exists():
        print(f"records.json 不存在：{rp}", file=sys.stderr)
        sys.exit(65)
    try:
        records = json.loads(rp.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"records.json 解析失败：{exc}", file=sys.stderr)
        sys.exit(65)
    if not isinstance(records, list):
        print("records.json 顶层必须是数组", file=sys.stderr)
        sys.exit(65)

    merged, unmatched, log = 0, [], []
    by_rid = rid_index(records)
    for detail in details:
        rec = match_record(detail, records, by_rid)
        if rec is None:
            unmatched.append(flat(detail.get("rid")) or norm_title(detail.get("title"))[:20] or "?")
            continue
        filled = []
        for key in MERGEABLE:
            if key in ("rid", "platform"):
                continue
            incoming = flat(detail.get(key))
            if incoming and flat(rec.get(key)) == "":
                rec[key] = detail[key] if isinstance(detail[key], list) else incoming
                filled.append(key)
        if filled:
            merged += 1
            log.append({"rid": rec.get("rid", ""), "fields": ";".join(filled),
                        "time": datetime.now().isoformat(timespec="seconds")})
        else:
            log.append({"rid": rec.get("rid", ""), "fields": "(无新字段可补)",
                        "time": datetime.now().isoformat(timespec="seconds")})

    out = Path(args.out) if args.out else rp
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    if log:
        lp = rp.parent / "detail_log.csv"
        with open(lp, "a", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["rid", "fields", "time"])
            if fh.tell() == 0:
                w.writeheader()
            w.writerows(log)

    stats = {"details": len(details), "merged": merged,
             "no_new_fields": len(log) - merged, "unmatched": unmatched}
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"✓ {merged}/{len(details)} 条补进字段 → {out}（日志 raw/detail_log.csv）")
        if unmatched:
            print(f"! {len(unmatched)} 条没匹配上（rid/url/篇名都对不上）：{', '.join(unmatched[:5])}")
            print("  检查 detail 里是否带了 rid 或与 records 一致的 url/题名")
    sys.exit(0 if merged or not unmatched else 66)


if __name__ == "__main__":
    main()
