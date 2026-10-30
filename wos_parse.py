#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""WoS Full Record（Tab delimited）→ records.json。

关键设计：rid 按导出行序稳定生成（W0001…），rank_by_citation 只作展示列。
下游任何 join 只能用 rid —— 这是 S1 会话「89 篇错挂 88 篇」的根因修复。

用法：
    /usr/bin/python3 scripts/wos_parse.py export.txt -o raw/records.json
    /usr/bin/python3 scripts/wos_parse.py export.txt -o raw/records_new.json --start 21  # 增量
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

KEY_FIELDS = ["UT", "TI", "AU", "SO", "PY", "VL", "IS", "BP", "EP", "DI",
              "TC", "Z9", "AB", "DE", "ID", "WC", "SU", "HC", "OA", "SN", "EI", "C1"]


def norm(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def to_int(value):
    try:
        return int(re.sub(r"[^\d-]", "", str(value)) or 0)
    except Exception:  # noqa: BLE001
        return 0


def read_export(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            return [], []
        rows, short = [], 0
        for raw in reader:
            if not raw or not any(x.strip() for x in raw):
                continue
            if len(raw) < max(5, len(header) // 2) and rows:
                # 多行摘要被拆成续行：并回上一条的 AB，不新起记录
                rows[-1]["AB"] = (rows[-1].get("AB", "") + " " + " ".join(x.strip() for x in raw)).strip()
                short += 1
                continue
            raw = raw + [""] * (len(header) - len(raw))
            rows.append(dict(zip(header, [c.strip() for c in raw])))
        return rows, [short]


def build(rows, start=1):
    recs = []
    for i, row in enumerate(rows, start):
        g = lambda k: norm(row.get(k, ""))  # noqa: E731
        recs.append({
            "rid": f"W{i:04d}",
            "platform": "wos",
            "rank_by_export": i,
            "ut": g("UT"),
            "title": g("TI"),
            "authors": g("AU"),
            "source": g("SO"),
            "year": g("PY"),
            "volume": g("VL"),
            "issue": g("IS"),
            "pages": f"{g('BP')}-{g('EP')}".strip("-"),
            "doi": g("DI").lower(),
            "cited": to_int(g("Z9")),
            "cited_core": to_int(g("TC")),
            "downloads": 0,
            "abstract": g("AB"),
            "keywords": g("DE"),
            "keywords_plus": g("ID"),
            "wc": g("WC"),
            "su": g("SU"),
            "oa": g("OA"),
            "highly_cited": g("HC"),
            "issn": g("SN"),
            "type": g("DT"),
            "language": g("LA"),
            "quality_tags": [t for t, ok in (("OA", g("OA").upper() == "OA"),
                                             ("HC", g("HC").upper() == "Y")) if ok],
            "raw": {k: row.get(k, "") for k in row},
        })
    ranked = sorted(recs, key=lambda r: (-r["cited"], -r["cited_core"]))
    for rank, rec in enumerate(ranked, 1):
        rec["rank_by_citation"] = rank
    return recs


def main():
    ap = argparse.ArgumentParser(description="解析 WoS Tab 全记录导出")
    ap.add_argument("export", help="WoS 导出的 .txt（Tab delimited）")
    ap.add_argument("-o", "--out", required=True, help="输出 records.json")
    ap.add_argument("--rid-map", default="", help="可选：输出 rid 映射 CSV")
    ap.add_argument("--start", type=int, default=1,
                    help="rid 起始序号，默认 1；增量补文献时传「已有最大序号+1」")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.export)
    if not src.exists():
        print(f"文件不存在：{src}", file=sys.stderr)
        sys.exit(64)

    rows, short = read_export(src)
    if not rows:
        print("没有解析到记录（检查是否 Tab delimited + Full Record）", file=sys.stderr)
        sys.exit(65)

    missing = [k for k in ("TI", "UT") if k not in rows[0]]
    if missing:
        print(f"表头缺少必需字段 {missing}；实际表头前 10 项：{list(rows[0])[:10]}", file=sys.stderr)
        sys.exit(65)

    recs = build(rows, args.start)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.rid_map:
        rp = Path(args.rid_map)
        rp.parent.mkdir(parents=True, exist_ok=True)
        with open(rp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["rid", "rank_by_citation", "rank_by_export", "doi", "title"])
            for r in recs:
                w.writerow([r["rid"], r["rank_by_citation"], r["rank_by_export"], r["doi"], r["title"]])

    stats = {
        "records": len(recs),
        "unique_rid": len({r["rid"] for r in recs}),
        "with_doi": sum(1 for r in recs if r["doi"]),
        "years": dict(sorted(Counter(r["year"] for r in recs).items())),
        "types": dict(Counter(r["type"] for r in recs).most_common()),
        "continuation_lines": short[0] if short else 0,
    }
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"✓ {len(recs)} 条记录 → {out}（rid 唯一 {stats['unique_rid']}，有 DOI {stats['with_doi']}）")
        if stats["continuation_lines"]:
            print(f"! 合并了 {stats['continuation_lines']} 行续行到上一条摘要，请抽查 2-3 条")
    sys.exit(0)


if __name__ == "__main__":
    main()
