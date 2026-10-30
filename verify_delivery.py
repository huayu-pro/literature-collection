#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行（PDF 校验需要 pymupdf；缺失时自动降级为跳过并记 warning）
"""交付校验器：交付前最后一道闸门。位掩码退出码，任一位置位即不得宣称完成。

位 1  引用完整性：索引里的路径存在、文件都进了索引、无重复路径/重复 rid；
      缺文件条目已逐条列入 未获取全文.md；题录已导出 文献题录*.txt
位 2  身份一致性：文件名前缀 rid == 行 rid；MD front-matter rid 一致；PDF 首页 DOI 与记录一致
位 4  计数一致性：报告 STATS 块 == index_stats.json；manifest 行数 == pdf 文件数；交付量与目标差距 >20% 未说明；
      题录文件条目数 == records.json 条数
位 8  内容可用性：正文字数达标或已标 thin；HTML 来源有标题层级；PDF 非空且扫描件已标 scan
位 16 会话登记：raw/_logs/session.json（显式 --require-session 时）存在且含 session_id/机构名/时间戳
位 32 检索台账：检索台账.csv（或 --ledger 指定路径）≥3 行且每行 hits/refine_before/after 齐全

用法：
    /usr/bin/python3 scripts/verify_delivery.py <工作目录> --json
    /usr/bin/python3 scripts/verify_delivery.py <工作目录> --brief 00_需求确认.json
    /usr/bin/python3 scripts/verify_delivery.py <工作目录> --require-session --ledger 检索台账.csv
    /usr/bin/python3 scripts/verify_delivery.py --lint-assets
"""
import argparse
import csv
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from unicodedata import normalize as unicodedata_normalize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import (  # noqa: E402
    INDEX_COLUMNS, MANIFEST_COLUMNS, LEDGER_COLUMNS, BRIEF_KEYS, STATS_MIN_KEYS,
    SESSION_KEYS, LEDGER_MIN_ROWS, LEDGER_REQUIRED_COLS,
)
from reason_codes import REASONS, canonical  # noqa: E402

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;)\]\}]+", re.I)
RID_FILE_RE = re.compile(r"^([A-Z]\d{4})_")
STATS_BLOCK_RE = re.compile(r"<!--\s*STATS\s*(\{.*?\})\s*-->", re.S)
# 缺口判定的结构化锚点（v1.3 的 GAP_WORDS 全文关键词匹配可被「正文里恰好出现『缺口』二字」绕过）
GAP_HEADING_RE = re.compile(r"^#{1,6}\s*.*(缺口|待核对|未获取)", re.M)
GAP_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+\S|\|\s*\S|\d+\.\s+\S)", re.M)


def fail(code, msg):
    print(msg, file=sys.stderr)
    sys.exit(code)


def rel_posix(path, workdir):
    try:
        return path.resolve().relative_to(workdir.resolve()).as_posix()
    except Exception:  # noqa: BLE001
        return str(path)


def load_json(path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_csv_header(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh), [])


def parse_front_matter(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, min(len(lines), 80)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, "\n".join(lines[end + 1:])


def norm_doi(value):
    if not value:
        return ""
    v = value.strip().lower()
    v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v)
    v = v.rstrip(".,;:)）】]")
    return v


def norm_title(value):
    v = unicodedata_normalize("NFKC", value or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", v)


def title_sim(a, b):
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def pdf_head_text(path, pages=2):
    try:
        import pymupdf  # noqa: F401
    except Exception:  # noqa: BLE001
        return None, 0, "pymupdf 缺失"
    try:
        doc = pymupdf.open(str(path))
        n = min(pages, doc.page_count)
        text = "\n".join(doc.load_page(i).get_text("text") for i in range(n))
        total = doc.page_count
        doc.close()
        return text, total, ""
    except Exception as exc:  # noqa: BLE001
        return None, 0, str(exc)


def extract_doi(text):
    m = DOI_RE.search(text or "")
    return norm_doi(m.group(0)) if m else ""


class Checker:
    def __init__(self, workdir, min_chars=4000, records_override="", citations_expected=0,
                 recursive=None, ledger_override="", require_session=False, require_ledger=False):
        self.wd = Path(workdir).expanduser().resolve()
        self.min_chars = min_chars
        self.records_override = Path(records_override) if records_override else None
        self.citations_expected = citations_expected
        # 与 build_index.py --recursive 同口径（默认 None → 跟随调用方传来的默认值 False）
        self.recursive = recursive
        self.ledger_override = ledger_override
        self.require_session = require_session
        self.require_ledger = require_ledger
        self.problems = []
        self.warnings = []
        self.index_rows = []
        self.stats = {}
        self.record_count = 0

    def add(self, bit, check, detail, rid="", path="", fix=""):
        self.problems.append({
            "bit": bit, "check": check, "rid": rid, "path": path,
            "detail": detail, "fix": fix,
        })

    def warn(self, check, detail):
        self.warnings.append({"check": check, "detail": detail})

    # ---------- 位 1 ----------
    def check_references(self):
        index_path = self.wd / "index.csv"
        if not index_path.exists():
            self.add(1, "refs.index", "index.csv 不存在", path="index.csv", fix="先跑 build_index.py")
            return
        try:
            self.index_rows = read_csv_rows(index_path)
        except Exception as exc:  # noqa: BLE001
            self.add(1, "refs.index", f"index.csv 解析失败：{exc}", path="index.csv")
            return
        self.check_no_fulltext_md()
        self.check_citations_files()

        indexed = set()
        seen_paths, seen_rids = {}, {}
        for row in self.index_rows:
            rid = (row.get("rid") or "").strip()
            if rid:
                seen_rids[rid] = seen_rids.get(rid, 0) + 1
            for key in ("rel_path_md", "rel_path_pdf"):
                rel = (row.get(key) or "").strip()
                if not rel:
                    continue
                p = self.wd / rel
                indexed.add(rel)
                seen_paths[rel] = seen_paths.get(rel, 0) + 1
                if not p.exists():
                    self.add(1, "refs.missing", f"索引指向的文件不存在：{rel}", rid=rid, path=rel,
                             fix="补文件或把该行 status 改为 missing_file")

        for rel, n in seen_paths.items():
            if n > 1:
                self.add(1, "refs.dup_path", f"同一路径被 {n} 行引用：{rel}", path=rel)
        for rid, n in seen_rids.items():
            if n > 1:
                self.add(1, "refs.dup_rid", f"rid 重复 {n} 次：{rid}", rid=rid)

        extra = []
        ack = set()
        dup_index = self.wd / "index_duplicates.csv"
        if dup_index.exists():
            try:
                ack = {(r.get("duplicate") or "").strip() for r in read_csv_rows(dup_index)}
            except Exception:  # noqa: BLE001
                ack = set()
        for sub in ("正文", "备选", "pdf"):
            d = self.wd / sub
            if not d.exists():
                continue
            pattern = "*.md" if sub != "pdf" else "*.pdf"
            # 口径必须与 build_index.py 一致：v1.3 这里无界 rglob 而 build_index 默认
            # 只 glob 一层，用户把文件放进 正文/子目录/ 时——build_index 不扫（不入索引），
            # verify 却扫到了（报未入索引），位 1 恒失败且 fix 文案「重跑 build_index」无效
            # （重跑同样不扫）。--recursive 两边同开关才一致。
            walker = d.rglob(pattern) if self.recursive else d.glob(pattern)
            for p in sorted(walker):
                rel = rel_posix(p, self.wd)
                if rel not in indexed and p.name not in ack:
                    extra.append(rel)
        for rel in extra[:30]:
            fix = ("重跑 build_index.py（本目录含子目录，加 --recursive）" if self.recursive
                   else "重跑 build_index.py")
            self.add(1, "refs.unindexed", f"文件未进索引：{rel}", path=rel, fix=fix)
        if len(extra) > 30:
            self.add(1, "refs.unindexed", f"另有 {len(extra) - 30} 个未入索引文件（已省略）")
        if not self.recursive:
            self.warn_subdirs()

    def warn_subdirs(self):
        """非递归扫描时提醒子目录里的文件被两边同时跳过——否则「两个脚本口径一致地
        看不见同一批文件」会变成沉默盲区，用户以为交付完整其实漏了。"""
        for sub in ("正文", "备选", "pdf"):
            d = self.wd / sub
            if not d.exists():
                continue
            pattern = "*.md" if sub != "pdf" else "*.pdf"
            for child in sorted(p for p in d.iterdir() if p.is_dir()):
                if any(child.rglob(pattern)):
                    self.warn("refs.subdir_skipped",
                              f"{sub}/{child.name}/ 下有文件但本次未递归扫描；"
                              f"build_index.py 与 verify_delivery.py 同时加 --recursive 才会纳入")

    def find_records(self):
        """题录真源探测；不存在或空数组返回 (None, [])——空数组继续降级读下一候选，
        与 export_citations/build_index 的口径一致（records.json 写了 [] 时三边都读 cnki_records.json）。"""
        for name in ("records.json", "records.dedup.json", "cnki_records.json"):
            p = self.wd / "raw" / name
            if p.exists():
                try:
                    data = load_json(p)
                    if isinstance(data, list) and data:
                        return p, [r for r in data if isinstance(r, dict)]
                except Exception:  # noqa: BLE001
                    continue
        return None, []

    def check_no_fulltext_md(self):
        """缺文件的条目必须在 未获取全文.md 里逐条可查（题录 + 链接 + 原因），防只报数不给人。"""
        missing_rids = {(r.get("rid") or "").strip() for r in self.index_rows
                        if (r.get("status") or "") == "missing_file" and (r.get("rid") or "").strip()}
        if not missing_rids:
            return
        p = self.wd / "未获取全文.md"
        if not p.exists():
            self.add(1, "refs.no_fulltext", f"{len(missing_rids)} 条缺文件但没有 未获取全文.md",
                     fix="重跑 build_index.py（v1.1+ 自动生成）")
            return
        text = p.read_text(encoding="utf-8", errors="replace")
        listed = set(re.findall(r"^### ([A-Z]\d{4}[A-Za-z0-9]*)", text, re.M))
        lost = missing_rids - listed
        if lost:
            self.add(1, "refs.no_fulltext",
                     f"缺文件但未列进 未获取全文.md：{', '.join(sorted(lost))}",
                     path="未获取全文.md", fix="重跑 build_index.py，不要手改清单")

    def check_citations_files(self):
        """题录在手的记录必须已导出 文献题录*.txt，且条目数与题录真源对账。"""
        if self.records_override:
            src, records = self.records_override, [r for r in load_json(self.records_override)
                                                   if isinstance(r, dict)]
        else:
            src, records = self.find_records()
        self.record_count = len(records)
        if src is None or not records:
            return
        files = sorted(self.wd.glob("文献题录*.txt"))
        if not files:
            self.add(1, "refs.citations",
                     f"{len(records)} 条题录（{Path(src).name}）没有导出 文献题录*.txt",
                     fix="跑 scripts/export_citations.py <工作目录>")
            return
        entries = 0
        for f in files:
            text = f.read_text(encoding="utf-8-sig", errors="replace")
            if text.lstrip("﻿").startswith("FN Clarivate"):
                entries += len(re.findall(r"^ER\s*$", text, re.M))
            else:
                entries += len(re.findall(r"^RT\s", text, re.M))
        expected = self.citations_expected if self.citations_expected else len(records)
        if entries != expected:
            note = "" if expected == len(records) else "（--citations-expected 指定值）"
            self.add(4, "count.citations",
                     f"题录文件条目 {entries} ≠ 期望 {expected} 条{note}",
                     fix="重跑 export_citations.py；--only 过滤过的导出需配 verify --citations-expected N")


    # ---------- 位 2 ----------
    def check_identity(self):
        for row in self.index_rows:
            rid = (row.get("rid") or "").strip()
            if not rid:
                continue
            for key in ("rel_path_md", "rel_path_pdf"):
                rel = (row.get(key) or "").strip()
                if not rel:
                    continue
                m = RID_FILE_RE.match(Path(rel).name)
                if not m:
                    self.add(2, "id.filename", f"文件名没有 rid 前缀：{rel}", rid=rid, path=rel,
                             fix="按 <rid>_<作者><年>_<刊> 重命名")
                elif m.group(1) != rid:
                    self.add(2, "id.filename", f"文件名前缀 {m.group(1)} ≠ 行 rid {rid}", rid=rid, path=rel,
                             fix="这一条专防交付物错挂：统一用 rid，rank 只做展示列")

            rel_md = (row.get("rel_path_md") or "").strip()
            if rel_md and (self.wd / rel_md).exists():
                meta, _ = parse_front_matter(self.wd / rel_md)
                fm_rid = (meta.get("rid") or "").strip()
                if fm_rid and fm_rid != rid:
                    self.add(2, "id.frontmatter", f"MD front-matter rid={fm_rid} ≠ 行 rid={rid}",
                             rid=rid, path=rel_md)

            rel_pdf = (row.get("rel_path_pdf") or "").strip()
            doi = norm_doi(row.get("doi"))
            if rel_pdf and doi and (self.wd / rel_pdf).exists():
                text, _, err = pdf_head_text(self.wd / rel_pdf)
                if text is None:
                    self.warn("id.pdf", f"{rel_pdf} 无法读取（{err}），跳过 DOI 校验")
                else:
                    found = extract_doi(text)
                    if found and found != doi:
                        sim = title_sim(row.get("title", ""), text)
                        if sim < 0.9:
                            self.add(2, "id.pdf_doi",
                                     f"PDF 内嵌 DOI={found} ≠ 记录 DOI={doi}，篇名相似度 {sim:.2f}",
                                     rid=rid, path=rel_pdf,
                                     fix="PDF 挂错了：按 DOI 重新匹配，不要用文件名猜")

    # ---------- 位 4 ----------
    def check_counts(self):
        stats_path = self.wd / "index_stats.json"
        if stats_path.exists():
            try:
                self.stats = load_json(stats_path)
            except Exception as exc:  # noqa: BLE001
                self.add(4, "count.stats", f"index_stats.json 解析失败：{exc}", path="index_stats.json")

        report = self.wd / "检索报告.md"
        if report.exists():
            text = report.read_text(encoding="utf-8", errors="replace")
            m = STATS_BLOCK_RE.search(text)
            if not m:
                self.add(4, "count.report", "检索报告.md 缺少 <!-- STATS {...} --> 机器可读块",
                         path="检索报告.md", fix="用 assets/检索报告.template.md 重渲染")
            elif self.stats:
                try:
                    block = json.loads(m.group(1))
                except Exception as exc:  # noqa: BLE001
                    self.add(4, "count.report", f"STATS 块不是合法 JSON：{exc}", path="检索报告.md")
                else:
                    for key, value in block.items():
                        if key in self.stats and self.stats[key] != value:
                            self.add(4, "count.report",
                                     f"报告数字 {key}={value} ≠ index_stats.json={self.stats[key]}",
                                     path="检索报告.md", fix="报告数字一律由脚本变量填入，不要手写")
                    missing_keys = [k for k in STATS_MIN_KEYS
                                    if k not in block and k in self.stats]
                    if missing_keys:  # 漏报关键计数同样是对不上账，只比交集会放行
                        self.add(4, "count.report",
                                 f"报告 STATS 块缺少键：{', '.join(missing_keys)}",
                                 path="检索报告.md", fix="用 assets/检索报告.template.md 重渲染")

        if self.stats:
            total = int(self.stats.get("total") or 0)
            delivered = int(self.stats.get("with_md") or 0) + int(self.stats.get("with_pdf") or 0)
            missing = int(self.stats.get("missing_file") or 0)
            text = report.read_text(encoding="utf-8", errors="replace") if report.exists() else ""
            if total and delivered == 0:
                self.add(4, "count.empty", f"{total} 条记录没有任何正文或 PDF 文件",
                         fix="先跑下载阶段，或把目标数量改为 0")
            if total and missing and missing / total > 0.1:
                ok, why = self.has_gap_section()
                if not ok:
                    self.add(4, "count.missing",
                             f"{missing}/{total} 条记录缺文件，且报告没有缺口说明（{why}）",
                             fix="在「缺口说明」节下逐条列出，或补齐文件")

        manifest = self.wd / "manifest.csv"
        pdf_files = list((self.wd / "pdf").rglob("*.pdf")) if (self.wd / "pdf").exists() else []
        if pdf_files and not manifest.exists():
            self.add(4, "count.manifest", f"pdf/ 有 {len(pdf_files)} 个文件但没有 manifest.csv",
                     path="manifest.csv", fix="跑 pdf_fetch.py verify 生成")
        elif manifest.exists():
            try:
                rows = read_csv_rows(manifest)
            except Exception as exc:  # noqa: BLE001
                self.add(4, "count.manifest", f"manifest.csv 解析失败：{exc}", path="manifest.csv")
            else:
                ok_rows = [r for r in rows if (r.get("status") or "") == "ok"]
                if len(ok_rows) != len(pdf_files):
                    self.add(4, "count.manifest",
                             f"manifest status=ok 行数 {len(ok_rows)} ≠ pdf 文件数 {len(pdf_files)}",
                             path="manifest.csv", fix="重跑 pdf_fetch.py verify")

    def has_gap_section(self):
        """结构化缺口判定：要求报告里有「缺口/待核对/未获取」标题节，且该节下至少一条列表项。

        v1.3 用 GAP_WORDS 全文关键词匹配（含「缺 」「差 」这类两字词），任何报告只要
        正文里碰巧出现这些字就被判为「已说明缺口」，位 4 的计数校验形同虚设。
        这里改为：先定位标题节，再要求节内有条目（列表/表格/编号行）——只写一句
        「存在缺口」而没列条目，仍然不通过（「不给人清单」与不写等价）。
        """
        report = self.wd / "检索报告.md"
        if not report.exists():
            return False, "检索报告.md 不存在"
        text = report.read_text(encoding="utf-8", errors="replace")
        ms = list(GAP_HEADING_RE.finditer(text))
        if not ms:
            return False, "报告没有「缺口/待核对/未获取」标题节"
        for m in ms:
            # 该标题到下一个同级或更高级标题之间的内容
            rest = text[m.end():]
            nxt = re.search(r"^#{1,%d}\s+\S" % (len(m.group(0).split()[0])), rest, re.M)
            section = rest[:nxt.start()] if nxt else rest
            if GAP_ITEM_RE.search(section):
                return True, ""
        return False, "缺口节下没有列出任何条目（光写「存在缺口」不算说明）"

    def check_brief_gap(self, brief):
        target = brief.get("target_count")
        try:
            target = int(target)
        except Exception:  # noqa: BLE001
            return
        delivered = [r for r in self.index_rows
                     if (r.get("rel_path_md") or "").strip() or (r.get("rel_path_pdf") or "").strip()]
        if target <= 0:
            return
        gap = abs(target - len(delivered)) / target
        if gap > 0.2:
            ok, why = self.has_gap_section()
            if not ok:
                self.add(4, "count.gap",
                         f"目标 {target} 篇，实交付 {len(delivered)} 篇，差距 {gap:.0%} 且报告未说明（{why}）",
                         fix="在报告的「缺口说明」节下逐条列出缺口篇目与原因（付费墙/无全文/筛选淘汰）")

    # ---------- 位 16 ----------
    def check_session(self):
        """会话登记门禁：v1.3 里 SKILL.md 硬要求把 sid 写进 raw/_logs/session.json，
        但全仓无生产者也无读者——典型的「无生产者的门禁」，永远不可能失败。
        v1.4 由 register_session.py 生产、本函数读取；显式 --require-session 才启用
        （G0/G1 阶段可能还没开浏览器，默认不该挡住）。"""
        p = self.wd / "raw" / "_logs" / "session.json"
        if not p.exists():
            self.add(16, "session.missing", "raw/_logs/session.json 不存在",
                     path="raw/_logs/session.json",
                     fix="跑 scripts/register_session.py <工作目录> --sid <sid> --institution <机构名>")
            return
        try:
            data = load_json(p)
        except Exception as exc:  # noqa: BLE001
            self.add(16, "session.parse", f"session.json 解析失败：{exc}",
                     path="raw/_logs/session.json", fix="重新跑 register_session.py 覆盖它")
            return
        if not isinstance(data, dict):
            self.add(16, "session.parse", "session.json 顶层必须是对象",
                     path="raw/_logs/session.json")
            return
        empty = [k for k in SESSION_KEYS if not str(data.get(k) or "").strip()]
        if empty:
            self.add(16, "session.keys", f"session.json 缺少字段：{', '.join(empty)}",
                     path="raw/_logs/session.json",
                     fix="跑 register_session.py 重新登记（--sid 与 --institution 都必填）")

    # ---------- 位 32 ----------
    def check_ledger(self):
        """检索台账门禁：v1.3 的三条台账门禁（≥3 行、含 hits、含 refine_before/after）
        全是口头门禁——verify 从不读这个文件，写不写都一样。
        表头用 schema.LEDGER_COLUMNS（与 assets 模板同一真源），缺列即红。"""
        path = Path(self.ledger_override) if self.ledger_override else self.wd / "检索台账.csv"
        if not path.is_absolute() and not self.ledger_override:
            path = self.wd / path
        if not path.exists():
            self.add(32, "ledger.missing", f"检索台账不存在：{path.name}",
                     path=str(path),
                     fix="用 assets/检索台账.template.csv 建台账并逐条记检索式（--ledger 可显式指定路径）")
            return
        try:
            header = read_csv_header(path)
            rows = read_csv_rows(path)
        except Exception as exc:  # noqa: BLE001
            self.add(32, "ledger.parse", f"检索台账解析失败：{exc}", path=str(path))
            return
        missing_cols = [c for c in LEDGER_COLUMNS if c not in header]
        if missing_cols:
            self.add(32, "ledger.header", f"检索台账缺列：{', '.join(missing_cols)}",
                     path=str(path),
                     fix=f"表头必须为 {','.join(LEDGER_COLUMNS)}（assets/检索台账.template.csv）")
            return
        if len(rows) < LEDGER_MIN_ROWS:
            self.add(32, "ledger.rows", f"检索台账只有 {len(rows)} 行，要求 ≥{LEDGER_MIN_ROWS} 行",
                     path=str(path),
                     fix="每条检索式一行（含宽式/窄式/补漏式至少三条），空台账无法复现")
        for i, row in enumerate(rows, 2):  # 第 1 行是表头
            blank = [c for c in LEDGER_REQUIRED_COLS if not str(row.get(c) or "").strip()]
            if blank:
                qid = str(row.get("qid") or "").strip() or f"第{i}行"
                self.add(32, "ledger.values", f"台账 {qid} 缺 {', '.join(blank)}",
                         path=str(path),
                         fix="命中数与筛选前后计数必须记全，否则筛选过程不可复现")

    # ---------- 位 8 ----------
    def check_content(self):
        for row in self.index_rows:
            rid = (row.get("rid") or "").strip()
            rel_md = (row.get("rel_path_md") or "").strip()
            if rel_md and (self.wd / rel_md).exists():
                meta, body = parse_front_matter(self.wd / rel_md)
                raw_chars = meta.get("chars")
                try:
                    chars = int(raw_chars) if raw_chars else len(re.sub(r"\s+", "", body))
                except Exception:  # noqa: BLE001
                    chars = len(re.sub(r"\s+", "", body))
                status = (meta.get("status") or row.get("status") or "").strip()
                if chars < self.min_chars and status != "thin":
                    self.add(8, "content.thin", f"正文 {chars} 字 < {self.min_chars} 且未标 thin",
                             rid=rid, path=rel_md, fix="移入 备选/ 并把 status 改为 thin")
                access = (row.get("access") or meta.get("access") or "").upper()
                if access == "HTML" and "## " not in body:
                    self.add(8, "content.heading", "HTML 来源的 MD 没有二级标题，标题层级丢失",
                             rid=rid, path=rel_md)

            rel_pdf = (row.get("rel_path_pdf") or "").strip()
            if not rel_pdf or not (self.wd / rel_pdf).exists():
                continue
            p = self.wd / rel_pdf
            size = p.stat().st_size
            if size < 10240:
                self.add(8, "content.pdf_size", f"PDF 只有 {size} 字节，判为无效下载", rid=rid, path=rel_pdf)
                continue
            text, pages, err = pdf_head_text(p, pages=3)
            if text is None:
                self.warn("content.pdf", f"{rel_pdf} 无法读取（{err}）")
                continue
            if pages == 0:
                self.add(8, "content.pdf_pages", "PDF 页数为 0", rid=rid, path=rel_pdf)
            elif len(re.sub(r"\s+", "", text)) < 50:
                flagged = (row.get("status") or "").lower() in ("scan", "scan_only")
                if not flagged:
                    self.add(8, "content.pdf_scan", "PDF 无可提取文字且未标 scan（疑似扫描件）",
                             rid=rid, path=rel_pdf, fix="标 status=scan 或换文献，不要做无效 OCR")

    def run(self, brief=None):
        self.check_references()
        self.check_identity()
        self.check_counts()
        if brief:
            self.check_brief_gap(brief)
        self.check_content()
        if self.require_session:
            self.check_session()
        if self.require_ledger:
            self.check_ledger()
        mask = 0
        for p in self.problems:
            mask |= p["bit"]
        return mask


def lint_assets(skill_root):
    """模板表头必须与脚本 schema 完全一致，防止模板与代码漂移。"""
    problems = []
    assets = Path(skill_root) / "assets"
    pairs = [
        ("检索台账.template.csv", LEDGER_COLUMNS),
        ("文献清单.template.csv", INDEX_COLUMNS),
        ("manifest.template.csv", MANIFEST_COLUMNS),
    ]
    for name, expect in pairs:
        p = assets / name
        if not p.exists():
            problems.append(f"缺少模板：{name}")
            continue
        got = read_csv_header(p)
        if got != expect:
            problems.append(f"{name} 表头不一致\n  期望 {expect}\n  实际 {got}")

    bp = assets / "brief.template.json"
    if not bp.exists():
        problems.append("缺少模板：brief.template.json")
    else:
        try:
            got = list(load_json(bp).keys())
            if got != BRIEF_KEYS:
                problems.append(f"brief.template.json 键不一致：{got}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"brief.template.json 解析失败：{exc}")

    ip = assets / "索引.template.md"
    if not ip.exists() or "{{" not in ip.read_text(encoding="utf-8"):
        problems.append("索引.template.md 缺失或不含 {{占位符}}")
    else:
        problems += lint_index_template(ip.read_text(encoding="utf-8"))
    rp = assets / "检索报告.template.md"
    if not rp.exists() or "<!-- STATS" not in rp.read_text(encoding="utf-8"):
        problems.append("检索报告.template.md 缺失或不含 <!-- STATS 块")
    else:
        problems += lint_report_template(rp.read_text(encoding="utf-8"))
    return problems


def lint_index_template(text):
    """内容一致性：模板的总览表列名与分组方式必须和 build_index.render_markdown() 一致。

    v1.3 的模板是「单组 + 列名『分类|条数』」，代码是「按 platform 循环 + 列名『平台|条数』」，
    表头 lint 查不出这种漂移（两者 CSV 表头都对）。这里按代码的实际输出做内容级比对。
    """
    problems = []
    header = [line for line in text.splitlines() if line.strip().startswith("| 分类") or
              line.strip().startswith("| 平台")]
    if not header:
        problems.append("索引.template.md 总览表缺少表头行（代码输出为「| 平台 | 条数 | 有正文 | 有 PDF | 位置 |」）")
    elif "分类" in header[0]:
        problems.append("索引.template.md 总览表头仍是「分类」，代码 render_markdown() 输出的是「平台」"
                        "（按 platform 循环，不是单组）")
    # 代码是对 stats["by_platform"] 循环，模板里必须有可重复的组占位（{{GROUP}} 出现在
    # 表行与小节标题两处 = 可重复；只出现一次说明退化成单组）
    if text.count("{{GROUP}}") < 2:
        problems.append("索引.template.md 的 {{GROUP}} 只出现一次；代码按 platform 循环输出多组，"
                        "模板必须可重复渲染（表行 + 小节标题各一处）")
    for token in ("{{TOTAL}}", "{{WITH_MD}}", "{{WITH_PDF}}", "{{MISSING_BLOCK}}", "{{ITEMS}}"):
        if token not in text:
            problems.append(f"索引.template.md 缺占位符 {token}（build_index.render_markdown 会填它）")
    return problems


def lint_report_template(text):
    """检索报告模板必须含 STATS 六键（位 4 校验的就是这六键，模板缺一个全批报告都红）。"""
    problems = []
    for key in STATS_MIN_KEYS:
        if key not in text:
            problems.append(f"检索报告.template.md 的 STATS 块缺键 {key}（verify 位 4 会拦）")
    if "{{GAP_NOTE}}" not in text:
        problems.append("检索报告.template.md 缺 {{GAP_NOTE}}（缺口说明节，位 4 结构化判定依赖它）")
    for token in ("{{TOPIC}}", "{{TARGET_COUNT}}", "{{DELIVERED}}", "{{QUERY_TABLE}}"):
        if token not in text:
            problems.append(f"检索报告.template.md 缺占位符 {token}（render_report.py 会填它）")
    return problems


def lint_reason_codes(skill_root):
    """失败原因词汇表必须只有一套：cnki-playbook §12 与 reason_codes.py 逐项对齐。"""
    problems = []
    pb = Path(skill_root) / "references" / "cnki" / "cnki-playbook.md"
    if not pb.exists():
        return ["缺少 references/cnki/cnki-playbook.md（原因枚举表在那里）"]
    text = pb.read_text(encoding="utf-8")
    for code in REASONS:
        if code not in text:
            problems.append(f"cnki-playbook.md §12 缺原因值 {code}（reason_codes.py 已定义）")
    return problems


def main():
    ap = argparse.ArgumentParser(description="文献交付交叉校验（位掩码退出码）")
    ap.add_argument("workdir", nargs="?", help="运行时工作目录")
    ap.add_argument("--brief", default="", help="需求确认 JSON，校验 7 个必填键与目标差距")
    ap.add_argument("--brief-only", default="", help="G0 阶段用：只校验需求确认 7 键，不跑交付校验")
    ap.add_argument("--min-chars", type=int, default=4000)
    ap.add_argument("--records", default="", help="题录真源覆盖（与 export/build 的 --records 同口径）")
    ap.add_argument("--citations-expected", type=int, default=0,
                    help="题录期望条目数；export --only 只导部分记录时用它豁免对账")
    ap.add_argument("--recursive", type=int, default=0, choices=(0, 1),
                    help="与 build_index.py --recursive 同口径：1=递归扫 正文/备选/pdf 子目录（默认 0）")
    ap.add_argument("--ledger", default="",
                    help="检索台账路径（显式指定即启用位 32 台账门禁）；"
                         "相对路径按工作目录解析，与 --brief 同口径；不传则不校验台账")
    ap.add_argument("--require-session", action="store_true",
                    help="启用位 16：要求 raw/_logs/session.json 由 register_session.py 登记")
    ap.add_argument("--lint-assets", action="store_true",
                    help="只校验 assets 模板与 schema / 代码输出是否一致")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.lint_assets:
        root = Path(__file__).resolve().parent.parent
        problems = lint_assets(root) + lint_reason_codes(root)
        if args.json:
            print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
        else:
            print("模板校验通过" if not problems else "\n".join(problems))
        sys.exit(0 if not problems else 1)

    if not args.workdir:
        fail(64, "缺少工作目录；或使用 --lint-assets")
    wd = Path(args.workdir).expanduser()
    if not wd.is_dir():
        fail(64, f"工作目录不存在：{wd}")

    if args.brief_only:  # G0 门禁：此时还没有 index.csv，交付校验必然置位，只能单验 brief
        bp = Path(args.brief_only)
        if not bp.is_absolute():
            bp = wd / bp
        if not bp.exists():
            fail(64, f"需求确认文件不存在：{bp}")
        try:
            brief = load_json(bp)
        except Exception as exc:  # noqa: BLE001
            fail(65, f"需求确认 JSON 解析失败：{exc}")
        missing = [k for k in BRIEF_KEYS if k not in brief or brief[k] in ("", None, [])]
        if missing:
            fail(64, f"需求确认缺少字段：{', '.join(missing)}")
        print("✓ 需求确认 7 键齐全（--brief-only）")
        sys.exit(0)

    brief = None
    if args.brief:
        bp = Path(args.brief)
        if not bp.is_absolute():
            bp = wd / bp
        if not bp.exists():
            fail(64, f"需求确认文件不存在：{bp}")
        try:
            brief = load_json(bp)
        except Exception as exc:  # noqa: BLE001
            fail(65, f"需求确认 JSON 解析失败：{exc}")
        missing = [k for k in BRIEF_KEYS if k not in brief or brief[k] in ("", None, [])]
        if missing:
            fail(64, f"需求确认缺少字段：{', '.join(missing)}")

    if args.records and not Path(args.records).exists():
        fail(64, f"--records 文件不存在：{args.records}")
    if args.ledger:
        lp = Path(args.ledger)
        if not lp.is_absolute():
            lp = wd / lp
        if not lp.exists():
            fail(64, f"--ledger 文件不存在：{lp}（相对路径按工作目录 {wd} 解析）")
        args.ledger = str(lp)
    checker = Checker(wd, min_chars=args.min_chars, records_override=args.records,
                      citations_expected=args.citations_expected,
                      recursive=bool(args.recursive), ledger_override=args.ledger,
                      require_session=args.require_session,
                      require_ledger=bool(args.ledger))
    mask = checker.run(brief)
    result = {
        "ok": mask == 0,
        "exit": mask,
        "workdir": str(wd),
        "problems": checker.problems,
        "warnings": checker.warnings,
        "stats": checker.stats,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not checker.problems:
            print(f"✓ 交付校验通过：{len(checker.index_rows)} 条记录")
        for p in checker.problems:
            print(f"✗ [位{p['bit']}] {p['check']} {p['rid']} {p['path']}\n    {p['detail']}\n    → {p['fix']}")
        for w in checker.warnings:
            print(f"! {w['check']}: {w['detail']}")
    sys.exit(mask)


if __name__ == "__main__":
    main()
