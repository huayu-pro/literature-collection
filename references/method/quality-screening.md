# 质量筛选口径

> 读完能做什么：把 500 条初检结果压到 30 条「头部文献」，并且能解释每一条为什么留下、为什么被淘汰。
> 原则：先筛来源层级，再看引用；新发表论文用年均口径，不用总被引一刀切。

## 1. 双平台维度对照

| 维度 | 知网（CNKI） | Web of Science |
| --- | --- | --- |
| 来源层级 | 来源类别：CSSCI / 北大核心 / CSCD / SCI | 期刊分区（JCR/中科院）— 检索页拿不到，见 §5 |
| 学科 | `CLC` 分类号 / 168 专题导航 | `WC`（WoS Categories）/ `SU`（Research Areas） |
| 文献类型 | 期刊 / 学位论文 / 会议 / 报纸 | `DT`：Article / Review / Proceedings Paper |
| 被引 | 被引频次（结果页 `#CF` 排序） | `TC`（核心合集）/ `Z9`（全库） |
| 下载 | 下载频次（`#DFR` 排序） | 无 |
| 年份 | 检索控制区时间范围 | `PY` / refine 出版年 |
| 作者 | `AU` / `AF` | `AU` / `AF`（作者标识符 `AI`） |
| 基金 | `FU` 基金文献筛选 | `FO` / `FG` |
| 语言 | 中文为主，默认中英文扩展 | `LA`（refine 面板，不是检索字段） |
| OA | 无 | `OA` 字段 + OpenAlex 兜底 |
| 高质量标记 | CSSCI/北核标签 | `HC`（Highly Cited）、`OA` |

## 2. 知网筛选顺序（每步记录筛后数）

1. **来源类别**：结果页左侧 `a[title="CSSCI"]` / `a[title="北大核心"]` / `a[title="CSCD"]`，勾选其所在 `li` 的 checkbox。2 万级通常降到百级。
2. **文献来源**：限定 2–5 本领域顶刊（`JN`），或排除日报/会议通知。
3. **作者/机构**：追核心团队时用；做综述时不要过早限定，会漏掉外部视角。
4. **基金**：只保留国家级/省部级基金成果时用；会显著缩小样本。
5. **被引与下载**：按 `#CF` 降序，取前 N；再按 `#DFR` 复核一遍「高下载低被引」的新文。
6. **人工过标题**：只在这一步看标题，前面都用机器可判据。

排序操作（a11y 树不给 ref，必须 evaluate）：

```js
(() => {
  const el = document.querySelector("#orderList #CF");
  if (!el) return JSON.stringify({ok:false, step:"no_cf"});
  el.click();
  const desc = el.className.includes("DESC") || el.closest("li")?.className.includes("DESC");
  if (!desc) el.click();                    // 第一次是 ASC，第二次才是 DESC
  return JSON.stringify({ok:true, cls: el.className});
})()
```

## 3. WOS 筛选顺序

1. **refine 文献类型**：`Article` + `Review`（排除 Editorial / Letter / Meeting Abstract）。
2. **refine 语言**：`English`（或按需保留中文）。
3. **refine 学科**：`WC` 精确到子学科（如 `Political Science`），不要用 `SU` 的宽类。
4. **refine 出版年**：与 brief 的 `year_range` 对齐。
5. **排序**：`Sort by: Times Cited — highest first`。
6. **按 `Z9` 复核**：`TC` 只统计核心合集，跨库引用看 `Z9`。

## 4. 新发表放宽公式

```text
年均被引 = cited / max(1, 当前年 - 发表年)
年均下载 = downloads / max(1, 当前年 - 发表年)
```

| 发表年差 | 用哪个口径 | 理由 |
| --- | --- | --- |
| ≥ 3 年 | 总被引 | 有足够时间积累 |
| 1–2 年 | 年均被引 | 总被引天然吃亏 |
| 当年 | 只看下载 + 来源层级 + 作者 | 引用还没来得及发生 |

入选线示例（可按 brief 覆盖）：

| 来源层级 | 3 年以上 | 1–2 年 | 当年 |
| --- | --- | --- | --- |
| CSSCI / SSCI | 被引 ≥ 20 | 年均 ≥ 8 | 下载 ≥ 300 |
| 北大核心 / SCIE | 被引 ≥ 10 | 年均 ≥ 4 | 下载 ≥ 150 |
| 普通期刊 | 被引 ≥ 5 | 年均 ≥ 2 | 下载 ≥ 50 |

## 5. 分区/JIF 拿不到时的三级替代

WOS 检索页**不提供** JIF 与分区（属 InCites 能力）。不要假装有。

| 级别 | 替代指标 | 来源 | 列名必须写成 |
| --- | --- | --- | --- |
| 1 | `2yr_mean_citedness`（两年均被引） | OpenAlex `sources` | 「2yr 均被引（非 JIF）」 |
| 2 | 期刊 h-index | OpenAlex / Scimago | 「期刊 h-index（非分区）」 |
| 3 | WoS 类别内相对排名 | JCR 官网人工查 | 「类别排名（人工核对，日期）」 |

**禁止**把上述任一指标写成「JIF」「一区」「Q1」。评审一眼能看出来。

## 6. 质量分与排序

```text
score = 0.75 * norm(cited) + 0.15 * norm(2yr_mean_citedness) + 0.10 * norm(主题词命中数)
```

- `norm` 用 min-max 或分位数，同一批次内归一。
- 权重可由 `00_需求确认.json` 的 `quality_gate` 覆盖（例如纯理论综述把主题命中权重提到 0.3）。
- 排序结果写进 `index.csv`，**不要只排不记**。

落地（v1.4 起可执行，此前公式里的 `2yr_mean_citedness` 根本取不到，只能凭感觉排）：

```sh
/usr/bin/python3 scripts/enrich_metrics.py raw/records.json --dry-run --mailto 你的邮箱   # 先探命中率
/usr/bin/python3 scripts/enrich_metrics.py raw/records.json --mailto 你的邮箱 --json      # 写回 citedness_2yr
/usr/bin/python3 scripts/build_index.py "<工作目录>" --title "<题目>"                      # 算 score
```

`build_index.py` 按批次内 min-max 归一化算 `score` 并写入 `index.csv` 的 `score` 列，
同时把 `citedness_2yr` 一并落列（两列均为 v1.4 新增）。同一批次所有值相同时该维度全 0，
不制造虚假区分度。`topic_hits`（主题词命中数）由调用方在 records 里填，缺省按 0 参与归一。
权重常量在 `scripts/schema.py` 的 `score_weights()`。

## 7. 标签字典（写进 `quality_tags`，逗号分隔）

```text
CSSCI  北大核心  CSCD  SSCI  SCIE  ESCI  AHCI  OA  PREPRINT  HC  无全文
```

## 8. 不达标处置

| 情况 | 处置 | `reason` |
| --- | --- | --- |
| 非核心且低被引 | 移入 `备选/` | `非核心` |
| 类型不符（社论/书评/会议通知） | 移入 `备选/` | `类型不符` |
| 被引低于入选线 | 移入 `备选/` | `低被引` |
| 找不到全文 | 保留题录，不建正文 | `无全文` |
| 与已收文献重复 | 合并，保留字段最全者 | `重复` |

**备选不是垃圾桶**：`备选/` 里的文件仍要进索引，标 `status=thin` 或 `note=备选`，方便二次取用。
