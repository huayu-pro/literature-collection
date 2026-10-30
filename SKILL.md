---
name: literature-collection
description: |
  Use when someone needs a batch of academic literature rather than one paper:
  clarify scope, build CNKI or Web of Science queries, screen by source tier and
  citations, fetch HTML or PDF full text through the user's already-logged-in
  browser, convert to Markdown, and deliver an indexed folder with CSV and report.
  Exclude single-paper metadata lookups (查 DOI、查定义), paywall bypass, and non-academic
  web scraping; single-link full-text conversion is supported via the minimal path.
  触发词：文献搜集、批量下载论文、知网检索、WOS检索、文献综述找文献、下载全文、文献索引、补文献、导出题录、文献题录、参考文献列表、GB/T 7714、APA格式、MLA格式、导出RIS、Zotero。
metadata:
  version: "1.4.0"
---

# 文献搜集与全文下载（知网 / Web of Science）

依赖：`browser-skill`（bsk 0.3.3）、`/usr/bin/python3`（需 `pymupdf`：PDF 页数与内嵌 DOI 校验）、`curl`；`pdftotext/pdfinfo` 仅人工核对 PDF 数字时用，`pypdf`/`openpyxl` 仅个别人工场景用，三者缺失都只 warn 不挡流程（`env_check.py --json` 可查）。命令行一律写 `/usr/bin/python3`，不要写 `python3`（PATH 上的可能缺依赖）。
前提：用户浏览器已登录机构账号（机构 IP 或漫游），有对应数据库订阅。**没有订阅也能用**，但只能交付题录与 OA 全文。

## 1. 快速开始

三条可直接粘给用户的开场白：

> 帮我搜集 30 篇 CSSCI 关于「基层治理数字化」的文献，2016 年以后，要 Markdown 正文和索引。

> 在 WOS 找 populism 与 political communication 交叉的文献，近十年，只要 Article/Review，先出清单再下载。

> 把这个知网链接的正文抓成 Markdown，保留标题和脚注。

五分钟最小路径（单篇知网 HTML）：

```sh
bsk browsers --json
bsk session start --json --browser <id>                    # 记下 sid
bsk navigate https://www.cnki.net/ --session $sid          # 断言机构名
bsk navigate https://kns.cnki.net/kns8s/AdvSearch --session $sid
# 填式子 → Escape → focus '#btnSearch' → Enter
# 结果页点「HTML阅读」→ 滑块 → 提取 .pdfFullBox .study-c → page.json
/usr/bin/python3 scripts/html_to_md.py page.json -o 正文/C0001_x.md --rid C0001
```

## 2. 什么时候用 / 不用

| 分类 | 场景 | 判据 |
| --- | --- | --- |
| **该用** | 写综述要 30 篇核心文献；补一个专题的全文库；把已有 PDF 批量转 MD 并建索引 | 需要「题录 + 全文 + 索引」三件套，或数量 ≥5 篇 |
| **不该用** | 查一篇论文的 DOI；只要一个定义；抓新闻/公众号；绕过付费墙 | 单篇随手查 → 用 `cnki-literature-retrieval`；非学术网页 → 用通用抓取 |
| **拿不准** | 用户只说了题目没说数量；说了「找一些」；只给了一个链接 | 问一句「要几篇、要不要全文」；单链接单篇走 §1 最小路径 |

「拿不准」的三种判法：只给题目 → 先问数量与年份；说「找一些」→ 按 30 篇默认并复述给用户确认；只给链接 → 单篇走 §1，不进六阶段。

## 3. 六阶段主流程

### G0 需求澄清（不得跳过，不得先开浏览器）

一次性给出 7 项 + 默认值，让用户一次确认，不要连环追问：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `topic` | 无 | 主题，必须能写成一句人话 |
| `platform` | 问用户 | `cnki` / `wos` / `both` |
| `discipline` | 无 | 学科，用于 `CLC` 或 `WC` 限定 |
| `year_range` | 近 10 年 | `2016-2026` |
| `target_count` | 30 | 最终要几篇 |
| `quality_gate` | 知网 CSSCI+北核；WOS Article/Review | 质量门槛 |
| `deliverable` | 索引.md + index.csv + 文献题录.txt + 正文/*.md | 交付形态；有缺文件时另附 未获取全文.md |

写入 `00_需求确认.json`（模板见 `assets/brief.template.json`）。
**门禁**：7 键齐全非空，`verify_delivery.py <工作目录> --brief-only 00_需求确认.json` 退出 0（G0 还没有 index.csv，用 `--brief-only` 单验需求，别跑全量校验）。

### G1 浏览器与登录态

```sh
bsk browsers --json
bsk session start --json --browser <id-or-label>     # 同 profile 共享 cookie，别并行开两个会话
bsk navigate https://www.cnki.net/ --session $sid
bsk evaluate '(() => document.body.innerText.slice(0,400))()' --session $sid --json
```

**门禁**：知网正文含机构名 + 「个人登录」；WOS 右上出现机构名。`session_id` 写进 `raw/_logs/session.json`（用 `scripts/register_session.py`，不要手拼 JSON——只记 sid 与机构名，不落盘 cookie）：
```sh
/usr/bin/python3 scripts/register_session.py "<工作目录>" --sid $sid --institution "某大学" --platform cnki
/usr/bin/python3 scripts/verify_delivery.py "<工作目录>" --require-session      # 位 16 校验
```
**失败去向**：停下问人。不重登、不新开 profile、不猜账号。

### G2 检索式构造

以领域资深学者视角做四类扩展（同义/近义/上下位/相关），再按平台语法成型。详见 `method/query-design.md`。

```text
知网：TI = (基层治理 + 基层社会治理) * (数字化 + 数字技术 + 技术治理)
WOS ：TS=("grassroots governance" OR "local governance") AND TS=(digital* OR "smart govern*")
```

**门禁**：`检索台账.csv` ≥3 行；知网单框 ≤120 字符且括号配对；WOS 表达式不含 `TS=` 前缀（它只属于 Query Preview 框）。
台账三条门禁现由脚本执行（此前只是口头要求，verify 从不读它）：

```sh
/usr/bin/python3 scripts/verify_delivery.py "<工作目录>" --ledger "<工作目录>/检索台账.csv"   # 位 32
```

### G3 质量筛选

知网：来源类别（CSSCI/北核）→ 刊名 → 作者/机构 → 基金 → 被引/下载。结果页行交给 `cnki_scan.py` 解析（输出 cnki_records.json + HTML 白名单 + no_html 清单）。
WOS：refine（DT/LA/WC/PY）→ 按 `TC`/`Z9` 排序 → 复核期刊。导出 Full Record 后交 `wos_parse.py` 解析成 records.json。
新发表用年均口径，见 `method/quality-screening.md` §4。
代理指标（OpenAlex `2yr_mean_citedness`，**非 JIF**）用 `scripts/enrich_metrics.py` 采集，先 `--dry-run` 探命中率：

```sh
/usr/bin/python3 scripts/enrich_metrics.py raw/records.json --dry-run --mailto 你的邮箱
/usr/bin/python3 scripts/enrich_metrics.py raw/records.json --mailto 你的邮箱 --json   # 写回 citedness_2yr
```

**门禁**：每条记录有 `quality_tags` 与 `cited`；筛选前后计数写回台账。
`quality_tags` 由 `cnki_scan.py` 从来源类别列解析（CSSCI/北大核心/CSCD/SCI/SSCI/EI/AMI/OA）；左侧面板未勾选导致解析为空时，按 `cnki-playbook.md` §9 用 `index.csv` 白名单补筛，不要手改 JSON 填标签。

### G4 下载与转换

**知网先判两次，再决定通道**：
1. 结果页看 `td.operat` 是「HTML阅读」还是「原版阅读」；
2. 进详情页看 `li.btn-html a` 是否存在。
两次都说没有 HTML → 才下 PDF。只有一次命中就下结论，会把可 HTML 的文献误判成 PDF。
判完用 `plan_download.py` 落成计划表（消费 `raw/html_whitelist.json` 与 `raw/no_html.json`——它们此前是零消费者产物，只能靠人回看 JSON 手判），并把无入口条目接进 未获取全文.md 的原因链：

```sh
/usr/bin/python3 scripts/plan_download.py "<工作目录>" --json
/usr/bin/python3 scripts/plan_download.py "<工作目录>" --confirm raw/detail_probe.json   # 详情页二次确认后回传
# → raw/download_plan.csv（rid/通道/URL）+ raw/no_html_reasons.json（build_index 会读它填原因）
```

| 通道 | 动作 | 脚本 |
| --- | --- | --- |
| HTML | 滑块验证 → 提取 `.pdfFullBox .study-c` | `html_to_md.py`（脚注重编号） |
| 详情页补字段 | 知网详情页抓关键词/摘要/卷期页码/ISSN/CN/机构 | `cnki_detail_scan.py` 合并回 records.json（题录导出的 K1/AB/vo/IS/OP/SN/CN/AD 全靠它喂饱） |
| PDF（知网） | `bsk download @eN --out pdf/<rid>_...pdf` | 暂不 OCR；0 字符直接换文献 |
| PDF（WOS） | OpenAlex OA 直链 → 4 线程 curl → 四重校验 | `pdf_fetch.py` → `pdf_to_md.py` |

**门禁**：`manifest.csv` 每行有 `rid/file/bytes/pages/doi_match/status`；每篇 MD 有 front-matter 与「转换损耗声明」。
下载失败不重试硬凑：登记 `manifest.csv` 失败行（rid + reason），G5 会把失败篇目连同题录、知网/WoS 链接写进 未获取全文.md，供人工补齐。

### G5 索引与交付

```sh
/usr/bin/python3 scripts/dedupe.py raw/records.json --log raw/dedupe_log.csv
# ↑ 默认原地模式：首次备份 records.raw.json，去重结果写回 records.json，
#   被合并 rid 的 正文/备选/pdf 文件自动改名到胜者 rid——下游三个脚本无需任何参数就吃到去重结果
/usr/bin/python3 scripts/build_index.py "<工作目录>" --title "<题目>"      # 同时生成 未获取全文.md（仅当有缺文件）
/usr/bin/python3 scripts/render_report.py "<工作目录>" --title "<题目>"    # 检索报告.md（数字全部取自 index_stats.json）
/usr/bin/python3 scripts/export_citations.py "<工作目录>"                 # 文献题录.txt（知网/WoS 真实导出格式）
/usr/bin/python3 scripts/export_citations.py "<工作目录>" --format gbt7714  # 可选：参考文献.md / --format ris / bibtex
/usr/bin/python3 scripts/verify_delivery.py "<工作目录>" --brief 00_需求确认.json --json
```

**增量补文献**（已有 C0001-C0030 再补 10 篇）：新批次扫描/解析用 `--start 31` 续编 rid（`cnki_scan.py --start` / `wos_parse.py --start`），再用 `merge_records.py` 合并进 `raw/records.json`（重复 rid 且篇名不同会 fail fast 退出 65，续编就不会撞），最后跑上面 G5 全链——dedupe 原地模式顺手把新旧批次间的重复文献合掉：

```sh
/usr/bin/python3 scripts/merge_records.py raw/records.json raw/new_batch.json --json
```

**门禁**：`verify_delivery.py` 退出码 0。非 0 一律不得宣称完成；按 `problems[].fix` 逐条修。

### G5 脚本参数速查（此前四组零文档）

| 脚本 | 参数 | 说明 |
| --- | --- | --- |
| `build_index.py` | `--records` | 题录真源覆盖，默认 `<工作目录>/raw/records.json`（降级顺序 records.json → records.dedup.json → cnki_records.json） |
| | `--md-dir` | 可重复，默认同时扫 `正文` 与 `备选` |
| | `--pdf-dir` | 可重复，默认 `pdf` |
| | `--recursive` | **默认 False，只扫一层**。文件放在 `正文/子目录/` 下时必须加它，且 `verify_delivery.py --recursive 1` 要同步加——两边口径不一致时，一边不扫、另一边扫到，位 1 会恒失败且「重跑 build_index」无效 |
| | `--outdir` | 索引产物输出目录，默认与 workdir 相同 |
| | `--min-chars` | 正文达标字数，默认 4000；不足标 `thin` |
| | `--json` | 输出 stats JSON（含 total/with_md/with_pdf/missing_file/unregistered/thin） |
| `verify_delivery.py` | `--brief-only` | G0 阶段用：只校验需求确认 7 键，不跑交付校验（此时还没有 index.csv） |
| | `--min-chars` | 与 build_index 同口径，默认 4000 |
| | `--records` | 题录真源覆盖（与 export/build 同口径） |
| | `--lint-assets` | 只校验 assets 模板与 schema / 代码输出是否一致（含原因枚举与文档对齐） |
| | `--recursive 0\|1` | 与 build_index `--recursive` 配套，默认 0 |
| | `--ledger <路径>` | 显式指定台账即启用位 32 台账门禁 |
| | `--require-session` | 启用位 16 会话登记门禁 |
| `pdf_fetch.py` | `fetch` | OpenAlex 查 OA 直链 → 4 线程 curl → 四重校验；`--dry-run` 只探命中率不下载（**Q1 估命中率必须带它**）；`--mailto` 填自己的邮箱，不硬编码 |
| | `verify` | 对已有 `pdf/` 逐篇四重校验，不合格 **move 进 `_quarantine/`** 并写 `reasons.csv`——这是唯一会隔离坏 PDF 并登记原因的路径，`--dir` 指 pdf 目录、`--records` 指题录 |
| `dedupe.py` | `--fuzzy` | 模糊阈值 0-100，**默认 92**；三级判重 L1 DOI/UT → L2 篇名归一 → L3 模糊 + 同首作者 + 年差 ≤1 |
| | `--out` | 旁路模式：只写该文件、不动 records.json、不改文件名（G5 默认走原地模式，不加这个） |

两个配套交付物（字段映射与编码细则见 `references/shared/deliverables-format.md`）：
- **文献题录.txt**：题录在手就必须导出，可直接导入 NoteExpress/EndNote；条目数必须 == records.json 条数；两平台混合时分写成 文献题录_知网.txt + 文献题录_WOS.txt，不混装——导入器只认一种格式。
- **未获取全文.md**：缺全文的篇目单独成册，每条必有题录、失败原因、获取链接三样；缺链接写「待补」不编造；补齐后重跑 build_index 自动移除。

## 4. 九条硬规则

1. **单一 rid 贯穿**：文件名前缀 = 清单行 = 报告引用；`rank` 只能出现在展示列，禁止用于 join。
2. **两次确认才下 PDF**：结果页 + 详情页；两次都无 HTML 才走 PDF。
3. **交付前交叉校验**：路径存在、rid 一致、PDF 内嵌 DOI 一致、报告数字 == `index_stats.json`。
4. **无机器校验不得宣称「全部成功/零错配」**：结论句必须由脚本变量填入。
5. **验证码/登录墙停下求助**：`bsk request-help`；不伪造事件流、不轮换 UA、不上代理池。
6. **不绕付费墙**：拿不到就登记 DOI + 原因，不用错文件凑数。
7. **只 move 不删**：失败文件进 `_quarantine/`，重复文件进 `index_duplicates.csv`。
8. **全绝对路径**：Bash cwd 每次重置，所以**调用方一律传绝对路径**（工作目录、--records、--ledger 都写全）。脚本内部只在两处自己解析路径：`verify_delivery.py --lint-assets` 用它定位自身包目录，`build_index.py` 用它把相对 `--md-dir/--pdf-dir` 锚到 workdir；不要指望脚本替你补全相对路径。
9. **登录失败即停**：不重登、不换 profile、不试密码。

## 5. 平台路由速查

| 项 | 知网 | WOS |
| --- | --- | --- |
| 检索入口 | `kns.cnki.net/kns8s/AdvSearch` | `wos/woscc/advanced-search` 的 Query Preview |
| 字段语法 | `SU %= / TI = / AU =`，字段内 `* + -` | `TS= / TI= / WC=`，`AND OR NOT NEAR/n` |
| 排序 | `#orderList #CF` 二次点击切 DESC | `Sort by: Times Cited` |
| 质量筛选 | 来源类别 CSSCI/北核 | refine：DT/LA/WC/PY |
| 导出 | GB/T 7714 / EndNote / RefWorks | Full Record + Tab delimited（71 字段） |
| 全文通道 | HTML 优先，PDF 兜底 | OA PDF（OpenAlex） |
| 题录导出 | 文献题录.txt：RT 标签 + CRLF | 文献题录.txt：FN/VR/ER + BOM + LF |
| 首要坑 | 联想浮层挡按钮、滑块、reader 400001 | `TS=` 写错框、`DT/LA` 当字段、`SU` 学科名 |

## 6. 自检清单（每条可机器验证）

- [ ] `00_需求确认.json` 含 7 键，`verify_delivery.py --brief` 退出 0
- [ ] `/usr/bin/python3 scripts/env_check.py --json` 返回 `ok=true`（必填只有 `pymupdf`；`pypdf`/`openpyxl` 降为可选，缺了只是 warn）
- [ ] `检索台账.csv` ≥3 行，每条有 `hits` 与 `refine_before/after`：`verify_delivery.py --ledger 检索台账.csv`（位 32 自动拦，空台账/缺列必红）
- [ ] `raw/_logs/session.json` 由 `register_session.py` 登记：`verify_delivery.py --require-session`（位 16）
- [ ] `records.json` 的 `rid` 唯一：`/usr/bin/python3 -c "import json;r=json.load(open('raw/records.json'));print(len(r),len({x['rid'] for x in r}))"`（两数相等）
- [ ] 索引覆盖无遗漏：`正文/`、`备选/`、`pdf/` 里没有未入索引的文件（verify 位 1 自动拦；有题录无文件的行合法，标 missing_file）
- [ ] 每篇 MD 有 `rid/chars/status` 三个 front-matter 键
- [ ] `manifest.csv` 中 `status=ok` 行数 == `pdf/` 文件数
- [ ] `pdf/` 下没有 <10KB 的文件
- [ ] `文献题录*.txt` 已导出且条目数 == raw/records.json 条数（`export_citations.py --json`；`--only` 部分导出改用 `verify_delivery.py --citations-expected N`）
- [ ] 有 missing_file 条目时 `未获取全文.md` 存在且覆盖全部 rid（位 1 自动拦）
- [ ] `索引.md` 含「缺口与待核对」节
- [ ] `检索报告.md` 由 `render_report.py` 生成（不手写数字），`<!-- STATS -->` 含 total/with_md/with_pdf/missing_file/unregistered/thin 全部键且值与 `index_stats.json` 相等（漏键也会被位 4 拦）；`render_report.py --check` 可单独对账
- [ ] 交付量与目标差距 >20% 时，「缺口与待核对」节下**逐条列出**条目——位 4 是结构化判定（标题节 + 节内条目），全文里出现「缺口」二字不再算说明
- [ ] `verify_delivery.py` 退出码 0
- [ ] 仓库内无真实邮箱、无 cookie、无 token：`grep -rInE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+' scripts/ | grep -v example`

## 7. 参考索引（按什么时候读）

| 什么时候读 | 读哪篇 |
| --- | --- |
| 要写知网检索式、不确定字段码/运算符 | `references/cnki/cnki-syntax.md` |
| 知网页面填不进/点不动/滑块/400001/正文提取、失败原因取值 | `references/cnki/cnki-playbook.md` |
| WOS 报 Invalid query、导出解析、71 字段、OA 抓取 | `references/wos/wos-playbook.md` |
| 不知道怎么扩词、命中太多或太少 | `references/method/query-design.md` |
| 不知道怎么定「头部文献」、分区拿不到 | `references/method/quality-screening.md` |
| 导出题录、题录导不进 NoteExpress/EndNote、未获取清单排版 | `references/shared/deliverables-format.md` |
| 登记会话、判下载通道、采集代理指标、合并批次、渲染报告 | `references/shared/scripts-guide.md` |
| 要核对交付物长什么样（题录/参考文献/未获取全文各格式） | `evals/sample-outputs/`（脱敏样例，README 列了每种的生成命令） |
| 遇到任何报错/异常/交付对不上账 | `references/shared/pitfall-library.md` |

## 8. Gotchas

| 现象 | 原因 | 改法 |
| --- | --- | --- |
| `bsk fill` 报 not fillable | a11y ref 指到 DIV 包装层 | 用 `#gradetxt > dd input[type=text]`；多 input 用 `inputs.pop()` |
| 搜索按钮点击无效 | 联想浮层遮挡 | `press Escape` → `focus '#btnSearch'` → `press Enter` |
| 正文只有 2200 字 | 滑块未过 | 调 Vue `mousedownFn/mouseMoveFn/moseUpFn`，判 `confirmSuccess` |
| reader 报 400001 | 复用旧 invoice URL | 每次从结果页重进 |
| WOS 报 Invalid query | `TS=` 写进了普通输入框 | 改用 Query Preview |
| WOS 命中 0 | `SU="Political Science"` | `SU` 是 `Government & Law`，`WC` 才是 Political Science |
| 89 篇 PDF 挂错 88 篇 | 两套排名混用 | 只用 rid；跑 `verify_delivery.py` 位 2 |
| `pdftotext` 把 1966 读成 16 | 字体子集 + 无文本层 | 中文优先 HTML；关键数字回原 PDF 核对 |

## 9. FAQ

**Q1 没有机构订阅能用吗？** 能，但只能交付题录 + OA 全文；先探 OA 命中率再定目标数量——**必须带 `--dry-run`**，否则会真的开始下载：

```sh
/usr/bin/python3 scripts/pdf_fetch.py fetch --records raw/records.json --outdir pdf/ --mailto 你的邮箱 --dry-run
```

（同一思路也适用于代理指标：`enrich_metrics.py --dry-run` 先探 `2yr_mean_citedness` 命中率，低于 50% 就别拿它当唯一排序依据。）
**Q2 拿不到 JIF/分区怎么办？** WOS 检索页没有这个能力；用 OpenAlex `2yr_mean_citedness` 代理，列名写「非 JIF」，绝不写成一区/Q1。
**Q3 扫描版 PDF 要不要 OCR？** 不要。`text_layer_ratio < 0.05` 直接判 `scan`，换文献或只留题录；OCR 成本高、错误率高。
**Q4 知网 HTML 覆盖率有多高？** 实测文革类 ≈35%、大跃进类 ≈47%、2000 年后新刊 ≈50%；所以必须两次确认，不能假设都有。
**Q5 能不能直接构造结果页 URL 批量抓？** 不能。知网结果内嵌渲染，URL 传检索式返回 0 条，只能界面操作。
**Q6 中文文献要不要也去 WOS 查？** 不要。WOS 对中文期刊覆盖弱；中文走知网、英文走 WOS，两边用 DOI/篇名去重。
**Q7 索引里的「文件缺失，待核对」要补吗？** 不自动补。先查 `_quarantine/reasons.csv` 与 `raw/records.json`，确认是没下到还是命名不一致，再人工决定。
**Q8 能不能把 `备选/` 的文件算进交付数？** 不算。`备选/` 只进索引不进主库；报告里的「实交付」只统计 `status=ok`。
**Q9 文献题录.txt 怎么用？格式以什么为准？** 直接在 NoteExpress/EndNote/RefWorks 里「导入题录」选对应过滤器；格式对照真实导出样例复刻（知网：RT/A1/T1/…/LK + 空行分隔；WoS：FN/VR 头 + ER 结尾 + 3 空格续行）。两平台混合时分两个文件，因为导入器只认一种格式。要 Zotero 用 `--format ris`，要 LaTeX 用 `--format bibtex`，要直接可粘贴的引用列表用 `--format gbt7714`（参考文献.md，GB/T 7714-2015 顺序编码制）、`--format apa`（APA 第 7 版）、`--format mla`（MLA 第 9 版 Works Cited）；各格式长什么样见 `evals/sample-outputs/`。
**Q10 未获取全文.md 里「待补链接」怎么办？** 说明题录缺 url/ut/doi——回检索平台补抓这三项再重跑 build_index.py；不要手工编链接。

## 10. Prompt 示例（15 条，可直接复制）

```text
1  帮我搜集 30 篇 CSSCI 关于「基层治理数字化」的文献，2016 年以后。
2  知网找「继续革命理论」的党史文献，篇名精确，先给我 20 条清单。
3  在 WOS 找 Trump 与 populism 的交叉研究，近十年，Article/Review。
4  两个库都要：中文知网 20 篇 + 英文 WOS 20 篇，最后合并去重。
5  先别下载，按被引排序给我前 40 条，我挑完再下。
6  只要 HTML 能读的，没有 HTML 的列出来就行，不要 PDF。
7  把 pdf/ 里这些论文批量转成 Markdown，保留标题和脚注。
8  给这批文献建索引，标注获取方式和本地路径。
9  补 10 篇 2024 年以后的新文献，不要重复已有的。
10 帮我判断这批文献够不够支撑一篇综述，缺哪个方向。
11 这个知网链接抓成 Markdown，脚注要保留。
12 检查交付：文件名、DOI、索引对不对得上。
13 把这批文献导出成题录文件，知网的用知网格式、WOS 的用 savedrecs 格式。
14 把这批文献按 GB/T 7714 排成参考文献列表，再导一份 RIS 给 Zotero。
15 已有的三十篇基础上再补 10 篇新的，不要重复，rid 接着编。
```

## 11. 运行时目录契约

```text
<工作目录>/
├── 00_需求确认.json
├── 检索台账.csv
├── raw/                     # records.json 是题录唯一真源（dedupe 原地改写它，原始备份 records.raw.json；detail_log.csv 记字段补抓）
│   ├── _logs/session.json    # register_session.py 登记：session_id + 机构名 + 时间戳（无 cookie）
│   ├── download_plan.csv     # plan_download.py：rid / 通道（HTML|PDF|NONE）/ URL
│   ├── no_html_reasons.json  # plan_download.py：无入口条目原因，build_index 填进 未获取全文.md
│   └── html_whitelist.json  no_html.json   # cnki_scan.py 产出，由 plan_download.py 消费
├── pdf/                     # <rid>_<作者><年>_<刊>.pdf
├── 正文/                     # <rid>_<题名前20字>.md
├── 备选/                     # 质量不达标但保留
├── _quarantine/             # 失败隔离 + reasons.csv（绝不删除）
├── 索引.md  index.csv  index_stats.json  index_duplicates.csv
├── 文献题录.txt               # 单平台；混合批次为 _知网/_WOS 两个文件
├── 未获取全文.md               # 仅当有缺文件条目；补齐重跑即自动消失
├── manifest.csv
├── 参考文献.md  文献题录.ris  文献题录.bib   # 可选：--format gbt7714/ris/bibtex
└── 检索报告.md               # render_report.py 生成，含 <!-- STATS {...} --> 机器可读块
```

`index_duplicates.csv` 只在本次确有重复文件时写出；去重解决后重跑 build_index 会自动删除——
旧名残留会让 verify 位 1 把它当「已豁免」，放行真正未入索引的文件。

## 12. 边界、安全与隐私

- **适用对象**：需要批量文献的研究生、助教、研究助理；不要求会写代码，脚本已封装。
- **合理使用**：仅下载用户机构已订阅或开放获取的内容；不绕付费墙、不破解验证码、不批量轰炸。
- **不采集登录信息**：不读取、不落盘 cookie/token/密码；`raw/_logs/` 只记 session_id 与机构名。
- **日志与中间产物留存期限**：`raw/_logs/` 与 `raw/html/` 属过程数据，默认在交付时告知用户可整目录删除；需要留作复现证据时由用户明确指定保留期限，技能自身不做长期留存，也不在报告里粘贴日志原文（只引结论行）。
- **机构名可脱敏**：对外报告可用「某高校」代替真实机构名。
- **代理指标必须标注**：非 JIF、非分区、非官方排名，一律在列名或脚注写明。
- **超范围给替代方案**：万方/维普/Scopus/arXiv 不在本技能内，告知用户可另建适配层，不硬套知网脚本。
- **不确定就标「待验证」**：字段名、类目名、覆盖率先查界面再写结论。
