# CHANGELOG

## 1.4.0（2026-10-25）

功能新增 → minor。修复栏与功能新增栏分列；每项都跑了必红用例（永不失败的门禁等于没有门禁）。

### 修复栏

1. **新建 CHANGELOG.md**（本文件），记本轮全部改动。
2. **`raw/_logs/session.json` 无生产者**：新增 `scripts/register_session.py`（写 sid + 机构名 + 时间戳，不落盘 cookie），`verify_delivery.py` 新增位 16 + `--require-session`。
3. **检索台账三条口头门禁变真门禁**：`verify_delivery.py` 新增 `check_ledger()` + 位 32 + `--ledger`（复用 `schema.LEDGER_COLUMNS`）。空台账、缺列、缺 hits/refine 值分别必红。
4. **重复键静默丢数据 ×3 全部改 fail fast**：`pdf_fetch.py`（原 last-wins，被丢条目连失败行都没有，成孤儿）、`cnki_detail_scan.py`（原 first-wins，补抓字段只上到第一条）、`dedupe.py`（原不设 rid 主键，两条同 rid 不同篇名同时保留 → 下游 `build_index.py` 毫无征兆 exit 65）。三处改为检出即报中文错误退出 65。
5. **`html_whitelist.json` / `no_html.json` 零消费者**：由 `plan_download.py` 消费；`no_html` 条目经 `raw/no_html_reasons.json` 进 `未获取全文.md` 原因链（原显示「未登记原因」）。
6. **知网 `quality_tags` 恒为 `[]`**：`cnki_scan.py` 改为从来源类别列解析（CSSCI / 北大核心 / CSCD / SCI / SSCI / EI / AMI / OA），拉丁缩写按词边界匹配（`CSSCI` 不再被误判成 `SCI`+`SSCI`）。
7. **两套失败原因词汇表并存**：统一到 `scripts/reason_codes.py`（10 值枚举 + `canonical()` 映射），`pdf_fetch.py` 写 manifest 前归一；`cnki-playbook.md §12` 同步对齐并加映射表；`--lint-assets` 校验两边一致。
8. **CLI 未文档化 ×4 组**：SKILL.md §3 补 G5 参数速查表（`build_index` 的 `--records/--md-dir/--pdf-dir/--recursive/--outdir/--min-chars/--json`、`verify_delivery` 的 `--brief-only/--min-chars/--records/--lint-assets`、`pdf_fetch` 的 `verify` 子命令、`dedupe` 的 `--fuzzy`）。
9. **`build_index --recursive` 与 verify `rglob` 口径不一致**：verify 同步 `--recursive 0|1`（默认 0），非递归时给 `refs.subdir_skipped` warning 提示盲区；两边不再「一边扫到一边没扫」导致位 1 恒失败。
10. **`index_duplicates.csv` 陈旧不覆写**：无重复时主动删除，杜绝旧名豁免放行真正的未入索引文件。
11. **`env_check.py` 过度门禁**：`pypdf` / `openpyxl` 全仓无 import，降为可选（warn）并写明实际用途；必填只留 `pymupdf`。
12. **样例自相矛盾**：`evals/sample-outputs/文献题录.txt` 的 `SR 2` 与 `make_delivery_fixture.py` 的 `f"SR {i}"` 改为恒 `SR 1`，与 references / smoke-cases 口径一致。
13. **WOS「71 字段」集合不一致**：`WOS_ORDER` 补 `SU`（Research Areas，此前被静默丢弃），降级路径 `wos_fallback_raw` 也补 `SU`/`WC`；与 `wos-playbook.md §8` 清单对齐。
14. **`index.csv` 缺排序列**：新增 `score` / `citedness_2yr` 两列（`quality-screening.md §6` 要求「只排不记等于没排」），`build_index.fill_scores()` 按批次内 min-max 归一计算。
15. **两处文档-代码漂移**：`cnki-playbook.md` 的「12 个标准键」改为实际 20 键（12 标准 + 8 流程辅助）；`assets/索引.template.md` 总览表「分类」改「平台」对齐 `render_markdown()`，`--lint-assets` 新增内容级检查（列名、可重复 `{{GROUP}}`、报告模板 STATS 六键与缺口占位符）。
16. **硬规则 8 表述失真**：原称「脚本内用 `Path(__file__).resolve()`」，实际只有两处自解析，真实契约是「调用方传绝对路径」——按真实契约改写。
17. **FAQ Q1 未提示 `--dry-run`**：补上（否则真的会开始下载），并指向 `enrich_metrics.py --dry-run`。
18. **`check_brief_gap` 缺口门禁可绕过**：原 `GAP_WORDS` 全文关键词匹配（含「缺 」「差 」两字词）改为结构化判定——要求「缺口/待核对/未获取」标题节且节内至少一条列表项；光写「存在缺口」仍被拦。
19. **description 缺 `Exclude`**：`Not for` 改为 `Exclude`（≤1024 字符、无尖括号）。

### 功能新增栏

- **F1 `scripts/render_report.py`**：检索报告渲染器（此前有 schema、有模板、有门禁却没有 renderer，只能人手填数字，与硬规则 4 自相矛盾）。读 `index_stats.json` + `00_需求确认.json` + 台账 + `index.csv` 渲染 `assets/检索报告.template.md` 并注入 STATS；`--check` 单独对账。
- **F2 台账校验器**：即修复 3 的可执行部分（位 32 + `--ledger`）。
- **F3 `scripts/merge_records.py`**：增量批次合并进既有 `raw/records.json`（此前无任何脚本支持，只能临场写 inline Python）。rid 撞车且篇名不同 → 退出 65 且不写入；同 rid 同篇名只补空字段。
- **F4 `scripts/enrich_metrics.py`**：OpenAlex 指标采集，`2yr_mean_citedness` / OA 命中率写回 records，`index.csv` 增列（配合修复 14）。必须先 `--dry-run` 探命中率；指标是「非 JIF」。
- **F5 `scripts/plan_download.py`**：下载计划生成器，消费 `html_whitelist.json` / `no_html.json`，输出 rid / 通道 / URL 计划表，并把无入口条目接进未获取原因链（配合修复 5）。
- **F6 `scripts/register_session.py`**：会话登记（修复 2 的脚本侧）。
- **新增 `scripts/schema.py`**：全仓 schema 唯一真源（`INDEX_COLUMNS` / `MANIFEST_COLUMNS` / `LEDGER_COLUMNS` / `BRIEF_KEYS` / `STATS_MIN_KEYS` / `PLAN_COLUMNS` / `SESSION_KEYS` / 台账阈值 / 打分权重），消除此前加一列要改三处的漂移源。
- **新增 `references/shared/scripts-guide.md`**：六个新入口的判据、坑与数据流图。

### 未改动

- 打包布局与命名保持原样；未安装、未发布。
- 知网/WOS 界面选择器、题录导出格式、四重校验口径均未改动。
