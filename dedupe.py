#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""三级去重：DOI/UT 精确 → 规范化篇名 → 模糊（相似度 + 全名前缀 + 年差 ≤1）。

默认原地模式（G5 推荐）：备份 raw/records.json → raw/records.raw.json（仅首次），
去重结果写回 records.json——下游 build_index/export_citations/verify 的题录真源
由此真正吃到去重结果；被合并 rid 的 正文/备选/pdf 文件自动改名为胜者 rid。
传 --out 则走旧旁路模式：只写 --out 文件、不动 records.json、不改名。
用法：
    /usr/bin/python3 scripts/dedupe.py raw/records.json --log raw/dedupe_log.csv   # 原地
    /usr/bin/python3 scripts/dedupe.py raw/records.json -o raw/records.dedup.json  # 旁路
"""
import argparse
import csv
import json
import re
import shutil
import sys
from difflib import SequenceMatcher
from pathlib import Path
from unicodedata import normalize as unicodedata_normalize

FILE_DIRS = ("正文", "备选", "pdf")  # 自动改名扫描的目录（相对 records.json 的上级）

PUNCT_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
DOI_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.I)


def norm_doi(value):
    v = (value or "").strip().lower()
    v = DOI_PREFIX_RE.sub("", v)
    return v.rstrip(".,;:)）】]")


def norm_title(value):
    v = unicodedata_normalize("NFKC", value or "").lower()
    return PUNCT_RE.sub("", v)


def first_author(value):
    v = re.split(r"[;；,，、]", value or "")[0]
    v = unicodedata_normalize("NFKC", v).lower()
    v = re.sub(r"\b[a-z]\.", "", v)
    return PUNCT_RE.sub("", v)[:12]


def year_of(value):
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else 0


def fill_count(rec):
    return sum(1 for v in rec.values() if v not in ("", None, [], {}))


def similar(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def merge(keep, drop):
    merged = dict(keep)
    for key, value in drop.items():
        if merged.get(key) in ("", None, [], {}) and value not in ("", None, [], {}):
            merged[key] = value
    # 胜者的 doi 可能带 URL 前缀/尾括号（匹配靠 norm_doi 完成），交付前回写干净值，
    # 否则下游 https://doi.org/<doi> 链接是坏的
    if merged.get("doi"):
        merged["doi"] = norm_doi(merged["doi"])
    merged["merged_from"] = sorted(set(keep.get("merged_from", [keep["rid"]]) + drop.get("merged_from", [drop["rid"]])))
    return merged


def rename_files(workdir, log):
    """被合并 rid 的文件改名为胜者 rid 前缀；目标已存在则不动并警告。"""
    renames, skipped = [], []
    for entry in log:
        dropped, kept_rid = entry["dropped_rid"], entry["kept_rid"]
        if dropped == kept_rid:
            continue
        for sub in FILE_DIRS:
            d = Path(workdir) / sub
            if not d.is_dir():
                continue
            for f in sorted(d.glob(f"{dropped}_*")):
                dest = f.with_name(f"{kept_rid}_{f.name.split('_', 1)[1]}")
                if dest.exists():
                    skipped.append(f"{f.name} → {dest.name}（目标已存在，未动）")
                    continue
                shutil.move(str(f), str(dest))
                renames.append(f"{f.name} → {dest.name}")
    return renames, skipped


def main():
    ap = argparse.ArgumentParser(description="文献三级去重（默认原地改写 records.json）")
    ap.add_argument("records", help="records.json")
    ap.add_argument("-o", "--out", default="", help="旁路模式：写此文件、不动 records.json、不改名")
    ap.add_argument("--log", default="", help="去重日志 CSV")
    ap.add_argument("--fuzzy", type=int, default=92, help="模糊阈值（0-100），默认 92")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.records)
    if not src.exists():
        print(f"文件不存在：{src}", file=sys.stderr)
        sys.exit(64)
    try:
        records = json.loads(src.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"JSON 解析失败：{exc}", file=sys.stderr)
        sys.exit(65)
    if not isinstance(records, list):
        print("records.json 顶层必须是数组", file=sys.stderr)
        sys.exit(65)

    kept, log = [], []
    index_by_key = {}
    rid_seen = {}
    for rec in records:
        rid = rec.get("rid") or f"X{len(kept) + 1:04d}"
        rec["rid"] = rid
        # rid 主键：v1.3 只按 DOI/UT/篇名判重，不设 rid 主键——同一 rid 挂两篇不同
        # 篇名的记录会同时保留（三条判重全不命中），下游 build_index 毫无征兆地
        # exit 65，而 dedupe 明明是「去重脚本」却说自己成功去掉了 0 条。
        # 这里一律 fail fast：rid 撞车且篇名不同 = 上游编号错误，不是重复文献。
        if rid in rid_seen:
            other = rid_seen[rid]
            if norm_title(other.get("title")) != norm_title(rec.get("title")):
                print(f"rid 撞车：{rid} 同时挂了两篇不同文献"
                      f"（{str(other.get('title') or '')[:24]!r} vs {str(rec.get('title') or '')[:24]!r}）。"
                      f"这不是重复文献，是编号错误——用 cnki_scan.py --start / wos_parse.py --start "
                      f"给新批次重编 rid 后再去重", file=sys.stderr)
                sys.exit(65)
        rid_seen[rid] = rec
        doi = norm_doi(rec.get("doi"))
        ut = (rec.get("ut") or "").strip().lower()
        title_key = norm_title(rec.get("title"))
        level, hit = 0, None

        for key in ([f"doi:{doi}"] if doi else []) + ([f"ut:{ut}"] if ut else []):
            if key in index_by_key:
                level, hit = 1, index_by_key[key]
                break

        if hit is None and title_key and f"t:{title_key}" in index_by_key:
            level, hit = 2, index_by_key[f"t:{title_key}"]

        if hit is None and title_key:
            year, author = year_of(rec.get("year")), first_author(rec.get("authors"))
            if author and year:
                for cand in kept:
                    if first_author(cand.get("authors")) != author:
                        continue
                    if abs(year_of(cand.get("year")) - year) > 1:
                        continue
                    sim = similar(title_key, norm_title(cand.get("title")))
                    if sim >= args.fuzzy / 100:
                        level, hit = 3, cand
                        break

        if hit is None:
            kept.append(rec)
            for key in ([f"doi:{doi}"] if doi else []) + ([f"ut:{ut}"] if ut else []) + ([f"t:{title_key}"] if title_key else []):
                index_by_key[key] = rec
            continue

        winner = hit if fill_count(hit) >= fill_count(rec) else rec
        loser = rec if winner is hit else hit
        merged = merge(winner, loser)
        for i, existing in enumerate(kept):
            if existing is hit:
                kept[i] = merged
                break
        for key, value in list(index_by_key.items()):
            if value is hit:
                index_by_key[key] = merged
        log.append({
            "kept_rid": merged["rid"], "dropped_rid": loser["rid"], "level": level,
            "reason": {1: "DOI/UT 精确", 2: "篇名归一", 3: f"模糊≥{args.fuzzy}且同姓年差≤1"}[level],
            "title": loser.get("title", ""),
        })

    # 兜底 fail fast：三级判重都没合掉的同 rid 记录（例如两条篇名都为空）必须拦住，
    # 不能让它带着重复 rid 进 index——下游 build_index 会 exit 65，而这里却报「去重成功」
    dup_rids = sorted({str(r.get("rid") or "") for r in kept
                       if sum(1 for x in kept if str(x.get("rid") or "") == str(r.get("rid") or "")) > 1
                       and str(r.get("rid") or "")})
    if dup_rids:
        print(f"去重后仍有重复 rid：{', '.join(dup_rids[:10])}（三级判重都没合掉，"
              f"多半是两条记录篇名都为空）；人工核查 records.json 后重跑", file=sys.stderr)
        sys.exit(65)

    renames, skipped = [], []
    if args.out:  # 旁路模式（旧行为）
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    else:  # 原地模式：首次备份后写回，下游三脚本（build_index/export/verify）无需任何参数
        backup = src.with_suffix(".raw.json")
        if not backup.exists():
            shutil.copy2(src, backup)
        src.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
        renames, skipped = rename_files(src.parent.parent, log)

    if args.log:
        lp = Path(args.log)
        lp.parent.mkdir(parents=True, exist_ok=True)
        with open(lp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["kept_rid", "dropped_rid", "level", "reason", "title"])
            w.writeheader()
            w.writerows(log)

    by_level = {str(i): sum(1 for x in log if x["level"] == i) for i in (1, 2, 3)}
    stats = {"before": len(records), "after": len(kept), "removed": len(records) - len(kept),
             "by_level": by_level, "mode": "bypass" if args.out else "inplace",
             "renamed_files": len(renames)}
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        where = Path(args.out).name if args.out else f"{src}（原地，备份 raw/{src.stem}.raw.json）"
        print(f"✓ {stats['before']} → {stats['after']}（去掉 {stats['removed']}；"
              f"L1={by_level['1']} L2={by_level['2']} L3={by_level['3']}）→ {where}")
        if renames:
            print(f"  改名 {len(renames)} 个文件到胜者 rid：")
            for r in renames[:10]:
                print(f"    {r}")
        for s in skipped[:5]:
            print(f"! {s}")
    sys.exit(0)


if __name__ == "__main__":
    main()
