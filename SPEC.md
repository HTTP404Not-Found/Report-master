# Report-master — SPEC.md

> Status: DRAFT v0.3 | Date: 2026-06-13 | Review: integrated sub-agent review + wai font/DOCX hardening
> Owner: Zero (wai's AI agent)
> Reference: reverse-engineer-ppt-master skill

---

## 1. Concept & Vision

**Report-master** 是 AI-driven 的報告書生成系統，類似 ppt-master 但輸出格式為**專業報告書**（PDF / DOCX），而非簡報。

核心定位：讓使用者從空白頁開始，用 90% 的 AI 協作消除報告書寫的啟動阻力，產出結構完整、排版專業、可直接交付的報告書。

**與 ppt-master 的核心差異**：

| 維度 | ppt-master | Report-master |
|---|---|---|
| 輸出格式 | PPTX（單一格式） | PDF + DOCX（雙格式標配） |
| 內容結構 | 自由形式投影片 | 強制結構章節（封面→目錄→正文→參考文獻） |
| AI 生成單位 | 每頁 SVG | 每節 HTML / Markdown |
| 中間格式 | SVG | HTML（或 Markdown） |
| 工程轉換 | SVG → DrawingML（Python） | HTML → PDF（weasyprint）+ HTML → DOCX（pandoc） |
| 模板系統 | 投影片佈局 + 品牌 | 報告書結構範本（學術論文 / 商業提案 / 規格書 / 政府公文） |
| 頁碼 / 編號 | 投影片編號 | 章節編號、圖表編號、公式編號、引用文獻 |
| 特殊元素 | 動畫、圖表座標 | 註腳、交叉引用、參考文獻文、目次 |

---

## 2. 設計哲學

### 2.1 AI as Report Designer, Not Finisher

報告書比簡報更接近「正式文件」——有結構慣例（封面、目次、參考文獻）、有引用規範（APA / MLA / Chicago）、有排版標準（行距、縮排、頁眉頁腳）。AI 處理結構規劃、內容生成、格式建議，人類負責最終校對和專業判斷。

### 2.2 技術選型：中間格式 = HTML

選擇理由：
1. **LLM 生成可靠性**：HTML 是 AI 訓練數據中最豐富的標記格式之一，可靠性遠高於 DOCX XML 或 PDF
2. **雙格式轉換成熟**：HTML → PDF（weasyprint）品質極佳；HTML → DOCX（pandoc）保留樣式結構
3. **世界觀一致**：HTML 的 block-level / inline model 與 PDF / DOCX 的排版模型相近
4. **調試直觀**：任何瀏覽器直接預覽，人類可讀

**不放棄的路**：不直接生成 DOCX XML（太複雜）/ 不直接生成 PDF（不可編輯）/ 不直接生成 Markdown（PDF 轉換依賴 pandoc + weasyprint，效果不如 HTML 直接轉）

### 2.3 Pipeline 形態

同 ppt-master 的 serial pipeline，但 stage 方向不同：

```
輸入（PDF/DOCX/URL/Markdown/純文字）
    ↓
Stage 1: 內容理解 & 結構規劃
    ├── 格式轉換 → Markdown
    ├── 專案初始化
    └── Strategist：章節大綱規劃 + Eight Confirmations（報告書版）
         ├── report_spec.md（人類可讀）
         └── report_lock.md（機器執行合同，防 drift）
    ↓
Stage 2: AI 内容生成
    └── Executor：逐節生成 HTML
         ├── report_output/（HTML 源文件）
         ├── quality_checker（質量門禁）
         └── footnote/ref_manager（註腳/引用管理）
    ↓
Stage 3: 工程轉換
    ├── html_to_pdf.py（weasyprint）
    └── html_to_docx.py（pandoc）
         ↓
    exports/
    ├── report_<timestamp>.pdf（主要交付格式）
    ├── report_<timestamp>.docx（編輯用格式）
    └── backup/<ts>/report_output/（HTML 源存檔）
```

---

## 3. 系統架構決策

### 3.1 Eight Confirmations（報告書版）

不同於投影片的 8 個確認，報告書的確認點：

1. **格式類型**：學術論文 / 商業提案 / 技術規格書 / 政府公文 / 書籍章節
2. **輸出語言** + **引用規範**：中文 + APA？英文 + MLA？無引用？
3. **目標讀者**：主管 / 審查委員 / 客戶 / 公众
4. **報告標題 + 子標題**
5. **章節數量範圍**：章節深度
6. **圖表需求**：需要哪些圖表（流程圖、架構圖、數據圖）？
7. **附錄需求**：代碼清單、數據字典、訪談大綱？
8. **輸出格式偏好**：PDF 優先 / DOCX 優先 / 雙格式

### 3.2 report_lock.md（防 drift 機制）

等同於 ppt-master 的 `spec_lock.md`：
- 機器可讀執行合同
- 包含：字體 family、字體大小、颜色 scheme、行距、頁面尺寸、圖表樣式、引用格式
- **每節重新讀一次**，防止長報告書的字體/颜色漂移
- **字體與排版欄位均為 required**（依 § 3.4.1）：中文字體固定為標楷體、英文字體固定為 Times New Roman、封面 / 主標題 / H1-H3 / 內文 / 表格 / 圖說的字級與樣式不得為空

### 3.3 模板系統（報告書結構範本）

三種 kind（類比 ppt-master）：

| Kind | 內容 | 範例 |
|---|---|---|
| **structure** | 章節結構大綱（目次的章節層次） | 商業提案：執行摘要→背景→方案→效益→時程→預算 |
| **format** | 排版格式（字體/行距/縮排/頁眉頁腳） | APA 第7版格式 |
| **full** | structure + format + 示例內容 | 亞洲大學論文格式 |

**觸發規則**：同 ppt-master，只有顯式目錄路徑才激活模板流。

### 3.4 特殊元素處理

| 元素 | 處理方式 |
|---|---|
| **目次（TOC）** | `tocgen` 或 Pandoc 自動產生，置於第一章之前 |
| **註腳（footnote）** | HTML `<sup><a href="#fnN">N</a></sup>` + `<aside id="fnN">`，PDF/DOCX 轉換時保留 |
| **交叉引用** | Markdown/Pandoc 語法 `[{#sec:intro}]` → PDF bookmark + DOCX cross-ref |
| **參考文獻** | CSL + YAML metadata → Bibliographic entries（csl + bib 文件） |
| **圖表編號** | `Figure N`, `Table N`, `Equation N` — 由 executor 寫入，quality checker 驗證 |
| **附錄** | 特殊章節，不計入主要章節編號 |
| **頁眉頁腳** | 報告書特定：章節名（左）/ 報告名（中）/ 頁碼（右） |

#### 3.4.1 字體與排版規定（硬性規則 · MANDATORY）

以下字體與排版規則為 **強制規定（required）**，非可選建議。從第一天起即寫入 `report_lock.md` schema 並由 Executor / Converter 全鏈路遵守：

| 元素 | 字體（中/英） | 字級 | 其他 |
|---|---|---|---|
| **封面（第一頁）** | 標楷體 / Times New Roman | 22pt | **粗體、置中對齊** |
| **表目錄（TOC）** | 標楷體 / Times New Roman | 20pt | — |
| **主標題** | 標楷體 / Times New Roman | 22pt | **粗體、置中對齊** |
| **H1 層級** | 標楷體 / Times New Roman | 18pt | **粗體** |
| **H2 層級** | 標楷體 / Times New Roman | 16pt | **粗體** |
| **H3 層級** | 標楷體 / Times New Roman | 14pt | **粗體** |
| **內文（body）** | 標楷體 / Times New Roman | 12pt | 行距 1.5 |
| **表格內容** | 標楷體 / Times New Roman | 12pt | — |
| **圖說（caption）** | 標楷體 / Times New Roman | 10pt | **置中對齊** |

**字體鎖定（不可變更）**：

- **中文字體**：標楷體（DFKai-SB / KaiTi / 系統對應字）— 固定，不允許在 `report_lock.md` 中覆寫為其他中文字體
- **英文字體**：Times New Roman — 固定，不允許覆寫為 Calibri / Arial / 其他西文 sans-serif

**Schema 強制性**：`report_lock.md` 必須包含以下 required 欄位，未提供時 Strategist 拒絕產出 lock 並 BLOCKING 詢問：

```yaml
fonts:
  cjk: 標楷體            # required, fixed
  latin: Times New Roman  # required, fixed
formatting:
  cover: { font_size: 22, bold: true, align: center }
  toc: { font_size: 20 }
  title: { font_size: 22, bold: true, align: center }
  h1: { font_size: 18, bold: true }
  h2: { font_size: 16, bold: true }
  h3: { font_size: 14, bold: true }
  body: { font_size: 12, line_spacing: 1.5 }
  table: { font_size: 12 }
  caption: { font_size: 10, align: center }
```

**quality_checker 驗證項**：產出後必須逐節驗證上述規則（取樣 3 處內文 + 所有 H1/H2 + 至少 1 個表格 + 至少 1 個圖說），違規計為 **BLOCKING** 錯誤。

---

## 4. 文件結構（規劃）

```
report-master/
├── AGENTS.md                    ← 入口，general AI agent 讀
├── SPEC.md                      ← 本文件
├── SKILL.md                     ← 主 workflow authority
├── skills/report-master/
│   ├── SKILL.md
│   ├── workflows/
│   │   ├── topic-research.md    ← 無源材料時：網絡搜集
│   │   ├── create-template.md   ← 創建結構/格式範本
│   │   ├── resume-execute.md   ← Phase B 断点续传
│   │   ├── generate-citations.md← 引用管理 workflow
│   │   ├── live-preview.md     ← HTML 实时预览
│   │   └── visual-review.md    ← 可选的视觉自查
│   ├── references/
│   │   ├── strategist.md       ← Strategist 角色定義
│   │   ├── executor-base.md    ← Executor 通用指南
│   │   ├── shared-standards.md ← HTML/CSS 約束（哪些 HTML 特性轉換後丟失）
│   │   ├── report-formats.md    ← 格式類型定義（學術/商業/規格/公文）
│   │   ├── citation-formats.md  ← 引用格式（APA/MLA/Chicago/GBC）
│   │   └── toc-guide.md        ← 目次生成規則
│   ├── scripts/
│   │   ├── source_to_md/        ← 格式轉換（PDF/DOCX/HTML/URL）
│   │   ├── project_manager.py  ← 專案初始化
│   │   ├── config.py           ← 配置管理
│   │   ├── report_gen.py       ← 主生成器（HTML 輸出）
│   │   ├── quality_checker.py   ← 報告書質量檢查
│   │   ├── toc_generator.py    ← 目次生成
│   │   ├── footnote_manager.py ← 註腳/引用管理
│   │   ├── html_to_pdf.py      ← HTML → PDF（weasyprint）
│   │   ├── html_to_docx.py     ← HTML → DOCX（pandoc）
│   │   └── update_spec.py      ← 變更傳播工具
│   └── templates/
│       ├── structures/          ← 結構範本
│       ├── formats/            ← 排版格式範本（APA/chicago/...)
│       └── full/               ← 完整範本包
├── docs/
│   ├── technical-design.md     ← 技術設計文檔
│   └── rules/                  ← 風格規則
└── examples/                   ← 23+ 個完整 example reports
```

---

## 5. Phase 1 開發計劃（本次）

### 5.1 核心模組優先序

```
第1批（MVP）：
  1. project_manager.py      — 專案初始化 + 目錄結構
  2. config.py              — 配置管理（.env 加載鏈）
  3. source_to_md/*.py      — 格式轉換（至少支援 PDF + DOCX + URL）
  4. report_gen.py（核心）   — HTML 生成引擎
  5. quality_checker.py      — 質量門禁

第2批：
  6. html_to_pdf.py         — PDF 轉換
  7. html_to_docx.py        — DOCX 轉換
  8. toc_generator.py       — 目次自動產生
  9. footnote_manager.py    — 註腳處理

第3批：
  10. Strategist workflow   — Eight Confirmations + report_spec.md/report_lock.md
  11. Executor workflow     — 逐節生成 + quality gate
  12. SKILL.md 主流程        — Stage 1 → 2 → 3 串聯
  13. 模板系統               — structures/formats/full
  14. live-preview workflow — HTML 实时预览
  15. examples/             — 3 個完整示例
```

### 5.2 關鍵技術決策待確認

| 決策點 | 選項 | 建議 |
|---|---|---|
| PDF 轉換引擎 | weasyprint / pdfkit / playwright | weasyprint（CSS 支援最好） |
| DOCX 轉換引擎 | pandoc / mammoth / python-docx | pandoc（HTML→DOCX 品質最佳） |
| 中間 HTML 樣式 | 純 CSS / Tailwind CDN / 內聯樣式 | 內聯 + 少量 CSS（便於 weasyprint） |
| 引用管理 | pandoc-citeproc /bibtex / CSL | pandoc-citeproc + CSL（支援廣） |
| 圖表渲染 | Mermaid / Chart.js / 純 SVG | Mermaid（流程圖/架構圖）+ Chart.js（數據圖） |
| 章節編號 | HTML5 outline / 手動寫入 | 手動寫入（quality checker 驗證） |

---

## 6. 架構風險與修正（v0.2 Review 結果）

### R1. HTML → DOCX fidelity is lossy
Pandoc's HTML→DOCX 會丟失 CSS Grid/Flex/positioning/::before/::after。**Fix**: 在 `shared-standards.md` 定義 HTML 子集（僅支援 `<table>`, `<img>`, `<h1-h6>`, `<sup>`, `<aside>`, lists, `<p>/<div>`），禁止 CSS Grid/Flex/positioning；使用 `--reference-doc=custom.docx` 做品牌一致性。

#### R1.1 DOCX Fidelity Hardening（必執行的 5 項具體措施）

針對中文報告書場景（DOCX 為主要交付格式），HTML → DOCX 的格式忠實度是 **#1 風險點**。下列措施為強制要求，從 Stage 3 `html_to_docx.py` 開始即實現：

**a) 禁用 CSS positioning / flexbox / grid**
   - 在 `shared-standards.md` 明確列為 **禁止**：不允許 `display: flex`、`display: grid`、`position: absolute/fixed`、`float`（除 `<img>` 標準用法）
   - quality_checker 對生成的 HTML 做 CSS 掃描，發現禁用規則計為 **BLOCKING**
   - 採用傳統 block flow（`<div>`, `<p>`, `<table>`, `<section>`, headings）保證 pandoc 可映射為 DOCX 段落

**b) 僅使用 pandoc 保留的最小 CSS 子集 + 內聯樣式**
   - 允許：`font-family`, `font-size`, `font-weight`, `color`, `text-align`, `line-height`, `margin`, `padding`, `border`, `text-decoration`
   - 重要樣式（如標題、封面、表格）優先採 **內聯 style**（`style="font-family: '標楷體'; font-size: 22pt; ..."`），不依賴外部 CSS 命中
   - pandoc 的 `--css=` 參數效果不穩，**避免使用**，所有樣式都進 HTML 本身

**c) Reference DOCX template 預載字體定義**
   - 提供 `templates/reference/report-master-template.docx`：
     - 預載字體樣式：`Body Text` → Times New Roman 12pt、`Heading 1-3` → 標楷體粗體（依 § 3.4.1 規格）
     - `Normal.dotm` style mapping：標楷體為 CJK mainfont、Times New Roman 為 Latin mainfont
   - `html_to_docx.py` 始終呼叫 `pandoc --reference-doc=templates/reference/report-master-template.docx`
   - template 本身由 `templates/reference/build_template.py` 從 python-docx 生成（避免手改 docx 損壞）

**d) Post-processing DOCX 驗證步驟**
   - pandoc 轉換後，呼叫 `docx_validator.py`（基於 `python-docx` 或 `mammoth`）：
     1. 打開 DOCX 確認無損壞
     2. 驗證 key 樣式存在：`Heading 1/2/3`、封面段落、表格
     3. 抽樣讀取 3 個內文段落的 `run.font.name`，驗證 = `標楷體`（CJK）+ `Times New Roman`（Latin）
     4. 檢查表格 cell 的字體、圖說段落是否置中
     5. 任何驗證失敗 → `export_checker.py` 回報為 **BLOCKING**，要求重跑
   - 同時做 mammoth **round-trip check**：`mammoth docx → html` 後比對關鍵元素（標題數、表格數、圖片數），mismatch 警告

**e) 字體嵌入（font embedding）**
   - 在 `html_to_docx.py` 中：pandoc 指令加上 `--pdf-engine=` 對 PDF 嵌入字體（DOCX 端透過 reference template 確保字體隨文檔發佈）
   - 對 PDF：weasyprint 端呼叫 `fontconfig` 設定 `embed-fonts: true`，確保接收端無對應字體也能正確顯示
   - `fonts/` bundle 目錄（沿用 R6）包含標楷體 .ttf/.otf 與 Times New Roman，config.py 在 init 時 fail-fast 檢查

**f) 平行輸出路徑（進階選項）** — 針對 DOCX fidelity 極度敏感的場景
   - 除 pandoc 路徑外，提供 `html_to_docx_direct.py`：使用 `python-docx` 直接從結構化 HTML 段落生成 DOCX
   - 略過 pandoc mapping，**完全控制**字體、樣式、段落屬性
   - 預設關閉，由 report_lock.md 的 `output.docx_engine: python-docx | pandoc` 顯式開啟
   - 適用場景：政府公文、學術論文投稿（審稿方對格式極敏感）

**Risk level**: HIGH — 不處理等於交付出排版崩壞的 DOCX，等同產出失敗。

### R2. Eight Confirmations 缺少硬性決策
**Fix**: 擴展為 **10 Confirmations**，新增 page_size（A4/Letter/Legal/JIS-B5）、margins、line_spacing（APA=2.0, IEEE=1.0）、language_variant（zh-TW vs zh-CN）。`report_lock.md` schema 把這四項列為 **required**。

### R3. 敘事 drift 無防禦
長報告書（50+ 頁）需要：① `glossary.md`（Executor 每節先讀術語表）；② 每 5 節重新讀 `report_spec.md`；③ `quality_checker` 加入 cross-reference 驗證。

### R4. Pipeline 缺乏迭代迴圈
報告需要 v1→review→v2。**Fix**: 加入 Stage 2.5 `revise` workflow（接收 section IDs 重新生成）+ `delta_checker.py`（版本 diff）。儲存 `report_v{n}.html`，不覆蓋。

### R5. Mermaid + Chart.js 在 weasyprint 會靜默失敗
weasyprint 無 JS 引擎，Mermaid/Chart.js 會顯示原始原始碼。**Fix**: 使用 `mermaid-cli` (`mmdc`) 在 Stage 2 預先渲染為 SVG 再內嵌；圖表用 `matplotlib`/`pygal` server-side 產生 SVG；**移除 Chart.js**。

### R6. 無 CJK/字體策略
weasyprint 需要系統字體，pandoc 需要 `mainfont`/`CJKmainfont`。**Fix**: `fonts/` bundle 目錄 + `config.py` 在 init 時 fail-fast 檢查字體。

### R7. 無版本管理 / CI
**Fix**: 從第一天就規劃 `update_report.py`；以 `examples/` 為整合測試（`compileall` + quality_checker 對 3 個 examples 跑一遍）。

### R8. 無轉換後檢查
**Fix**: 加入 `export_checker.py`（頁數、圖片存在、字體 subsetting、DOCX 可正常打開、目次連結可點）。

---

### 6.2 技術棧修正

| 工具 | SPEC 選擇 | 評估 | 備選 |
|---|---|---|---|
| PDF 引擎 | weasyprint | ✅ 正確 | ≥ v60 對 CSS Grid 有部分支援 |
| DOCX 引擎 | pandoc | ✅ 正確 | 加 `mammoth` round-trip check 驗證結構 |
| 引用 | pandoc-citeproc + CSL | ⚠️ pandoc-citeproc 已廢棄 | 改用內建 `--citeproc` |
| 圖表 | Mermaid + Chart.js | ❌ weasyprint 無 JS，兩者均靜默失敗 | mermaid-cli 預渲染 SVG + matplotlib/pygal |
| 數學公式 | 未指定 | ❌ 關鍵缺口 | `katex-cli` server-side 預渲染 |
| 目次 | tocgen / pandoc | ✅ pandoc 足夠 | — |
| 註腳 | HTML `<sup><a>` + `<aside>` | ⚠️ PDF 正常；DOCX 不保留此模式 | 使用 pandoc 原生 `^[note]` Markdown 語法 |

---

### 6.3 Pipeline 修正

1. **Stage 0 新增 Format Probe**：在 Eight Confirmations 前，先檢查源材料推斷 report_type（學術/商業/規格），讓後續決策有不同的 defaults。
2. **`quality_checker` 改為 Stage 2 內的逐節 gate**：不等所有節生成完再做質量門禁，Section-level blocking 是正確粒度。
3. **Stage 3 明確為 batch（PDF + DOCX 並行執行）**：兩者獨立，並行節省時間。

### 6.4 還缺少的關注點

- **Error taxonomy & retry policy** — `error_helper.py` 等價物
- **Asset management** — 圖片放在哪、DPI 多少、授權政策
- **Concurrency stance** — 明確禁止 sections 的 parallel sub-agents
- **Diff / versioning** — v1 和 v2 之間的差異
- **Tagged PDF accessibility**（WCAG / Section 508）

---

## 7. Phase 1 開發計劃（v0.2 修正版）

```
第0批（先於一切）：
  0. report_lock.md schema         ← JSON schema for 機器執行合同
  0. shared-standards.md（HTML 子集）← 定義哪些 HTML 可安全轉換

第1批（MVP）：
  1. project_manager.py           — 專案初始化 + 目錄結構
  2. config.py                  — 配置管理（字體 fail-fast）
  3. source_to_md/*.py           — 格式轉換（PDF + DOCX + URL）
  4. html_to_pdf.py（核心）     — weasyprint HTML→PDF，極簡 CSS profile
  5. quality_checker.py          — 質量門禁（HTML 語法 + 交叉引用）

第2批：
  6. html_to_docx.py             — pandoc HTML→DOCX + mammoth round-trip check
  7. toc_generator.py            — 目次自動產生（pandoc --toc）
  8. footnote_manager.py         — pandoc 原生 ^[note] 語法
  9. mermaid_cli + 圖表渲染       — mmdc 預渲染 SVG（移除 Chart.js）

第3批：
  10. katex-cli 數學公式渲染      — server-side PNG，嵌入 HTML
  11. Strategist workflow        — 10 Confirmations + report_spec.md / report_lock.md
  12. Executor workflow         — 逐節生成 + per-section quality gate
  13. Stage 2.5 revise          — 迭代迴圈（v1→review→v2）
  14. export_checker.py          — post-export 檢查
  15. 3 個完整 examples         — 整合測試 + Demo
```

---

## 8. 與 ppt-master 的繼承 vs 差異

### 6.1 從 ppt-master 繼承

- ✅ Serial pipeline（Stage 1 → 2 → 3）
- ✅ Eight Confirmations gate（BLOCKING，單一確認點）
- ✅ spec_lock anti-drift 機制
- ✅ Role-specialized references（Strategist ↔ Executor 角色切換）
- ✅ 格式轉換層（source_to_md/*）
- ✅ quality_checker 門禁（BLOCKING error）
- ✅ `examples/` 作為集成測試
- ✅ `docs/rules/` 顯式風格規則

### 6.2 差異點（需重新設計）

- ❌ SVG 中間層 → HTML 中間層
- ❌ 動畫系統 → 註腳/交叉引用/參考文獻系統
- ❌ 投影片佈局 → 報告書結構範本
- ❌ 單一 PPTX 輸出 → PDF + DOCX 雙輸出
- ❌ 無目次/章節編號 → 強制目次 + 多級章節編號
- ❌ 無引用管理 → 強制引用格式（APA/MLA/Chicago）

---

## 7. 開源策略

建議：参考 ppt-master 經驗，預留 marketplace 發布能力。

（暫定，待 wai 確認方向後細化）

---

*SPEC.md v0.3 — 整合 sub-agent review + wai 字體/DOCX fidelity hardening (2026-06-13)*