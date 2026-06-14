---
name: report-master
description: Generate professional DOCX reports from Markdown / HTML sources via the report-master pipeline. Use when the user asks to "生成報告書", "做 DOCX 報告", "轉 Word", "從 Markdown 出報告", "make a report", "compile report", or wants a structured deliverable (academic paper, business proposal, spec, government document). **Pipeline 採 5 步驟 phase flow：(1) 規劃+線上補充資料 → (2) 用資料擴充拓展 → (3) 編排內容 → (4) 用戶確認 → (5) 最後編排格式。底層實作為 Stage 0 (source probe) → Stage 1 (lock contract + topic-research) → Stage 1.5 (phase-3-outliner) → Stage 2 (per-section HTML generation + quality gate) → Stage 3 (DOCX render; HTML 為 pipeline intermediate + opt-in named output)。** v1.4.0 起 PDF 不再由 orchestrator 產出 (html_to_pdf.py 模組保留供 legacy opt-in)。Do NOT use for slide decks (use ppt-master) or short notes.
---

# SKILL.md — Report-master 主 workflow authority

> **文件版本：v1.4** · 對應 SPEC.md v0.3 + architecture.md v1.0 + planning/skill-update-plan.md v1 · 2026-06-14
> **v1.4.0 重大變更**: DOCX 為 user-facing 主交付物;HTML 為 pipeline intermediate + opt-in 命名輸出 (`--format docx,html`);PDF user-facing 輸出退役 (html_to_pdf.py 模組保留供 legacy opt-in)。
> **5 步驟 phase flow** 由 wai 於 2026-06-14 06:30 確認。
> **Reference**：reverse-engineer-ppt-master（相似設計哲學；HTML 中間格式 vs SVG 中間格式）
> **Inherits**：Spec-Lock anti-drift、role specialization (Strategist / Executor)、per-section quality gate、examples as integration tests、5 步驟 phase flow + feedback routing。

---

## 1. 何時使用本 skill

下列任一觸發詞 → 啟動 report-master：

| 觸發詞（中） | 觸發詞（英） |
|--------------|--------------|
| 生成報告書 / 寫一份報告 / 出報告 | generate report / make a report / write up |
| 做 DOCX 報告 / 轉 Word | DOCX report / Word version |
| ~~做 PDF 報告 / 轉 PDF~~（v1.4.0 退役,改走 DOCX） | ~~PDF report / compile to PDF~~（legacy opt-in via `scripts.html_to_pdf`）|
| 從 Markdown 出報告 | Markdown to report |
| 學術論文 / 商業提案 / 規格書 / 政府公文 | academic paper / business proposal / spec / gov doc |

**反例**（不要用本 skill）：

- 簡報 / slides → 用 `ppt-master`
- 短筆記 / blog → 直接 Markdown 渲染即可
- 純資料 dump → 用 Markdown table

---

## 2. Pipeline — 5-Step Phase Flow（規劃→擴充→編排→確認→格式化）

Report-master 對外提供 5 步驟 phase flow；底層實作為既有 Stage 0–3 + `workflows/*.md`。所有 sub-agent 在生成 / 修改 / 排錯時，**應以 5 步驟框架思考與溝通**，遇到具體指令再下鑽到對應 stage 與 workflow。

### 2.0 5 步驟 phase flow 總覽（給 sub-agent 與使用者的「心智模型」）

| 步驟 | 語意 | 底層 stage 對應 | 主要 workflow | sub-agent 行為 |
|------|------|----------------|----------------|----------------|
| **1. 規劃 + 線上補充資料** | 收斂使用者意圖 + 同步整合 web research | Stage 0 + Stage 1 | `topic-research`（整合進 planning）、`strategist` | 啟動 topic-research 蒐集 high-level 證據；Strategist 跑 10 Confirmations；**研究綁在規劃裡，不寫完才補** |
| **2. 用資料擴充拓展** | 寫作有憑有據，資料源 pin 進 prompt 可追溯 | Stage 1.5 → Stage 2 | `topic-research`（Content Expansion 子階段）、`executor` | Executor 對每節讀 `chapter_N_research.md`（如缺，自動觸發 topic-research + `web_search` 補足）；**所有資料源在 prompt 中顯式列出** |
| **3. 編排內容** | 結構先定，內容對齊骨架 | Stage 1.5（Outliner） | `phase-3-outliner` | 產出 `0_outline.md`（機讀藍圖）+ `0_outline_for_review.md`（人讀摘要）；每章標題、層級、核心問題、所需資料、預估字數 |
| **4. 用戶確認** | 看到結構 + 內容再確認；DOCX 還沒碰，改起來便宜 | （gate 階段） | `user-confirmation` | 等待使用者回覆「OK / 修改 / REDO」；寫入 `0_confirmed.json`；Executor 啟動前必讀此檔 |
| **5. 最後編排格式** | 純機械 export（DOCX / 粗體修復），內容不再變動 | Stage 2.5 → Stage 3 | `visual-review`（可選）、`html_to_docx`（PDF 退役） | 跑 export_checker 5 項 DOCX 驗收；任何內容異動 → 退回步驟 2（嚴禁在 step 5 改字 / 改措辭） |

**底層 Stage 編號 → 5 步驟 映射**：

```
Step 1 (規劃+研究)     = Stage 0 (source probe) + Stage 1 (Strategist) + topic-research 整合
Step 2 (擴充)          = Stage 2 (Executor) + topic-research Content Expansion
Step 3 (編排)          = Stage 1.5 (phase-3-outliner)  ← 注意：可在 Step 2 之前或之後，依「先骨架後肉 / 先肉後整骨」二擇一
Step 4 (確認)          = user-confirmation gate
Step 5 (格式化)        = Stage 2.5 (visual-review 可選) + Stage 3 (html_to_docx;v1.4.0 起 html_to_pdf 不預設呼叫)
```

> **⚠️ Step 3 在流程中的位置是 wai 須明確決策的開放問題**（見 Section D.1 Q1）：是要「骨架先於肉」（Outliner 早於 Executor）還是「肉先於骨架」（Outliner 校對 Executor 輸出）？

#### 2.1 5 步驟的 Feedback Routing（步驟 4 → 退回規則）

步驟 4（用戶確認）收到「修改」回饋時，依回饋性質退回對應步驟：

| 回饋類型 | 退回步驟 | 觸發 workflow | 動作 |
|----------|----------|----------------|------|
| **內容 / 事實 / 資料問題**（數字錯、引用錯、案例錯、證據不足） | **→ Step 2（擴充）** | `topic-research` v1.1 Content Expansion 補強 → `executor` 重生成該節 | 重跑 `web_search` 取得新證據；更新 `chapter_N_research.md`；Executor 重新生成該節 HTML（保留其他節不動） |
| **章節順序 / 結構問題**（章節該拆 / 該合 / 該換位置） | **→ Step 3（編排）** | `phase-3-outliner` | 重新規劃 outline；**可能** 連動影響多節 Executor 輸出 |
| **純文字 / 標題措辭**（某段太冗、結論改 bullet、標題換個說法） | **→ Step 4 inline 改**（不退回） | `revise`（Stage 2.5） | 用 `revise_helper` 做單節 HTML 局部修訂；不重跑 Outliner、不重跑研究 |

**判定準則**（給 sub-agent 用）：

- 涉及「資料、數字、引用、案例、定義」→ **Step 2**
- 涉及「章節、順序、層級、架構、骨架」→ **Step 3**
- 涉及「措辭、文法、長度、bullet 化、標題用字」→ **Step 4 inline**
- 同時多類 → 從**結構→內容→文字** 順序處理（先 Step 3、再 Step 2、最後 Step 4 inline）

#### 2.2 5 步驟 vs 既有 Stage 編號 對照速查表

| 5 步驟 | 對應 Stage | 對應 workflow(s) | 主要產出 | 主要消費 |
|--------|------------|------------------|----------|----------|
| Step 1 規劃 | Stage 0 + Stage 1 | `topic-research`、`strategist` | `0_strategist.md`（含 RQ1…RQn）、`research_notes.md` | `phase-3-outliner` |
| Step 2 擴充 | Stage 1.5 → Stage 2 | `topic-research` v1.1、 `executor` | `chapter_N_research.md`、`chapter_N.html` | `bundle` |
| Step 3 編排 | Stage 1.5（Outliner） | `phase-3-outliner` | `0_outline.md`、`0_outline_for_review.md` | `user-confirmation`、`executor` |
| Step 4 確認 | （gate） | `user-confirmation` | `0_confirmed.json` | `executor` 啟動前必讀 |
| Step 5 格式化 | Stage 2.5 + Stage 3 | `visual-review`（可選）、`html_to_docx`（v1.4.0 起 PDF 模組保留但不預設呼叫） | `report_final.docx`（+ 可選 `report_final.html`） | 使用者交付 |

---

下面是底層 Stage 細節（**developer-facing**，與上方 5 步驟框架**兩個視角並存**）：

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
│   Executor = 逐節 + per-section quality gate（見 references/executor-base.md）
│   對每一節：                                                          │
│     重讀 report_lock.md (防 formatting drift)                        │
│     重讀 glossary.md (防 narrative drift)                            │
│     載入前節已生成 HTML（防內容重複、術語一致）                       │
│     Executor 生成該節 HTML（內聯樣式優先）                            │
│     quality_checker.py 過門（per-section gate）                       │
│       → PASS: 寫入 report_output/section_N.html                      │
│       → BLOCKING: 列出禁用清單命中項；重做（最多 2 次）               │
│     進度持久化到 lock.metadata.progress（auto-resume）               │
├──────────────────────────────────────────────────────────────────────┤
│ Stage 2.5 — 迭代（可選，人類 review → v_n+1）                          │
│   delta_checker.py 對 report_v_n vs v_n+1 做 section-level diff      │
│   選定 section IDs 重跑 Stage 2                                      │
├──────────────────────────────────────────────────────────────────────┤
│ Stage 3 — 工程轉換（DOCX 為主;v1.4.0 起 PDF 不再由 orchestrator 產出） │
│   主要路徑:                                                          │
│     html_to_docx.py (pandoc + reference docx) → DOCX                 │
│   可選 named output:                                                 │
│     --format docx,html → 額外產 report_<ts>.html (供使用者取用)       │
│   docx_validator.py 抽樣驗字體/樣式（mammoth round-trip）             │
│   export_checker.py post-export 檢查（v1.4.0: DOCX-only, 5 項驗收）   │
│   產出 exports/report_<ts>.docx（+ 可選 report_<ts>.html）            │
│   存檔 backup/<ts>/report_output/                                    │
│                                                                       │
│   v1.4.0 retired: html_to_pdf.py 模組保留供 legacy opt-in,但不在     │
│   orchestrator 預設呼叫路徑內。使用者如需 PDF,可手動執行:            │
│     python -m scripts.html_to_pdf --input <bundle.html>              │
│                                --output <out.pdf> --lock-file <lock>  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 與 `scripts/report_gen.py` 的呼叫協議

主 entry point 是 `python -m scripts.report_gen`，三種使用情境：

### 3.1 全自動（Stage 2 + 3）— v1.4.0: DOCX 主路徑 + HTML opt-in

```bash
python -m scripts.report_gen \
  --source <input_dir|input.html> \
  --output <exports_dir> \
  --lock <report_lock.md> \
  [--format docx,html]   # 預設 docx;加 html 顯式產 HTML 命名輸出
```

行為（v1.4.0）:
1. 讀 `report_lock.md` → 校驗 required 欄位（缺 → BLOCKING）
2. 對每節 HTML 跑 `quality_checker.py`
3. 跑 `html_to_docx.py`（DOCX 主路徑;**不再平行跑 html_to_pdf.py**）
4. 若 `--format docx,html`,額外 copy bundle 為 timestamped `<ts>.html` 命名輸出
5. 跑 `export_checker.py` 5 項 DOCX 驗收
6. PASS → 寫入 `exports/report_<ts>.docx`（+ 可選 `report_<ts>.html`）;FAIL → 非零退出 + reason

**PDF 退役說明**: `--format pdf,docx` 仍可傳入,**但 PDF 項目被靜默忽略**（log 一行 info）。如需 PDF,使用者手動跑 `python -m scripts.html_to_pdf`（legacy opt-in,模組保留）。

### 3.2 只跑 Stage 3（HTML 已生成,只轉 DOCX [+ 可選 HTML]）

```bash
python -m scripts.report_gen render \
  --html <bundle.html> \
  --output <exports_dir> \
  --format docx[,html]   # 預設 docx;加 html 顯式產 HTML 命名輸出
```

### 3.3 只跑 Stage 2（生成 HTML）

```bash
python -m scripts.report_gen generate \
  --lock <report_lock.md> \
  --sections <id,id,...> \
  --output <report_output_dir>
```

### 3.4 DOCX 引擎路由(lock → engine, v1.3.3 新增 — D3)

依 `lock.output.docx_engine` 選擇 DOCX 生成路徑:

| `lock.output.docx_engine` | 呼叫腳本 | 適用場景 |
|---------------------------|----------|----------|
| `pandoc`(預設) | `scripts.html_to_docx.html_to_docx` | 一般學術 / 商業報告;接受 Markdown 中介層 |
| `python-docx` | `scripts.html_to_docx_direct.html_to_docx_direct` | 政府公文 / 期刊投稿;完全控制字體 / 段落 / 表格 |

**路由意圖**:使用者於 Stage 1 `report_lock.md` 內指定 `output.docx_engine`,Stage 3 應依此路由到對應腳本。

**目前狀態(v1.3.3 起)**:`report_gen.py` 的 DOCX 產生仍寫死呼叫 `html_to_docx`(pandoc),**未做自動 routing**。當 lock 指定 `output.docx_engine: python-docx` 時,使用者需:

```bash
# 手動跑 direct 路徑(不走 report_gen)
python -m scripts.html_to_docx_direct \
  --input <bundle.html> \
  --output <out.docx> \
  --lock-file <report_lock.md>
```

**TODO(下一輪)**:`report_gen.py` 增加 `--docx-engine` CLI flag + 自動讀 lock routing(與 `output.format` 同樣在 CLI 讀),讓 single entrypoint 可覆蓋兩條 DOCX 路徑。

---

## 4. Step 4 反饋路由（Feedback Routing）

> 本章取代舊版「Stage 2.5 迭代觸發條件」。5 步驟框架下，**所有使用者回饋走 §2.1 的 feedback routing 三分類**（內容→Step 2、結構→Step 3、文字→Step 4 inline）。
> 舊版「>30% 大改 → 回 Stage 1」規則**保留為兜底**（適用於結構性崩壞或多步驟同時失敗），但**首選**走 feedback routing。

### 4.1 Feedback Routing 三分類（與 §2.1 重複一次以便查閱）

| 回饋類型 | 判定關鍵字 | 退回步驟 | 觸發 workflow | 動作 |
|----------|------------|----------|----------------|------|
| 內容 / 事實 / 資料 | 數字、引用、案例、證據、定義、來源 | Step 2 擴充 | `topic-research` v1.1 + `executor` | 重跑 `web_search` 補強；重生成該節 HTML |
| 章節順序 / 結構 | 章節、章序、拆、合併、位置、層級、骨架 | Step 3 編排 | `phase-3-outliner` | 重規劃 outline；連動影響多節 |
| 純文字 / 標題措辭 | 太長、太短、bullet 化、措辭、換句話說 | Step 4 inline | `revise`（Stage 2.5 局部修訂） | 單節 HTML 修訂；不動 outline、不重跑研究 |

### 4.2 兜底規則（保留舊 Stage 2.5 行為）

| 條件 | 動作 | 對應 5 步驟 |
|------|------|--------------|
| 多步驟同時失敗（如 Step 1+2+3 全錯） | 回到 Step 1 重跑整體 | 全 5 步驟 |
| 使用者要求「全部打掉重來」 | 回到 Step 1 | 全 5 步驟 |
| `lock_signature` 不一致（`resume-execute` 偵測） | 回到 Step 1 重收斂 | Step 1 + 後續全部 |
| quality_checker 連續 2 次 BLOCKING 同一節 | 退回 Step 2 重擴充 | Step 2 |
| 圖表編號不連續、交叉引用 broken | quality_checker BLOCKING，退回 Step 2 | Step 2 |

`delta_checker.py` 與 `revise_helper.py` 行為不變（不覆蓋既有 `report_v_n.html`）。

---

## 5. 與其他 workflow 的關係（含 5 步驟歸屬標記）

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

- `topic-research`：Step 1（高層研究）+ Step 2（Content Expansion）— 雙重角色
- `generate-citations`：Step 1 期間呼叫（建立 / 更新 BibTeX + CSL）
- `phase-3-outliner`：**Step 3** 編排核心（吃 RQs → 產 Section Blueprint）
- `user-confirmation`：**Step 4** 確認 gate（讀 outline → 等使用者 → 寫 `0_confirmed.json`）
- `live-preview`：Step 5 期間呼叫（逐節瀏覽器預覽）
- `visual-review`：Step 5 之前可選跑（DOCX 截圖 / 版面自查;v1.4.0 起以 DOCX 為標的）
- `revise`：Step 4 inline 反饋（純文字修訂，不退回）
- `resume-execute`：Step 2/3 斷點續傳

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
- 每節開工前重讀 `report_lock.md` + `glossary.md` + 前節 HTML（防 drift）
- 依 `references/executor-base.md` 7-step 流程生成該節 HTML（內聯樣式優先）
- 提交 `quality_checker` 過門；不通過則重生成（最多 2 次，仍 FAIL → 寫入 lock.metadata.errors）
- 進度持久化到 `lock.metadata.progress`（支援 auto-resume / 斷點續傳）
- Stage 3 由 `html_to_pdf.py` + `html_to_docx.py` 觸發（Executor 不直接執行）

**不做**：不會改 lock 結構、不會跑 Stage 3 轉換、不會跨節並行 sub-agent（敘事必漂移）。

**詳細 workflow**：見 `references/executor-base.md`（T3-2）。
- 7-step 逐節流程（load → prompt → quality → write → next）
- Mermaid 逐節生成流
- 自動接續 `metadata.progress`（含 `--restart` / `--section N`）
- CLI helper：`python -m scripts.executor --lock <path> --output <dir> [--section N]`
- 與 Strategist / quality_checker / Stage 3 的邊界定義

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
| 輸出 | PPTX | **DOCX**（v1.4.0+ user-facing 主交付物）|
| 中間格式 | SVG | **HTML**（pipeline intermediate + `--format docx,html` opt-in 命名輸出）|
| 舊輸出 | — | ~~PDF~~（v1.4.0 起 user-facing 退役;`html_to_pdf.py` 模組保留供 legacy opt-in）|
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

## 9. Stage 3 驗收 checklist（export_checker.py — v1.4.0: 5 項 DOCX-only）

每份報告產出後自動跑（v1.4.0 起僅驗收 DOCX）：

- [ ] DOCX 可開啟（zip + word/document.xml 解析無例外）
- [ ] DOCX 含 `[Content_Types].xml`
- [ ] DOCX 含 `word/document.xml`
- [ ] DOCX 至少 1 段（paragraph count > 0）
- [ ] 目次連結有效（DOCX TOC field 或 bookmark）

**v1.4.0 移除**（PDF user-facing 輸出退役,對應驗收項不再適用）:
- ~~PDF 可開啟（PyMuPDF 解析無例外）~~
- ~~PDF 字體已嵌入（至少含標楷體 / Times New Roman 任一）~~
- ~~PDF 頁數 > 0~~

任何一項失敗 → 整份報告 **PASS=false**，main agent 收到 reason 清單。

---

## 10. 失敗 / 求助指引（依 5 步驟分類）

### 10.1 依 5 步驟分類的失敗處理

| 步驟 | 症狀 | 原因 / 處理 |
|------|------|-------------|
| **Step 1（規劃）** | `0_strategist.md` 缺 RQ 區塊 | 補 10 Confirmations；走 `strategist` workflow §3 |
| **Step 1** | `research_notes.md` 為空且無 source | 走 `topic-research`（無源路徑）；sub-questions ≥ 3 才 PASS |
| **Step 1** | web_search 無結果 | 降級：Executor 使用 LLM 內部知識；章節標註 `[research: insufficient data]` |
| **Step 2（擴充）** | `chapter_N_research.md` 缺且 Executor 卡住 | 自動觸發 topic-research 子階段；如仍無資料 → 降級同上 |
| **Step 2** | `QualityCheckError: display: flex` | 改用 block flow（見 `shared-standards.md` §3） |
| **Step 2** | `LockMissingFieldsError` | 補 `report_lock.md` 欄位後退回 Step 1 |
| **Step 3（編排）** | Outliner 產出章節數 > 10 | Outliner 先問使用者「章節數是否太多？」再繼續 |
| **Step 3** | Outliner 邏輯順序不通過 | 退回 Step 3 重規劃；見 `phase-3-outliner.md` §4.4 拓樸規則 |
| **Step 4（確認）** | `0_confirmed.json` 缺 / `executor_can_start=false` | Executor 拒絕啟動；走 `user-confirmation` 重跑 |
| **Step 4 inline** | `delta_checker.check_lock()` BLOCKING | `revise_helper` 不應改 lock；還原後重跑 |
| **Step 5（格式化）** | `FontNotFoundError: 標楷體` | 見 `fonts/README.md` 安裝指引；或 `apt install fonts-noto-cjk` |
| **Step 5** | `PandocNotFoundError` | `apt install pandoc` 或下載 binary；見 `docs/.env.example` |
| **Step 5** | `MMDCNotFoundError` | `npm install -g @mermaid-js/mermaid-cli`；或允許 Stage 2 保留 `<pre class="mermaid">` 待後處理 |
| **Step 5** | `KaTeXNotFoundError` | 同上；可選 |
| **Step 5** | `ExportCheckFailed: paragraph count=0` | html_to_docx 渲染失敗；檢查 HTML 結構與字體路徑 |
| **Step 5** | DOCX 內文殘留 `**` | 檢查 `bundle.py` 上游清理 + `html_to_docx` `handle_strong()`（見 C2 bold 修復） |
| **跨步驟** | pytest 任何 fail | 立即停止，問 wai |
| **跨步驟** | git conflict / 多 agent commits 衝突 | main agent resolve，不打斷 sub-agent |

---

## 11. 版本演進

| 版本 | 狀態 | 說明 |
|------|------|------|
| v0.0 | done | placeholder |
| v1.0 | done | Track B 完工：report_gen + quality_checker + html_to_* + validators + checkers + renderers + tests + examples |
| v1.1 | done | T3-1 Strategist workflow + T3-2 Executor workflow（逐節 + per-section quality gate） |
| v1.2 | done | Stage 1.5 Outliner 拆分 + User confirmation gate + topic-research v1.1 Content Expansion + DOCX bold 修復（4 大核心問題修復） |
| **v1.3** | **done** | **5 步驟 sub-agent phase flow 上層抽象（規劃→擴充→編排→確認→格式化）+ feedback routing 三分類（取代舊 Stage 2.5 觸發規則）** |
| **v1.4** | **done (this release)** | **PDF user-facing 輸出退役:DOCX 為主交付物;HTML 為 pipeline intermediate + opt-in 命名輸出;export_checker 7 項 → 5 項 DOCX-only;html_to_pdf.py 模組保留供 legacy opt-in** |
| v2.0 | TBD | Stage 4 / pipeline-as-service;multi-locale |

---

*SKILL.md v1.4 — 對應 SPEC.md v0.3 + architecture.md v1.0 + planning/skill-update-plan.md v1, 2026-06-14. v1.4.0 變更: PDF user-facing 輸出退役;DOCX 為主交付物。*