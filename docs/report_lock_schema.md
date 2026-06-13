# report_lock.md — Schema 規格

> 對應 SPEC.md §3.4.1 + §6.1 R1.1 + §6.2 R2（升級 10 Confirmations）
> 機器可讀執行合同 — Executor 每節重讀一次，防 formatting drift。
> 任何 required 欄位缺失 → **BLOCKING**，Strategist 拒絕產出 lock。

---

## 1. 檔案格式

YAML frontmatter + Markdown 註解（給人類讀）。**所有鍵名僅允許小寫英文 + 數字 + 下底線**。

```markdown
---
# ← YAML 在這裡
fonts:
  cjk: 標楷體
  latin: Times New Roman
formatting:
  ...
---

# report_lock.md

> 機器執行合同 — 任何修改需同步 SPEC.md §3.4.1。
> 產生時間：2026-06-13 12:34:56
> 專案：demo-academic

（Markdown 註解 / 變更日誌）
```

---

## 2. Required 欄位（缺一不可）

| Key | Type | 值 | 備註 |
|-----|------|-----|------|
| `fonts.cjk` | string | **固定 `標楷體`** | 不可覆寫為其他中文字體 |
| `fonts.latin` | string | **固定 `Times New Roman`** | 不可覆寫為 Calibri / Arial |
| `formatting.cover` | object | `{font_size: 22, bold: true, align: center}` | 封面 |
| `formatting.toc` | object | `{font_size: 20}` | 表目錄 |
| `formatting.title` | object | `{font_size: 22, bold: true, align: center}` | 主標題 |
| `formatting.h1` | object | `{font_size: 18, bold: true}` | H1 層級 |
| `formatting.h2` | object | `{font_size: 16, bold: true}` | H2 層級 |
| `formatting.h3` | object | `{font_size: 14, bold: true}` | H3 層級 |
| `formatting.body` | object | `{font_size: 12, line_spacing: 1.5}` | 內文 |
| `formatting.table` | object | `{font_size: 12}` | 表格 |
| `formatting.caption` | object | `{font_size: 10, align: center}` | 圖說 |
| `page_size` | enum | `A4 \| Letter \| Legal \| JIS-B5` | 紙張 |
| `margins` | object | `{top: 2.5cm, bottom: 2.5cm, left: 3cm, right: 2cm}` | 單位 cm |
| `line_spacing` | float | `1.0 \| 1.5 \| 2.0` | APA=2.0、IEEE=1.0、預設 1.5 |
| `language_variant` | enum | `zh-TW \| zh-CN \| en-US \| en-GB` | 語言變體 |
| `citation_style` | enum | `APA \| MLA \| Chicago \| GBC \| none` | 引用格式 |
| `output.docx_engine` | enum | `pandoc \| python-docx` | DOCX 引擎 |

**共 17 個 required 欄位**。缺任一 → BLOCKING。

---

## 3. Optional 欄位（建議填，不會 BLOCKING）

| Key | Type | 預設 | 備註 |
|-----|------|------|------|
| `output.tagged_pdf` | bool | `false` | 啟用 WCAG tagged PDF |
| `output.embed_fonts` | bool | `true` | PDF 字體嵌入（建議開） |
| `metadata.title` | string | — | 報告標題 |
| `metadata.author` | string | — | 作者 |
| `metadata.abstract` | string | — | 摘要 |
| `metadata.date` | string | — | 報告日期 (ISO 8601) |
| `sections` | list | `[]` | 章節大綱（path + title） |
| `assets.csl_file` | string | `APA.csl` | CSL 引用樣式檔 |
| `assets.bib_file` | string | `references.bib` | BibTeX 檔 |

---

## 4. Schema 版本

`schema_version: 1`（v1 對應 SPEC.md v0.3）。未來 schema 變更遞增版本號，向下相容。

---

## 5. OK 範例

```markdown
---
schema_version: 1
fonts:
  cjk: 標楷體
  latin: Times New Roman
formatting:
  cover: {font_size: 22, bold: true, align: center}
  toc: {font_size: 20}
  title: {font_size: 22, bold: true, align: center}
  h1: {font_size: 18, bold: true}
  h2: {font_size: 16, bold: true}
  h3: {font_size: 14, bold: true}
  body: {font_size: 12, line_spacing: 1.5}
  table: {font_size: 12}
  caption: {font_size: 10, align: center}
page_size: A4
margins: {top: 2.5cm, bottom: 2.5cm, left: 3cm, right: 2cm}
line_spacing: 1.5
language_variant: zh-TW
citation_style: APA
output:
  docx_engine: pandoc
  embed_fonts: true
metadata:
  title: 範例學術論文
  author: Zero
  date: 2026-06-13
---

# report_lock.md

> 機器執行合同（demo-academic）
> 產生時間：2026-06-13 12:34:56
```

✅ 17 個 required 欄位齊備。Strategist 通過，Executor 可讀。

---

## 6. BLOCKING 範例（缺 `citation_style` + `output.docx_engine`）

```markdown
---
schema_version: 1
fonts:
  cjk: 標楷體
  latin: Times New Roman
formatting:
  cover: {font_size: 22, bold: true, align: center}
  toc: {font_size: 20}
  title: {font_size: 22, bold: true, align: center}
  h1: {font_size: 18, bold: true}
  h2: {font_size: 16, bold: true}
  h3: {font_size: 14, bold: true}
  body: {font_size: 12, line_spacing: 1.5}
  table: {font_size: 12}
  caption: {font_size: 10, align: center}
page_size: A4
margins: {top: 2.5cm, bottom: 2.5cm, left: 3cm, right: 2cm}
line_spacing: 1.5
language_variant: zh-TW
# ← citation_style 缺失（BLOCKING）
output:
  # ← docx_engine 缺失（BLOCKING）
  embed_fonts: true
---

# report_lock.md
```

❌ Strategist 回報：

```
[BLOCKING] report_lock.md 缺少以下 required 欄位：
  - citation_style
  - output.docx_engine
請補齊後重跑 Stage 1。
```

---

## 7. 程式讀寫

讀寫由 `scripts/report_lock.py` 提供：

```python
from scripts.report_lock import read_lock, write_lock, validate_lock

data = read_lock("path/to/report_lock.md")
validate_lock(data)               # raises LockMissingFieldsError if BLOCKING
write_lock("path/to/report_lock.md", data)   # 保留 Markdown 註解
```

`validate_lock()` 對 required 欄位逐一檢查，缺一即 raise `LockMissingFieldsError`，列出缺失欄位名稱。

---

## 8. 與 SPEC.md 的關係

本 schema 是 SPEC.md §3.4.1 + §6.1 R1.1 + §6.2 R2 的**機器可讀落地**。SPEC.md 改字體規則時，本檔 + `scripts/report_lock.py` 必須同步更新。

---

*report_lock_schema.md v1 — 對應 SPEC.md v0.3, 2026-06-13*
