---
name: report-master
description: Generate professional PDF + DOCX reports from Markdown / HTML sources via the report-master pipeline. Use when the user asks to "生成報告書", "做 PDF 報告", "做 DOCX 報告", "從 Markdown 出報告", "make a report", "compile report", or wants a structured deliverable (academic paper, business proposal, spec, government document). Runs Stage 0 (source probe) → Stage 1 (lock contract) → Stage 2 (per-section HTML generation + quality gate) → Stage 3 (PDF + DOCX parallel render). Do NOT use for slide decks (use ppt-master) or short notes.
---

# SKILL.md — Report-master 主 workflow authority

> **文件版本：v1.0** · 對應 SPEC.md v0.3 + architecture.md v1.0 · 2026-06-13
> **Reference**：reverse-engineer-ppt-master（相似設計哲學；HTML 中間格式 vs SVG 中間格式）
> **Inherits**：Spec-Lock anti-drift、role specialization (Strategist / Executor)、per-section quality gate、examples as integration tests。

---

## 1. 何時使用本 skill

下列任一觸發詞 → 啟動 report-master：

| 觸發詞（中） | 觸發詞（英） |
|--------------|--------------|
| 生成報告書 / 寫一份報告 / 出報告 | generate report / make a report / write up |
| 做 PDF 報告 / 轉 PDF | PDF report / compile to PDF |
| 做 DOCX 報告 / 轉 Word | DOCX report / Word version |
| 從 Markdown 出報告 | Markdown to report |
| 學術論文 / 商業提案 / 規格書 / 政府公文 | academic paper / business proposal / spec / gov doc |

**反例**（不要用本 skill）：

- 簡報 / slides → 用 `ppt-master`
- 短筆記 / blog → 直接 Markdown 渲染即可
- 純資料 dump → 用 Markdown table

---

## 2. Pipeline（Stage 0 → Stage 1 → Stage 2 → Stage 3）

```
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 0 — Format Probe + Source Ingestion (Track A)                  │
│   接收 PDF/DOCX/URL/Markdown/純文字                                   │
│   ↓ source_to_md/* 統一為 normalized.md                              │
│   ↓ Format Probe 推斷 report_type (academic/business/spec/gov)         │
├──────────────────────────────────────────────────────────────────────┤
│ Stage 1 — 規劃（Strategist + 10 Confirmations + report_lock.md）      │
│   project_manager.py init  ← Track A                                 │
│   Strategist 角色：10 確認對話                                        │
│     1. 格式類型  2. 輸出語言 + 引用  3. 目標讀者  4. 報告標題+子標題   │
│     5. 章節數量  6. 圖表需求  7. 附錄  8. 輸出格式偏好                │
│     9. page_size + margins + line_spacing + language_variant（升級） │
│    10. citation_style + CSL 引用樣式                                 │
│   寫入 report_lock.md (YAML frontmatter + Markdown 註解)             │
├──────────────────────────────────────────────────────────────────────┤
│ Stage 2 — AI 內容生成（Executor 逐節 HTML + quality gate）            │
│   對每一節：                                                          │
│     重讀 report_lock.md (防 formatting drift)                        │
│     重讀 glossary.md (防 narrative drift)                            │
│     Executor 生成該節 HTML（內聯樣式優先）                            │
│     quality_checker.py 過門（per-section gate）                       │
│       → PASS: 寫入 report_output/section_N.html                      │
│       → BLOCKING: 列出禁用清單命中項；重做                            │
├──────────────────────────────────────────────────────────────────────┤
│ Stage 2.5 — 迭代（可選，人類 review → v_n+1）                          │
│   delta_checker.py 對 report_v_n vs v_n+1 做 section-level diff      │
│   選定 section IDs 重跑 Stage 2                                      │
├──────────────────────────────────────────────────────────────────────┤
│ Stage 3 — 工程轉換（PDF + DOCX 平行）                                 │
│   並行：                                                             │
│     html_to_pdf.py (weasyprint + fonts/ 嵌入)                        │
│     html_to_docx.py (pandoc + reference docx)                        │
│   docx_validator.py 抽樣驗字體/樣式（mammoth round-trip）             │
│   export_checker.py post-export 檢查（頁數/字體/圖片/連結）           │
│   產出 exports/report_<ts>.pdf + exports/report_<ts>.docx            │
│   存檔 backup/<ts>/report_output/                                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 與 `scripts/report_gen.py` 的呼叫協議

主 entry point 是 `python -m scripts.report_gen`，三種使用情境：

### 3.1 全自動（Stage 2 + 3）

```bash
python -m scripts.report_gen \
  --source <input_dir|input.html> \
  --output <exports_dir> \
  --lock <report_lock.md>
```

行為：
1. 讀 `report_lock.md` → 校驗 required 欄位（缺 → BLOCKING）
2. 對每節 HTML 跑 `quality_checker.py`
3. 平行跑 `html_to_pdf.py` 與 `html_to_docx.py`
4. 跑 `export_checker.py` 驗收
5. PASS → 寫入 `exports/report_<ts>.{pdf,docx}`；FAIL → 非零退出 + reason

### 3.2 只跑 Stage 3（HTML 已生成，只轉 PDF/DOCX）

```bash
python -m scripts.report_gen render \
  --html <bundle.html> \
  --output <exports_dir> \
  --format pdf,docx
```

### 3.3 只跑 Stage 2（生成 HTML）

```bash
python -m scripts.report_gen generate \
  --lock <report_lock.md> \
  --sections <id,id,...> \
  --output <report_output_dir>
```

---

## 4. Stage 2.5 迭代迴圈觸發條件

| 條件 | 動作 |
|------|------|
| 人類對 v1 不滿意 | 選定 section IDs，產 v2 |
| 字體/顏色偏離 lock | quality_checker 自動 BLOCKING，重生該節 |
| 圖表編號不連續 | quality_checker BLOCKING，重生該節 |
| 交叉引用 broken | quality_checker BLOCKING，重生該節 |
| 大改（>30% 內容） | 回到 Stage 1 重跑 Strategist |

`delta_checker.py` 永遠保留 `report_v_n.html` 不覆蓋。

---

## 5. 與其他 workflow 的關係

```
                       ┌──────────────┐
                       │ topic-research│ ← 無源材料時啟動
                       └──────┬───────┘
                              ↓
┌─────────────────────┐   ┌─────────┐   ┌──────────────────────┐
│ create-template      │──→│  本 skill │←──│ resume-execute       │
│ (範本生成)            │   │ report-  │   │ (斷點續傳)            │
└─────────────────────┘   │ master   │   └──────────────────────┘
                          └────┬─────┘
                               │
                ┌──────────────┼──────────────┐
                ↓              ↓              ↓
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │generate-     │ │ live-preview │ │ visual-review│
        │citations     │ │ (HTML 即時預覽)│ │ (可選視覺自查) │
        └──────────────┘ └──────────────┘ └──────────────┘
```

- `generate-citations`：Stage 1 期間呼叫，建立/更新 BibTeX + CSL
- `live-preview`：Stage 2 期間呼叫，逐節瀏覽器預覽
- `visual-review`：Stage 3 之前可選跑，PDF 截圖自查
- `resume-execute`：Stage 2/3 斷點續傳

---

## 6. 兩個 AI 角色

### Strategist（規劃者）

**何時啟動**：Stage 1。

**職責**：
- 與使用者進行 **10 Confirmations 對話**（見 SPEC §3.3 + REVIEW R2）
- 寫入 `report_lock.md`（YAML）與 `report_spec.md`（大綱）
- 拒絕產出 lock 若 required 欄位缺失（BLOCKING）

**不做**：不會寫 HTML、不會調用 weasyprint、不會 review 內容品質。

**詳細 workflow**：見 `references/strategist.md`（T3-1）。
- 10 個問題的 BLOCKING / WARN 條件
- 對話流程 Mermaid 圖
- 5 種範本（academic / business / spec / gov / custom）對齊 `scripts/project_manager.py`
- CLI helper：`python -m scripts.strategist --template <type> --output <path>`

### Executor（執行者）

**何時啟動**：Stage 2。

**職責**：
- 每節開工前重讀 `report_lock.md` + `glossary.md`
- 依 `executor-base.md` 規則生成該節 HTML（內聯樣式優先）
- 提交 `quality_checker` 過門；不通過則修正重提

**不做**：不會改 `report_lock.md`、不會跑 Stage 3 轉換、不會跨節並行 sub-agent（敘事必漂移）。

---

## 7. `report_lock.md` 引用規則

任何時候 Executor 寫 HTML 之前：

1. **必須重讀** `report_lock.md`（防止格式化漂移）
2. **必須重讀** `glossary.md`（防止術語漂移）
3. **必須遵循** `shared-standards.md`（HTML/CSS 子集）

`report_lock.md` 17 個 required 欄位若任一缺失：

- Strategist：拒絕產出 lock
- Executor：拒絕生成（raise `LockMissingFieldsError`）

---

## 8. 與 ppt-master 的差異（明確聲明）

| 維度 | ppt-master | report-master |
|------|------------|---------------|
| 輸出 | PPTX | **PDF + DOCX**（雙交付物） |
| 中間格式 | SVG | **HTML** |
| AI 單位 | 每頁 | **每節** |
| 章節 | 投影片 | **章節（封面→目次→正文→參考文獻）** |
| 編號 | 投影片 # | **章節 / 圖表 / 公式編號** |
| 引用 | 無 | **APA / MLA / Chicago / GBC** |
| 引用支援 | N/A | **pandoc `--citeproc` + CSL** |
| 公式 | Chart.js | **KaTeX server-side PNG** |
| 防 drift | spec_lock.md | **report_lock.md**（17 required 欄位） |
| 字體 | 品牌字體 | **標楷體 + Times New Roman（鎖死）** |

`reverse-engineer-ppt-master` skill 中的 446 行 `error_helper.py` 與 `update_spec.py` 模式本 skill 直接採用（見 `scripts/error_helper.py` 與 `scripts/update_spec.py`）。

---

## 9. Stage 3 驗收 checklist（export_checker.py）

每份報告產出後自動跑：

- [ ] PDF 可開啟（PyMuPDF 解析無例外）
- [ ] PDF 字體已嵌入（至少含標楷體 / Times New Roman 任一）
- [ ] PDF 頁數 > 0
- [ ] DOCX 可開啟（zip + word/document.xml 解析無例外）
- [ ] DOCX 含 `[Content_Types].xml`
- [ ] DOCX 含 `word/document.xml` 且至少 1 段
- [ ] 目次連結（PDF bookmark 或 DOCX TOC field）有效

任何一項失敗 → 整份報告 **PASS=false**，main agent 收到 reason 清單。

---

## 10. 失敗 / 求助指引

| 症狀 | 原因 / 處理 |
|------|-------------|
| `LockMissingFieldsError` | 補 report_lock.md 欄位後重跑 Stage 1 |
| `QualityCheckError: display: flex` | 改用 block flow（見 shared-standards.md §3） |
| `FontNotFoundError: 標楷體` | 見 `fonts/README.md` 安裝指引；或 `apt install fonts-noto-cjk` |
| `PandocNotFoundError` | `apt install pandoc` 或下載 binary；見 `docs/.env.example` |
| `MMDCNotFoundError` | `npm install -g @mermaid-js/mermaid-cli`；或允許 Stage 2 保留 `<pre class="mermaid">` 待後處理 |
| `KaTeXNotFoundError` | 同上；可選 |
| `ExportCheckFailed: page count=0` | weasyprint 渲染失敗；檢查 HTML 結構與字體路徑 |

---

## 11. 版本演進

| 版本 | 狀態 | 說明 |
|------|------|------|
| v0.0 | done | placeholder |
| v1.0 | **current** | Track B 完工：report_gen + quality_checker + html_to_* + validators + checkers + renderers + tests + examples |
| v1.1 | planned | Stage 2.5 迭代 UI；mermaid/katex CLI 自動安裝 |
| v2.0 | TBD | Stage 4 / pipeline-as-service；multi-locale |

---

*SKILL.md v1.0 — 對應 SPEC.md v0.3 + architecture.md v1.0, 2026-06-13*