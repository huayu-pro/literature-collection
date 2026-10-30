#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""把 records.json 导出成文献题录 txt（可直接导入 NoteExpress / EndNote / RefWorks）。

格式对照真实导出样例复刻，两种格式互不兼容，按平台分开输出：
- 知网格式（platform=cnki 的记录）：RT/SR/A1/AD/T1/JF/YR/.../DS/LK 标签，记录间空行，
  UTF-8 无 BOM + CRLF。对照样例 CNKI-20261024151227296.txt。
- WoS 格式（platform=wos 的记录）：FN/VR 头 + PT/AU/TI/.../ER，续行缩进 3 空格，
  UTF-8 带 BOM + LF。对照样例 savedrecs.txt。

文件命名：单平台批次写「文献题录.txt」；两个平台都有记录时，两种格式不能混在一个
文件里（导入器只认一种），改为「文献题录_知网.txt」+「文献题录_WOS.txt」。

WoS 记录优先用 wos_parse.py 保留的 raw 原始字段（导出保真），缺失时退回规范化字段。

其他格式（--format，全平台记录一起导）：
  gbt7714 → 参考文献.md（GB/T 7714-2015 顺序编码制，写综述直接可用）
  apa    → 参考文献-apa.md（APA 第 7 版）
  mla    → 参考文献-mla.md（MLA 第 9 版 Works Cited）
  ris     → 文献题录.ris（Zotero/EndNote 通用导入）
  bibtex  → 文献题录.bib（LaTeX/Zotero）

用法：
    /usr/bin/python3 scripts/export_citations.py <工作目录> [--records 路径] [--json]
    /usr/bin/python3 scripts/export_citations.py <工作目录> --only cnki   # 只导知网记录
    /usr/bin/python3 scripts/export_citations.py <工作目录> --format gbt7714
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# 知网格式字段输出顺序（对照样例归纳；LA 后的分号是样例原样）
CNKI_ORDER = [
    ("RT", "rt"), ("SR", "sr"), ("A1", "a1"), ("AD", "ad"), ("T1", "t1"),
    ("JF", "jf"), ("YR", "yr"), ("IS", "is"), ("vo", "vo"), ("OP", "op"),
    ("K1", "k1"), ("AB", "ab"), ("SN", "sn"), ("CN", "cn"), ("LA", "la"),
    ("DS", "ds"), ("LK", "lk"), ("DO", "do"),
]
# WoS 格式字段输出顺序（对照 savedrecs.txt；涵盖 71 字段导出中常用的全部标签）
# 覆盖 wos-playbook 71 字段导出中的全部标签（含 BE/GP/FP/PN/MA/DL/D2、SU）；
# RIC 不在 71 字段清单里，不输出。
# v1.3 漏了 SU（Research Areas）：wos-playbook §8 的 71 字段清单里有它，WOS_ORDER 里
# 没有，于是 wos_parse.py 解析出来的 su 值被静默丢弃，导出文件比真实导出少一列。
WOS_ORDER = [
    "PT", "AU", "AF", "BA", "BF", "CA", "TI", "SO", "SE", "BS", "LA", "DT",
    "CT", "CY", "CL", "SP", "HO", "DE", "ID", "AB", "C1", "C3", "RP", "EM",
    "RI", "OI", "SI", "FU", "FX", "CR", "NR", "TC", "Z9", "U1", "U2",
    "PU", "PI", "PA", "SN", "EI", "BN", "J9", "JI", "PD", "PY", "VL", "IS",
    "AR", "BP", "EP", "DI", "EA", "PG", "WC", "WE", "SC", "GA", "UT", "PM",
    "OA", "HC", "HP", "DA", "BE", "GP", "FP", "PN", "SU", "MA", "DL", "D2", "ER",
]
WOS_LINE_WIDTH = 78          # 含 3 空格缩进，样例续行折行宽度
WOS_INDENT = "   "
# 样例中多值字段逐值一行（AU Deberdt, R / "   Le Billon, P"），不是分号连接
WOS_MULTI_VALUE_TAGS = {"AU", "AF", "BA", "BF", "CA", "C1", "C3", "OI", "SI"}
# 样例 18 条 AB 全部单行（最长 1923 字符）——AB 不折行
WOS_NO_FOLD_TAGS = {"AB"}

CNKI_TYPE_MAP = {
    "期刊": "Journal Article", "Journal Article": "Journal Article", "Article": "Journal Article",
    "学位论文": "Dissertation", "Dissertation": "Dissertation",
    "会议": "Proceedings Article", "Proceedings Article": "Proceedings Article",
    "报纸": "Newspaper Article", "Newspaper Article": "Newspaper Article",
    "图书": "Book", "Book": "Book", "Book Chapter": "Book Chapter",
}


def flat(value):
    """list → 分号连接；内部换行归一为空格——裸换行会破坏题录标签格式（导入器按行切记录）。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ";".join(str(v).strip() for v in value if str(v).strip())
    return re.sub(r"[\r\n\t]+", " ", str(value)).strip()


def load_records(workdir, explicit):
    """题录唯一真源是 records.json；dedup 产物次之；知网单跑时是 cnki_records.json。"""
    candidates = [Path(explicit)] if explicit else [
        workdir / "raw" / "records.json",
        workdir / "raw" / "records.dedup.json",
        workdir / "raw" / "cnki_records.json",
    ]
    dup_source = None
    for p in candidates:
        if p and p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(data, list) and data:
                recs = [r for r in data if isinstance(r, dict)]
                dups = [rid for rid in {r.get("rid") for r in recs}
                        if sum(1 for r in recs if r.get("rid") == rid) > 1]
                if dups:
                    # 重复 rid 会让题录条数与索引口径分裂（build_index 按 rid 去重）。
                    # 不死锁：继续降级读 records.dedup.json——G5 先跑 dedupe 后这里能接上
                    dup_source = p
                    continue
                return p, recs
    if dup_source:
        print(f"{dup_source.name} 去重后仍存在重复 rid——多半是同一 rid 挂了两篇不同文献，"
              f"dedupe 合不掉；人工核查 records.json，为不同文献重编 rid 后再导出",
              file=sys.stderr)
        sys.exit(65)
    return None, []


def platform_of(rec):
    p = (rec.get("platform") or "").lower()
    if p in ("cnki", "wos"):
        return p
    return "cnki" if str(rec.get("rid", "")).startswith("C") else (
        "wos" if str(rec.get("rid", "")).startswith("W") else "cnki")


# ---------- 知网格式 ----------

def cnki_entry(rec, seq):
    g = lambda k: flat(rec.get(k))  # noqa: E731
    values = {
        "rt": CNKI_TYPE_MAP.get(g("type"), "Journal Article"),
        "sr": "1",  # 样例 13 条记录 SR 恒为 1，不写导出序号
        "a1": g("authors") or g("author"),
        "ad": g("institution") or g("affiliation") or g("ad"),
        "t1": g("title"),
        "jf": g("source") or g("journal"),
        "yr": g("year"),
        "is": g("issue"),
        "vo": g("volume"),
        "op": g("pages") or g("op"),
        "k1": g("keywords"),
        "ab": g("abstract"),
        "sn": g("issn") or g("sn"),
        "cn": g("cn"),
        "la": (g("language") or "中文").rstrip(";") + ";",
        "ds": "CNKI",
        "lk": g("url") or g("lk"),
        "do": g("doi").lower(),
    }
    lines = []
    for tag, key in CNKI_ORDER:
        if values.get(key):
            lines.append(f"{tag} {values[key]}")
        elif key == "vo" and values.get("jf"):
            lines.append("vo")  # 样例 9/13 处：卷号缺失仍保留空 vo 行（知网导出器行为）
    return "\r\n".join(lines) + "\r\n"


def render_cnki(records):
    body = "\r\n".join(cnki_entry(rec, i) for i, rec in enumerate(records, 1))
    return body, sum(1 for _ in records)


# ---------- WoS 格式 ----------

def fold_wos(tag, value):
    """值超过行宽时按词折行，续行缩进 3 空格（对照样例 TI/DE/FX 续行）。

    没有空格可断（中文/长 URL）就整行保留不硬切——样例 AB 单行 1923 字符证明超宽合法，
    硬切反而会在导入端拼接时插入多余断点。
    """
    first = f"{tag} {value}"
    if tag in WOS_NO_FOLD_TAGS or len(first) <= WOS_LINE_WIDTH:
        return [first]
    lines, cur = [], first
    while len(cur) > WOS_LINE_WIDTH:
        cut = cur.rfind(" ", len(WOS_INDENT), WOS_LINE_WIDTH + 1)
        if cut <= len(WOS_INDENT):
            break
        lines.append(cur[:cut].rstrip())
        cur = WOS_INDENT + cur[cut:].lstrip()
    lines.append(cur)
    return lines


def wos_field_lines(tag, value):
    """多值字段（作者/ORCID/机构）逐值一行；其余按词折行。"""
    if tag in WOS_MULTI_VALUE_TAGS and ";" in value:
        parts = [v.strip() for v in value.split(";") if v.strip()]
        if len(parts) > 1:
            return [f"{tag} {parts[0]}"] + [WOS_INDENT + v for v in parts[1:]]
    return fold_wos(tag, value)


def wos_fallback_raw(rec):
    """没有原始导出字段时，从规范化字段构造最小可导入记录。"""
    def j9(source):
        words = re.findall(r"[A-Za-z]{2,}", source or "")
        stop = {"of", "the", "and", "in", "for", "a", "an", "on"}
        parts = [w[:5].capitalize() for w in words if w.lower() not in stop]
        return " ".join(parts) if parts else (source or "")[:20]

    return {
        "PT": "J", "AU": flat(rec.get("authors")), "TI": flat(rec.get("title")),
        "SO": flat(rec.get("source")), "LA": flat(rec.get("language")) or "English",
        "DT": flat(rec.get("type")) or "Article", "AB": flat(rec.get("abstract")),
        "DE": flat(rec.get("keywords")), "ID": flat(rec.get("keywords_plus")),
        "SN": flat(rec.get("issn")), "JI": j9(flat(rec.get("source"))),
        "PY": str(rec.get("year") or ""), "DI": flat(rec.get("doi")).lower(),
        "BP": (flat(rec.get("pages")).split("-") + [""])[0],
        "EP": (flat(rec.get("pages")).split("-") + ["", ""])[1],
        "VL": flat(rec.get("volume")), "IS": flat(rec.get("issue")),
        "TC": str(rec.get("cited") or ""), "Z9": str(rec.get("cited") or ""),
        "UT": flat(rec.get("ut")), "DA": date.today().isoformat(),
        # SU（Research Areas）此前只在有 raw 时才输出；无 raw 的降级路径漏了它，
        # 与 71 字段清单不一致（wos-playbook §8 的 22 个关键字段里含 SU）
        "SU": flat(rec.get("su")), "WC": flat(rec.get("wc")),
    }


def wos_entry(rec):
    raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
    raw = {k: v for k, v in raw.items() if str(v or "").strip()}
    if not raw:
        raw = wos_fallback_raw(rec)
    raw.setdefault("DA", date.today().isoformat())
    raw.setdefault("PT", "J")
    lines = []
    for tag in WOS_ORDER:
        if tag == "ER":
            continue
        value = flat(raw.get(tag))
        if value:
            lines += wos_field_lines(tag, value)
    lines.append("ER")
    return "\n".join(lines)


def render_wos(records):
    head = "FN Clarivate Analytics Web of Science\nVR 1.0"
    entries = "\n\n".join(wos_entry(rec) for rec in records)
    return head + "\n" + entries + "\n\nEF", len(records)


# ---------- GB/T 7714 / RIS / BibTeX ----------

GB_TYPE_MAP = {"期刊": "J", "Journal Article": "J", "Article": "J", "Article; Early Access": "J",
               "Review": "J", "会议": "C", "Proceedings Article": "C",
               "学位论文": "D", "Dissertation": "D",
               "图书": "M", "Book": "M", "Book Chapter": "M",
               "报纸": "N", "Newspaper Article": "N"}


def gb_author(name):
    """英文「姓, 名缩写」→「姓 名缩写」（Lamour, C → Lamour C）；中文原样。"""
    name = name.strip()
    if "," in name and not re.search(r"[\u4e00-\u9fff]", name):
        family, _, given = name.partition(",")
        initials = "".join(p[0].upper() for p in given.replace("-", " ").split() if p)
        return f"{family.strip()} {initials}".strip()
    return name


def gb_authors(rec):
    names = [gb_author(x) for x in re.split(r"[;；]", flat(rec.get("authors"))) if x.strip()]
    if len(names) > 3:
        et = "等" if any(re.search(r"[\u4e00-\u9fff]", n) for n in names) else "et al"
        return ", ".join(names[:3] + [et])
    return ", ".join(names)


def render_gbt7714(records):
    lines = ["# 参考文献（GB/T 7714-2015 顺序编码制）", "",
             "> 由 export_citations.py 从 records.json 生成；页码/卷期缺失时按可得字段降级输出。", ""]
    for i, rec in enumerate(records, 1):
        parts = [f"[{i}] "]
        authors = gb_authors(rec)
        if authors:
            parts.append(f"{authors}. ")
        parts.append(f"{flat(rec.get('title'))}")
        doc_type = GB_TYPE_MAP.get(flat(rec.get("type")), "J")
        parts.append(f"[{doc_type}]. ")
        parts.append(f"{flat(rec.get('source'))}, " if rec.get("source") else "")
        parts.append(f"{flat(rec.get('year'))}, " if rec.get("year") else "")
        vol, iss = flat(rec.get("volume")), flat(rec.get("issue"))
        if vol and iss:
            parts.append(f"{vol}({iss}): ")
        elif vol:
            parts.append(f"{vol}: ")
        elif iss:
            parts.append(f"({iss}): ")
        pages = flat(rec.get("pages"))
        if pages:
            parts.append(f"{pages}")  # 句点统一在末尾补，页码处不再单独加，避免「..」
        line = "".join(parts).rstrip(" ,: ") + "."
        lines.append(line)
    lines.append("")
    return "\n".join(lines), len(records)


def apa_author(name):
    """英文「姓, 名缩写」补齐 APA 缩写句点（Lamour, C → Lamour, C.）；中文原样。"""
    name = name.strip()
    if "," in name and not re.search(r"[\u4e00-\u9fff]", name):
        family, _, given = name.partition(",")
        initials = "".join(p[0].upper() + "." for p in given.replace("-", " ").split() if p)
        return f"{family.strip()}, {initials}".strip().rstrip(",")
    return name


def apa_authors(rec):
    names = [apa_author(x) for x in re.split(r"[;；]", flat(rec.get("authors"))) if x.strip()]
    if len(names) > 3:
        et = "等" if any(re.search(r"[\u4e00-\u9fff]", n) for n in names) else "et al."
        return ", ".join(names[:3]) + f", {et}"
    if len(names) > 1:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return ", ".join(names)


def render_apa(records):
    """APA 第 7 版（简化作者截断：>3 位同 GB/T 7714 的 3 位+et al. 策略）。"""
    lines = ["# 参考文献（APA 7th）", "",
             "> 由 export_citations.py 从 records.json 生成；页码/卷期缺失时按可得字段降级输出。", ""]
    for rec in records:
        parts = []
        authors = apa_authors(rec)
        if authors:
            parts.append(f"{authors}. ")
        parts.append(f"({flat(rec.get('year'))}). " if rec.get("year") else "(n.d.). ")
        parts.append(f"{flat(rec.get('title'))}. ")
        if rec.get("source"):
            parts.append(f"*{flat(rec.get('source'))}*, ")
        vol, iss = flat(rec.get("volume")), flat(rec.get("issue"))
        if vol and iss:
            parts.append(f"{vol}({iss})")
        elif vol or iss:
            parts.append(vol or iss)
        pages = flat(rec.get("pages")).replace("-", "–")
        if pages:
            parts.append(f", {pages}" if (vol or iss) else f"{pages}")
        doi = flat(rec.get("doi"))
        if doi:
            parts.append(f". https://doi.org/{doi}")
        line = "".join(parts).rstrip(" ,:.") + "."
        lines.append(line)
    lines.append("")
    return "\n".join(lines), len(records)


def mla_author(name):
    """MLA 首作者「姓, 名」原样（源数据即此形）；中文原样。"""
    return name.strip()


def render_mla(records):
    """MLA 第 9 版（works-cited 简化体例：作者. “文题.” 期刊, 卷, 期, 年, pp. 页码.）。"""
    lines = ["# 参考文献（MLA 9th, Works Cited）", "",
             "> 由 export_citations.py 从 records.json 生成；页码/卷期缺失时按可得字段降级输出。", ""]
    for rec in records:
        names = [mla_author(x) for x in re.split(r"[;；]", flat(rec.get("authors"))) if x.strip()]
        head = names[0] if names else ""
        if len(names) > 2:
            others = ", ".join(names[1:])
            has_cjk = any(re.search(r"[\u4e00-\u9fff]", n) for n in names)
            et = "等" if has_cjk else "et al."
            head = f"{head}, {et}"
        elif len(names) == 2:
            head = f"{head}, and {names[1]}"
        parts = []
        if head:
            parts.append(f"{head}. ")
        parts.append(f"“{flat(rec.get('title'))}.” ")
        if rec.get("source"):
            parts.append(f"*{flat(rec.get('source'))}*, ")
        vol, iss = flat(rec.get("volume")), flat(rec.get("issue"))
        if vol:
            parts.append(f"vol. {vol}, ")
        if iss:
            parts.append(f"no. {iss}, ")
        if rec.get("year"):
            parts.append(f"{flat(rec.get('year'))}, ")
        pages = flat(rec.get("pages"))
        if pages:
            parts.append(f"pp. {pages} ")
        line = "".join(parts).rstrip(" ,") + "."
        lines.append(line)
    lines.append("")
    return "\n".join(lines), len(records)


def ris_entry(rec, seq):
    def w(tag, val):
        val = flat(val)
        return f"{tag}  - {val}" if val else ""
    lines = [f"ID  - {rec.get('rid', seq)}", "TY  - JOUR"]
    for a in [x.strip() for x in re.split(r"[;；]", flat(rec.get("authors"))) if x.strip()]:
        lines.append(f"AU  - {a}")
    for tag, key in (("TI", "title"), ("JO", "source"), ("PY", "year"), ("VL", "volume"),
                     ("IS", "issue"), ("DO", "doi"), ("AB", "abstract")):
        line = w(tag, rec.get(key))
        if line:
            lines.append(line)
    pages = flat(rec.get("pages"))
    if pages:
        bp, _, ep = pages.partition("-")
        if bp:
            lines.append(f"SP  - {bp}")
        if ep:
            lines.append(f"EP  - {ep}")
    for k in re.split(r"[;；]", flat(rec.get("keywords"))):
        if k.strip():
            lines.append(f"KW  - {k.strip()}")
    url = flat(rec.get("url")) or (f"https://doi.org/{rec.get('doi')}" if rec.get("doi") else "")
    if url:
        lines.append(f"UR  - {url}")
    lang = flat(rec.get("language"))
    if lang:
        lines.append(f"LA  - {lang}")
    lines.append("ER  - ")
    return "\r\n".join(lines)


def render_ris(records):
    entries = "\r\n".join(ris_entry(rec, i) for i, rec in enumerate(records, 1))
    return entries + "\r\n", len(records)


def bibtex_escape(text):
    return re.sub(r"([{}\"%&$#_~^\\])", r"\\\1", str(text))


def bibtex_entry(rec):
    fields = []
    authors = " and ".join(a.strip() for a in re.split(r"[;；]", flat(rec.get("authors"))) if a.strip())
    if authors:
        fields.append(f"  author = {{{bibtex_escape(authors)}}}")
    for name, key in (("title", "title"), ("journal", "source"), ("year", "year"),
                      ("volume", "volume"), ("number", "issue"), ("doi", "doi"),
                      ("abstract", "abstract")):
        val = flat(rec.get(key))
        if val:
            fields.append(f"  {name} = {{{bibtex_escape(val)}}}")
    pages = flat(rec.get("pages")).replace("-", "--")
    if pages:
        fields.append(f"  pages = {{{pages}}}")
    keywords = ", ".join(k.strip() for k in re.split(r"[;；]", flat(rec.get("keywords"))) if k.strip())
    if keywords:
        fields.append(f"  keywords = {{{bibtex_escape(keywords)}}}")
    return f"@article{{{rec.get('rid', 'untitled')},\n" + ",\n".join(fields) + "\n}"


def render_bibtex(records):
    return "\n\n".join(bibtex_entry(rec) for rec in records) + "\n", len(records)


def main():
    ap = argparse.ArgumentParser(description="导出知网/WoS 格式文献题录")
    ap.add_argument("workdir")
    ap.add_argument("--records", default="", help="records.json 路径，默认自动探测 raw/ 下三个候选")
    ap.add_argument("--only", choices=["cnki", "wos"], default="", help="只导出某一平台的记录")
    ap.add_argument("--format", choices=["auto", "gbt7714", "apa", "mla", "ris", "bibtex"], default="auto",
                    help="auto=知网/WoS 题录 txt（默认）；gbt7714/ris/bibtex 为全平台附加导出")
    ap.add_argument("--prefix", default="文献题录", help="输出文件名前缀")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser().resolve()
    if not wd.is_dir():
        print(f"目录不存在：{wd}", file=sys.stderr)
        sys.exit(64)
    src, records = load_records(wd, args.records)
    if not records:
        print("没有可用题录记录（探测 raw/records.json → records.dedup.json → cnki_records.json）",
              file=sys.stderr)
        sys.exit(65)

    cnki_recs = [r for r in records if platform_of(r) == "cnki"]
    wos_recs = [r for r in records if platform_of(r) == "wos"]
    if args.only == "cnki":
        wos_recs = []
    if args.only == "wos":
        cnki_recs = []
    if not cnki_recs and not wos_recs:
        print("过滤后没有记录可导出", file=sys.stderr)
        sys.exit(65)
    # 附加格式：全平台记录一起导，与 auto 的 txt 互不冲突
    extra_outputs = {}
    if args.format != "auto":
        all_recs = records
        renderers = {"gbt7714": (render_gbt7714, "参考文献.md", "utf-8"),
                     "apa": (render_apa, "参考文献-apa.md", "utf-8"),
                     "mla": (render_mla, "参考文献-mla.md", "utf-8"),
                     "ris": (render_ris, "文献题录.ris", "utf-8"),
                     "bibtex": (render_bibtex, "文献题录.bib", "utf-8")}
        fn, fname, enc = renderers[args.format]
        text, count = fn(all_recs)
        (wd / fname).write_text(text, encoding=enc, newline="")
        extra_outputs[fname] = count
        for name, cnt in extra_outputs.items():
            print(f"✓ {cnt} 条（{args.format} 格式）→ {wd / name}")
        sys.exit(0)

    unknown = [r.get("rid") for r in records
               if not (r.get("platform") or "").lower() in ("cnki", "wos")
               and not str(r.get("rid", "")).startswith(("C", "W"))]
    if unknown:
        print(f"! 警告：{len(unknown)} 条记录平台不明，已按知网格式导出：{', '.join(map(str, unknown[:5]))}"
              + ("…" if len(unknown) > 5 else ""), file=sys.stderr)

    # 单平台 → 文献题录.txt；双平台 → 两种格式分文件（导入器只认一种格式）
    outputs = {}
    if cnki_recs and wos_recs:
        outputs[f"{args.prefix}_知网.txt"] = ("cnki", cnki_recs)
        outputs[f"{args.prefix}_WOS.txt"] = ("wos", wos_recs)
    elif cnki_recs:
        outputs[f"{args.prefix}.txt"] = ("cnki", cnki_recs)
    else:
        outputs[f"{args.prefix}.txt"] = ("wos", wos_recs)

    # 先清掉本脚本上一次运行留下的旧产物（恰好三个规范名），否则 --only 切换后旧文件残留，题录对账必错
    for stale in (f"{args.prefix}.txt", f"{args.prefix}_知网.txt", f"{args.prefix}_WOS.txt"):
        if stale not in outputs:
            (wd / stale).unlink(missing_ok=True)

    written = {}
    for name, (fmt, recs) in outputs.items():
        text, count = render_cnki(recs) if fmt == "cnki" else render_wos(recs)
        dest = wd / name
        if fmt == "cnki":
            dest.write_bytes(text.encode("utf-8"))            # 无 BOM + CRLF（样例原样）
        else:
            dest.write_bytes(("﻿" + text).encode("utf-8"))    # BOM + LF（样例原样）
        written[name] = {"format": fmt, "records": count}

    stats = {
        "source": str(src), "records_total": len(records),
        "cnki_records": len(cnki_recs), "wos_records": len(wos_recs),
        "files": written,
        "entries_written": sum(v["records"] for v in written.values()),
    }
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        for name, v in written.items():
            print(f"✓ {v['records']} 条（{'知网' if v['format'] == 'cnki' else 'WoS'}格式）→ {wd / name}")
        if stats["records_total"] != stats["entries_written"]:
            print(f"! 仅导出 {stats['entries_written']}/{stats['records_total']} 条"
                  f"（--only 过滤或平台未知）")
    sys.exit(0)


if __name__ == "__main__":
    main()
