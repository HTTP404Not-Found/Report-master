# templates/reference/ — DOCX reference template

> 對應 architecture.md §介面定義 (`templates/reference/report-master-template.docx`)
> Track B 範圍：建檔 + 程式化產生器 + 驗證。

`report-master-template.docx` 是 pandoc HTML→DOCX 的 reference docx，
預先鎖死字體與樣式（讓 `scripts.html_to_docx` 透過 `--reference-doc=` 套用）。

## 字體鎖死規則（由 `scripts/build_template.py` 寫入）

- CJK 字體 = **標楷體**
- Latin 字體 = **Times New Roman**
- 章節樣式 H1=22pt / H2=18pt / H3=14pt（皆粗體）
- Normal 樣式 = 12pt / 行距 1.5
- Caption 樣式 = 10pt / 置中
- Title 樣式 = 22pt / 粗體 / 置中（封面用）

## 如何產生 reference.docx

**全自動**：

```bash
python -m scripts.build_template \
  --output templates/reference/report-master-template.docx
```

預設 type=`academic`（學術論文封面）。支援五種封面 placeholder：

| type | 用途 |
|------|------|
| `academic` | 學術論文（Author / Affiliation / Date） |
| `business` | 商業報告（Department / Report ID / Date） |
| `spec` | 技術規格書（Product / Version / Author / Date） |
| `gov` | 政府公文（Agency / Doc No. / Date） |
| `custom` | 自訂（最通用 placeholder） |

範例：

```bash
# 商業報告
python -m scripts.build_template --output /tmp/biz.docx --type business

# 自訂封面標題
python -m scripts.build_template --output /tmp/x.docx --type custom \
  --cover-title "Q3 季度回顧" \
  --cover-line "Author: wai" \
  --cover-line "Team: Platform"
```

CLI help：

```bash
python -m scripts.build_template --help
```

## 客製化

想改 defaults（字體、字級、行距、封面 placeholder）？改 `scripts/build_template.py` 的：

- `DEFAULT_CJK_FONT` / `DEFAULT_LATIN_FONT`（檔案最上方）
- `HEADING_SIZES_PT` / `BODY_SIZE_PT` / `CAPTION_SIZE_PT` / `TITLE_SIZE_PT`
- `BODY_LINE_SPACING`
- `COVER_PLACEHOLDERS`（新增 type 也加這裡）

然後重跑上面那行 CLI 即可（會覆寫 `report-master-template.docx`）。

## 環境變數覆寫

若 `report-master-template.docx` 不在本目錄，可透過環境變數指定：

```bash
export REPORT_MASTER_REFERENCE_DOCX=/path/to/your/reference.docx
python -m scripts.html_to_docx input.html -o output.docx
```

`html_to_docx.py` 會自動偵測：

1. `$REPORT_MASTER_REFERENCE_DOCX`（最高優先）
2. `<project>/templates/reference/report-master-template.docx`
3. pandoc 內建 default（fallback；字體不會自動套用 Report-master 規範）

## 驗證

裝好 template 後，跑 smoke test：

```bash
# 1. 重新產生
python -m scripts.build_template --output templates/reference/report-master-template.docx

# 2. 驗證 template 自身（字體 + mammoth round-trip）
.venv/bin/python scripts/docx_validator.py templates/reference/report-master-template.docx

# 3. end-to-end：HTML → DOCX + 驗
python -m scripts.report_gen --source examples --output /tmp/rm-test --lock examples/lock.md
.venv/bin/python scripts/docx_validator.py /tmp/rm-test/report_*.docx
```

預期 `cjk_font` 與 `latin_font` checks 顯示 `passed: True`。

## Track B 不做的事

- ❌ 不自動下載 / 安裝 reference.docx
- ❌ 不自動 bundle 標楷體 / Times New Roman（見 `fonts/README.md`）
- ❌ 不手動建 template（過去曾建議用 Word / LibreOffice 開 pandoc default 改；現已全面改為 `scripts/build_template.py` 程式化產生）

*templates/reference/README.md v2 — T2-2 程式化產生器, 2026-06-13*