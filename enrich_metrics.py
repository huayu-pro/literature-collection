#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""OpenAlex 指标采集：把 2yr_mean_citedness / OA 命中率写回 records.json。

背景：SKILL.md FAQ Q2、pitfall-library、quality-screening §5 反复承诺用 OpenAlex
`2yr_mean_citedness` 作 JIF/分区的代理指标，但 v1.3 的 pdf_fetch.py 只请求
doi,best_oa_location,open_access,locations——从不请求该字段，于是 §6 的打分公式
（score = 0.75*norm(cited) + 0.15*norm(2yr_mean_citedness) + 0.10*norm(主题词命中数)）
完全不可执行，只能凭感觉排。本脚本让这条公式真正能算。

口径纪律（quality-screening §5 「禁止写成 JIF」）：
    写出的列名固定为 citedness_2yr，报告/索引里必须标「非 JIF」；本脚本不写任何
    分区 / JIF / Q1 字样，也不做任何「是否一区」判断。

用法（必须先探命中率再决定要不要写）：
    /usr/bin/python3 scripts/enrich_metrics.py raw/records.json --dry-run --mailto you@example.com
    /usr/bin/python3 scripts/enrich_metrics.py raw/records.json --mailto you@example.com --json
    /usr/bin/python3 scripts/enrich_metrics.py raw/records.json -o raw/records.enriched.json

退出码：0 成功（含部分未命中）；64 参数/文件错误；65 网络或接口失败且无任何结果。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
# works 的 primary_location.source 只有期刊身份，没有 2yr_mean_citedness——
# 该指标挂在 OpenAlex 的 source 实体（/sources/...）上，需要第二步按 ISSN/source id 取
SELECT = "doi,primary_location,open_access,best_oa_location,locations"
SOURCE_SELECT = "id,ids,display_name,issn_l,summary_stats"
BATCH = 50
RETRIES = (0, 2, 4, 6)


def norm_doi(value):
    v = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    return v.rstrip(".,;:)）】]")


def _get(url, params, mailto):
    if mailto:
        params["mailto"] = mailto
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": "application/json"})
    last = ""
    for attempt, wait in enumerate(RETRIES):
        if wait:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code == 429 and attempt < len(RETRIES) - 1:
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if attempt < len(RETRIES) - 1:
                continue
            raise
    raise RuntimeError(last or "OpenAlex 请求失败")


def openalex_batch(dois, mailto):
    return _get("https://api.openalex.org/works",
                {"filter": "doi:" + "|".join(dois), "per-page": str(BATCH), "select": SELECT},
                mailto)


def openalex_sources(keys, mailto):
    """按 source id 或 ISSN 批量取期刊级指标（2yr_mean_citedness 只在这里有）。"""
    # 只用 issn 过滤式（实测可用）；拿 OpenAlex 完整 URL 当 ids.openalex.org 的值会被 400 拒，
    # 因此 source_key_of 返回的 URL 型 id 在这里被跳过，改由 ISSN-L 命中
    issns = sorted(k for k in keys if not k.startswith("http"))
    out, errors = {}, []
    for i in range(0, len(issns), BATCH):
        chunk = issns[i:i + BATCH]
        try:
            data = _get("https://api.openalex.org/sources",
                        {"filter": "issn:" + "|".join(chunk),
                         "per-page": str(BATCH), "select": SOURCE_SELECT}, mailto)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        for src in data.get("results", []):
            for key in (src.get("issn_l"), (src.get("ids") or {}).get("openalex"), src.get("id")):
                if key:
                    out[key] = src
        time.sleep(0.25)
    return out, errors


def citedness_of_source(src):
    """2yr_mean_citedness 在 source 实体的 summary_stats 里（OpenAlex 现版不再顶层暴露）。"""
    stats = src.get("summary_stats") or {}
    if stats.get("2yr_mean_citedness") is not None:
        return stats["2yr_mean_citedness"]
    if src.get("2yr_mean_citedness") is not None:  # 兼容旧版形态
        return src["2yr_mean_citedness"]
    return None


def source_key_of(work):
    """取出能定位 source 实体的键。

    优先 ISSN-L：`/sources?filter=issn:<issn_l>` 是实测可用的过滤式，而拿完整
    OpenAlex URL 当 ids.openalex.org 过滤值会被拒（400）——不能用 id 硬拼。
    """
    for holder in [(work.get("primary_location") or {}).get("source")] + \
                  [(loc or {}).get("source") for loc in work.get("locations") or []]:
        if isinstance(holder, dict):
            if holder.get("issn_l"):
                return holder["issn_l"], holder.get("display_name") or ""
            if holder.get("id"):
                return holder["id"], holder.get("display_name") or ""
    return "", ""


def pick_citedness(work, sources=None):
    """2yr_mean_citedness：works 顶层没有，必须走 source 实体的 summary_stats。"""
    for holder in ((work.get("primary_location") or {}).get("source"),):
        if isinstance(holder, dict):
            v = citedness_of_source(holder)
            if v is not None:
                return v, (holder.get("display_name") or "")
    if sources:
        key, name = source_key_of(work)
        src = sources.get(key) if key else None
        if isinstance(src, dict):
            v = citedness_of_source(src)
            if v is not None:
                return v, name or (src.get("display_name") or "")
    return None, ""


def pick_oa(work):
    oa = work.get("open_access") or {}
    if oa.get("oa_url"):
        return True, oa["oa_url"]
    best = (work.get("best_oa_location") or {})
    if best.get("pdf_url"):
        return True, best["pdf_url"]
    if best.get("landing_page_url"):
        return True, best["landing_page_url"]
    for loc in work.get("locations") or []:
        if (loc or {}).get("pdf_url"):
            return True, loc["pdf_url"]
    return False, ""


def main():
    ap = argparse.ArgumentParser(description="OpenAlex 指标采集（2yr 均被引 / OA 命中）")
    ap.add_argument("records", help="records.json")
    ap.add_argument("-o", "--out", default="", help="输出路径，默认原地改写 records")
    ap.add_argument("--mailto", default="", help="OpenAlex 礼貌池邮箱；必填你自己的，不要硬编码")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条有 DOI 的记录")
    ap.add_argument("--dry-run", action="store_true",
                    help="只探命中率并打印，不写回任何文件")
    ap.add_argument("--overwrite", action="store_true",
                    help="已有 citedness_2yr 也用新值覆盖（默认只补空值）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.records)
    if not src.exists():
        print(f"文件不存在：{src}", file=sys.stderr)
        sys.exit(64)
    try:
        records = json.loads(src.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        print(f"records.json 解析失败：{exc}", file=sys.stderr)
        sys.exit(64)
    if not isinstance(records, list) or not records:
        print("records.json 必须是非空数组", file=sys.stderr)
        sys.exit(64)

    targets = [r for r in records if norm_doi(r.get("doi"))]
    if args.limit:
        targets = targets[:args.limit]
    if not targets:
        print("没有带 DOI 的记录，无法从 OpenAlex 取指标；先补抓 DOI", file=sys.stderr)
        sys.exit(64)

    by_doi = {}
    errors = []
    for i in range(0, len(targets), BATCH):
        batch = targets[i:i + BATCH]
        try:
            data = openalex_batch([norm_doi(r["doi"]) for r in batch], args.mailto)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"批次 {i // BATCH + 1}：{exc}")
            continue
        for work in data.get("results", []):
            by_doi[norm_doi(work.get("doi"))] = work
        time.sleep(0.25)

    if not by_doi and errors:
        print("OpenAlex 全部批次失败：" + "；".join(errors[:3]), file=sys.stderr)
        sys.exit(65)

    # 第二步：按 source id / ISSN-L 批量取期刊级指标
    keys = {k for k in (source_key_of(w)[0] for w in by_doi.values()) if k}
    sources, src_errors = openalex_sources(keys, args.mailto) if keys else ({}, [])
    errors += src_errors

    hit_cited = hit_oa = 0
    for rec in records:
        work = by_doi.get(norm_doi(rec.get("doi")))
        if not work:
            continue
        citedness, source_name = pick_citedness(work, sources)
        is_oa, oa_url = pick_oa(work)
        if citedness is not None:
            hit_cited += 1
            if args.overwrite or rec.get("citedness_2yr") in ("", None):
                rec["citedness_2yr"] = round(float(citedness), 3)
        if source_name:
            rec.setdefault("source_oa_name", source_name)
        rec["oa_available"] = bool(is_oa) if (args.overwrite or not rec.get("oa_available")) \
            else rec["oa_available"]
        if is_oa:
            hit_oa += 1
            if oa_url and (args.overwrite or not rec.get("oa_url")):
                rec["oa_url"] = oa_url

    rate_c = hit_cited / len(targets)
    rate_o = hit_oa / len(targets)
    stats = {"records": len(records), "with_doi": len(targets),
             "matched": len(by_doi), "citedness_hit": hit_cited,
             "citedness_rate": round(rate_c, 3), "oa_hit": hit_oa,
             "oa_rate": round(rate_o, 3), "errors": errors,
             "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
             "written": None}

    if args.dry_run:
        stats["mode"] = "dry-run"
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            print(f"探命中率（未写回）：{len(targets)} 条有 DOI，OpenAlex 匹配 {len(by_doi)} 条")
            print(f"  2yr 均被引命中 {hit_cited} 条（{rate_c:.0%}）；OA 直链命中 {hit_oa} 条（{rate_o:.0%}）")
            print("  命中率 <50% 时别用它当唯一排序依据；改用被引 + 来源层级。")
        sys.exit(0)

    out = Path(args.out) if args.out else src
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    stats["mode"] = "bypass" if args.out else "inplace"
    stats["written"] = str(out)
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"✓ 指标已写入 {out}：2yr 均被引 {hit_cited}/{len(targets)}（{rate_c:.0%}），"
              f"OA {hit_oa}/{len(targets)}（{rate_o:.0%}）")
        print("  列名 citedness_2yr 是「2yr 均被引（非 JIF）」，禁止写成 JIF / 一区 / Q1。")
        if errors:
            print(f"! {len(errors)} 个批次失败（已跳过）：{errors[0]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
