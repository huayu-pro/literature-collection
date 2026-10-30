#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""全仓共享的 schema 常量（表头 / 键名唯一真源）。

背景：v1.3 的 INDEX_COLUMNS 在 build_index.py 与 verify_delivery.py 各写一份，
LEDGER_COLUMNS 只在 verify_delivery 里有而 assets 模板另写一份——加一列要改三处，
漏一处就出现「模板与代码漂移」（v1.3 的 索引.template.md 漂移即由此而来）。
本模块是唯一真源；改列只改这里，lint_assets 会强制模板跟着走。

用法：
    from schema import INDEX_COLUMNS, MANIFEST_COLUMNS, LEDGER_COLUMNS, BRIEF_KEYS
"""
# 索引表头（index.csv / assets/文献清单.template.csv）
INDEX_COLUMNS = [
    "rid", "platform", "title", "authors", "source", "year", "cited", "downloads",
    "quality_tags", "access", "rel_path_md", "rel_path_pdf", "chars", "status", "note",
    # v1.4 增列（method/quality-screening.md §6「排序结果写进 index.csv，不要只排不记」）：
    # score = 0.75*norm(cited) + 0.15*norm(citedness_2yr) + 0.10*norm(主题词命中数)
    # citedness_2yr 由 enrich_metrics.py 从 OpenAlex 采集，是「2yr 均被引（非 JIF）」
    "score", "citedness_2yr",
]

# PDF 下载清单表头（manifest.csv / assets/manifest.template.csv）
MANIFEST_COLUMNS = ["rid", "doi", "url", "file", "status", "bytes", "pages", "doi_match", "reason"]

# 检索台账表头（检索台账.csv / assets/检索台账.template.csv）
LEDGER_COLUMNS = [
    "qid", "platform", "query_raw", "fields", "refine_before", "refine_after",
    "hits", "date", "institution", "note",
]

# 需求确认 7 键（00_需求确认.json / assets/brief.template.json）
BRIEF_KEYS = ["topic", "platform", "discipline", "year_range", "target_count",
              "quality_gate", "deliverable"]

# 检索报告 STATS 块最小键集（verify 位 4 校验）
STATS_MIN_KEYS = ["total", "with_md", "with_pdf", "missing_file", "unregistered", "thin"]

# 下载计划表头（plan_download.py 产物 raw/download_plan.csv）
PLAN_COLUMNS = ["rid", "title", "channel", "url", "reason", "detail_confirmed"]

# 会话登记必需键（register_session.py 产物 raw/_logs/session.json）
SESSION_KEYS = ["session_id", "institution", "registered_at"]

# 台账门禁：数据行下限（G2 门禁「≥3 行」）
LEDGER_MIN_ROWS = 3
# 台账必填列：缺值即视为该条没记全（G2 门禁「含 hits 与 refine_before/after」）
LEDGER_REQUIRED_COLS = ("refine_before", "refine_after", "hits")


def score_weights():
    """quality-screening.md §6 的权重；brief 的 quality_gate 可覆盖。"""
    return {"cited": 0.75, "citedness_2yr": 0.15, "topic_hits": 0.10}


if __name__ == "__main__":
    print("INDEX_COLUMNS   :", ",".join(INDEX_COLUMNS))
    print("MANIFEST_COLUMNS:", ",".join(MANIFEST_COLUMNS))
    print("LEDGER_COLUMNS  :", ",".join(LEDGER_COLUMNS))
    print("BRIEF_KEYS      :", ",".join(BRIEF_KEYS))
    print("STATS_MIN_KEYS  :", ",".join(STATS_MIN_KEYS))
    print("PLAN_COLUMNS    :", ",".join(PLAN_COLUMNS))
    print("SESSION_KEYS    :", ",".join(SESSION_KEYS))
