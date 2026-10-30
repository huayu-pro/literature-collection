#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""知网结果页行 JSON → 题录 + HTML 白名单。

输入（bsk evaluate 的输出）支持两种形态：
    {"rows": [{"title":..., "href":..., "author":..., "source":..., "date":..., "operat":...}]}
    [ {...}, {...} ]

判定规则：td.operat 的「HTML阅读」与「原版阅读」互斥。两者同时为真说明选择器抓错，脚本报警。

用法：
    /usr/bin/python3 scripts/cnki_scan.py rows.json -o raw/
    /usr/bin/python3 scripts/cnki_scan.py rows.json -o raw/ --start 31   # 增量：已有 C0001-C0030
"""
import argparse
import json
import re
import sys
from pathlib import Path

HTML_WORDS = ("HTML阅读", "HTML 阅读", "html阅读")
PDF_WORDS = ("原版阅读", "PDF下载", "PDF 下载", "pdf下载")

# 来源类别 → quality_tags。v1.3 恒写 [] 让 G3 门禁「每条记录有 quality_tags」机器不可满足，
# v1.4 起从来源类别字段解析（结果页 td.source 常把「CSSCI 北大核心」并在同一格里，
# 也有独立的 src_category / 来源类别 列；两个来源都看，命中即合并去重）
QUALITY_TAGS = (
    ("CSSCI", ("CSSCI", "中文社会科学引文索引", "南大核心", "C刊")),
    ("北大核心", ("北大核心", "中文核心", "北京大学图书馆核心")),
    ("CSCD", ("CSCD", "中国科学引文数据库")),
    ("SCI", ("SCI",)),
    ("SSCI", ("SSCI",)),
    ("EI", ("EI",)),
    ("AMI", ("AMI", "中国人文社会科学期刊")),
    ("OA", ("OA", "开放获取", "开放访问")),
)
# 结果行里可能承载来源类别的键（按优先级尝试，全部为空才判定无标签）
CATEGORY_KEYS = ("category", "src_category", "source_category", "core", "tags", "marks",
                 "来源类别", "核心期刊", "类别")


def parse_quality_tags(*texts):
    """从来源类别文本里解析质量标签；无命中返回 []（保留「确实没有」的可判定性）。

    拉丁缩写必须按词边界匹配：CSSCI 里含子串 "SCI"、"SSCI"，用 in 会把一条 CSSCI
    期刊误标成 SCI+SSCI（中文核心库被当成国际库，质量门槛直接失真）。
    """
    blob = " ".join(str(t or "") for t in texts).strip()
    if not blob:
        return []
    upper = blob.upper()
    out = []
    for tag, words in QUALITY_TAGS:
        for w in words:
            if re.search(r"[\u4e00-\u9fff]", w):
                if w in blob:
                    out.append(tag)
                    break
            elif re.search(r"(?<![A-Z0-9])%s(?![A-Z0-9])" % re.escape(w.upper()), upper):
                out.append(tag)
                break
    return out


def pick(row, *keys, default=""):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def to_int(value):
    try:
        return int(re.sub(r"[^\d]", "", str(value)) or 0)
    except Exception:  # noqa: BLE001
        return 0


def year_of(value):
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return m.group(0) if m else ""


def cnki_id(href):
    m = re.search(r"filename=([^&]+)", href or "")
    if m:
        return m.group(1)
    m = re.search(r"/kcms/detail/detail\.aspx\?.*?dbcode=([^&]+)", href or "")
    return m.group(1) if m else ""


def normalize_url(href):
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://kns.cnki.net" + href
    return href


def main():
    ap = argparse.ArgumentParser(description="知网结果页行解析")
    ap.add_argument("rows", help="结果页行 JSON")
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--prefix", default="C", help="rid 前缀，默认 C")
    ap.add_argument("--start", type=int, default=1,
                    help="rid 起始序号，默认 1；增量补文献时传「已有最大序号+1」，避免与既有 rid 冲突")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        data = json.loads(Path(args.rows).read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"JSON 解析失败：{exc}", file=sys.stderr)
        sys.exit(65)

    rows = data.get("rows", []) if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        print("没有结果行；先确认 table.result-table-list tbody tr 已加载", file=sys.stderr)
        sys.exit(65)
    bad = [r for r in rows if not isinstance(r, dict)]
    if bad:  # bsk evaluate 偶尔返回字符串数组，逐行 pick 会 TypeError 裸崩
        print(f"结果行必须是对象，发现 {len(bad)} 个非对象行（选择器可能抓错了列）", file=sys.stderr)
        sys.exit(65)

    outdir = Path(args.outdir)
    raw = outdir / "raw" if outdir.name != "raw" else outdir
    raw.mkdir(parents=True, exist_ok=True)

    records, whitelist, no_html, warnings = [], [], [], []
    for i, row in enumerate(rows, args.start):
        rid = f"{args.prefix}{i:04d}"
        operat = str(pick(row, "operat", "operation", "操作"))
        has_html = any(w in operat for w in HTML_WORDS)
        has_pdf = any(w in operat for w in PDF_WORDS)
        if has_html and has_pdf:
            warnings.append(f"{rid} 同时命中 HTML 与原版阅读，选择器可能抓错：{operat!r}")

        title = str(pick(row, "title", "题名", "篇名")).strip()
        href = normalize_url(str(pick(row, "href", "url", "link", "链接")))
        rec = {
            "rid": rid,
            "platform": "cnki",
            "title": title,
            "authors": str(pick(row, "author", "authors", "作者")).strip(),
            "source": str(pick(row, "source", "来源", "文献来源")).strip(),
            "year": year_of(pick(row, "date", "日期", "年")),
            "date": str(pick(row, "date", "日期")),
            "type": str(pick(row, "type", "类型", "文献类型")),
            "cited": to_int(pick(row, "cited", "被引", "被引频次")),
            "downloads": to_int(pick(row, "download", "downloads", "下载", "下载频次")),
            "url": href,
            "cnki_id": cnki_id(href),
            "operat": operat,
            "has_html": has_html,
            "has_pdf": has_pdf,
            "access": "HTML" if has_html else ("PDF" if has_pdf else ""),
            "quality_tags": parse_quality_tags(
                pick(row, *CATEGORY_KEYS), pick(row, "source", "来源", "文献来源")),
            "note": "",
        }
        records.append(rec)
        (whitelist if has_html else no_html).append({"rid": rid, "title": title, "href": href})

    (raw / "cnki_records.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    (raw / "html_whitelist.json").write_text(json.dumps(whitelist, ensure_ascii=False, indent=1), encoding="utf-8")
    (raw / "no_html.json").write_text(json.dumps(no_html, ensure_ascii=False, indent=1), encoding="utf-8")

    coverage = len(whitelist) / len(records)
    stats = {"rows": len(records), "has_html": len(whitelist), "no_html": len(no_html),
             "html_coverage": round(coverage, 3), "warnings": warnings}
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"✓ {len(records)} 行 → {raw/'cnki_records.json'}")
        print(f"  HTML 可读 {len(whitelist)} 篇（覆盖率 {coverage:.0%}），无 HTML {len(no_html)} 篇")
        for w in warnings:
            print(f"! {w}")
    sys.exit(0)


if __name__ == "__main__":
    main()
