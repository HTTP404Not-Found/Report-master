# templates/reference/ — DOCX reference template (placeholder)

> 對應 architecture.md §介面定義 (`templates/reference/report-master-template.docx`)
> Track B 範圍：建立目錄結構 + README 說明。實際 .docx 由 Track A 或使用者手動產出。

## 為什麼需要 reference.docx

pandoc HTML→DOCX 預設使用 Calibri / Times New Roman / Consolas 等系統字體，
但 Report-master 規定：

- CJK 字體 = **標楷體**（鎖死）
- Latin 字體 = **Times New Roman**（鎖死）
- 章節樣式（H1-H3）對齊 `report_lock.md` 的 `formatting.h1/h2/h3`

要讓 pandoc 產出的 DOCX 自動套用這些規則，需預先建立一份 reference.docx
並透過 `pandoc --reference-doc=<file>` 指定。

## 如何產生 reference.docx

### 方法 A：用 pandoc 自身（最快）

```bash
pandoc -o report-master-template.docx \
  --print-default-data-file=reference.docx \
  /dev/null
```

然後用 Word / LibreOffice 開啟，修改：

1. **字體**：Normal 樣式 → 中文標楷體 / Latin Times New Roman / 12pt / 行距 1.5
2. **Heading 1**：標楷體 / 18pt / 粗體
3. **Heading 2**：標楷體 / 16pt / 粗體
4. **Heading 3**：標楷體 / 14pt / 粗體
5. **Caption**：10pt / 置中
6. **Table**：12pt
7. 儲存為 `report-master-template.docx`，放在本目錄

### 方法 B：用 python-docx（程式化）

見 `scripts/html_to_docx_direct.py` TODO — 平行路徑完工後可一鍵生成。

### 方法 C：從 LibreOffice 範本匯出

1. 用 LibreOffice Writer 建立樣板
2. 設定字體與段落樣式（同上）
3. File → Templates → Save as Template
4. 匯出為 .docx

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

裝好 reference.docx 後，跑 smoke test：

```bash
python -m scripts.report_gen --source examples --output /tmp/rm-test --lock examples/lock.md
.venv/bin/python scripts/docx_validator.py /tmp/rm-test/report_*.docx
```

預期 `cjk_font` 與 `latin_font` checks 顯示 `passed: True`。

## Track B 不做的事

- ❌ 不自動下載 / 安裝 reference.docx（每個團隊的字體授權不同）
- ❌ 不自動 bundle 標楷體 / Times New Roman（見 `fonts/README.md`）

*templates/reference/README.md v1 — Track B placeholder, 2026-06-13*