#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行（需要 pymupdf 做页数与内嵌 DOI 校验）
"""WOS 文献 PDF 获取与校验。

fetch：OpenAlex 批量查 OA 直链 → 域名优先级 → 4 线程 curl → 即时四重校验
verify：对已有 pdf/ 目录逐篇校验，不合格 move 到 _quarantine/（绝不删除）

四重校验：%PDF- 魔数 → ≥10KB → pymupdf 页数 ≥1 → 首页内嵌 DOI == 记录 DOI
（无 DOI 时降级为篇名相似度）

用法：
    /usr/bin/python3 scripts/pdf_fetch.py fetch --records raw/records.json --outdir pdf/ \
        --mailto you@example.com --limit 50 --dry-run
    /usr/bin/python3 scripts/pdf_fetch.py verify --dir pdf/ --records raw/records.json
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from unicodedata import normalize as unicodedata_normalize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reason_codes import canonical  # noqa: E402

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
DOMAIN_PRIORITY = [
    (1, "mdpi.com"), (1, "frontiersin.org"), (2, "springer"), (2, "cogitatio"),
    (3, "wiley.com"), (3, "oup.com"), (3, "cambridge.org"),
    (4, "sagepub.com"), (4, "tandfonline.com"), (7, "sciencedirect.com"), (9, "ssrn.com"),
]
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;)\]\}]+", re.I)


def norm_doi(value):
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v)
    return v.rstrip(".,;:)）】]")


def norm_text(value):
    v = unicodedata_normalize("NFKC", value or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", v)


def priority(url):
    low = (url or "").lower()
    for rank, domain in DOMAIN_PRIORITY:
        if domain in low:
            return rank
    return 5


def safe_name(text, limit=40):
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]", "", text or "").strip()
    text = re.sub(r"\s+", "", text)
    return text[:limit] or "unknown"


def pdf_name(rec):
    first = re.split(r"[;；,，]", rec.get("authors") or "")[0].strip()
    surname = safe_name(first.split()[-1] if first and " " in first else first, 16)
    journal = safe_name(rec.get("source") or "", 24)
    return f"{rec['rid']}_{surname}{rec.get('year', '')}_{journal}.pdf"


def openalex_batch(dois, mailto):
    params = {"filter": "doi:" + "|".join(dois), "per-page": "50",
              "select": "doi,best_oa_location,open_access,locations"}
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt, wait in enumerate((0, 2, 4, 6)):
        if wait:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                continue
            raise
    return {"results": []}


def resolve_oa(records, mailto, limit=0):
    targets = [r for r in records if norm_doi(r.get("doi"))]
    if limit:
        targets = targets[:limit]
    found = {}
    for i in range(0, len(targets), 50):
        batch = targets[i:i + 50]
        try:
            data = openalex_batch([norm_doi(r["doi"]) for r in batch], mailto)
        except Exception as exc:  # noqa: BLE001
            print(f"! OpenAlex 批次 {i//50+1} 失败：{exc}")
            continue
        for work in data.get("results", []):
            doi = norm_doi(work.get("doi"))
            urls = []
            best = (work.get("best_oa_location") or {}).get("pdf_url")
            oa = (work.get("open_access") or {}).get("oa_url")
            if best:
                urls.append(best)
            if oa:
                urls.append(oa)
            for loc in work.get("locations") or []:
                if loc.get("pdf_url"):
                    urls.append(loc["pdf_url"])
            urls = sorted({u for u in urls if u}, key=priority)
            if urls:
                found[doi] = urls[0]
        time.sleep(0.25)
    return found


def validate_pdf(path, rec):
    info = {"bytes": path.stat().st_size if path.exists() else 0, "pages": 0, "doi_match": "n/a"}
    if info["bytes"] < 10240:
        return False, "too_small", info
    with open(path, "rb") as fh:
        if fh.read(5) != b"%PDF-":
            return False, "not_pdf", info
    try:
        import pymupdf
        doc = pymupdf.open(str(path))
        info["pages"] = doc.page_count
        text = "\n".join(doc.load_page(i).get_text("text") for i in range(min(2, doc.page_count)))
        doc.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"unreadable:{exc}", info
    if info["pages"] < 1:
        return False, "no_pages", info
    m = DOI_RE.search(text)
    doi = norm_doi(rec.get("doi"))
    if m and doi:
        info["doi_match"] = "yes" if norm_doi(m.group(0)) == doi else "no"
        if info["doi_match"] == "no":
            sim = SequenceMatcher(None, norm_text(rec.get("title")), norm_text(text)).ratio()
            if sim < 0.9:
                return False, "doi_mismatch", info
    elif doi:
        info["doi_match"] = "absent"
        sim = SequenceMatcher(None, norm_text(rec.get("title")), norm_text(text)).ratio()
        if sim < 0.6:
            return False, "title_mismatch", info
    return True, "ok", info


def download(url, dest):
    cmd = ["curl", "-sS", "-L", "--max-time", "30", "-A", UA,
           "-H", "Accept: application/pdf,*/*", "-o", str(dest), "-w", "%{http_code}|%{content_type}", url]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def write_manifest(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["rid", "doi", "url", "file", "status",
                                           "bytes", "pages", "doi_match", "reason"])
        w.writeheader()
        w.writerows(rows)


def index_by_rid(records, source):
    """rid → 记录，重复 rid 直接退出。

    v1.3 是 `{r["rid"]: r for r in records}` 的 last-wins：被丢的那条既不会下载，
    也不会在 manifest.csv 里留下失败行——它直接变成孤儿，交付时谁都不知道少了一篇。
    重复 rid 是上游没跑 dedupe 或用错了 --start 的信号，必须拦在下载之前。
    """
    out, dups = {}, []
    for r in records:
        rid = str(r.get("rid") or "").strip()
        if not rid:
            continue
        if rid in out:
            dups.append(rid)
        out[rid] = r
    if dups:
        print(f"records 存在重复 rid：{', '.join(sorted(set(dups)))}；"
              f"先跑 dedupe.py（原地模式）或用 --start 续编 rid 再下载，"
              f"不要靠 dict 覆盖 silently 丢一篇（{source}）", file=sys.stderr)
        raise SystemExit(65)
    return out


def cmd_fetch(args):
    records = json.loads(Path(args.records).read_text(encoding="utf-8-sig"))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    found = resolve_oa(records, args.mailto, args.limit)
    by_rid = index_by_rid(records, "pdf_fetch fetch")
    pairs = [(rid, url) for rid, url in
             ((rid, found.get(norm_doi(rec.get("doi")))) for rid, rec in by_rid.items()) if url]
    print(f"OA 直链命中 {len(pairs)}/{min(len(records), args.limit or len(records))}")
    if args.dry_run:
        for rid, url in pairs[:20]:
            print(f"  {rid}  {url}")
        return 0

    results, failed = [], []

    def job(item):
        rid, url = item
        dest = outdir / pdf_name(by_rid[rid])
        rc, out, err = download(url, dest)
        ok, reason, info = validate_pdf(dest, by_rid[rid]) if dest.exists() else (False, "no_file", {})
        if not ok and dest.exists():
            q = outdir.parent / "_quarantine"
            q.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(q / dest.name))
        return {"rid": rid, "doi": by_rid[rid].get("doi", ""), "url": url, "file": dest.name,
                "status": "ok" if ok else "invalid", "bytes": info.get("bytes", 0),
                "pages": info.get("pages", 0), "doi_match": info.get("doi_match", "n/a"),
                # 统一到 scripts/reason_codes.py 的规范枚举；未登记写法落 network，不再自造第二套词汇表
                "reason": canonical(reason) if not ok else ""}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(job, pairs):
            results.append(row)
            if row["status"] != "ok":
                failed.append(row)
            time.sleep(0.15)
    # 有 DOI 但 OpenAlex 没给 OA 直链的条目此前一行都不写（静默消失，manifest 行数与
    # records 条数对不上账也没人发现）；显式登记 no_oa，让 未获取全文.md 有原因可写
    planned = {rid for rid, _ in pairs}
    eligible = None
    if args.limit:
        # --limit 是「只处理前 N 条有 DOI 的记录」；与 resolve_oa 的截断口径必须一致，
        # 否则会给被 limit 排除的条目也登记 no_oa，manifest 平白多出失败行
        eligible = {str(r.get("rid") or "").strip()
                    for r in [x for x in records if norm_doi(x.get("doi"))][:args.limit]}
    for rid in sorted(by_rid):
        if rid in planned or not norm_doi(by_rid[rid].get("doi")):
            continue
        if eligible is not None and rid not in eligible:
            continue
        row = {"rid": rid, "doi": by_rid[rid].get("doi", ""), "url": "", "file": "",
               "status": "invalid", "bytes": 0, "pages": 0, "doi_match": "n/a",
               "reason": canonical("no_oa")}
        results.append(row)
        failed.append(row)
    results.sort(key=lambda r: r["rid"])
    write_manifest(outdir.parent / "manifest.csv", results)
    print(f"✓ 下载 {len(results) - len(failed)} 篇，失败 {len(failed)} 篇 → {outdir.parent/'manifest.csv'}")
    for row in failed[:10]:
        print(f"! {row['rid']} {row['reason']} {row['file']}")
    return 0


def cmd_verify(args):
    pdfdir = Path(args.dir)
    records = index_by_rid(json.loads(Path(args.records).read_text(encoding="utf-8-sig")),
                           "pdf_fetch verify")
    rows = []
    quarantine = pdfdir.parent / "_quarantine"
    reasons = []
    for pdf in sorted(pdfdir.glob("*.pdf")):
        m = re.match(r"^([A-Z]\d{4})_", pdf.name)
        rid = m.group(1) if m else ""
        rec = records.get(rid, {})
        ok, reason, info = validate_pdf(pdf, rec) if rec else (False, "no_record", {"bytes": pdf.stat().st_size, "pages": 0, "doi_match": "n/a"})
        row = {"rid": rid, "doi": rec.get("doi", ""), "url": "", "file": pdf.name,
               "status": "ok" if ok else "invalid", "bytes": info.get("bytes", 0),
               "pages": info.get("pages", 0), "doi_match": info.get("doi_match", "n/a"),
               "reason": canonical(reason) if not ok else ""}
        rows.append(row)
        if not ok:
            quarantine.mkdir(parents=True, exist_ok=True)
            shutil.move(str(pdf), str(quarantine / pdf.name))
            reasons.append({"rid": rid, "file": pdf.name,
                            "reason": canonical(reason), "detail": ""})
    write_manifest(pdfdir.parent / "manifest.csv", rows)
    if reasons:
        with open(quarantine / "reasons.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["rid", "file", "reason", "detail"])
            w.writeheader()
            w.writerows(reasons)
    print(f"✓ 校验 {len(rows)} 个 PDF：通过 {sum(1 for r in rows if r['status']=='ok')}，"
          f"隔离 {len(reasons)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="PDF 获取与四重校验")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("--records", required=True)
    f.add_argument("--outdir", required=True)
    f.add_argument("--mailto", default="", help="OpenAlex 礼貌池邮箱；必填你自己的邮箱，不要硬编码")
    f.add_argument("--limit", type=int, default=0)
    f.add_argument("--workers", type=int, default=4)
    f.add_argument("--dry-run", action="store_true")
    f.set_defaults(func=cmd_fetch)

    v = sub.add_parser("verify")
    v.add_argument("--dir", required=True)
    v.add_argument("--records", required=True)
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    if args.cmd == "fetch" and not args.mailto:
        print("! 未提供 --mailto，OpenAlex 会降速；建议填真实邮箱（写在命令行，不写进脚本）")
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
