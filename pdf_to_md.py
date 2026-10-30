#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行（需要 pymupdf）
"""PDF → Markdown（保留标题层级、脚注、引用标记，并显式声明转换损耗）。

版面处理要点：
- 按 pymupdf 的 block 顺序渲染，只在 block 内按 y 排序 —— 避免双栏论文左右栏交错
- 字号加权众数定正文基准；≥1.12 倍或全大写短行判标题，按倍数分 H2/H3/H4
- 跨 ≥60% 页面重复的行判页眉页脚，丢弃
- 页底小字号且编号开头的行判脚注，全文按出现顺序重编号
- 引用标记（[12]、（张三，2019））原样保留
- 表格能结构化就转 MD，转不了就写「见原 PDF p.N」，绝不臆造

用法：
    /usr/bin/python3 scripts/pdf_to_md.py in.pdf -o 正文/W0007_x.md \
        --meta raw/records.json --rid W0007

退出码：0 正常；3 正文不足；4 无文本层（判扫描件）；64/65 参数或读取错误。
"""
import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_END = tuple("。！？；：.!?;:")
FOOT_RE = re.compile(r"^\s*(\d{1,3}|[①-⑳])[\s.、)）]")


def yaml_line(key, value):
    if isinstance(value, bool):
        return f"{key}: {'true' if value else 'false'}"
    if isinstance(value, (int, float)):
        return f"{key}: {value}"
    return f"{key}: {json.dumps(str(value), ensure_ascii=False)}"


def page_blocks(doc):
    """保持 block 顺序（专栏/段落边界），block 内按 y 排序。"""
    pages = []
    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        height = page.rect.height
        blocks = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            lines = []
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                txt = "".join(s.get("text", "") for s in spans).strip()
                if not txt:
                    continue
                lines.append({
                    "txt": txt,
                    "size": round(max(s.get("size", 0) for s in spans), 1),
                    "y0": line["bbox"][1], "y1": line["bbox"][3],
                    "x0": line["bbox"][0], "h": height,
                })
            if lines:
                lines.sort(key=lambda x: x["y0"])
                blocks.append(lines)
        pages.append(blocks)
    return pages


def all_lines(pages):
    for blocks in pages:
        for block in blocks:
            for line in block:
                yield line


def base_size(pages):
    counter = Counter()
    for line in all_lines(pages):
        counter[line["size"]] += len(line["txt"])
    return counter.most_common(1)[0][0] if counter else 10.0


def repeated_noise(pages):
    total = max(1, len(pages))
    hits = Counter()
    for blocks in pages:
        seen = set()
        for block in blocks:
            for line in block:
                key = re.sub(r"\d+", "#", line["txt"].strip().lower())[:80]
                if key and key not in seen and len(key) < 80:
                    hits[key] += 1
                    seen.add(key)
    return {k for k, n in hits.items() if n / total >= 0.6}


def detect_title(pages, base):
    if not pages:
        return "", 0
    first = [line for block in pages[0] for line in block][:20]
    if not first:
        return "", 0
    top = max(first, key=lambda x: x["size"])
    if top["size"] < base * 1.3 or len(top["txt"]) < 5:
        return "", 0
    idx = first.index(top)
    parts = [top["txt"]]
    for line in first[idx + 1: idx + 3]:
        if abs(line["size"] - top["size"]) < 0.3 and not line["txt"].endswith(SENT_END):
            parts.append(line["txt"])
        else:
            break
    return " ".join(parts).strip(), len(parts)


def heading_level(line, base):
    ratio = line["size"] / base if base else 1.0
    txt = line["txt"]
    if len(txt) > 60 or txt.endswith(SENT_END):
        return 0
    if ratio >= 1.5:
        return 2
    if ratio >= 1.25:
        return 3
    if ratio >= 1.12:
        return 4
    if txt.isupper() and 4 <= len(txt) <= 50 and len(txt.split()) <= 8:
        return 2
    return 0


def join_line(prev, cur):
    if prev.endswith("-") and cur[:1].islower():
        return prev[:-1] + cur
    if CJK_RE.search(prev[-1:]) or CJK_RE.search(cur[:1]):
        return prev + cur
    return prev + " " + cur


def main():
    ap = argparse.ArgumentParser(description="PDF 转 Markdown")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--meta", default="")
    ap.add_argument("--rid", default="")
    ap.add_argument("--min-chars", type=int, default=4000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        import pymupdf
    except Exception as exc:  # noqa: BLE001
        print(f"需要 pymupdf：{exc}；用 /usr/bin/python3 运行")
        raise SystemExit(64)

    src = Path(args.pdf)
    if not src.exists():
        print(f"文件不存在：{src}")
        raise SystemExit(64)
    try:
        doc = pymupdf.open(str(src))
    except Exception as exc:  # noqa: BLE001
        print(f"PDF 打不开：{exc}")
        raise SystemExit(65)

    pages = page_blocks(doc)
    base = base_size(pages)
    noise = repeated_noise(pages)
    title, title_lines = detect_title(pages, base)
    total_pages = doc.page_count

    out, footnotes = [], []
    seen_title = headings = tables_found = tables_rendered = 0
    warnings = []

    for pno, blocks in enumerate(pages, 1):
        out.append(f"<!-- p.{pno} -->")
        page_chars = sum(len(l["txt"]) for b in blocks for l in b)
        for block in blocks:
            para, prev_y1 = "", None
            for line in block:
                key = re.sub(r"\d+", "#", line["txt"].strip().lower())[:80]
                if key in noise:
                    continue
                if seen_title < title_lines and line["txt"] in title:
                    seen_title += 1
                    continue
                m = FOOT_RE.match(line["txt"])
                if line["y0"] > line["h"] * 0.82 and line["size"] < base * 0.9 and m:
                    footnotes.append({"page": pno, "marker": m.group(1),
                                      "text": FOOT_RE.sub("", line["txt"]).strip()})
                    continue
                if re.fullmatch(r"\d{1,4}", line["txt"]):
                    continue

                level = heading_level(line, base)
                if level:
                    if para:
                        out.append(para)
                        para, prev_y1 = "", None
                    out.append(f"{'#' * level} {line['txt']}")
                    headings += 1
                    continue

                if not para:
                    para = line["txt"]
                elif prev_y1 is not None and line["y0"] - prev_y1 > base * 0.45:
                    out.append(para)
                    para = line["txt"]
                else:
                    para = join_line(para, line["txt"])
                prev_y1 = line["y1"]
            if para:
                out.append(para)

        try:
            finder = doc.load_page(pno - 1).find_tables()
            for table in getattr(finder, "tables", []):
                tables_found += 1
                md = None
                try:
                    md = table.to_markdown()
                except Exception:  # noqa: BLE001
                    md = None
                if md and md.count("|") > 4:
                    out.append(md)
                    tables_rendered += 1
                else:
                    out.append(f"> 表格未结构化，见原 PDF p.{pno}")
        except Exception:  # noqa: BLE001
            pass

        if page_chars == 0:
            out.append(f"<!-- p.{pno} 无文本层（图片页）-->")

    pages_with_text = sum(1 for blocks in pages if sum(len(l["txt"]) for b in blocks for l in b) >= 50)
    ratio_text = round(pages_with_text / total_pages, 3) if total_pages else 0.0
    body = "\n\n".join(x for x in out if x.strip())
    if footnotes:
        body += "\n\n## 注释\n\n" + "\n\n".join(
            f"[^{i}]: （原编号 {f['marker']}，p.{f['page']}）{f['text']}"
            for i, f in enumerate(footnotes, 1))

    chars = len(re.sub(r"\s+", "", body))
    status = "scan" if ratio_text < 0.05 else ("ok" if chars >= args.min_chars else "thin")
    if tables_found > tables_rendered:
        warnings.append(f"{tables_found - tables_rendered} 处表格未结构化")
    if footnotes:
        warnings.append("正文上标编号未改写，注释按出现顺序重编号")

    meta = {}
    if args.meta:
        try:
            for rec in json.loads(Path(args.meta).read_text(encoding="utf-8-sig")):
                if rec.get("rid") == args.rid:
                    meta = rec
                    break
        except Exception:  # noqa: BLE001
            pass

    front = [
        "---",
        yaml_line("rid", args.rid or meta.get("rid", "")),
        yaml_line("title", meta.get("title") or title),
        yaml_line("authors", meta.get("authors", "")),
        yaml_line("source", meta.get("source", "")),
        yaml_line("year", meta.get("year", "")),
        yaml_line("cited", int(meta.get("cited") or 0)),
        yaml_line("downloads", int(meta.get("downloads") or 0)),
        yaml_line("access", "PDF"),
        yaml_line("quality_tags", ",".join(meta.get("quality_tags") or [])),
        yaml_line("chars", chars),
        yaml_line("status", status),
        yaml_line("pages", total_pages),
        yaml_line("headings", headings),
        yaml_line("footnotes", len(footnotes)),
        yaml_line("tables_found", tables_found),
        yaml_line("tables_rendered", tables_rendered),
        yaml_line("text_layer_ratio", ratio_text),
        yaml_line("engine", f"pymupdf {pymupdf.__version__}"),
        yaml_line("source_pdf", str(src)),
        yaml_line("converted_at", datetime.now().astimezone().isoformat(timespec="seconds")),
        "---", "",
        f"# {meta.get('title') or title or src.stem}", "",
    ]
    if meta.get("authors"):
        front += [f"> **作者**：{meta.get('authors')}　**出处**：{meta.get('source', '')} {meta.get('year', '')}",
                  f"> **被引 / 下载**：{meta.get('cited', 0)} / {meta.get('downloads', 0)}　**获取方式**：PDF（WOS/OA）", ""]

    front += ["## 转换损耗声明", "",
              f"- 引擎：pymupdf {pymupdf.__version__}；{total_pages} 页，文本层覆盖率 {ratio_text:.0%}",
              f"- 标题：按字号/全大写识别 {headings} 处；脚注：收集 {len(footnotes)} 条",
              f"- 表格：识别 {tables_found} 处，结构化 {tables_rendered} 处" +
              ("；其余已标注「见原 PDF」，未臆造" if tables_found > tables_rendered else ""),
              "- 图片与公式：未提取/未还原；需要图表请回原 PDF",
              "- 页眉页脚与孤立页码已去除；双栏按 block 顺序渲染，仍可能有个别顺序错乱", ""]

    outpath = Path(args.out)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text("\n".join(front) + "\n" + body + "\n", encoding="utf-8")

    result = {"rid": args.rid, "pages": total_pages, "chars": chars, "status": status,
              "headings": headings, "footnotes": len(footnotes),
              "tables": [tables_found, tables_rendered],
              "text_layer_ratio": ratio_text, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False) if args.json else
          f"{'✓' if status == 'ok' else '!'} {src.name} → {outpath.name}  {total_pages} 页 / {chars} 字 / "
          f"标题 {headings} / 脚注 {len(footnotes)} / 文本层 {ratio_text:.0%} / status={status}")
    raise SystemExit(0 if status == "ok" else (3 if status == "thin" else 4))


if __name__ == "__main__":
    main()
