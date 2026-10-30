# 脚本指引：v1.4 新增的六个入口

> 何时读：要登记会话、判下载通道、采集代理指标、合并增量批次、渲染检索报告，
> 或想确认「哪个产物由谁写、被谁消费」时。SKILL.md §3 只给命令，本篇给判据与坑。

## 0. 一张数据流图（谁写 → 谁读）

```
cnki_scan.py ──▶ cnki_records.json / html_whitelist.json / no_html.json
                                        │
                                        ▼
                              plan_download.py ──▶ download_plan.csv（G4 执行依据）
                                        │          no_html_reasons.json
                                        ▼
                              build_index.py ◀── 填进 未获取全文.md 的原因链

register_session.py ──▶ raw/_logs/session.json ──▶ verify_delivery.py --require-session（位 16）

merge_records.py ──▶ records.json（增量批次，rid 撞车 fail fast）
cnki_detail_scan.py ──▶ records.json（补抓空字段，重复 rid fail fast）
enrich_metrics.py ──▶ records.json（citedness_2yr / oa_available）──▶ build_index（index.csv 的 score）

build_index.py ──▶ index.csv / 索引.md / index_stats.json ──▶ render_report.py ──▶ 检索报告.md
                                        └──────────────────────────▶ verify_delivery.py（位 4）
```

v1.3 的两类断点已补齐：`html_whitelist.json`/`no_html.json` 曾有生产者无消费者，
`raw/_logs/session.json` 曾有门禁无生产者。

## 1. register_session.py —— 会话登记

```sh
/usr/bin/python3 scripts/register_session.py "<工作目录>" --sid $sid --institution "某大学" --platform cnki
/usr/bin/python3 scripts/register_session.py "<工作目录>" --check        # 只读校验，退出 0/65
/usr/bin/python3 scripts/verify_delivery.py "<工作目录>" --require-session  # 位 16
```

- 必需三键：`session_id` / `institution` / `registered_at`。缺任一位 16 就红。
- **只记 sid 与机构名，不落盘 cookie / token / 密码**（SKILL.md §12）。机构名可写「某高校」脱敏。
- `--sid` 或 `--institution` 缺一即退出 64，不会写半个文件。
- 为什么要有它：SKILL.md §G1 一直要求把 sid 写进这个文件，但 v1.3 全仓没生产者也没读者——
  那种门禁永远不可能失败。现在两端都齐了。

## 2. plan_download.py —— 下载计划

```sh
/usr/bin/python3 scripts/plan_download.py "<工作目录>" --json
/usr/bin/python3 scripts/plan_download.py "<工作目录>" --confirm raw/detail_probe.json
```

- 判通道只依据 `cnki_scan.py` 已记录的 `has_html` / `has_pdf`，**不做猜测式补全**。
- 硬规则 2 要求两次确认：本脚本只认第一次（结果页）。详情页结论用 `--confirm` 传入
  `[{rid, has_html}]`；`--confirm` 只对「HTML → 无 HTML」降级生效，不会反向升级（不猜）。
- 产物 `raw/no_html_reasons.json` 会被 `build_index.py` 读走，填进 未获取全文.md 的
  「未获取原因」。v1.3 里这批条目只能显示「未登记原因」，原因链断在这里。
- 原因优先级（低→高）：`manifest.csv` 失败行 → `no_html_reasons.json` → `_quarantine/reasons.csv`。

## 3. enrich_metrics.py —— OpenAlex 代理指标

```sh
/usr/bin/python3 scripts/enrich_metrics.py raw/records.json --dry-run --mailto 你的邮箱
/usr/bin/python3 scripts/enrich_metrics.py raw/records.json --mailto 你的邮箱 --json
```

- 写回 `citedness_2yr`（两年均被引）、`oa_available`、`oa_url`、`source_oa_name`。
- **列名必须带「非 JIF」**：这是 `2yr_mean_citedness`，不是影响因子、不是分区、不是 Q1。
  脚本自身不写任何 JIF/一区/Q1 字样，报告与索引里也不许写（quality-screening §5）。
- `--dry-run` 只探命中率不写回。命中率 <50% 时别拿它当唯一排序依据，退回被引 + 来源层级。
- 两步取数：`/works` 拿 `primary_location.source`，再按 **ISSN-L** 查 `/sources?filter=issn:...`，
  因为 `2yr_mean_citedness` 在 source 实体的 `summary_stats` 里，works 顶层没有。
  拿 OpenAlex 完整 URL 当 `ids.openalex.org` 过滤值会被 API 拒（400），不要那样写。
- 只补空字段；要覆盖已有值加 `--overwrite`。全部批次失败且无任何结果 → 退出 65。

## 4. merge_records.py —— 增量批次合并

```sh
/usr/bin/python3 scripts/merge_records.py raw/records.json raw/new_batch.json --json
/usr/bin/python3 scripts/merge_records.py raw/records.json raw/new_batch.json -o raw/merged.json
```

- 默认原地改写 `records`（第一条参数）；`-o` 写到别处。
- **rid 撞车 fail fast**：同 rid 但篇名不同 → 退出 65 且**不写入任何文件**，
  错误信息里给出可用的 `--start N`。同 rid 同篇名 → 只补空字段，已有值不覆盖。
- 合并后条数 = 旧 + 新（新增部分）；`updated` 计的是补了字段的既有条目。
- 为什么要有它：SKILL.md §3 一直声称「把新 records 合并进 raw/records.json」，
  但 v1.3 没有任何脚本支持（`cnki_scan.py` 是整体覆写），只能靠 agent 临场写 inline Python。

## 5. render_report.py —— 检索报告渲染

```sh
/usr/bin/python3 scripts/render_report.py "<工作目录>" --title "基层治理数字化" --json
/usr/bin/python3 scripts/render_report.py "<工作目录>" --check     # 只校验 STATS 块对账
```

- 数字全部取自脚本产物：`index_stats.json`（六键 + no_fulltext）、`index.csv`（access 分布）、
  台账（`refine_before/after` 合计）、`00_需求确认.json`（主题/目标/门槛）。**不手写任何数字**。
- STATS 块整体重写，模板里残留的手写数字不会泄漏到产物。
- 缺口说明按结构化格式输出（标题节 + 表格/列表条目），满足 verify 位 4 的结构化判定。
- `--check` 单独对账：STATS 缺键或与 `index_stats.json` 不等 → 退出 4。

## 6. verify_delivery.py 的三个新开关

| 开关 | 位 | 启用条件 |
| --- | --- | --- |
| `--require-session` | 16 | 显式加才启用（G0/G1 可能还没开浏览器，默认不该挡） |
| `--ledger <路径>` | 32 | 传了路径就启用；文件不存在直接退出 64 |
| `--recursive 1` | — | 与 `build_index.py --recursive` **必须同步**，否则一边扫到一边没扫，位 1 恒失败 |

`--lint-assets` 现在不只比表头，还做内容级一致性：索引模板总览表的列名（平台，不是「分类」）、
`{{GROUP}}` 可重复渲染（出现 ≥2 次）、报告模板的 STATS 六键与缺口占位符，
以及 `cnki-playbook.md §12` 的原因枚举与 `scripts/reason_codes.py` 是否逐项对齐。

## 7. 失败原因只有一套：scripts/reason_codes.py

v1.3 曾有两套互不映射的词汇表（playbook 的 7 值人工枚举 vs `pdf_fetch.py` 自造的 8 值流式值）。
现在唯一真源是 `scripts/reason_codes.py` 的 10 值枚举，`pdf_fetch.py` 写 manifest 前经
`canonical()` 归一，未登记写法一律落 `network`（宁可笼统，也不让第二套词汇表复活）。

```sh
/usr/bin/python3 scripts/reason_codes.py          # 打印全表
/usr/bin/python3 scripts/reason_codes.py doi_mismatch   # → mismatch（DOI/篇名与记录不符）
```

新增原因值必须同时改 `reason_codes.py` 与 `cnki-playbook.md §12`，`--lint-assets` 会校验。
