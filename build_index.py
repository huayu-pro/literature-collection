#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""扫描实际文件重建索引：索引.md + index.csv + index_stats.json。

只信文件系统：题录来自 records.json，正文/PDF 来自磁盘实际文件。
有记录无文件 → 「文件缺失，待核对」；有文件无记录 → 「未登记文件，待核对」；不猜补。

用法：
    /usr/bin/python3 scripts/build_index.py <工作目录> --title "基层治理数字化"
    /usr/bin/python3 scripts/build_index.py <目录> --md-dir 论文MD --recursive --json
"""
import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import INDEX_COLUMNS, score_weights  # noqa: E402

RID_RE = re.compile(r"^([A-Z]\d{4})_")
PLATFORM_LABEL = {"cnki": "中国知网（CNKI）", "wos": "Web of Science", "unknown": "未识别平台"}


def parse_front_matter(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = next((i for i in range(1, min(len(lines), 80)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, "\n".join(lines[end + 1:])


def read_records(path):
    if not path or not Path(path).exists():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, list) or not data:
        return None
    out, dups = {}, []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        rid = (rec.get("rid") or "").strip()
        if rid:
            if rid in out:
                dups.append(rid)
            out[rid] = rec
    if dups:  # 与 export_citations 口径一致：绝不静默 last-wins 丢一篇
        print(f"records 存在重复 rid：{', '.join(sorted(set(dups)))}；"
              f"先跑 dedupe.py（原地模式），同 rid 不同文献需人工重编 rid", file=sys.stderr)
        raise SystemExit(65)
    return out


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def collect(md_dirs, pdf_dirs, recursive):
    """按 rid 前缀分组；没有 rid 的文件单独收集，后面自动编号。"""
    md_files, pdf_files, orphan_md, orphan_pdf = {}, {}, [], []
    for d in md_dirs:
        p = Path(d)
        if not p.exists():
            continue
        for f in (p.rglob("*.md") if recursive else p.glob("*.md")):
            m = RID_RE.match(f.name)
            (md_files.setdefault(m.group(1), []) if m else orphan_md).append(f)
    for d in pdf_dirs:
        p = Path(d)
        if not p.exists():
            continue
        for f in (p.rglob("*.pdf") if recursive else p.glob("*.pdf")):
            m = RID_RE.match(f.name)
            (pdf_files.setdefault(m.group(1), []) if m else orphan_pdf).append(f)
    return md_files, pdf_files, sorted(orphan_md), sorted(orphan_pdf)


def legacy_meta(body):
    """兼容早期归档：没有 YAML front-matter，用引用块记录元信息。"""
    head = "\n".join(body.splitlines()[:14])
    meta = {}
    for key, pattern in (("authors", r"\*\*作者\*\*[：:]\s*([^　\n|]+)"),
                         ("source", r"\*\*出处\*\*[：:]\s*([^　\n|]+)"),
                         ("cited_download", r"\*\*被引\s*/\s*下载\*\*[：:]\s*([0-9]+\s*/\s*[0-9]+)"),
                         ("access", r"\*\*正文来源\*\*[：:]\s*([^　\n|]+)")):
        m = re.search(pattern, head)
        if m:
            meta[key] = m.group(1).strip()
    if "cited_download" in meta:
        cited, _, downloads = meta.pop("cited_download").partition("/")
        meta["cited"], meta["downloads"] = cited.strip(), downloads.strip()
    m = re.search(r"^#\s+(.+)$", body, re.M)
    if m:
        meta["title"] = m.group(1).strip()
    if "中国知网" in head or "CNKI" in head:
        meta["platform"] = "cnki"
    return meta


def infer_platform(rid, rec, meta):
    if rec.get("platform"):
        return rec["platform"]
    if meta.get("platform"):
        return meta["platform"]
    if rid.startswith("C"):
        return "cnki"
    if rid.startswith("W"):
        return "wos"
    return "unknown"


def choose(cands, manifest_ok):
    """优先 manifest status=ok，其次正文字数/文件体积大者，最后名字短者。"""
    if len(cands) == 1:
        return cands[0]
    return sorted(cands, key=lambda p: (0 if p.name in manifest_ok else 1,
                                       -p.stat().st_size, len(p.name)))[0]


def manifest_ok_files(workdir):
    p = workdir / "manifest.csv"
    if not p.exists():
        return set()
    try:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            return {Path(r.get("file", "")).name for r in csv.DictReader(fh)
                    if (r.get("status") or "") == "ok"}
    except Exception:  # noqa: BLE001
        return set()


def failure_reasons(workdir):
    """未获取原因登记，优先级从低到高：
    1. manifest.csv 失败行（PDF 通道的下载结果）
    2. raw/no_html_reasons.json（plan_download.py 登记的「无 HTML 入口」——v1.3 里这批
       条目在 未获取全文.md 只能显示「未登记原因」，原因链断在这里）
    3. _quarantine/reasons.csv（人工或 pdf_fetch verify 隔离的最终结论，最高优先）
    """
    reasons = {}
    p = workdir / "manifest.csv"
    if p.exists():
        try:
            with open(p, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    if (r.get("status") or "") != "ok":
                        reasons[r.get("rid", "")] = (r.get("reason") or "").strip() or "未登记原因"
        except Exception:  # noqa: BLE001
            pass
    nh = workdir / "raw" / "no_html_reasons.json"
    if nh.exists():
        try:
            for r in json.loads(nh.read_text(encoding="utf-8-sig")):
                if isinstance(r, dict) and r.get("rid"):
                    reason = (r.get("reason") or "").strip()
                    detail = (r.get("detail") or "").strip()
                    reasons[r["rid"]] = " / ".join(x for x in (reason, detail) if x) or "未登记原因"
        except Exception:  # noqa: BLE001
            pass
    q = workdir / "_quarantine" / "reasons.csv"
    if q.exists():
        try:
            with open(q, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    if r.get("rid"):
                        reasons[r["rid"]] = (r.get("reason") or "").strip() or "已隔离（见 reasons.csv）"
        except Exception:  # noqa: BLE001
            pass
    return reasons


def source_links(rec, platform):
    """题录可回链：知网详情页 / WoS full-record / DOI。一条都没有就明确标注待补。"""
    links = []
    url = (rec.get("url") or "").strip()
    if url:
        links.append(("知网详情页" if platform == "cnki" else "来源链接", url))
    ut = (rec.get("ut") or "").strip()
    if ut:
        links.append(("WoS 记录", f"https://www.webofscience.com/wos/woscc/full-record/{ut}"))
    doi = (rec.get("doi") or "").strip().lower()
    if doi:
        links.append(("DOI", f"https://doi.org/{doi}"))
    return links


def render_no_fulltext(workdir, title, missing_rows, records, reasons, generated):
    """题录在手、全文未获取的记录单独成册：每条给题录 + 回链 + 失败原因，方便人工补齐。"""
    lines = [
        f"# {title} · 未获取全文清单", "",
        f"> 生成时间：{generated}　条目：{len(missing_rows)} 篇",
        "> 这些文献的题录已收录进索引与文献题录.txt，但 HTML/PDF 全文未获取。",
        "> 每条附获取链接与失败原因；按原因决定：付费墙 → 机构内手动下载；扫描件/无 OA → 换文献或只留题录。",
        "",
    ]
    by_plat = {}
    for r in missing_rows:
        by_plat.setdefault(r["platform"], []).append(r)
    for plat in sorted(by_plat):
        rows = by_plat[plat]
        lines += [f"## {PLATFORM_LABEL.get(plat, plat)}（{len(rows)} 篇）", ""]
        for r in rows:
            rec = records.get(r["rid"], {})
            lines.append(f"### {r['rid']}　{r['title']}")
            bits = [b for b in (r["authors"], f"{r['source']} {r['year']}".strip(),
                                f"被引 {r['cited']} / 下载 {r['downloads']}") if b]
            lines.append(f"- 题录：{' · '.join(bits)}")
            keywords = rec.get("keywords")
            if isinstance(keywords, (list, tuple)):
                keywords = ";".join(keywords)
            if keywords:
                lines.append(f"- 关键词：{keywords}")
            reason = reasons.get(r["rid"], "未登记原因（检查 manifest.csv / _quarantine/reasons.csv）")
            lines.append(f"- 未获取原因：{reason}")
            links = source_links(rec, plat)
            if links:
                lines.append("- 获取链接：" + " · ".join(f"[{t}]({u})" for t, u in links))
            else:
                lines.append("- 获取链接：待补（题录无 url/ut/doi，需回检索平台补抓）")
            lines.append("")
    lines += ["## 补齐后", "",
              "```bash",
              f'/usr/bin/python3 scripts/build_index.py "{workdir}" --title "{title}"',
              "```",
              "重跑后本清单与索引同步更新；补齐的条目会自动从本清单消失。", ""]
    return "\n".join(lines)


def rel_of(path, workdir):
    try:
        return path.relative_to(workdir).as_posix()
    except Exception:  # noqa: BLE001
        return str(path)


def normalize_access(value, md, pdf):
    v = (value or "").upper()
    if "HTML" in v:
        return "HTML"
    if "PDF" in v or "原版" in v:
        return "PDF"
    return "HTML" if md else "PDF" if pdf else ""


def make_row(workdir, rid, rec, mds, pdfs, min_chars, ok_names):
    md = choose(mds, ok_names) if mds else None
    pdf = choose(pdfs, ok_names) if pdfs else None
    meta, body = parse_front_matter(md) if md else ({}, "")
    if md and not meta:
        meta = legacy_meta(body)
    chars = safe_int(meta.get("chars"), len(re.sub(r"\s+", "", body)))
    status = (meta.get("status") or "").strip()
    if not status and md:
        status = "ok" if chars >= min_chars else "thin"

    if not md and not pdf:
        row_status, note = "missing_file", "文件缺失，待核对"
    elif not rec and rid.startswith("X"):
        row_status, note = "unregistered", "未登记文件，待核对"
    elif not rec:
        row_status, note = "unregistered", "未登记文件，待核对"
    else:
        row_status, note = (status or "ok"), ""
    if row_status == "ok" and md and chars < min_chars:
        row_status, note = "thin", f"篇幅不足（{chars} 字）"

    fallback_title = (md or pdf).stem.split("_", 1)[-1] if (md or pdf) else rid
    row = {
        "rid": rid,
        "platform": infer_platform(rid, rec, meta),
        "title": rec.get("title") or meta.get("title") or fallback_title,
        "authors": rec.get("authors") or meta.get("authors") or "",
        "source": rec.get("source") or meta.get("source") or "",
        "year": str(rec.get("year") or meta.get("year") or ""),
        "cited": safe_int(rec.get("cited") if rec else meta.get("cited")),
        "downloads": safe_int(rec.get("downloads") if rec else meta.get("downloads")),
        "quality_tags": ",".join(rec.get("quality_tags") or []) or meta.get("quality_tags", ""),
        "access": normalize_access(rec.get("access") or meta.get("access"), md, pdf),
        "rel_path_md": rel_of(md, workdir) if md else "",
        "rel_path_pdf": rel_of(pdf, workdir) if pdf else "",
        "chars": chars,
        "status": row_status,
        "note": note,
        # score / citedness_2yr 由 fill_scores() 在整批归一时回填（见下方 §6 公式）
        "score": "",
        "citedness_2yr": "",
    }
    dups = [{"rid": rid, "kept": (md or pdf).name, "duplicate": extra.name,
             "reason": "同一 rid 多个文件"}
            for extra in mds + pdfs if extra not in (md, pdf)]
    return row, dups


def build_rows(workdir, records, md_files, pdf_files, orphan_md, orphan_pdf, min_chars, ok_names):
    rows, duplicates = [], []
    rids = sorted(set(records) | set(md_files) | set(pdf_files))
    for rid in rids:
        row, dups = make_row(workdir, rid, records.get(rid, {}),
                             md_files.get(rid, []), pdf_files.get(rid, []), min_chars, ok_names)
        rows.append(row)
        duplicates += dups
    for i, md in enumerate(orphan_md, 1):
        row, dups = make_row(workdir, f"X{i:04d}", {}, [md], [], min_chars, ok_names)
        row["note"] = "未登记文件，待核对（自动编号）"
        rows.append(row)
        duplicates += dups
    for j, pdf in enumerate(orphan_pdf, len(orphan_md) + 1):
        row, dups = make_row(workdir, f"X{j:04d}", {}, [], [pdf], min_chars, ok_names)
        row["note"] = "未登记文件，待核对（自动编号）"
        rows.append(row)
        duplicates += dups
    fill_scores(rows, records)
    return rows, duplicates


def fill_scores(rows, records):
    """quality-screening.md §6：score = 0.75*norm(cited) + 0.15*norm(citedness_2yr)
    + 0.10*norm(主题词命中数)；只排不记等于没排，所以分数与代理指标都写进 index.csv。
    norm 用批次内 min-max（全批次同一值 → 该维度全 0，不制造虚假区分度）。"""
    def values(key, cast=int):
        out = []
        for r in rows:
            rec = records.get(r["rid"]) or {}
            raw = r.get(key)
            if raw in ("", None):
                raw = rec.get("citedness_2yr") if key == "citedness_2yr" else rec.get(key)
            try:
                out.append(cast(raw))
            except Exception:  # noqa: BLE001
                out.append(0)
        return out

    def normed(vals):
        lo, hi = min(vals), max(vals)
        if hi == lo:
            return [0.0] * len(vals)
        return [(v - lo) / (hi - lo) for v in vals]

    n_cited = normed(values("cited"))
    n_2yr = normed([float(v) for v in values("citedness_2yr", float)])
    n_topic = normed(values("topic_hits"))
    w = score_weights()
    for i, r in enumerate(rows):
        s = w["cited"] * n_cited[i] + w["citedness_2yr"] * n_2yr[i] + w["topic_hits"] * n_topic[i]
        r["score"] = round(s, 4)
        rec = records.get(r["rid"]) or {}
        v2 = rec.get("citedness_2yr")
        r["citedness_2yr"] = "" if v2 in ("", None) else v2


def render_markdown(workdir, title, rows, stats, generated):
    lines = [
        f"# {title} · 文献索引", "",
        f"> 生成时间：{generated}　生成脚本：`scripts/build_index.py`",
        f"> 条目总数：{stats['total']}　有正文：{stats['with_md']}　有 PDF：{stats['with_pdf']}",
        "> 口径：本索引由脚本扫描实际文件重建，不依赖记忆或对话上下文。",
        "> 「文件缺失，待核对」表示题录里有记录但磁盘上没有对应文件；不自动补、不猜。", "",
        "## 一、总览", "",
        "| 平台 | 条数 | 有正文 | 有 PDF | 位置 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for plat, count in sorted(stats["by_platform"].items()):
        sub = [r for r in rows if r["platform"] == plat]
        lines.append(f"| {PLATFORM_LABEL.get(plat, plat)} | {count} | "
                     f"{sum(1 for r in sub if r['rel_path_md'])} | "
                     f"{sum(1 for r in sub if r['rel_path_pdf'])} | `{workdir}` |")

    lines += ["", "## 二、文献清单", ""]
    for plat in sorted(stats["by_platform"]):
        lines += [f"### {PLATFORM_LABEL.get(plat, plat)}", ""]
        for r in [x for x in rows if x["platform"] == plat]:
            target = r["rel_path_md"] or r["rel_path_pdf"]
            link = f"[{r['title']}]({quote(target, safe='/')})" if target else r["title"]
            bits = [b for b in (r["authors"], f"{r['source']} {r['year']}".strip(),
                                f"被引 {r['cited']} / 下载 {r['downloads']}",
                                r["access"], r["quality_tags"]) if b]
            mark = "" if r["status"] in ("ok",) else f"　**（{r['note'] or r['status']}）**"
            lines.append(f"- **{r['rid']}** {link}　—　{' · '.join(bits)}{mark}")
        lines.append("")

    missing = [r for r in rows if r["status"] in ("missing_file", "unregistered", "thin")]
    lines += ["## 三、缺口与待核对", ""]
    if not missing:
        lines.append("本批次无缺失文件。")
    else:
        if any(r["status"] == "missing_file" for r in missing):
            lines.append(f"- 全文未获取的条目详见 [未获取全文.md](未获取全文.md)"
                         f"（含题录、获取链接与失败原因，共 {stats['no_fulltext']} 篇）")
        for r in missing:
            lines.append(f"- **{r['rid']}** {r['title']}　—　{r['status']}：{r['note']}")
    lines += ["", "## 四、复现命令", "", "```bash",
              f'/usr/bin/python3 scripts/build_index.py "{workdir}" --title "{title}"',
              f'/usr/bin/python3 scripts/verify_delivery.py "{workdir}" --json',
              "```", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="扫描文件重建文献索引")
    ap.add_argument("workdir")
    ap.add_argument("--title", default="")
    ap.add_argument("--records", default="", help="默认 <workdir>/raw/records.json")
    ap.add_argument("--md-dir", action="append", default=[], help="可重复，默认 正文")
    ap.add_argument("--pdf-dir", action="append", default=[], help="可重复，默认 pdf")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--outdir", default="", help="索引产物输出目录，默认与 workdir 相同")
    ap.add_argument("--min-chars", type=int, default=4000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser().resolve()
    if not wd.is_dir():
        print(f"目录不存在：{wd}")
        raise SystemExit(64)
    outdir = Path(args.outdir).expanduser().resolve() if args.outdir else wd
    outdir.mkdir(parents=True, exist_ok=True)

    # 默认同时扫 正文/ 与 备选/：文档要求备选文件进索引，漏扫会让 verify 位 1 报未入索引
    md_dirs = [wd / d if not Path(d).is_absolute() else Path(d)
               for d in (args.md_dir or ["正文", "备选"])]
    pdf_dirs = [wd / d if not Path(d).is_absolute() else Path(d) for d in (args.pdf_dir or ["pdf"])]
    # records.json 是题录唯一真源；它不存在时才依次降级（dedup 产物 → 知网单跑产物），三者口径与
    # export_citations.py / verify_delivery.py 保持一致，避免有的脚本看得见题录、有的看不见
    if args.records:
        records = read_records(args.records)
    else:
        records = None
        for name in ("records.json", "records.dedup.json", "cnki_records.json"):
            records = read_records(wd / "raw" / name)
            if records is not None:
                break
        if records is None:
            records = {}
    md_files, pdf_files, orphan_md, orphan_pdf = collect(md_dirs, pdf_dirs, args.recursive)
    rows, duplicates = build_rows(wd, records, md_files, pdf_files, orphan_md, orphan_pdf,
                                  args.min_chars, manifest_ok_files(wd))

    stats = {
        "total": len(rows),
        "with_md": sum(1 for r in rows if r["rel_path_md"]),
        "with_pdf": sum(1 for r in rows if r["rel_path_pdf"]),
        "missing_file": sum(1 for r in rows if r["status"] == "missing_file"),
        "unregistered": sum(1 for r in rows if r["status"] == "unregistered"),
        "thin": sum(1 for r in rows if r["status"] == "thin"),
        "no_fulltext": 0,
        "by_access": {},
        "by_platform": {},
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    for r in rows:
        stats["by_access"][r["access"] or "none"] = stats["by_access"].get(r["access"] or "none", 0) + 1
        stats["by_platform"][r["platform"]] = stats["by_platform"].get(r["platform"], 0) + 1

    no_fulltext_rows = [r for r in rows if r["status"] == "missing_file"]
    stats["no_fulltext"] = len(no_fulltext_rows)

    with open(outdir / "index.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (outdir / "index_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # 重跑必须重写或删除：v1.3 里旧文件既不覆写也不删除，去重解决后旧名残留会让
    # verify 位 1 把它当「已豁免」，真正未入索引的文件被放行（陈旧豁免 = 门禁失效）
    dup_path = outdir / "index_duplicates.csv"
    if duplicates:
        with open(dup_path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["rid", "kept", "duplicate", "reason"])
            w.writeheader()
            w.writerows(duplicates)
    else:
        dup_path.unlink(missing_ok=True)

    title = args.title or wd.name
    md_text = render_markdown(wd, title, rows, stats, stats["generated_at"])
    (outdir / "索引.md").write_text(md_text, encoding="utf-8")

    if no_fulltext_rows:
        nf_text = render_no_fulltext(wd, title, no_fulltext_rows, records,
                                     failure_reasons(wd), stats["generated_at"])
        (outdir / "未获取全文.md").write_text(nf_text, encoding="utf-8")
    else:
        (outdir / "未获取全文.md").unlink(missing_ok=True)  # 补齐后重跑即自动清掉旧清单

    if args.json:
        print(json.dumps({**stats, "duplicates": len(duplicates)}, ensure_ascii=False, indent=2))
    else:
        print(f"✓ {stats['total']} 条 → {outdir/'索引.md'}")
        print(f"  正文 {stats['with_md']} / PDF {stats['with_pdf']} / 缺失 {stats['missing_file']} "
              f"/ 未登记 {stats['unregistered']} / 篇幅不足 {stats['thin']}")
        if no_fulltext_rows:
            print(f"  ! {len(no_fulltext_rows)} 篇未获取全文 → {outdir/'未获取全文.md'}"
                  f"（题录 + 获取链接 + 失败原因）")
        if duplicates:
            print(f"! {len(duplicates)} 个重复文件已记入 index_duplicates.csv（未删除）")


if __name__ == "__main__":
    main()
