# shared-standards.md — HTML/CSS 子集約束

> 對應 SPEC.md §6.1 R1（HTML→DOCX fidelity 是 lossy）+ R1.1（DOCX fidelity hardening）
> 給 Executor / quality_checker 共用 — 定義「哪些 HTML 可安全轉 PDF/DOCX」。

---

## 1. 為什麼要這份

weasyprint 對 CSS 支援廣，但 **pandoc HTML→DOCX 會丟失**：

- CSS Grid（`display: grid`）
- Flexbox（`display: flex`）
- Positioning（`position: absolute / fixed / sticky`）
- `::before`、`::after` 偽元素
- 任意 `float`（除 `<img>` 標準用法）
- 外部 CSS（`--css=foo.css` 效果不穩）

若 LLM 產出含上述規則的 HTML，**PDF 看起來正常但 DOCX 會崩**。這份約束防止此漂移。

---

## 2. 禁用清單（命中即 BLOCKING）

| 規則 | 原因 |
|------|------|
| `display: flex` / `display: grid` / `display: inline-flex` / `display: inline-grid` | pandoc HTML→DOCX 完全丟失 |
| `position: absolute` / `position: fixed` / `position: sticky` | DOCX 無對應概念 |
| `float: left` / `float: right`（非 `<img>`） | 段落 flow 會被打斷 |
| `::before` / `::after` 偽元素 | DOCX 不支援 pseudo-element |
| 外部 CSS（`<link rel="stylesheet">` 或 `@import`） | pandoc `--css=` 效果不穩 |
| JavaScript（`<script>`、`onclick=`） | weasyprint 無 JS 引擎，靜默失敗 |
| `iframe` / `object` / `embed` | 沙箱化內嵌，PDF/DOCX 無法保留 |
| `<canvas>` | weasyprint 無 JS，渲染為空白 |

**檢測方式**：`quality_checker.py` 用 regex + BeautifulSoup 掃描，命中即 BLOCKING。

---

## 3. 允許清單（block flow 子集）

### 3.1 HTML 元素（僅允許以下）

| 元素 | 備註 |
|------|------|
| `<p>`, `<div>`, `<section>`, `<article>`, `<header>`, `<footer>`, `<nav>` | 區塊容器 |
| `<h1>`, `<h2>`, `<h3>`, `<h4>`, `<h5>`, `<h6>` | 標題層級 |
| `<span>`, `<strong>`, `<em>`, `<b>`, `<i>`, `<u>`, `<code>`, `<pre>` | 行內元素 |
| `<ul>`, `<ol>`, `<li>` | 列表 |
| `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` | 表格（pandoc 完整支援） |
| `<img>` | 圖片（需有 `alt`、建議 inline 或 `assets/`） |
| `<sup>`, `<sub>` | 上標下標（章節編號 / 註腳引用） |
| `<a>` | 連結（內部 anchor 與外部 URL） |
| `<blockquote>`, `<cite>`, `<q>` | 引用 |
| `<hr>` | 分隔線 |
| `<br>` | 強制換行（最後手段，盡量用 `<p>`） |

### 3.2 CSS 屬性（僅允許以下）

| 屬性 | 值範例 | 用途 |
|------|--------|------|
| `font-family` | `'標楷體', 'Times New Roman', serif` | 字體（中英混排可用 fallback） |
| `font-size` | `12pt`, `14pt`, `18pt`, `22pt` | 字級（與 report_lock.md 對齊） |
| `font-weight` | `normal`, `bold` | 粗體 |
| `font-style` | `normal`, `italic` | 斜體 |
| `color` | `#000000`, `black` | 文字色 |
| `background-color` | `#f5f5f5` | 背景色（極簡使用） |
| `text-align` | `left`, `center`, `right`, `justify` | 對齊 |
| `line-height` | `1.0`, `1.5`, `2.0` | 行距 |
| `margin`, `margin-top/-bottom/-left/-right` | `2.5cm`, `1em` | 外距 |
| `padding`, `padding-top/-bottom/-left/-right` | `0.5em`, `10px` | 內距 |
| `border`, `border-top/-bottom/-left/-right` | `1px solid #ccc` | 邊框 |
| `border-collapse` | `collapse` | 表格邊框合併 |
| `width`, `height` | `100%`, `auto`, `200px` | 尺寸（謹慎使用） |
| `text-decoration` | `underline`, `none` | 底線（連結預設） |
| `vertical-align` | `top`, `middle`, `bottom` | 垂直對齊（表格 cell） |
| `page-break-before`, `page-break-after` | `always`, `avoid` | 強制分頁 / 避免分頁 |

### 3.3 樣式承載方式（優先序）

1. **內聯 style**（最穩）：`<h1 style="font-family: '標楷體'; font-size: 18pt; font-weight: bold;">`
2. **`<style>` 區塊在同一 HTML 內**（次穩）：`<style>.h1 { font-family: '標楷體'; font-size: 18pt; }</style>`
3. **外部 CSS**（禁用，見 §2）

---

## 4. 字體規則（必遵守）

中英混排時，用 CSS `font-family` 串列：

```css
font-family: '標楷體', 'Times New Roman', serif;
```

瀏覽器 / weasyprint 會自動 fallback：

- 中文字 → 標楷體
- 英文字 → Times New Roman
- 其它 → serif

---

## 5. 章節編號（手動寫入）

HTML5 outline 在 PDF/DOCX 不可靠 → 章節編號**手動寫入**：

```html
<h1>第一章 緒論</h1>
<h2>1.1 研究背景</h2>
<h3>1.1.1 問題陳述</h3>
```

`quality_checker.py` 會驗證 H1/H2/H3 編號連續。

---

## 6. 註腳 / 交叉引用

- **註腳**：pandoc 原生 Markdown 語法 `^[note]`（推薦），或 HTML `<sup><a href="#fn1">1</a></sup>` + `<aside id="fn1">`
- **交叉引用**：HTML anchor `<a href="#sec:intro">§1</a>` 對應 `<h2 id="sec:intro">`

---

## 7. 圖表 / 公式

- **圖表**：用 server-side 預渲染的 SVG（`<img src="assets/fig_1.svg">`），不要用 `<canvas>` / `<script>`（Chart.js）
- **公式**：用 server-side 預渲染的 PNG（`<img src="assets/eq_1.png">`），不要用 MathJax / KaTeX live render
- **圖說**：用 `<p class="caption">Figure 1: ...</p>`，style 含 `text-align: center; font-size: 10pt;`

---

## 8. OK HTML 範例

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>範例報告</title>
<style>
  body { font-family: '標楷體', 'Times New Roman', serif; font-size: 12pt; line-height: 1.5; }
  h1 { font-family: '標楷體', 'Times New Roman', serif; font-size: 18pt; font-weight: bold; }
  h2 { font-family: '標楷體', 'Times New Roman', serif; font-size: 16pt; font-weight: bold; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ccc; padding: 0.5em; }
  .caption { text-align: center; font-size: 10pt; }
</style>
</head>
<body>
  <h1>第一章 緒論</h1>
  <p>本研究探討 <strong>標楷體</strong> 與 <em>Times New Roman</em> 的混排。</p>
  <h2>1.1 研究背景</h2>
  <p>參考文獻 <a href="#ref1">[1]</a> 指出...</p>
  <table>
    <thead><tr><th>項目</th><th>數值</th></tr></thead>
    <tbody>
      <tr><td>字數</td><td>12,345</td></tr>
    </tbody>
  </table>
  <p class="caption">Table 1: 範例表格</p>
</body>
</html>
```

✅ 全部使用允許清單；無禁用規則；無 JavaScript；無外部 CSS；字體採 fallback。

---

## 9. FAIL HTML 範例

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.example.com/bootstrap.css">  <!-- ❌ 外部 CSS -->
<style>
  .container { display: flex; justify-content: space-between; }  <!-- ❌ flex -->
  .hero { position: absolute; top: 0; left: 0; }                  <!-- ❌ position -->
  .quote::before { content: '"'; }                                <!-- ❌ ::before -->
</style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <h1>第一章 緒論</h1>
    </div>
    <div style="float: right;">                                   <!-- ❌ float 非 img -->
      <p>側欄</p>
    </div>
  </div>
  <script src="https://cdn.example.com/chart.js"></script>       <!-- ❌ JS -->
  <canvas id="myChart"></canvas>                                  <!-- ❌ canvas -->
</body>
</html>
```

❌ 命中禁用清單 6 處。`quality_checker.py` 會回報：

```
[BLOCKING] HTML 含禁用 CSS / 元素：
  line 4: external CSS (<link rel="stylesheet">)
  line 7: display: flex
  line 8: position: absolute
  line 9: ::before pseudo-element
  line 17: float: right (non-<img>)
  line 22: <script> tag
  line 23: <canvas> element
請改寫為允許清單後重提。
```

---

## 10. 速查表

| 想做的事 | 該用 | 不該用 |
|----------|------|--------|
| 圖表 | `<img src="assets/fig.svg">` | `<canvas>`、Chart.js、`<script>` |
| 公式 | `<img src="assets/eq.png">` | MathJax、KaTeX live |
| 多欄佈局 | `<table>` 切欄 | CSS Grid、Flex |
| 固定元素 | 不用 | `position: fixed` |
| 浮動圖說 | 文字段落，圖在前 | `float: left` 包圖 |
| 樣式承載 | 內聯 `style="..."` | 外部 `<link>`、`@import` |
| 註腳 | `^[note]` Markdown | 自寫 `<sup>` + `<aside>`（DOCX 會丟） |
| 目錄 | pandoc `--toc` 自動生成 | 手寫目錄 HTML |

---

*shared-standards.md v1 — 對應 SPEC.md v0.3 §6.1 R1+R1.1, 2026-06-13*
