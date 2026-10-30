# 干跑用例（13 个：1/2/3/5/6/7/8/9/10/11/12/13 离线可复现，4 需用户在场）

> 目的：不依赖浏览器登录态，验证「转换 → 解析 → 交付校验」三条链路。每个用例都给出期望值，跑完必须逐条比对。
> 解释器一律 `/usr/bin/python3`（本机 PATH 上的另一个 python3 缺 pymupdf）。
> v1.4 新增 8–13：覆盖新增脚本与新增/收紧的门禁，每条都给了必红用例（永不失败的门禁等于没有门禁）。

## 用例 1：知网 HTML 正文转换

```sh
mkdir -p /tmp/smoke/正文
/usr/bin/python3 scripts/html_to_md.py evals/fixtures/page.json \
  -o /tmp/smoke/正文/C0001_test.md --rid C0001 --min-chars 200 --json
```

期望（`--json` 输出）：

```json
{"rid": "C0001", "chars": 293, "status": "ok", "headings": 3, "footnotes": 3}
```

（chars 293 = 正文 265 + fixture 里无正文标记的「（1）参见…」定义 28 字；v1.2 起无引用定义保留在正文，
不再无痕删除——比 v1.1 的 265 多出的正是这条例子）

再检查文件：
- front-matter 含 `rid/title/chars/status/headings/footnotes`
- 正文没有重复的篇名 H1（首个 H1 被跳过）
- 脚注按**正文出现顺序**编号：`①→[^1]`、`（2）→[^2]`、`②→[^3]`
- 页内重置编号：同名标记第 n 次出现配第 n 个定义（两个「（1）」各得一个编号，第二个定义不丢）
- 引用多于定义时超出部分保留原文（不瞎配）
- 文末有 `## 注释`，每条保留「原编号」
- 噪声行 `引证文献` 已剔除
- 把 `--min-chars` 改成 4000 → 退出码 **3**、`status=thin`

## 用例 2：WOS 导出解析与去重

```sh
mkdir -p /tmp/smoke/raw
/usr/bin/python3 scripts/wos_parse.py evals/fixtures/wos_sample.txt \
  -o /tmp/smoke/raw/records.json --rid-map /tmp/smoke/raw/rid_map.csv --json
/usr/bin/python3 scripts/dedupe.py /tmp/smoke/raw/records.json \
  -o /tmp/smoke/raw/records.dedup.json --log /tmp/smoke/raw/dedupe_log.csv --json
```

期望：
- `records == 3`，`unique_rid == 3`
- `with_doi == 2`（第三条 `DI` 为空）
- `rid` 为 `W0001/W0002/W0003`，按导出行序
- `rank_by_citation`：`W0001=1, W0002=2, W0003=3`；`rank_by_export` 同为 1/2/3
- 去重 `before == 3`，`after == 3`，`by_level` 三档均为 0
- `rid_map.csv` 有 3 行数据 + 1 行表头

再验 dedupe 原地模式（G5 默认）与文件改名闭环：

```sh
mkdir -p /tmp/smoke3/raw /tmp/smoke3/正文
# 同一篇文献两个 rid（DOI 相同），C0001 已有正文文件
/usr/bin/python3 -c "
import json, pathlib
recs=[{'rid':'C0001','platform':'cnki','title':'双库重复文献','authors':'张三','source':'刊','year':'2024','doi':'10.1/dup','url':'u1','cited':1},
      {'rid':'W0001','platform':'wos','title':'双库重复文献','authors':'Zhang, S','source':'J','year':'2024','doi':'https://dx.doi.org/10.1/dup)','ut':'WOS:9','abstract':'abs'}]
pathlib.Path('/tmp/smoke3/raw/records.json').write_text(json.dumps(recs,ensure_ascii=False),encoding='utf-8')
pathlib.Path('/tmp/smoke3/正文/C0001_张三2024_刊.md').write_text('x',encoding='utf-8')"
/usr/bin/python3 scripts/dedupe.py /tmp/smoke3/raw/records.json --json
```

期望：
- `after == 1`，`mode == "inplace"`，`renamed_files == 1`
- `records.json` 只剩 1 条且 `doi == "10.1/dup"`（脏 doi 前缀/尾括号被回写干净）
- `正文/C0001_*.md` 已改名为 `W0001_*.md`（胜者 rid）
- 首次运行生成 `raw/records.raw.json` 备份；再跑一次不覆盖备份
- `build_index.py /tmp/smoke3` 与 `export_citations.py /tmp/smoke3` 直接吃去重结果，无需 --records

## 用例 3：交付校验的六种故障（必须精确置位）

```sh
/usr/bin/python3 evals/make_delivery_fixture.py /tmp/lit_delivery_test
for c in base bit1 bit2 bit4 bit8 citations nofulltext; do
  /usr/bin/python3 scripts/verify_delivery.py "/tmp/lit_delivery_test/$c" --json >/dev/null
  echo "$c exit=$?"
done
```

期望：

| 用例 | 注入的故障 | 期望退出码 |
| --- | --- | --- |
| `base` | 无（含 records.json + 文献题录.txt，2 条对 2 条） | **0** |
| `bit1` | 索引指向不存在的文件 + 文件未入索引 | **1** |
| `bit2` | 文件名前缀 rid ≠ 行 rid | **2** |
| `bit4` | 报告 STATS 数字 ≠ index_stats | **4** |
| `bit8` | 正文 100 字且未标 thin | **8** |
| `citations` | records 3 条但题录只有 2 条 | **4** |
| `nofulltext` | 有 missing_file 行但没有 未获取全文.md | **1** |

叠加故障时退出码应为位或（如同时 1 和 4 → 5）。

## 用例 5：题录导出（知网 + WoS 双格式）

```sh
mkdir -p /tmp/smoke2/raw
cp evals/fixtures/cnki_records_sample.json /tmp/smoke2/raw/cnki_records.json
/usr/bin/python3 scripts/wos_parse.py evals/fixtures/wos_sample.txt -o /tmp/smoke2/raw/wos.json --json
# 合并两平台记录（模拟 both 批次）
/usr/bin/python3 -c "
import json,pathlib
a=json.load(open('/tmp/smoke2/raw/cnki_records.json'))
b=json.load(open('/tmp/smoke2/raw/wos.json'))
pathlib.Path('/tmp/smoke2/raw/records.json').write_text(json.dumps(a+b,ensure_ascii=False),encoding='utf-8')"
/usr/bin/python3 scripts/export_citations.py /tmp/smoke2 --json
```

期望：
- 生成 `文献题录_知网.txt`（2 条）+ `文献题录_WOS.txt`（3 条），不混装单文件
- 知网文件：`RT Journal Article` 行数 == 2；UTF-8 无 BOM；CRLF 行尾；字段顺序 RT→SR→A1→T1→…→DS→LK；SR 恒为 `SR 1`（两条都是）；C0002 无卷号仍保留空 `vo` 行；其余缺失字段（关键词/链接）直接跳行；C0001 的 list 型关键词转 `;` 连接
- WoS 文件：首行 `FN Clarivate Analytics Web of Science`，次行 `VR 1.0`；`ER` 行数 == 3；文件以 `ER` 空行 `EF` 结尾（EF 后无换行）；UTF-8 带 BOM；LF 行尾；超长 TI/DE 按词折行、续行缩进 3 空格、无空格不硬切；AB 永不折行
- `--only cnki` → 只导知网记录且文件名变为 `文献题录.txt`，之前双平台运行留下的 `文献题录_知网.txt`/`_WOS.txt` 会被自动清掉（防旧产物残留导致对账错乱）；部分导出后跑 `verify_delivery.py --citations-expected 2` 豁免条目对账
- wos_sample.txt 若构造含多作者分号的记录：AU/AF 逐值一行（首行带标签，续值缩进 3 空格），不是分号单行
- 单平台批次（只有知网记录）→ 文件名就是 `文献题录.txt`
- `--format gbt7714` → `参考文献.md`：5 条 `[n] 作者. 题名[J]. 刊名, 年, 卷(期): 页.`；多作者 ≤3 全列、>3 前三加「等/et al」；无卷期行降级为 `刊名, 年.`，行尾单句点
- `--format ris` → `文献题录.ris`：每条 `TY  - JOUR` 开头 `ER  - ` 结尾，作者逐行 `AU  -`，页码拆 `SP/EP`，关键词逐行 `KW  -`
- `--format bibtex` → `文献题录.bib`：`@article{<rid>, ...}`，pages 用 `--`，`{}` 等特殊字符转义

## 用例 6：未获取全文清单与自动门禁

```sh
# 在用例 5 的 /tmp/smoke2 上：删掉全部正文 → 全部成为 missing_file
/usr/bin/python3 scripts/build_index.py /tmp/smoke2 --title "缺失测试" --json
test -f /tmp/smoke2/未获取全文.md && echo "清单已生成"
/usr/bin/python3 scripts/verify_delivery.py /tmp/smoke2 --json >/dev/null; echo "with-list exit=$?"
mv /tmp/smoke2/未获取全文.md /tmp/nf.bak
/usr/bin/python3 scripts/verify_delivery.py /tmp/smoke2 --json >/dev/null; echo "no-list exit=$?"
```

期望：
- `未获取全文.md` 按平台分节，每条含：题录行（作者·出处·被引/下载）、关键词、未获取原因、获取链接
- 有 manifest.csv 失败行 / _quarantine/reasons.csv 时原因取自登记；没有则写「未登记原因」
- 链接规则：知网记录给 `url`；WoS 记录给 `https://www.webofscience.com/wos/woscc/full-record/<UT>`；有 DOI 追加 `https://doi.org/<DOI>`；三项全无写「待补」
- `with-list` 至少不被位 1 的 `refs.no_fulltext` 拦（本目录 0 交付会置位 4，属预期）；`no-list` 退出码含位 1（`refs.no_fulltext`）
- 给某条补上正文文件后重跑 build_index：该条自动从清单消失；全部补齐时清单文件自动删除

## 用例 7：增量续编 + 详情页补字段

```sh
# 增量：已有 C0001/C0002，新扫描从 31 续编
/usr/bin/python3 scripts/cnki_scan.py evals/fixtures/rows.json -o /tmp/smoke4 --start 31 --json
# 详情补抓：C0002 补齐空字段，C9999 匹配不上要告警
/usr/bin/python3 scripts/cnki_detail_scan.py evals/fixtures/detail_page.json     --records /tmp/smoke4/raw/cnki_records.json --json
```

期望：
- `cnki_records.json` 的 rid 为 `C0031/C0032/...`（--start 生效，不与已有冲突）
- detail 合并 `merged == 1`：C0031 补进 keywords/abstract/volume/issue/pages/issn/cn/institution，
  只填空白键、已有值不覆盖；`raw/detail_log.csv` 追加一行记录补了哪些字段
- 未匹配条目 stderr 告警 + `unmatched` 数组；一条都没匹配上时退出码 66

## 用例 4（可选，需用户在场）：端到端 5 篇（走完 G5 应产出 文献题录.txt；若有无全文篇目，另有 未获取全文.md）

```sh
mkdir -p /tmp/e2e
/usr/bin/python3 scripts/env_check.py --workdir /tmp/e2e --json
# 走完 G0→G5，目标 5 篇，产出 00_需求确认.json / raw/ / 正文/ / 索引.md
/usr/bin/python3 scripts/build_index.py /tmp/e2e --title "e2e"
/usr/bin/python3 scripts/verify_delivery.py /tmp/e2e --brief /tmp/e2e/00_需求确认.json --json
```

期望：`verify_delivery.py` 退出 0；`索引.md` 条目数 == `index.csv` 行数 == 实际文件数。
若某篇因付费墙拿不到，报告「缺口说明」必须写到，否则位 4 会拦——这是预期行为，不是 bug。

## 用例 8：会话登记（位 16）

```sh
cp -r /tmp/lit_delivery_test/base /tmp/t8
/usr/bin/python3 scripts/register_session.py /tmp/t8 --sid bsk_test123 --institution "某大学"
/usr/bin/python3 scripts/verify_delivery.py /tmp/t8 --require-session --json >/dev/null; echo "exit=$?"
```

期望：
- 登记后 `raw/_logs/session.json` 含 `session_id/institution/registered_at` 三键，verify 退出 **0**
- 未登记时 `--require-session` 退出 **16**（`session.missing`）
- 缺 `--sid` 或 `--institution` → 退出 **64**，不写半个文件
- session.json 里 `institution` 为空 → 退出 **16**（`session.keys`）
- `register_session.py --check` 只读校验，正常退出 0

## 用例 9：检索台账门禁（位 32）

```sh
cp -r /tmp/lit_delivery_test/base /tmp/t9
/usr/bin/python3 scripts/verify_delivery.py /tmp/t9 --ledger /tmp/t9/检索台账.csv --json >/dev/null; echo "无台账 exit=$?"
```

| 注入 | 期望 |
| --- | --- |
| 台账不存在 | 退出 **64**（`--ledger` 路径不存在，参数错误） |
| 只有表头（0 行） | 退出 **32**（`ledger.rows`） |
| 缺 `fields/refine_*/hits` 等列 | 退出 **32**（`ledger.header`） |
| 3 行但某行 `hits`/`refine_before/after` 为空 | 退出 **32**（`ledger.values`） |
| 3 行齐全 | 退出 **0** |
| 不传 `--ledger` | 不校验台账（G0/G1 不该被挡） |

## 用例 10：重复 rid 三处 fail fast

```sh
# a) pdf_fetch（原 last-wins，被丢条目成孤儿）
mkdir -p /tmp/t10/raw
/usr/bin/python3 -c "
import json; recs=[{'rid':'W0001','platform':'wos','title':'第一篇','doi':'10.1000/a'},{'rid':'W0001','platform':'wos','title':'第二篇','doi':'10.1000/b'}]
open('/tmp/t10/raw/records.json','w').write(json.dumps(recs,ensure_ascii=False))"
/usr/bin/python3 scripts/pdf_fetch.py verify --dir /tmp/t10/pdf --records /tmp/t10/raw/records.json; echo "exit=$?"
```

期望：`fetch` 与 `verify` 两个子命令都退出 **65**，stderr 列出重复 rid；不产生任何下载或 manifest。

```sh
# b) cnki_detail_scan（原 first-wins，补抓字段只上到第一条）
#    两条同 rid 不同篇名的 records + 一条 rid=C0001 的 detail → 退出 65
# c) dedupe（原不设 rid 主键）→ 退出 65，错误信息指出是「编号错误」不是「重复文献」
```

期望：三处全部退出 **65** 且**不写入任何文件**；无重复 rid 时正常路径不受影响
（用例 2 的 `after == 1`、用例 7 的 `merged == 1` 必须仍然成立）。

## 用例 11：检索报告渲染（F1）

```sh
cp -r /tmp/lit_delivery_test/base /tmp/t11
/usr/bin/python3 scripts/build_index.py /tmp/t11 --title "t" >/dev/null
/usr/bin/python3 scripts/render_report.py /tmp/t11 --title "t" --json
/usr/bin/python3 scripts/render_report.py /tmp/t11 --check; echo "check exit=$?"
```

期望：
- `检索报告.md` 的 `<!-- STATS -->` 含 total/with_md/with_pdf/missing_file/unregistered/thin 六键，值与 `index_stats.json` 相等
- `unfilled_placeholders` 为空数组；`--check` 退出 **0**
- **删掉任一 STATS 键 → verify 位 4 必红**（逐一删 6 键各验一次）
- 把 `index_stats.json` 的 `total` 改成 99 → verify 退出 **4**（`count.report`），`--check` 也退出 **4**

## 用例 12：增量合并与下载计划（F3 / F5）

```sh
# F3 合并：旧 2 + 新 1 → 3；同 rid 同篇名只补空字段；同 rid 不同篇名 → 65
/usr/bin/python3 scripts/merge_records.py raw/records.json raw/new_batch.json --json
```

期望：`{"before":2,"batch":1,"after":3,"appended":1}`；rid 撞车时退出 **65** 且 records.json 未被改动。

```sh
# F5 计划：消费 html_whitelist.json / no_html.json
/usr/bin/python3 scripts/cnki_scan.py evals/fixtures/rows.json -o /tmp/t12 >/dev/null
/usr/bin/python3 scripts/plan_download.py /tmp/t12 --json
/usr/bin/python3 scripts/build_index.py /tmp/t12 --title "通道测试" >/dev/null
grep -A2 "### C0003" /tmp/t12/未获取全文.md
```

期望：`download_plan.csv` 4 行（HTML 2 / PDF 1 / NONE 1）；`no_html_reasons.json` 有 C0003；
`未获取全文.md` 里 C0003 的原因是 `no_html / 结果页两次均无入口`（v1.3 是「未登记原因」）；
删掉 `no_html_reasons.json` 重跑 → 原因退回「未登记原因」（证明链路真的在读它）。

## 用例 13：递归口径与陈旧豁免（修复 9 / 10）

```sh
mkdir -p /tmp/t13/正文/子目录 /tmp/t13/raw && cp /tmp/lit_delivery_test/base/raw/records.json /tmp/t13/raw/
cp /tmp/lit_delivery_test/base/正文/C0001_甲.md /tmp/t13/正文/子目录/
/usr/bin/python3 scripts/build_index.py /tmp/t13 --title t >/dev/null
/usr/bin/python3 scripts/verify_delivery.py /tmp/t13 --json | grep -c subdir_skipped   # 期望 >=1
/usr/bin/python3 scripts/build_index.py /tmp/t13 --title t --recursive >/dev/null
/usr/bin/python3 scripts/verify_delivery.py /tmp/t13 --recursive 1 --json >/dev/null; echo "exit=$?"
```

期望：
- 默认非递归：两边都不扫，位 1 不置位，但给 `refs.subdir_skipped` warning（盲区可见）
- 两边同加 `--recursive` / `--recursive 1`：文件进索引，位 1 也不置位
- **陈旧豁免**：先造重复写出 `index_duplicates.csv`，去重解决后重跑 build_index → 该文件被**删除**；
  再用旧名放一个真正的未入索引文件 → verify 位 1 必红（不再被豁免）

