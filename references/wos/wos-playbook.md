# Web of Science 操作手册（bsk 0.3.3 实测 + 官方文档）

> 读完能做什么：在 WOS 上跑出可复现的检索式、导出 71 字段全记录、拿到 OA 全文并转 Markdown。
> 三个致命陷阱先记住：`TS=` 不能写进普通输入框；`DT/LA` 不是检索字段；`SU` 里没有 Political Science。

## 1. 入口与登录断言

```sh
bsk navigate https://www.webofscience.clarivate.cn/wos/woscc/basic-search --session <sid>
bsk evaluate '(() => document.body.innerText.slice(0,400))()' --session <sid> --json
```

判据：右上角出现机构名（机构 IP 直通），或页面显示 `Sign In` 的机构入口。
- 显示机构名 → 继续。
- 显示登录墙 → 停下问人，不要猜账号。

## 2. 陷阱一：Query Preview 才认 `TS=`

| 位置 | 是否接受字段前缀 | 是否支持 `#1 AND #2` |
| --- | --- | --- |
| 新版 Fielded Search 输入框（basic-search 的「字段」模式） | ❌ 报 `Invalid query` | ❌ |
| `wos/woscc/advanced-search` 的 **Query Preview** 框 | ✅ | ✅ |

```text
正确：navigate .../wos/woscc/advanced-search → 在 Query Preview 填 TS=(...) → 搜索
错误：在 basic-search 的普通输入框填 TS=(...)
```

## 3. 字段标签

| 标签 | 含义 | 可检索 |
| --- | --- | --- |
| `TS` | 主题：标题 + 摘要 + 作者关键词 + Keywords Plus | ✅ 首选 |
| `TI` | 标题 | ✅ |
| `AB` | 摘要 | ✅ |
| `AK` | 作者关键词 | ✅ |
| `AU` | 作者 | ✅ |
| `AI` | 作者标识符（ResearcherID/ORCID） | ✅ |
| `SO` | 出版物名称 | ✅ |
| `PY` | 出版年 | ✅ |
| `WC` | WoS 学科类别（细） | ✅ |
| `SU` | 研究领域（宽） | ✅ |
| `OG` | 机构扩展 | ✅ |
| `FO` | 基金资助 | ✅ |
| `DT` | 文献类型 | ❌ **输出标签**，只能 refine |
| `LA` | 语言 | ❌ **输出标签**，只能 refine |
| `Z9` / `C1` / `U1` | 全库被引 / 作者地址 / 机构 | ❌ 输出标签 |

**判定信号**：检索后报 `Invalid query` 或 `0 results` 且字段名拼写正确 → 先怀疑把输出标签当成了检索字段。

## 4. 运算符

| 符号 | 含义 | 示例 |
| --- | --- | --- |
| `AND` / `OR` / `NOT` | 布尔 | `TS=(nanotub* AND carbon)` |
| `NEAR/n` | 两词间隔 ≤n | `TS=(Trump NEAR/5 populism)` |
| `SAME` | 同句（地址字段常用） | `OG=(Tsinghua SAME Beijing)` |
| `*` | 任意字符（含 0 个） | `nanotub*` |
| `?` | 单个字符 | `wom?n` |
| `$` | 0 或 1 个字符 | `colo$r` |
| `" "` | 精确短语 | `"Donald Trump"` |
| `( )` | 优先级 | `TI=(Sanit* AND (Fruit* OR Vegetable*))` |
| `#n` | 引用历史检索集 | `#1 NOT #2` |

官方示例（原样保留）：

```text
TS=nanotube
TS=(nanotub* AND carbon)
TS=(nanotub* AND carbon) NOT AU=Smalley RE
SO=Nature AND TS=Amphibian* AND PY=(2001-2010)
TI=(Sanit* AND (Fruit* OR Vegetable*))
#1 NOT #2
```

## 5. refine 面板（只能界面点，不能写进检索式）

| 面板项 | 对应字段 | 建议值 |
| --- | --- | --- |
| Document Types | `DT` | `Article` + `Review` |
| Languages | `LA` | `English`（按需保留中文） |
| Publication Years | `PY` | 与 brief 对齐 |
| WoS Categories | `WC` | 精确子学科 |
| Research Areas | `SU` | 宽类，仅在 WC 太细时用 |
| Authors / Affiliations | `AU` / `OG` | 追团队时用 |
| Funding Agencies | `FO` | 只保留基金成果时用 |
| Open Access | `OA` | 只要 OA 时勾选 |

## 6. 陷阱二：学科层级先查后写

| 层级 | 政治学叫什么 | 传播学叫什么 |
| --- | --- | --- |
| `SU`（Research Areas） | `Government & Law`（**没有 Political Science**） | `Communication` |
| `WC`（WoS Categories） | `Political Science` | `Communication` |

流程：
1. 先跑一条 `TS=(主题词)` 的宽式检索。
2. 在 refine 面板展开 `WC` / `SU`，**读出**当前结果集里真实存在的类目名。
3. 把读到的名字写进检索式，并在台账 `note` 记「类目名来自 refine 面板」。

实测：`SU="Political Science"` 命中 0；`WC=("Political Science" OR "Communication")` 正常。

## 7. 结果页与排序

```sh
bsk click 'text=Sort by' --session <sid>          # 或直接点表头 Times Cited
bsk wait-for-element 'app-results-list' --state visible --timeout 20s --session <sid> --json
```

- 每页默认 50，导出前不用翻页。
- 结果计数在页面上方 `N results`，记进台账 `refine_before`。
- 排序选 `Times Cited — highest first`，对应字段 `TC`；跨库引用看 `Z9`。

## 8. 导出（71 字段全记录）

| 选项 | 值 |
| --- | --- |
| 导出范围 | Records 1–N（每批 ≤1000） |
| 内容 | **Full Record** |
| 格式 | **Tab delimited** |
| 文件名 | `raw/wos_full_record_<N>.txt` |

解析（必须这样写，否则带引号的字段会串列）：

```python
import csv
with open(path, encoding="utf-8-sig", newline="") as f:
    reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
    header = [h.strip() for h in next(reader)]
```

71 字段顺序（实测表头，`PT` 起、`UT` 止）：

```text
PT AU BA BE GP AF BF CA TI SO SE BS LA DT CT CY CL SP HO DE ID AB C1 C3 RP EM
RI OI FU FP FX CR NR TC Z9 U1 U2 PU PI PA SN EI BN J9 JI PD PY VL IS PN SU SI
MA BP EP AR DI DL D2 EA PG WC WE SC GA PM OA HC HP DA UT
```

22 个关键字段：

```text
UT(唯一键) TI AU SO PY VL IS BP EP DI(DOI) TC(核心被引) Z9(全库被引)
AB DE(作者关键词) ID(Keywords Plus) WC SU HC OA SN EI C1(作者地址)
```

## 9. 指标口径

| 字段 | 含义 | 用法 |
| --- | --- | --- |
| `TC` | WoS 核心合集被引 | 默认排序依据 |
| `Z9` | 全库被引（含非核心） | 跨库比较更公平 |
| `HC` | Highly Cited 标记 | 高质量强信号 |
| `OA` | 开放获取状态 | 决定能否自动取全文 |

**JIF / 分区 / 影响因子拿不到**：属 InCites 能力。替代口径见 `method/quality-screening.md` §5，列名必须带「非 JIF」。

## 10. OA 全文获取

```sh
/usr/bin/python3 scripts/pdf_fetch.py fetch \
    --records raw/records.json --outdir pdf/ \
    --mailto you@example.com --limit 100 --workers 4
```

链路：OpenAlex `works?filter=doi:a|b|...`（50/批）→ `best_oa_location.pdf_url` → `open_access.oa_url` → `locations[].pdf_url` → 域名优先级 → curl。

| 域名 | 优先级 |
| --- | --- |
| MDPI / Frontiers | 1 |
| Springer / Cogitatio | 2 |
| Wiley / OUP / Cambridge | 3 |
| SAGE / T&F | 4 |
| ScienceDirect | 7 |
| SSRN | 9 |

限速基线：50 DOI/批、批间 0.25s、429 退避 2/4/6s、4 线程、单请求 30s 超时。

四重校验：`%PDF-` 魔数 → ≥10KB → 页数 ≥1 → **首页内嵌 DOI == 记录 `DI`**。任一不过 → `_quarantine/`，绝不改名凑数。

## 11. 错误码对照

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| `Invalid query` | 在普通输入框写了 `TS=` | 改用 Query Preview |
| `Invalid query` + 字段正确 | 把 `DT/LA/Z9` 当检索字段 | 走 refine 面板 |
| `0 results` + 类目名正确 | `SU` 层级记错 | 先读 refine 面板再写 |
| hCaptcha「贵机构有异常活动」 | 机构共享 IP + 自动化 | `bsk request-help` 请人过，不绕过、不轰炸 |
| 导出只有 500 条 | 单批上限 | 分两批 1–500、501–1000 |

## 12. 标准动作序列

```sh
bsk browsers --json
bsk session start --json --browser <id>                      # → sid
bsk navigate .../wos/woscc/advanced-search --session $sid
bsk observe --session $sid
# 在 Query Preview 填式子（用 @eN ref）
bsk fill @e12 --value 'TS=("Donald Trump" OR Trumpism) AND WC=("Political Science")' --session $sid
bsk press Enter --session $sid
bsk wait-for-element 'app-results-list' --state visible --timeout 30s --session $sid --json
# refine：DT=Article、LA=English、PY=2016-2026，再按 TC 排序
# 导出 Full Record / Tab delimited / 1000 一批
/usr/bin/python3 scripts/wos_parse.py raw/wos_full_record_818.txt -o raw/records.json --rid-map raw/rid_map.csv
bsk session stop $sid
```
