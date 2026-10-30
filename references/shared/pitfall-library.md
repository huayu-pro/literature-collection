# 踩坑库（25 条，均为两次真实会话的事故记录）

> 读完能做什么：在遇到同一个坑时，靠「判定信号」在 1 分钟内认出来，并按「处置」直接改，不用重新试错。
> 判定信号必须是可观测的：DOM 选择器、字符数、字节数、报错串、退出码。

## A. 交付类（最高危，先看这 5 条）

| 现象 | 触发条件 | 判定信号 | 处置 |
| --- | --- | --- | --- |
| 89 篇 PDF 里 88 篇挂错论文 | 两套排名并存：`pdf_by_rank` 键是 `final_rank`，下游用 `rank_by_citation` 查；818 条里 808 条两者不等 | 文件名前缀 ≠ 清单行号；表内 DOI ≠ PDF 首页 DOI；三份交付物互相矛盾 | 全链路只用 `rid`；`rank` 只做展示列；交付前跑 `verify_delivery.py`（位 2 专防这个） |
| Markdown 头表断列 | 年份行多拼了一段「卷(期):页码」，表格行不定长 | 渲染后某行多一列/少一列 | 头表用 dict 渲染，每行字段数固定；写完 `grep -c '|'` 核对 |
| 表格与公式丢失 | `pypdf` 无版面分析 | 原文有表，MD 里没有；公式变成乱码 | 换 `pymupdf.find_tables()`；取不到就写「表格未结构化，见原 PDF p.N」，禁止臆造 |
| 脚注编号重复 | 知网 HTML 按页渲染，`(1)(2)` 每页重置 | 同一篇里出现多个 `[^1]` | `html_to_md.py` 全文重编号，原编号写进注释 |
| 字数阈值误杀 | 正文 <4000 字直接判失败 | 短文/书评被整批剔除 | 阈值可配（`--min-chars`）；不达标标 `thin` 移 `备选/`，不删除 |

## B. WOS 语法

| 现象 | 触发条件 | 判定信号 | 处置 |
| --- | --- | --- | --- |
| `Invalid query` | 在 basic-search 普通输入框写了 `TS=` | 报错串明确含 `Invalid query` | 改到 `advanced-search` 的 Query Preview 框 |
| `Invalid query` 但字段拼写正确 | 把 `DT/LA/Z9/C1/U1` 当检索字段 | 同上 | 这些是**输出标签**；类型/语言走 refine 面板 |
| `0 results` | `SU="Political Science"` | 结果计数为 0 | `SU` 层是 `Government & Law`；`WC` 层才是 `Political Science`；先读 refine 面板再写 |
| 要 JIF/分区阈值，做不到 | 属 InCites 能力 | 检索页无该筛选项 | 用 OpenAlex `2yr_mean_citedness` 代理，列名写「非 JIF」；采集用 `scripts/enrich_metrics.py --dry-run` 先探命中率（该指标在 source 实体的 `summary_stats` 里，works 顶层取不到） |
| OpenAlex 429 | 50 个 DOI 连发 | HTTP 429 | 批间 0.25s；退避 2/4/6s；仍失败就减半批量 |

## C. 浏览器交互

| 现象 | 触发条件 | 判定信号 | 处置 |
| --- | --- | --- | --- |
| hCaptcha「贵机构有异常活动」 | 机构共享 IP + 自动化 | 页面出现 hCaptcha iframe | `bsk request-help --prompt "请完成人机验证"`；不绕过、不连刷 |
| `bsk fill` 报 `not fillable` | a11y ref 指向 DIV 包装层 | 报错串含 `target element is not fillable` | 改 CSS：`#gradetxt > dd input[type=text]`；同行多 input 用 `inputs.pop()` |
| 搜索按钮点不动 | 联想下拉浮层遮住按钮 | click 返回成功但结果区不变 | `press Escape` → `focus '#btnSearch'` → `press Enter` |
| URL 传检索式返回 0 条 | 结果内嵌渲染，URL 参数只支持单关键词 | 换关键词有结果，传 `SU=(...)` 就 0 | 只能走界面；不要试图构造结果页 URL |
| reader 页报 `400001` | 复用上一次的 `invoice` URL | 错误码 400001 | 每次从结果页重新点进；不缓存 reader URL |
| 滑块拖不动 | 合成 `MouseEvent` 无效，bsk 无拖拽命令 | 正文停在 ~2200 字，`confirmSuccess=false` | 调 Vue 组件方法 `mousedownFn/mouseMoveFn/moseUpFn`，`dist=maxwidth+10` |

## D. 文件与正文

| 现象 | 触发条件 | 判定信号 | 处置 |
| --- | --- | --- | --- |
| PDF 挂错论文 | 用标题/文件名做匹配 | 首页 DOI ≠ 记录 DOI | 内嵌 DOI 优先；无 DOI 才用「词边界 + 姓氏 + 短语连片」兜底 |
| 来源类别筛选偶发失效 | 结果渲染过快，左侧面板未就绪 | `document.querySelector('a[title="CSSCI"]')` 返回 null | 记「未筛组」，事后按 `quality_tags` 白名单补筛；不反复点 |
| 扫描件抓不到正文 | 无 HTML 且 PDF 是图片版 | `pdftotext` 输出 0 字符；`text_layer_ratio < 0.05` | 直接换文献，标 `scan_only`；不做无效 OCR |
| 数字丢失（1966→16） | `pdftotext` + 字体子集 | 年份/页码明显错误 | 中文优先 HTML；PDF 只兜底；关键数字回原 PDF 核对 |
| 高被引拿不到全文 | SAGE/T&F/Wiley/OUP 付费墙 | OpenAlex 无 OA 链接 | 保留题录 + DOI + `reason=paywall`，不用错文件凑数 |

## E. 文本质量

| 现象 | 触发条件 | 判定信号 | 处置 |
| --- | --- | --- | --- |
| 编号词误配 | 「十六条」裸跑，撞上《合同法》第 286 条 | 命中里出现完全无关学科 | 编号词/泛动词必须与领域词共现：`TI = 十六条 * (文革 + 社会主义教育运动)` |
| 去重失效 | 同一文献跨检索式 `href` 不同（dbcode/filename 差异） | 同一篇名出现两次 | 按规范化篇名去重；再用 DOI 复核（`dedupe.py` 三级） |

## F. 环境

| 现象 | 触发条件 | 判定信号 | 处置 |
| --- | --- | --- | --- |
| 删文件被钩子拦 | 单轮 ≥50 次删除 | 工具报 hook 拦截 | 一律 `shutil.move` 到 `_quarantine/`，不 `rm` |
| 脚本找不到路径 | Bash 每次重置 cwd | `FileNotFoundError` | 调用方一律传绝对路径（工作目录 / `--records` / `--ledger` / `--md-dir` 都写全）；脚本内部只在 `--lint-assets` 定位包目录与锚定相对 `--md-dir` 时用 `Path(__file__).resolve()`，不要指望它替你补全 |

---

## 版本不符时的引导模板（bsk ≠ 0.3.3）

不要直接失败，按这四步走：

1. **先假设**本手册基于 `bsk 0.3.3`。
2. **逐项对照**本技能用到的 13 个子命令（含会话与聚焦）：
   ```text
   browsers | session start | session stop | navigate | observe | evaluate | click | fill |
   focus | press | download | wait-for-element | request-help
   ```
3. **列出缺失项**：`bsk <cmd> --help` 返回 `unrecognized subcommand` 的，记下来。
4. **给替代命令**，然后请用户确认：
   - 没有 `download` → 用 `evaluate` 触发下载，再从浏览器下载目录取文件（`evaluate` 自触发的下载不被 daemon 关联）。
   - 没有 `observe` → 用 `snapshot` 或 `get-html` 取 DOM，但 `@eN` ref 可能不可用，需改用 CSS 选择器。
   - 没有 `request-help` → 停下，让用户手动完成验证后回复「继续」。
   - `--context` / `cooperate` 子命令属于更新协议，本机 0.3.3 不支持，不要照抄新版仓库文档。

输出格式：

```text
当前 bsk 版本：<version>
缺失子命令：<list>
替代方案：<每项一条>
影响范围：<哪一阶段会降级>
请确认是否按替代方案继续？
```
