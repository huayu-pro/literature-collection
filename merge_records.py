#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""增量批次合并：把新一批 records 合并进既有 raw/records.json。

背景：SKILL.md §3「增量补文献」要求把新 records 合并进 raw/records.json，但 v1.3
没有任何脚本支持合并（cnki_scan.py 是整体覆写），实战只能靠 agent 临场写 inline
Python——结果不一致且必然踩重复键（有的 last-wins 丢一篇，有的直接双份进索引）。
本脚本是这条要求的正式落点。

主键纪律：rid 冲突一律 fail fast，绝不静默 last-wins（那是丢数据）。
  同 rid 同篇名  → 视为同一条，用新批次补齐空字段（已填字段不覆盖）
  同 rid 不同篇名 → 报错退出 65，要求用 --start 续编 rid 后重跑

用法：
    /usr/bin/python3 scripts/merge_records.py raw/records.json new_batch.json
    /usr/bin/python3 scripts/merge_records.py raw/records.json new_batch.json -o raw/records.merged.json
    /usr/bin/python3 scripts/merge_records.py raw/records.json new_batch.json --prune-missing --json

退出码：0 成功；64 文件/参数错误；65 rid 冲突（同 rid 不同篇名）。
"""
import argparse
import json
import sys
from pathlib import Path
from unicodedata import normalize as unicodedata_normalize
import re

PUNCT_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def norm_title(value):
    v = unicodedata_normalize("NFKC", value or "").lower()
    return PUNCT_RE.sub("", v)


def load_list(path, label):
    p = Path(path)
    if not p.exists():
        print(f"{label} 文件不存在：{p}", file=sys.stderr)
        sys.exit(64)
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"{label} 解析失败：{exc}", file=sys.stderr)
        sys.exit(64)
    if isinstance(data, dict):
        data = data.get("records") or data.get("rows") or []
    if not isinstance(data, list):
        print(f"{label} 顶层必须是数组（或 {{records:[...]}}）", file=sys.stderr)
        sys.exit(64)
    return [r for r in data if isinstance(r, dict)]


def find_dups(records):
    seen, dups = set(), []
    for r in records:
        rid = str(r.get("rid") or "").strip()
        if not rid:
            continue
        if rid in seen:
            dups.append(rid)
        seen.add(rid)
    return sorted(set(dups))


def merge_one(old, new):
    """同一条（rid 与篇名一致）：新批次只补空字段，已有值不覆盖（既有真源优先）。"""
    merged = dict(old)
    filled = []
    for key, value in new.items():
        if key in ("rid", "platform"):
            continue
        if merged.get(key) in ("", None, [], {}) and value not in ("", None, [], {}):
            merged[key] = value
            filled.append(key)
    return merged, filled


def main():
    ap = argparse.ArgumentParser(description="增量批次合并进既有 records.json")
    ap.add_argument("records", help="既有 records.json（真源）")
    ap.add_argument("batch", help="新批次 records JSON")
    ap.add_argument("-o", "--out", default="", help="输出路径，默认原地改写 records")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    old = load_list(args.records, "既有 records")
    new = load_list(args.batch, "新批次")

    for label, group in (("既有 records", old), ("新批次", new)):
        bad = find_dups(group)
        if bad:
            print(f"{label} 内部存在重复 rid：{', '.join(bad[:10])}；"
                  f"先跑 dedupe.py 或人工重编 rid 再合并", file=sys.stderr)
            sys.exit(65)
        no_rid = [str(r.get("title", ""))[:20] for r in group if not str(r.get("rid") or "").strip()]
        if no_rid:
            print(f"{label} 有 {len(no_rid)} 条缺 rid（如 {no_rid[:3]}）；"
                  f"先用 cnki_scan.py --start / wos_parse.py --start 编 rid", file=sys.stderr)
            sys.exit(64)

    by_rid = {str(r["rid"]).strip(): r for r in old}
    conflicts, updated, appended = [], [], []
    for rec in new:
        rid = str(rec["rid"]).strip()
        cur = by_rid.get(rid)
        if cur is None:
            by_rid[rid] = rec
            appended.append(rid)
            continue
        if norm_title(cur.get("title")) != norm_title(rec.get("title")):
            conflicts.append((rid, cur.get("title", ""), rec.get("title", "")))
            continue
        merged, filled = merge_one(cur, rec)
        by_rid[rid] = merged
        if filled:
            updated.append((rid, filled))

    if conflicts:
        detail = "；".join(f"{rid}: {a!r} vs {b!r}" for rid, a, b in conflicts[:5])
        print(f"rid 撞车且篇名不同（{len(conflicts)} 处）：{detail}", file=sys.stderr)
        print(f"合并中止，未写入任何文件。用 cnki_scan.py --start {_next_start(by_rid)} "
              f"（或 wos_parse.py --start）给新批次续编 rid 后重跑", file=sys.stderr)
        sys.exit(65)

    # 保持既有顺序在前、新批次在后：rid 续编后就是天然的时间序，索引里也更好读
    order = [str(r["rid"]).strip() for r in old] + [str(r["rid"]).strip() for r in new
                                                    if str(r["rid"]).strip() in appended]
    result = [by_rid[r] for r in dict.fromkeys(order)]

    out = Path(args.out) if args.out else Path(args.records)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    stats = {"before": len(old), "batch": len(new), "after": len(result),
             "appended": len(appended), "updated": len(updated),
             "conflicts": len(conflicts), "out": str(out),
             "updated_fields": {rid: fs for rid, fs in updated[:20]}}
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"✓ 合并 {len(old)} + {len(new)} → {len(result)} 条 → {out}")
        print(f"  新增 {len(appended)} 条，补齐字段 {len(updated)} 条")
        for rid, fs in updated[:5]:
            print(f"    {rid} 补了 {';'.join(fs)}")
        if len(appended) + len(updated) != len(new):
            print(f"! 新批次 {len(new)} 条里有 {len(new) - len(appended) - len(updated)} 条既未新增也未补字段（完全重复）")
    sys.exit(0)


def _next_start(by_rid):
    """给错误提示算一个可用的起始序号：取现有最大数字尾号 +1。"""
    nums = []
    for rid in by_rid:
        m = re.search(r"(\d+)$", rid)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


if __name__ == "__main__":
    main()
