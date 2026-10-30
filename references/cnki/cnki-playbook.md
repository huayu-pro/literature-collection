# 知网操作手册（bsk 0.3.3 实测）

> 读完能做什么：从打开知网到拿到 30 篇 Markdown 正文，中途不被登录态、联想浮层、滑块、reader 400001 卡住。
> 所有选择器均为 2026-10 实检；版本不符时先读 `shared/pitfall-library.md` 末尾的引导模板。

## 1. 入口与登录断言

```sh
bsk browsers --json
bsk session start --json --browser <id-or-label>          # 记下 session_id
bsk navigate https://www.cnki.net/ --session <sid>
bsk evaluate '(() => document.body.innerText.slice(0,600))()' --session <sid> --json
```

判据：正文出现机构名 + 「个人登录」，例如 `山东大学 个人登录`。
- 出现 → 机构 IP 已认证，继续。
- 只有「登录/注册」→ **停下问人**，不要尝试账号密码，不要新开 profile。
- `bsk` 报找不到浏览器 → 让用户先打开装了扩展的 Chromium/Edge。

## 2. 高级检索页

```sh
bsk navigate https://kns.cnki.net/kns8s/AdvSearch --session <sid>
bsk observe --session <sid>
```

填写要点：
- 输入框真实节点是 `#gradetxt > dd input[type=text]`；同行有多个 hidden input，取最后一个可见的：
  ```js
  (() => { const dd = document.querySelector("#gradetxt > dd");
           const inputs = [...dd.querySelectorAll("input[type=text]")];
           const el = inputs.pop(); el.focus(); return el.outerHTML.slice(0,120); })()
  ```
- `bsk fill @e41` 报 `target element is not fillable` → a11y ref 指到了 DIV 包装层，改用上面的 CSS 选择器。
- 最多 10 个检索项；行间**从上到下依次运算**，不是全局 AND。

## 3. 搜索按钮被联想浮层挡住（高频卡点）

现象：`bsk click '#btnSearch'` 返回成功但页面没动；坐标点击也无效。
原因：输入后的联想下拉浮层盖住了按钮。

```sh
bsk press Escape --session <sid>
bsk focus '#btnSearch' --session <sid>
bsk press Enter --session <sid>
```

这是两次会话里最关键的一次突破；凡是「填完了点不动」，先走这三步。

## 4. 结果页结构

| 目标 | 选择器 | 备注 |
| --- | --- | --- |
| 结果行 | `table.result-table-list tbody tr` | 每页 20/50 |
| 篇名链接 | `td.name a` | 带 `target="_blank"` |
| 操作区 | `td.operat a` | 「HTML阅读」/「原版阅读」**互斥** |
| 排序条 | `#orderList` | 被引 `#CF`，下载 `#DFR` |
| 来源类别 | `a[title="CSSCI"]` 等 | 勾选其父 `li` 内 checkbox |

一次抓全行（题名/作者/来源/日期/类型/被引/下载/操作）：

```js
(() => {
  const rows = [...document.querySelectorAll("table.result-table-list tbody tr")];
  return JSON.stringify(rows.map(tr => {
    const t = s => (tr.querySelector(s)?.innerText || "").replace(/\s+/g, " ").trim();
    return {
      title: t("td.name"), href: tr.querySelector("td.name a")?.href || "",
      author: t("td.author"), source: t("td.source"), date: t("td.date"),
      type: t("td.type"), cited: t("td.cited"), download: t("td.download"),
      operat: t("td.operat")
    };
  }));
})()
```

## 5. 两次确认：到底有没有 HTML 全文

**第一次（结果页）**：看 `td.operat` 文本。
**第二次（详情页）**：进详情页看 `li.btn-html a` 是否存在。
两次结论一致才定性；只有一次命中就下结论 → 会把可 HTML 的文献误判成 PDF。

实测覆盖率（供预期管理，不要当承诺）：

| 文献类型 | HTML 可读比例 |
| --- | --- |
| 文革主题（1966–1976 老刊） | ≈35%（34 出 12） |
| 大跃进主题 | ≈47%（30 出 14） |
| 2000 年后新刊 | ≈50% |

## 6. 进阅读页（不能直接 click）

`li.btn-html a` 指向 `bar.cnki.net` 中转，且带 `target="_blank"`；脚本 click 常被吞。

```js
(() => {
  const a = document.querySelector("li.btn-html a");
  if (!a) return JSON.stringify({ok:false, step:"no_btn"});
  a.setAttribute("target", "_self");
  location.href = a.href;                     // 同标签跳转，避免标签爆炸
  return JSON.stringify({ok:true, href: a.href});
})()
```

到达判据：URL 含 `/reader/`。中转会 302 到 `kns.cnki.net/reader/xml?invoice=...`。

**400001 陷阱**：复用上一次的 reader URL 必报 `400001`。每次都必须从结果页重新进入，不要缓存 URL。

## 7. 滑块验证（正文被截断时）

现象：正文只有 ~2200 字，尾部出现「请向右滑动验证」。
原因：合成 `MouseEvent` 无效，`bsk` 也没有拖拽命令。
处置：直接驱动页面自身的 Vue 组件方法。

```js
(() => {
  const w = document.querySelector(".slider-wrapper");
  if (!w || !w.__vue__) return JSON.stringify({ok:false, step:"no_vue"});
  const vm = w.__vue__;
  if (vm.$data.confirmSuccess) return JSON.stringify({ok:true, step:"already"});
  const md = vm.$options.methods.mousedownFn.bind(vm);
  const mm = vm.$options.methods.mouseMoveFn.bind(vm);
  const mu = vm.$options.methods.moseUpFn.bind(vm);
  const r = document.querySelector("#js-handler")?.getBoundingClientRect();
  const sx = (r?.x || 40) + (r?.width || 30) / 2;
  const sy = (r?.y || 300) + (r?.height || 30) / 2;
  md({clientX: sx, clientY: sy, preventDefault: () => {}});
  const dist = vm.$data.maxwidth + 10;               // 实测 maxwidth=311
  for (let i = 1; i <= 32; i++) mm({clientX: sx + dist * i / 32, clientY: sy});
  mu({clientX: sx + dist, clientY: sy});
  return JSON.stringify({ok: vm.$data.confirmSuccess === true, dist,
                         len: document.querySelector(".pdfFullBox .study-c")?.innerText.length || 0});
})()
```

成功判据：返回 `ok:true`，且 `.study-c` 字符数从 ~2200 涨到 9000+。
失败：`confirmSuccess` 仍为 false → 重试 1 次；再失败就用 `bsk request-help` 请人过，不要连刷。

## 8. 正文提取

容器：`.pdfFullBox .study-c`。只取 `h1…h5, p, li` 的 `innerText`。

```js
(() => {
  const box = document.querySelector(".pdfFullBox .study-c");
  if (!box) return JSON.stringify({ok:false, step:"no_box"});
  const title = (document.querySelector("h1")?.innerText || "").replace(/\s+/g, " ").trim();
  const noise = /^(引证文献|问答精要|核心观点|文章大纲|进入CNKI AI|向右滑动验证)/;
  const nodes = [];
  for (const n of box.querySelectorAll("h1,h2,h3,h4,h5,p,li")) {
    const t = n.innerText.replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").trim();
    if (!t || noise.test(t)) continue;
    if (n.tagName === "H1" && t === title) continue;
    nodes.push({tag: n.tagName, txt: t});
  }
  return JSON.stringify({ok:true, chars: box.innerText.length, nodes});
})()
```

落盘：

```sh
bsk evaluate "$(cat extract.js)" --session <sid> --json > page.json
/usr/bin/python3 scripts/html_to_md.py page.json -o "正文/C0001_篇名.md" \
    --meta raw/records.json --rid C0001 --min-chars 4000
```

正文 < 4000 字 → 脚本标 `status=thin`，移入 `备选/`，不进主库（挡综述/书评/会议综述）。

## 9. 来源类别筛选

```js
(() => {
  const out = [];
  for (const t of ["CSSCI", "北大核心", "CSCD"]) {
    const a = document.querySelector(`a[title="${t}"]`);
    const cb = a?.closest("li")?.querySelector('input[type="checkbox"]');
    if (cb && !cb.checked) { cb.click(); out.push(t); }
  }
  return JSON.stringify({ok:true, clicked: out});
})()
```

渲染过快时左侧面板未就绪，`a` 为 null → **记录该组「未筛」**，事后用 `index.csv` 的 `quality_tags` 按 CSSCI 白名单补筛，不要反复点。

## 10. 题录导出（可选，但强烈建议）

结果页「导出/参考文献」→ 选格式：

| 用途 | 格式 |
| --- | --- |
| 中文论文参考文献 | GB/T 7714-2015 |
| EndNote | EndNote |
| Zotero | RefWorks / RIS |
| NoteExpress | NoteExpress |
| 自己解析 | CNKI E-Study（xls）或「自定义」选字段 |

每批 ≤50 条。导出文件放 `raw/`。`cnki_scan.py` 实际产出 20 个键（不是 12 个），
其中 12 个是题录导出会用到的标准键，其余 8 个是流程/判定用的辅助键：

| 组 | 键 | 用途 |
| --- | --- | --- |
| 标准题录键（12） | `rid` `title` `authors` `source` `year` `cited` `downloads` `type` `url` `doi` `quality_tags` `access` | 题录导出与索引字段 |
| 流程辅助键（8） | `platform` `date` `cnki_id` `operat` `has_html` `has_pdf` `note` `keywords`/`abstract`（详情页补抓后才有） | 通道判定、回链、补抓日志 |

`quality_tags` 由 `cnki_scan.py` 从来源类别列解析（CSSCI / 北大核心 / CSCD / SCI / SSCI / EI / AMI / OA），
左侧面板未勾选或页面未渲染出类别列时为空——此时 G3 门禁「每条记录有 quality_tags」会红，
按 §9 的办法用 `index.csv` 白名单补筛，不要手改 JSON 填空标签。

## 10b. 详情页补字段（喂饱题录导出）

结果页扫描（`cnki_scan.py`）只有标题/作者/被引/下载；题录导出的 K1/AB/vo/IS/OP/SN/CN/AD
要进详情页抓。在详情页用 `bsk evaluate` 取一个对象（选择器以现场 DOM 为准，下面是 0.3.3 实测锚点，
改版后优先找含「关键词」「摘要」文字的节点）：

```js
(() => {
  const t = sel => document.querySelector(sel)?.innerText.trim() || "";
  const li = sel => [...document.querySelectorAll(sel)].map(x => x.innerText.trim()).filter(Boolean);
  return {
    rid: "C0003",  // 必填：写当前文献的 rid，合并全靠它
    keywords: li("li.keywords a") || t(".keywords").split(/[;；]\s*/),
    abstract: t("span.abstract-text") || t("#ChDivSummary"),
    authors: li("h3.author a") || t("h3.author").split(";"),
    institution: li("h3.author em") ,
    source: t(".title a") || t("div.top-tip span:first-child a"),
    // 知网把卷期页写在「《刊名》2024年第3期12-25,120」这样的 top-tip 里，整体抓回让脚本外的 agent 拆
    issue_line: t("div.top-tip"),
  }
})()
```

卷/期/页码/ISSN/CN 多数藏在 `div.top-tip` 一行文本里，抓回来后手工拆成 `volume/issue/pages/issn/cn`
再合并。每篇抓完存成 detail 数组（`raw/detail_batch.json`），一次合并：

```sh
/usr/bin/python3 scripts/cnki_detail_scan.py raw/detail_batch.json --records raw/records.json
```

只补空字段、已有值不覆盖；日志在 `raw/detail_log.csv`。没带 rid 也能按 url/篇名匹配，
但 rid 最稳——白名单下载前顺手把详情页抓了，别攒到最后。

## 11. 批量下 PDF（仅当两次确认无 HTML）

```sh
bsk download @e12 --out "/abs/项目/pdf/C0001_张三2020_中共党史研究.pdf" \
    --session <sid> --timeout 2m --json
```

| 错误码 | 含义 | 处置 |
| --- | --- | --- |
| `download_path_mismatch` | 下载管理器改名了 | 去浏览器下载目录找同名文件，手动移入 |
| `download_capture_failed` | 没有可捕获的直链 | 判该篇无 PDF，记 `reason=no_pdf` |
| 超时 | PDF 在内置阅读器打开而非下载 | 同上，或改用 HTML 通道 |

## 12. 失败原因枚举（写进 `_quarantine/reasons.csv`）

唯一真源是 `scripts/reason_codes.py`（10 值）。v1.3 曾有两套词汇表并存——本节的人工枚举
与 `pdf_fetch.py` 四重校验自造的 `too_small/not_pdf/doi_mismatch/…` 互不映射，同一篇文献
在两条链路上得到两个原因，无法归类。下表与 `reason_codes.py` 逐项对齐，
**新增值必须同时改两处**，`verify_delivery.py --lint-assets` 会校验一致性。

```text
no_html      两次确认都没有 HTML 入口
no_pdf       有「原版阅读」但下载捕获失败
paywall      机构未订阅 / 需要个人付费
captcha      滑块或 hCaptcha 反复失败
scan_only    PDF 无文本层（pdftotext 0 字符）
thin_text    正文 < 4000 字
mismatch     DOI/篇名与记录不符
invalid_pdf  下载物不是有效 PDF（过小 / 无魔数 / 0 页 / 不可读）
no_oa        OpenAlex 无 OA 直链
network      下载或接口失败（超时 / 无文件落盘）
```

`pdf_fetch.py` 的原始 reason 经 `reason_codes.canonical()` 映射后统一写入：

| 原始值 | 规范值 |
| --- | --- |
| `too_small` / `not_pdf` / `no_pages` / `unreadable:*` | `invalid_pdf` |
| `doi_mismatch` / `title_mismatch` / `no_record` | `mismatch` |
| `no_file` | `network` |
