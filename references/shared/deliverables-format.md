# 交付物格式细则：文献题录.txt 与 未获取全文.md

> 何时读：导出/核对题录文件、排查「导入 NoteExpress/EndNote 失败」、检查 未获取全文.md 排版或链接缺失时。
> 格式对照真实导出样例复刻（知网 RT 标签格式 / WoS savedrecs 格式），不是自造格式。

## 1. 文献题录.txt

### 1.1 两种格式的硬性差异

| 项 | 知网格式（cnki 记录） | WoS 格式（wos 记录） |
| --- | --- | --- |
| 文件头 | 无 | `FN Clarivate Analytics Web of Science` + `VR 1.0` |
| 记录开头 | `RT Journal Article` | `PT J` |
| 记录结尾 | 空行分隔 | `ER` 行 + 空行；文件末尾 `ER` 空行 `EF`（EF 后无换行） |
| 多值字段 | 分号连接单行（A1 作者;作者） | **逐值一行**：首行带标签，后续值各占一行、缩进 3 空格（AU/AF/BA/BF/CA/C1/C3/OI/SI） |
| 折行 | 不折行 | 按词折行、续行缩进 3 空格（TI/DE/FX）；**AB 永不折行**（样例 18 条 AB 全单行，最长 1923 字符）；无空格可断（中文/URL）不硬切，整行保留 |
| 空值字段 | 整行跳过；唯 `vo` 例外：卷号缺失仍保留空 `vo` 行（样例 9/13 处） | 整行跳过 |
| 编码/行尾 | UTF-8 无 BOM + CRLF | UTF-8 带 BOM + LF |

### 1.2 字段映射（records.json → 题录）

知网格式按固定顺序输出，空值字段整行跳过：

| 标签 | 来源字段 | 说明 |
| --- | --- | --- |
| RT | type | 「期刊」→ Journal Article；未识别默认 Journal Article |
| SR | 固定 `1` | 样例 13 条记录 SR 恒为 1，不是导出序号 |
| A1 | authors | 多作者 `;` 分隔；list 型自动连接 |
| AD | institution/affiliation | 详情页补抓才有 |
| T1 / JF / YR | title / source / year | |
| IS / vo / OP | issue / volume / pages | OP 含补页写法 `212-233+260` |
| K1 / AB | keywords / abstract | |
| SN / CN | issn / cn | |
| LA | language | 默认 `中文;`（分号是样例原样） |
| DS | 固定 `CNKI` | |
| LK / DO | url / doi | doi 转小写 |

WoS 格式：有 `raw`（wos_parse.py 保留的 71 字段原始值）时按固定标签顺序输出（含 VL/IS/AR/OI/SI 等卷期与身份标签），导出保真；无 `raw` 时从规范化字段构造最小记录（PT J / AU / TI / SO / LA / DT / AB / DE / PY / VL / IS / DI / BP / EP / UT / DA…）。DA 取当天日期。标签顺序按真实 savedrecs 样例归纳：…PD PY VL IS AR BP EP DI EA PG…、OI 在 EM/RI 之后。

### 1.3 命名规则

- 单平台批次：`文献题录.txt`（一个文件，格式随平台）。
- 两平台混合：`文献题录_知网.txt` + `文献题录_WOS.txt`。不混装一个文件——导入器只认一种格式。
- `export_citations.py --only cnki|--wos` 切换口径后，旧产物会被自动清掉，防残留导致对账错乱。
- 条目对账：题录条目数 == records.json 条数，verify_delivery 位 4 自动拦；`--only` 只导部分记录属合法部分导出，需配 `verify_delivery.py --citations-expected N`（N=实际导出条数）豁免，并在报告说明。
- dedupe 默认原地模式：records.json 直接变成去重后的真源（首次自动备份 records.raw.json），
  被合并 rid 的文件已改名到胜者 rid，题录条目数天然对账；旁路产物 records.dedup.json 仅在显式 `-o` 时生成。
- 同 rid 挂两篇不同文献（dedupe 合不掉）时 build_index/export 都 fail fast，人工重编 rid。
- 平台不明（platform 缺失且 rid 非 C/W 前缀）的记录按知网格式导出并在 stderr 警告；此时索引里它标「未识别平台」，归属以警告为准人工核对。

### 1.4 附加格式（--format，全平台记录一起导）

| 格式 | 输出 | 用途 |
| --- | --- | --- |
| gbt7714 | 参考文献.md | GB/T 7714-2015 顺序编码制 `[1] 作者. 题名[J]. 刊名, 年, 卷(期): 页.`；>3 作者前三加「等/et al」，英文姓前名缩写 |
| apa | 参考文献-apa.md | APA 第 7 版 `作者, A. A., & 作者, B. B. (年). 题名. *刊名*, 卷(期), 页. https://doi.org/…`；作者缩写补句点，末位用 & 连接，页码用短横线 |
| mla | 参考文献-mla.md | MLA 第 9 版 Works Cited `作者. “题名.” *刊名*, vol. 卷, no. 期, 年, pp. 页.`；题名弯引号、刊名斜体 |
| ris | 文献题录.ris | Zotero/EndNote 导入；AU 逐行、SP/EP 拆页码、UR 给原文链接 |
| bibtex | 文献题录.bib | LaTeX/Zotero；key=rid，pages 用 `--`，特殊字符转义 |

五种格式都不与 auto 的 txt 冲突，可先后运行各出一份。题录质量依赖 `cnki_detail_scan.py`
把知网详情页的关键词/摘要/卷期页码合并进 records.json——不补抓，知网记录的这些字段就是空。

## 2. 未获取全文.md

生成条件：index 中存在 `status=missing_file` 的行（records 有题录、磁盘无 md/pdf）。全部补齐后重跑 build_index.py，文件自动删除。

每条五要素（缺一即不合格）：

1. `### <rid>　<题名>` 标题行——verify 位 1 靠它对账；
2. 题录行：作者 · 出处 年 · 被引/下载；
3. 关键词（有则写）；
4. 未获取原因：优先 `_quarantine/reasons.csv`，次 `manifest.csv` 失败行，都没有写「未登记原因」；
5. 获取链接：知网记录给 `url`（详情页）；WoS 记录给 `https://www.webofscience.com/wos/woscc/full-record/<UT>`；有 DOI 追加 `https://doi.org/<DOI>`；三项全无写「待补（需回检索平台补抓）」——绝不编造链接。

## 3. 常见错误

| 错误 | 纠正 |
| --- | --- |
| 两平台记录混进同一个题录文件 | 导入器只认一种格式；混合批次必须分文件 |
| 知网文件写成 LF 或加了 BOM | NoteExpress 对 CRLF 敏感；用脚本导出，不手拼 |
| WoS 摘要被折行 | AB 是唯一不折行的标签（样例全部单行）；其余标签超 78 字符按词折行、续行 3 空格，无空格不硬切 |
| 多作者挤成一行分号连接 | WoS 格式作者逐值一行（`AU Doe, J` 换行 `   Smith, A`），分号连接会让导入器读成一个作者 |
| 题录条目数 < records 数 | 先查 `--only` 是否过滤过；重跑 `export_citations.py` |
| 未获取全文.md 手工删改后与索引对不上 | 该文件是脚本产物，只通过重跑 build_index.py 更新 |
