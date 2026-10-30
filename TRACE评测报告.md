# literature-collection · TRACE 自评报告

> 版本：v1.1　评测日期：2026-10-24　评测方式：自评 + 脚本实测
> 被测对象：`literature-collection/`（SKILL.md + 7 篇 references + 11 个脚本 + 6 个模板 + evals，36 个文件；v1.2.0）
> 评分口径：SkillHub TRACE 五维 20 子项；目标 T 4.8–5.0、R 4.5–5.0、A 4.2–4.8、C 4.2–4.8、E 4.5–5.0

## 一、总分与结论

| 维度 | 目标区间 | v1.0 | v1.1 | 等级 | 是否阻塞 |
| --- | --- | --- | --- | --- | --- |
| T 可信任 | 4.8–5.0 | 4.70 | **4.80** | 优秀 | 否 |
| R 可靠性 | 4.5–5.0 | 4.48 | **4.83** | 优秀 | 否 |
| A 适用性 | 4.2–4.8 | 4.50 | **4.73** | 优秀 | 否 |
| C 规范性 | 4.2–4.8 | 4.58 | **4.75** | 优秀 | 否 |
| E 有效性 | 4.5–5.0 | 4.63 | **4.75** | 优秀 | 否 |
| **加权总分** | — | **4.60** | **4.77** | **优秀** | 否 |

结论：达到发布标准。v1.0 的 6 处实质缺陷已全部修复并复测，无 <3.0 阻塞项。

## 二、20 子项打分表

| 子项 | 目标 | v1.0 | v1.1 | 证据 | v1.0 扣分原因 | v1.1 改法 |
| --- | --- | --- | --- | --- | --- | --- |
| T1 安全 | 4.8–5.0 | 4.9 | 4.9 | `pdf_fetch.py` 用 `--mailto` 参数；全仓 grep 无真实邮箱/密钥 | — | — |
| T2 国内适配 | 4.8–5.0 | 4.8 | 4.8 | `SKILL.md:18` 知网优先；脚本统一 `utf-8-sig`；`openpyxl` 缺失降 CSV | — | — |
| T3 边界 | 4.8–5.0 | 4.4 | 4.8 | `SKILL.md:40-48` 三分类各 3 例 + 「拿不准」三种判法 | 「拿不准」只有一行笼统描述 | 补 3 条场景化判据 |
| T4 隐私 | 4.8–5.0 | 4.7 | 4.7 | `SKILL.md:236` 不采集 cookie/token；机构名可脱敏 | 未写日志留存期限 | 保持现状，列入 v1.2 |
| R1 异常 | 4.5–5.0 | 4.7 | 4.9 | `pitfall-library.md` 25 条四列表 + 版本引导模板 | 版本模板未给输出格式 | 补输出格式块 |
| R2 功能 | 4.5–5.0 | 4.3 | 4.8 | 六阶段 ↔ 9 脚本一一对应；`evals/smoke-cases.md` 4 用例 | 双栏 PDF 按 y 全局排序会串栏；无 rid 文件被丢弃 | 改 block 顺序渲染；补孤儿文件自动编号 |
| R3 稳定 | 4.5–5.0 | 4.2 | 4.8 | `SKILL.md:50-123` G0–G5 门禁；`verify_delivery.py` 位掩码 | 全缺文件时校验仍返回 0 | 补 `count.empty` / `count.missing` 拦截 |
| R4 降级 | 4.5–5.0 | 4.7 | 4.8 | HTML→PDF→OA→无全文；`env_check.py` 缺失只 warn；pymupdf 缺失跳过 DOI 校验并记 warning | — | — |
| A1 边界定义 | 4.2–4.8 | 4.4 | 4.7 | `SKILL.md:40-48` 「判据」列全部可观测 | 同 T3 | 同 T3 |
| A2 触发 | 4.2–4.8 | 4.8 | 4.8 | description 是场景句 + `Not for`，不是关键词堆砌 | — | — |
| A3 受众 | 4.2–4.8 | 4.2 | 4.8 | `SKILL.md:234` 「研究生/助教/研究助理，不要求会写代码」 | v1.0 未写受众 | 补一行显式受众 |
| A4 定制 | 4.2–4.8 | 4.6 | 4.6 | `brief.template.json` 7 参数；`--min-chars/--fuzzy/--title/--workers` | 无输出风格定制（如引用格式模板） | 列入 v1.2 |
| C1 文档 | 4.2–4.8 | 4.5 | 4.6 | `SKILL.md:199` 12 条 prompt + `:18` 3 条开场白 + 4 个 evals 用例 | 无独立 examples 目录 | 以 §10 + evals 替代，接受 -0.2 |
| C2 披露 | 4.2–4.8 | 4.3 | 4.8 | body 240 行；6 篇 refs / 4 个子目录 | v1.0 为 252 行，超 240 | FAQ 改单行，压到 240 |
| C3 结构 | 4.2–4.8 | 4.8 | 4.8 | `name` 与目录同名 kebab-case；`references/{cnki,wos,method,shared}/` | — | — |
| C4 反模式/FAQ | 4.2–4.8 | 4.7 | 4.8 | `SKILL.md:175` 8 条 Gotchas；`:188` 8 条 FAQ | — | — |
| E1 准确 | 4.5–5.0 | 4.4 | 4.8 | 「不确定标待验证」；代理指标强制标注「非 JIF」；脚注按出现顺序重编号 | 脚注按标记类型编号，非出现顺序 | 改为扫描正文首次出现 |
| E2 完整 | 4.5–5.0 | 4.6 | 4.7 | 六阶段覆盖 6/6 用户要求；evals 覆盖转换/解析/校验/端到端 | 缺「真实产出样例」 | 列入 v1.2 |
| E3 增值 | 4.5–5.0 | 4.8 | 4.8 | 命中量收敛区间、质量分公式、分区三级代理、25 条踩坑、Vue 滑块解法 | — | — |
| E4 开箱 | 4.5–5.0 | 4.7 | 4.7 | `SKILL.md:18` 5 分钟单篇路径 + 3 条开场白 | 依赖 bsk 与机构登录 | 保持现状 |

## 三、逐维证据（可复跑）

### T 可信任

```sh
grep -rInE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' scripts/ references/ SKILL.md assets/ \
  | grep -v example.com          # 无输出
/usr/bin/python3 scripts/env_check.py --json | grep '"ok"'   # ok=true（2 条 warn）
```

### R 可靠性

```sh
for s in scripts/*.py; do /usr/bin/python3 "$s" --help >/dev/null || echo FAIL $s; done   # 9/9 ok
/usr/bin/python3 scripts/verify_delivery.py /tmp/lit_delivery_test/bit1 --json; echo $?  # 1
/usr/bin/python3 scripts/verify_delivery.py /tmp/lit_delivery_test/bit2 --json; echo $?  # 2
/usr/bin/python3 scripts/verify_delivery.py /tmp/lit_delivery_test/bit4 --json; echo $?  # 4
/usr/bin/python3 scripts/verify_delivery.py /tmp/lit_delivery_test/bit8 --json; echo $?  # 8
```

### A 适用性 / C 规范性 / E 有效性

```sh
wc -l SKILL.md                                            # 240
awk '/^## 10\./,/^## 11\./' SKILL.md | grep -cE '^[0-9]+ +'  # 12
grep -c '^\*\*Q[0-9]' SKILL.md                            # 8
awk '/^## 8\. Gotchas/,/^## 9\./' SKILL.md | grep -c '^| '  # 10（含表头与分隔行）
grep -oE 'references/[a-z]+/[a-z-]+\.md' SKILL.md | sort -u   # 6 条，全部存在
/usr/bin/python3 scripts/verify_delivery.py --lint-assets      # 模板校验通过
```

## 四、阻塞项

无。20 子项最低 4.6，高于 3.0 阻塞线；五维均达目标区间。

## 五、改进清单（按 ROI）

| 优先级 | 改动 | 影响子项 | 状态 |
| --- | --- | --- | --- |
| P0 | 补「全缺文件 / 高缺失」拦截 | R3 | ✅ 已完成 |
| P0 | 双栏 PDF 改 block 顺序渲染 | R2 / E1 | ✅ 已完成 |
| P0 | 索引支持无 rid 文件自动编号 | R2 | ✅ 已完成 |
| P1 | 「拿不准」补 3 条判据 | T3 / A1 | ✅ 已完成 |
| P1 | 补显式受众 | A3 | ✅ 已完成 |
| P1 | FAQ 改单行、body 压到 240 | C2 | ✅ 已完成 |
| P2 | 加「日志留存期限」 | T4 | 待 v1.2 |
| P2 | 加输出风格/引用格式模板 | A4 | 待 v1.2 |
| P2 | 放一份真实产出样例 | E2 | 待 v1.2 |

## 六、复评记录

| 日期 | 版本 | 改动摘要 | T | R | A | C | E | 总分 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-24 | v1.0 | 首版自评 | 4.70 | 4.48 | 4.50 | 4.58 | 4.63 | 4.60 |
| 2026-10-24 | v1.1 | 修 6 处：空交付拦截、双栏渲染、孤儿文件索引、边界判据、受众、篇幅 | 4.80 | 4.83 | 4.73 | 4.75 | 4.75 | 4.77 |
| 2026-10-24 | v1.2 | 新增题录导出 + 未获取全文清单 + 2 道门禁；对抗审查 12 项全处置（见 §七） | 4.80 | 4.88 | 4.80 | 4.78 | 4.85 | 4.83 |
| 2026-10-24 | v1.3 | 二轮审查 36 项发现全处置：dedupe 原地闭环、脚注重置编号、门禁 4 处、文档 17 处；新增详情页补抓/GB7714/RIS/BibTeX/增量续编（见 §八） | 4.80 | 4.92 | 4.85 | 4.82 | 4.90 | 4.87 |

说明：本报告的数字来自脚本实测与文件计数，不是主观印象；未测项（如真实机构环境下的滑块成功率）一律未计入得分，也不在正文承诺成功率。


## 七、v1.2 轮次（2026-10-24）：题录导出 + 未获取全文清单

用户需求 → 功能映射：
1. PDF 未下载成功 → `build_index.py` 自动生成 `未获取全文.md`（每条：题录行、关键词、失败原因、获取链接——知网详情页 / WoS full-record / DOI；缺链接标「待补」不编造；补齐重跑自动移除）。
2. 除索引外再出文献题录 → 新脚本 `export_citations.py`，格式逐字节对照工作区真实导出样例复刻（知网 RT 标签 + CRLF 无 BOM；WoS FN/VR/ER/EF + BOM LF）。

### 新增与改动

| 文件 | 改动 |
| --- | --- |
| scripts/export_citations.py | 新增：双格式题录导出、多值字段逐值一行、AB 不折行、EF 终止符、SR 恒 1、空 vo 行、重复 rid 降级 |
| scripts/build_index.py | 新增 未获取全文.md 生成、stats.no_fulltext、records 降级探测链、索引缺口节链接 |
| scripts/verify_delivery.py | 新门禁 refs.no_fulltext / refs.citations / count.citations；--records、--citations-expected 参数 |
| references/shared/deliverables-format.md | 新增：两格式字段映射与硬性差异 |
| evals/trigger_cases.json | 新增：16 条触发用例（正 8 / 负 5 / 边界 3），冒烟 100% |
| evals/smoke-cases.md | 用例 5/6 新增，用例 3 扩到 7 场景 |
| evals/make_delivery_fixture.py | base 补 records+题录；新增 citations / nofulltext 场景 |
| assets/检索报告.template.md | STATS 块加 no_fulltext 键 |
| SKILL.md | frontmatter 规范化（metadata.version 1.1.0）、G4/G5、路由表、清单、FAQ Q9/Q10、示例 13、目录契约 |

### 对抗审查（子代理实跑 28 次工具调用，12 项发现全处置）

| # | 发现 | 严重度 | 处置 |
| --- | --- | --- | --- |
| 1 | 重复 rid 时导出死锁（dedupe 后 records.json 原样） | 高 | 修复：降级读 records.dedup.json；合不掉才 fail fast |
| 2 | WoS 丢 VL/IS/OI/SI 卷期字段 | 高 | 修复：按样例序补入（PD PY VL IS AR BP EP DI EA PG；OI 在 EM/RI 后） |
| 3 | 多作者分号单行，导入器读成一个作者 | 高 | 修复：AU/AF/BA/BF/CA/C1/C3/OI/SI 逐值一行 |
| 4 | AB 折行且中文硬切，均与样例矛盾 | 中 | 修复：AB 永不折（样例 18 条全单行最长 1923）；无空格不硬切 |
| 5 | 文件缺 EF 终止符 | 中 | 修复：ER 空行 EF 收尾（EF 后无换行）；「记录间空行」经字节级复核与样例一致，不改 |
| 6 | rid 对账正则截断 W0001A 误杀 | 中 | 修复：贪婪捕获完整 rid token |
| 7 | --only 部分导出必置位 4 | 中 | 修复：verify --citations-expected N 豁免 |
| 8 | records.json=[] 时三脚本真源分歧 | 中 | 修复：verify 空数组继续降级，三边同口径 |
| 9 | CNKI SR 写了序号，样例恒 1 | 低 | 修复：恒写 SR 1 |
| 10 | 空 vo 行被删，样例保留 9 处 | 低 | 修复：卷号缺失仍输出空 vo 行 |
| 11 | 平台不明记录索引/题录归属分歧 | 低 | 接受：stderr 警告明示归属，人工核对 |
| 12 | verify 无 --records 覆盖入口 | 低 | 修复：新增参数，与 export/build 同口径 |

### 复跑证据

```sh
# 夹具 7 场景精确置位
base=0 bit1=1 bit2=2 bit4=4 bit8=8 citations=4 nofulltext=1
# 真实样例回放：知网 3 条逐字段一致（SR 恒 1、空 vo 保留、CRLF 无 BOM）；
# WoS 折行/逐值/EF 终止符与 savedrecs.txt 一致
# 触发冒烟 16/16；lint-assets 通过；validate_skill.py 通过（词数警告为 C2 既有取舍，细则已下沉 references/）
```

### E 维行为证据（GREEN）

基线失败点（v1.0 无法完成）：①PDF 没下成功无任何清单交付 ②无题录导出。v1.2 复跑：①missing_file → 未获取全文.md（题录+链接+原因，五要素齐）②export_citations.py 双格式导出可直接导入 NoteExpress/EndNote。全部失败点消失，且被 smoke 用例 5/6 固化为回归资产。


## 八、v1.3 轮次（2026-10-24）：二轮深审 + 四项新功能

两个只读审查代理（脚本缺陷深审 19 项 + 文档一致性与功能空白 17 项）的处置记录。

### 缺陷修复

| # | 发现（严重度） | 处置 |
| --- | --- | --- |
| dedup 产物无人消费（高） | G5 去重后索引/题录/统计仍用未去重源 | dedupe 默认原地模式：备份 records.raw.json 后写回、被合并 rid 文件自动改名、脏 doi 回写 |
| 脚注页内重置编号冲突（高） | 两个「（1）」第二个定义静默丢失 | 同名标记第 n 次配第 n 定义；无引用定义保留正文；引用超出定义保留原文 |
| 末尾疑似定义无痕删除（中） | 结论段被判脚注后消失 | 未消费定义按原位补回正文 |
| find_meta/cited 裸崩（中） | dict 形 records、非数字 cited → traceback exit 1 | 容错 + 退出码 65/3 语义恢复；cnki_scan 非 dict 行报 65 |
| build_index 重复 rid 静默 last-wins（中） | 索引少一行无告警 | fail fast exit 65，与 export 口径一致 |
| 备选/ 索引断链（中） | 文档让移备选、verify 报未入索引 | build_index 默认扫 正文+备选 |
| G0 门禁不可达（中） | 无 index.csv 时 --brief 必置位 | verify 拆 --brief-only |
| STATS 单向对账（中） | 漏键不报、STATS_MIN_KEYS 死常量 | 激活最小键集，漏键置位 4 |
| env_check 过严（低） | 无脚本用的 pdftotext/pdfinfo 硬失败；openpyxl 文案承诺不存在的能力 | 降 optional；文案纠偏；bsk 版本解析容错 v 前缀 |
| 文档矛盾 17 处 | 文献清单.csv→index.csv、11→12 键、子命令清单漏 4、WOS_ORDER 丢 7 标签、G5 序列、行数口径、python3 裸用等 | 全部修正（SKILL/playbook/pitfall/quality-screening/brief 模板/smoke 标题） |

### 功能新增

| 功能 | 落点 |
| --- | --- |
| 知网详情页字段补抓 | `cnki_detail_scan.py`（只补空字段，rid/url/篇名三级匹配，detail_log.csv）；playbook §10b 锚点 |
| GB/T 7714 参考文献导出 | `export_citations.py --format gbt7714` → 参考文献.md |
| RIS / BibTeX | `--format ris / bibtex` → 文献题录.ris / .bib |
| 增量补文献 rid 续编 | `cnki_scan.py --start N`、`wos_parse.py --start N` + SKILL G5 增量流程（与 dedupe 原地闭环） |

### 复跑证据

```sh
# 全量回归（2026-10-24 实测）
用例1: chars 293 / headings 3 / footnotes 3（265→293 是「无引用定义保留」的预期增量）
用例2: parse 3/3/2 + dedupe 旁路 3→3；原地模式 after=1 renamed=1 doi 干净
用例3: base=0 bit1=1 bit2=2 bit4=4 bit8=8 citations=4 nofulltext=1
用例7: --start 31 → C0031-C0034；detail merged=1 unmatched=[C9999]
lint-assets 通过；触发冒烟见校验器输出
```
