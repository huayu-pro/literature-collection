#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""知网阅读页节点 JSON → Markdown。

保留标题层级；把页内脚注（(1)/（1）/① 这类按页重置的编号）改为全局 [^n] 并在文末「## 注释」保留原编号。
引用标记（[12]、（张三，2019））原样保留，不改写、不重排。

用法：
    /usr/bin/python3 scripts/html_to_md.py page.json -o 正文/C0001_篇名.md \
        --meta raw/cnki_records.json --rid C0001 --min-chars 4000

退出码：0 正常；3 正文不足 min-chars（文件仍写出，status=thin）；2 缺参数(argparse)；64/65 用法或数据错误。
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

NOISE = ("引证文献", "问答精要", "核心观点", "文章大纲", "进入CNKI AI", "向右滑动验证",
         "参考文献", "相关文献", "读者推荐", "下载本文", "分享到")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
DEF_PAREN_RE = re.compile(r"^[（(](\d{1,3})[）)]\s*(.+)$")
DEF_CIRCLE_RE = re.compile(r"^([①-⑳])\s*(.+)$")


def yaml_line(key, value):
    if isinstance(value, bool):
        return f"{key}: {'true' if value else 'false'}"
    if isinstance(value, int):
        return f"{key}: {value}"
    return f"{key}: {json.dumps(str(value), ensure_ascii=False)}"


def load_nodes(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        nodes = data.get("nodes") or data.get("items") or []
        chars = data.get("chars")
    elif isinstance(data, list):
        nodes, chars = data, None
    else:
        raise ValueError("输入必须是 {nodes:[...]} 或节点数组")
    clean = []
    for n in nodes:
        if isinstance(n, str):
            clean.append({"tag": "P", "txt": n})
        elif isinstance(n, dict):
            tag = (n.get("tag") or n.get("type") or "P").upper()
            txt = n.get("txt") or n.get("text") or n.get("innerText") or ""
            if txt.strip():
                clean.append({"tag": tag, "txt": txt})
    return clean, chars


def to_int(value):
    try:
        return int(re.sub(r"[^\d]", "", str(value or "")) or 0)
    except Exception:  # noqa: BLE001
        return 0


def find_meta(path, rid):
    if not path:
        return {}
    try:
        records = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if isinstance(records, dict):  # {"records":[...]} 包装形态
            records = records.get("records") or []
        if not isinstance(records, list):
            return {}
        for rec in records:
            if isinstance(rec, dict) and rec.get("rid") == rid:
                return rec
    except Exception:  # noqa: BLE001
        pass
    return {}


def collect_footnotes(nodes):
    """只在末尾 12 个节点里认脚注定义，避免把正文里的「（1）第一，…」误判。

    页内重置编号（(1)/（1）/①）必然产生两个不同的「（1）」注：
    同名定义按出现顺序收成列表，绝不 setdefault 丢弃——丢第二个定义是静默错挂。
    返回 defs={marker:[body...]} 与 def_nodes={节点索引: 第几个同名定义}。
    """
    defs, def_nodes, seen = {}, {}, {}
    for i in range(max(0, len(nodes) - 12), len(nodes)):
        txt = nodes[i]["txt"].strip()
        if len(txt) > 400:
            continue
        m = DEF_PAREN_RE.match(txt) or DEF_CIRCLE_RE.match(txt)
        if m:
            marker, body = m.group(1), m.group(2).strip()
            if body:
                seen[marker] = seen.get(marker, 0) + 1
                defs.setdefault(marker, []).append(body)
                def_nodes[i] = (marker, seen[marker])
    return defs, def_nodes


def number_footnotes(body, defs):
    """按正文出现顺序编号：同名标记第 n 次出现配第 n 个同名定义（页内重置语义）。

    出现次数超出定义数时，超出部分保留原文（无法配对就不瞎配）；
    返回 (body, notes)，notes={全局序号: (marker, 定义实例)} 按消费顺序。
    """
    patterns = []
    if any(c in defs for c in CIRCLED):
        patterns.append(r"[①-⑳]")
    paren = sorted([m for m in defs if m.isdigit()], key=len, reverse=True)
    if paren:
        patterns.append(r"[（(](?:" + "|".join(re.escape(m) for m in paren) + r")[）)]")
    if not patterns:
        return body, {}
    pattern = re.compile("|".join(patterns))
    used = {marker: 0 for marker in defs}
    notes = {}

    def repl(match):
        raw = match.group(0)
        key = raw.strip("（）()")
        if key not in defs:
            return raw
        used[key] += 1
        if used[key] > len(defs[key]):  # 引用多于定义（漏抓定义页）
            used[key] -= 1
            return raw
        notes[len(notes) + 1] = (key, defs[key][used[key] - 1])
        return f"[^{len(notes)}]"

    return pattern.sub(repl, body), notes


def render(nodes, title, defs, def_nodes):
    lines = []
    for i, node in enumerate(nodes):
        if i in def_nodes:  # 疑似定义先剔除，配不上号的再放回正文
            continue
        tag, txt = node["tag"], node["txt"].replace("\u00a0", " ").strip()
        if not txt:
            continue
        if any(w in txt for w in NOISE) and len(txt) < 40:
            continue
        if tag == "H1":
            if not lines and txt.replace(" ", "") == (title or "").replace(" ", ""):
                continue
            lines.append(f"## {txt}")
            continue
        if tag == "H2":
            lines.append(f"### {txt}")
            continue
        if tag in ("H3", "H4", "H5"):
            lines.append(f"{'#' * (int(tag[1]) + 1)} {txt}")
            continue
        if tag in ("LI", "UL", "OL"):
            lines.append(f"- {txt.lstrip('·•-　 ')}")
            continue
        lines.append(txt)

    body, notes = number_footnotes("\n\n".join(lines), defs)
    # 正文中没被引用到的定义（疑似误判的结论段/漏抓标记的定义）不无痕删除，按原位补回正文
    used_counts = {}
    for marker, _ in notes.values():
        used_counts[marker] = used_counts.get(marker, 0) + 1
    leftovers = []
    for i in sorted(def_nodes):
        marker, nth = def_nodes[i]
        if used_counts.get(marker, 0) < nth:
            leftovers.append(nodes[i]["txt"].replace("\u00a0", " ").strip())
    if leftovers:
        body += "\n\n" + "\n\n".join(leftovers)
    if notes:
        note_lines = [f"[^{num}]: （原编号 {marker}）{text}"
                      for num, (marker, text) in sorted(notes.items())]
        body += "\n\n## 注释\n\n" + "\n\n".join(note_lines)
    return body, len(notes)


def count_chars(text):
    return len(re.sub(r"\s+", "", text))


def main():
    ap = argparse.ArgumentParser(description="知网阅读页节点 JSON 转 Markdown")
    ap.add_argument("page", help="bsk evaluate 输出的 JSON")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--meta", default="", help="records.json，用于补题录")
    ap.add_argument("--rid", default="")
    ap.add_argument("--min-chars", type=int, default=4000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        nodes, reported_chars = load_nodes(args.page)
    except Exception as exc:  # noqa: BLE001
        print(f"解析失败：{exc}", file=sys.stderr)
        sys.exit(65)
    if not nodes:
        print("没有节点（选择器可能没抓到 .pdfFullBox .study-c）", file=sys.stderr)
        sys.exit(65)

    meta = find_meta(args.meta, args.rid)
    title = meta.get("title") or next((n["txt"].strip() for n in nodes if n["tag"] == "H1"), "")
    defs, def_nodes = collect_footnotes(nodes)
    body, note_count = render(nodes, title, defs, def_nodes)
    chars = count_chars(body)
    status = "ok" if chars >= args.min_chars else "thin"
    headings = len(re.findall(r"^#{2,5} ", body, re.M))

    front = [
        "---",
        yaml_line("rid", args.rid or meta.get("rid", "")),
        yaml_line("title", title),
        yaml_line("authors", meta.get("authors", "")),
        yaml_line("source", meta.get("source", "")),
        yaml_line("year", meta.get("year", "")),
        yaml_line("cited", to_int(meta.get("cited"))),
        yaml_line("downloads", to_int(meta.get("downloads"))),
        yaml_line("access", "HTML"),
        yaml_line("quality_tags", ",".join(meta.get("quality_tags") or [])),
        yaml_line("chars", chars),
        yaml_line("status", status),
        yaml_line("headings", headings),
        yaml_line("footnotes", note_count),
        yaml_line("fetched_at", datetime.now().astimezone().isoformat(timespec="seconds")),
        "---",
        "",
        f"# {title}" if title else "",
        "",
    ]
    if meta.get("authors"):
        front += [
            f"> **作者**：{meta.get('authors')}　**出处**：{meta.get('source', '')} {meta.get('year', '')}",
            f"> **被引 / 下载**：{meta.get('cited', 0)} / {meta.get('downloads', 0)}　**获取方式**：HTML 阅读全文（经滑块验证）",
            "",
        ]
    front += ["## 转换说明", "",
              f"> 本文由知网 HTML 阅读页正文转为 Markdown：保留标题层级与引用标记；脚注全局重编号 {note_count} 条，原编号见文末注释。"
              f"正文字符数 {chars}（页面报告 {reported_chars if reported_chars is not None else '未提供'}）。", ""]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(front) + "\n" + body + "\n", encoding="utf-8")

    result = {"rid": args.rid, "out": str(out), "chars": chars, "status": status,
              "headings": headings, "footnotes": note_count}
    print(json.dumps(result, ensure_ascii=False) if args.json else
          f"{'✓' if status == 'ok' else '!'} {out.name}  {chars} 字 / {headings} 个标题 / {note_count} 条脚注 / status={status}")
    sys.exit(0 if status == "ok" else 3)


if __name__ == "__main__":
    main()
