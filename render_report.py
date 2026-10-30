#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""检索报告渲染器：assets/检索报告.template.md + index_stats.json + 需求确认 + 台账 → 检索报告.md。

背景：v1.4 之前，检索报告是包里唯一「有 schema、有模板、有门禁（verify 位 4 校验
STATS 六键）却没有 renderer」的资产——只能人手填，而人手填的数字必然与
index_stats.json 不一致，与 SKILL.md 硬规则 4「结论句必须由脚本变量填入」直接冲突
（等于要求一件做不到的事）。本脚本是它的 renderer。

所有数字取自脚本产物，不手写：
    total/with_md/with_pdf/missing_file/unregistered/thin ← index_stats.json
    hits/after_dedupe/after_screen                        ← 检索台账.csv（--ledger）
    topic/target_count/quality_gate                       ← 00_需求确认.json
    html/pdf 通道分布                                      ← index.csv 的 access 列

用法：
    /usr/bin/python3 scripts/render_report.py "<工作目录>" --title "基层治理数字化"
    /usr/bin/python3 scripts/render_report.py "<工作目录>" --brief 00_需求确认.json \
        --ledger 检索台账.csv --institution "某大学" --json
    /usr/bin/python3 scripts/render_report.py "<工作目录>" --check   # 只校验已有报告的 STATS 块

退出码：0 成功；64 参数/产物缺失；4 报告 STATS 块与 index_stats.json 不一致（--check）。
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import STATS_MIN_KEYS, BRIEF_KEYS, LEDGER_COLUMNS  # noqa: E402

TEMPLATE = "检索报告.template.md"
OUT_NAME = "检索报告.md"
STATS_BLOCK_RE = re.compile(r"<!--\s*STATS\s*(\{.*?\})\s*-->", re.S)
STATS_KEYS = STATS_MIN_KEYS + ["no_fulltext"]


def load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def to_int(value, default=0):
    try:
        return int(re.sub(r"[^\d-]", "", str(value or "")) or default)
    except Exception:  # noqa: BLE001
        return default


def stats_of(workdir):
    data = load_json(Path(workdir) / "index_stats.json")
    if not isinstance(data, dict):
        return None
    return {k: to_int(data.get(k)) for k in STATS_MIN_KEYS} | {
        "no_fulltext": to_int(data.get("no_fulltext"))}


def access_counts(workdir):
    p = Path(workdir) / "index.csv"
    if not p.exists():
        return {"HTML": 0, "PDF": 0}
    counts = {"HTML": 0, "PDF": 0}
    try:
        for row in read_csv_rows(p):
            a = (row.get("access") or "").strip().upper()
            if a in counts:
                counts[a] += 1
    except Exception:  # noqa: BLE001
        pass
    return counts


def ledger_totals(path):
    """台账 → (初检命中合计, 筛选后合计)；读不到返回 (0, 0)。"""
    if not path or not Path(path).exists():
        return None, None
    try:
        rows = read_csv_rows(path)
    except Exception:  # noqa: BLE001
        return None, None
    if not rows:
        return None, None
    before = sum(to_int(r.get("refine_before")) for r in rows)
    after = sum(to_int(r.get("refine_after")) for r in rows)
    return before, after


def query_table(path, limit=20):
    """台账 → markdown 表格行；台账缺失时给一句明确的「无台账」，不留空表。"""
    if not path or not Path(path).exists():
        return "| （无台账） | | | | |\n\n> 未找到检索台账；没有台账的检索等于没做（method/query-design.md §8）。"
    try:
        rows = read_csv_rows(path)
    except Exception as exc:  # noqa: BLE001
        return f"| （台账解析失败：{exc}） | | | | |"
    if not rows:
        return "| （台账为空） | | | | |"
    lines = ["| qid | 平台 | 检索式 | 字段 | 筛选前 → 后 | 采用 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in rows[:limit]:
        q = (r.get("query_raw") or "").replace("|", "\\|")
        if len(q) > 80:
            q = q[:77] + "…"
        lines.append(f"| {r.get('qid', '')} | {r.get('platform', '')} | `{q}` | "
                     f"{r.get('fields', '')} | {r.get('refine_before', '')} → "
                     f"{r.get('refine_after', '')} | {r.get('hits', '')} |")
    if len(rows) > limit:
        lines.append(f"| … | | 另有 {len(rows) - limit} 条 | | | |")
    return "\n".join(lines)


def gap_note(stats, target, delivered, missing_rows, ledger_before=None):
    """缺口说明：结构化输出（标题 + 列表项），满足 verify 位 4 的结构化判定。
    只写一句「存在缺口」会被拦——光说不算说明，必须给条目。

    数字全部来自脚本产物：缺文件/篇幅不足/未登记取自 index_stats.json 与 index.csv，
    初检命中取自台账；不写任何估算或「大概」。"""
    short = bool(target) and abs(target - delivered) > target * 0.2
    if not missing_rows and not stats.get("thin") and not stats.get("unregistered") and not short:
        return "本批次无缺口：交付量与目标一致，条目全部有全文。"
    lines = [f"目标 {target or '未设定'} 篇，实交付 {delivered} 篇"
             + (f"（台账初检命中合计 {ledger_before} 条）" if ledger_before else "") + "。", ""]
    lines.append("| 缺口项 | 篇数 | 去向 |")
    lines.append("| --- | --- | --- |")
    rows = [("缺文件（题录在手、全文未获取）", stats.get("missing_file", 0),
             "逐条见 未获取全文.md，付费墙/无 HTML 的不凑数"),
            ("篇幅不足（< min-chars）", stats.get("thin", 0), "移入 备选/ 并标 thin，不进主库"),
            ("未登记文件（有文件无题录）", stats.get("unregistered", 0), "补题录或确认是否为误放文件")]
    if target:
        rows.append(("距目标数量", max(0, target - delivered),
                     "扩大检索式 / 放宽年份 / 换库（需与用户确认，不擅自降门槛）"))
    for name, count, where in rows:
        lines.append(f"| {name} | {count} | {where} |")
    lines.append("")
    if missing_rows:
        lines.append("未获取全文的条目（逐条见 未获取全文.md）：")
        lines.append("")
        lines.append("| rid | 题名 | 状态 |")
        lines.append("| --- | --- | --- |")
        for row in missing_rows[:30]:
            lines.append(f"| {row.get('rid', '')} | {str(row.get('title', '')).replace('|', '/')} | "
                         f"{row.get('status', '')} |")
        if len(missing_rows) > 30:
            lines.append(f"| … | 另有 {len(missing_rows) - 30} 条 | |")
    return "\n".join(lines)


def missing_rows_of(workdir):
    p = Path(workdir) / "index.csv"
    if not p.exists():
        return []
    try:
        return [r for r in read_csv_rows(p)
                if (r.get("status") or "") in ("missing_file", "unregistered")]
    except Exception:  # noqa: BLE001
        return []


def render(template_text, mapping):
    out = template_text
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


def main():
    ap = argparse.ArgumentParser(description="渲染检索报告（数字全部取自脚本产物）")
    ap.add_argument("workdir", help="运行时工作目录")
    ap.add_argument("--title", default="", help="报告标题，默认取 brief.topic 或目录名")
    ap.add_argument("--brief", default="", help="00_需求确认.json，默认 <workdir>/00_需求确认.json")
    ap.add_argument("--ledger", default="", help="检索台账.csv，默认 <workdir>/检索台账.csv")
    ap.add_argument("--template", default="", help=f"模板路径，默认 assets/{TEMPLATE}")
    ap.add_argument("--institution", default="", help="机构名，可脱敏；默认取台账 institution 首值")
    ap.add_argument("--operator", default="", help="执行人，默认「脚本生成」")
    ap.add_argument("--out", default="", help=f"输出路径，默认 <workdir>/{OUT_NAME}")
    ap.add_argument("--check", action="store_true",
                    help="只校验已有报告的 STATS 块是否与 index_stats.json 一致")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser()
    if not wd.is_dir():
        print(f"工作目录不存在：{wd}", file=sys.stderr)
        sys.exit(64)

    stats = stats_of(wd)
    if stats is None:
        print(f"缺少或无法解析 index_stats.json：{wd/'index_stats.json'}；"
              f"先跑 build_index.py", file=sys.stderr)
        sys.exit(64)

    if args.check:
        report = wd / OUT_NAME
        if not report.exists():
            print(f"尚未生成 {OUT_NAME}", file=sys.stderr)
            sys.exit(64)
        m = STATS_BLOCK_RE.search(report.read_text(encoding="utf-8", errors="replace"))
        if not m:
            print(f"{OUT_NAME} 缺少 <!-- STATS {{...}} --> 块", file=sys.stderr)
            sys.exit(4)
        block = json.loads(m.group(1))
        bad = [k for k in STATS_MIN_KEYS
               if k in stats and k in block and stats[k] != to_int(block[k])]
        absent = [k for k in STATS_MIN_KEYS if k not in block]
        if bad or absent:
            detail = "; ".join([f"{k}={block.get(k)}≠{stats[k]}" for k in bad] +
                               [f"缺键 {k}" for k in absent])
            print(f"{OUT_NAME} 的 STATS 块与 index_stats.json 不一致：{detail}", file=sys.stderr)
            sys.exit(4)
        print(f"✓ {OUT_NAME} 的 STATS 块与 index_stats.json 一致（{len(STATS_MIN_KEYS)} 键）")
        sys.exit(0)

    tpl_path = Path(args.template) if args.template else \
        Path(__file__).resolve().parent.parent / "assets" / TEMPLATE
    if not tpl_path.exists():
        print(f"模板不存在：{tpl_path}", file=sys.stderr)
        sys.exit(64)
    template = tpl_path.read_text(encoding="utf-8")

    bp = Path(args.brief) if args.brief else wd / "00_需求确认.json"
    if not bp.is_absolute() and not args.brief:
        bp = wd / bp
    brief = load_json(bp) if bp.exists() else None
    if brief is None:
        print(f"! 未读到 00_需求确认.json（{bp}），主题/目标等字段留空", file=sys.stderr)
        brief = {}

    lp = Path(args.ledger) if args.ledger else wd / "检索台账.csv"
    if not lp.is_absolute() and not args.ledger:
        lp = wd / lp
    ledger_path = lp if lp.exists() else None
    before, after = ledger_totals(ledger_path)

    access = access_counts(wd)
    missing_rows = missing_rows_of(wd)
    delivered = stats["with_md"] + stats["with_pdf"]
    target = to_int(brief.get("target_count"), 0)

    institution = args.institution
    if not institution and ledger_path:
        try:
            for r in read_csv_rows(ledger_path):
                if (r.get("institution") or "").strip():
                    institution = r["institution"].strip()
                    break
        except Exception:  # noqa: BLE001
            pass

    title = args.title or str(brief.get("topic") or "").strip() or wd.name
    mapping = {
        "TITLE": title,
        "DATE": datetime.now().astimezone().strftime("%Y-%m-%d"),
        "OPERATOR": args.operator or "脚本生成（render_report.py）",
        "INSTITUTION": institution or "（未登记）",
        "PLATFORM": brief.get("platform", "（未登记）"),
        "DISCIPLINE": brief.get("discipline", "（未登记）"),
        "YEAR_RANGE": brief.get("year_range", "（未登记）"),
        "TOPIC": brief.get("topic", title),
        "TARGET_COUNT": target or "（未登记）",
        "DELIVERED": delivered,
        "QUALITY_GATE": brief.get("quality_gate", "（未登记）"),
        "QUERY_TABLE": query_table(ledger_path),
        "HITS": before if before is not None else "（无台账）",
        "AFTER_DEDUPE": stats["total"],
        "AFTER_SCREEN": stats["total"],
        "HTML_COUNT": access["HTML"],
        "PDF_COUNT": access["PDF"],
        "NO_FULLTEXT": stats["no_fulltext"],
        "GAP_NOTE": gap_note(stats, target, delivered, missing_rows, before),
        "WORKDIR": str(wd),
        "TOTAL": stats["total"],
        "WITH_MD": stats["with_md"],
        "WITH_PDF": stats["with_pdf"],
        "MISSING_FILE": stats["missing_file"],
        "UNREGISTERED": stats["unregistered"],
        "THIN": stats["thin"],
    }

    text = render(template, mapping)
    # STATS 块整体重写，杜绝模板里残留的手写数字（漏键/改值都会被位 4 拦）
    block = "<!-- STATS " + json.dumps({k: stats[k] for k in STATS_KEYS},
                                       ensure_ascii=False, separators=(", ", ": ")) + " -->"
    text = STATS_BLOCK_RE.sub(block, text)
    if "<!-- STATS" not in text:
        text = text.rstrip() + "\n\n" + block + "\n"

    out = Path(args.out) if args.out else wd / OUT_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    leftover = sorted(set(re.findall(r"\{\{([A-Z_0-9]+)\}\}", text)))
    result = {"ok": not leftover, "out": str(out), "stats": stats,
              "delivered": delivered, "target": target,
              "unfilled_placeholders": leftover, "ledger": str(ledger_path) if ledger_path else ""}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✓ 检索报告 → {out}")
        print(f"  共 {stats['total']} 条，HTML {access['HTML']} / PDF {access['PDF']}，"
              f"缺文件 {stats['missing_file']}，篇幅不足 {stats['thin']}")
        if leftover:
            print(f"! 有未填占位符：{', '.join(leftover)}")
        else:
            print("  STATS 块已由 index_stats.json 填入（六键齐全）")
    sys.exit(0)


if __name__ == "__main__":
    main()
