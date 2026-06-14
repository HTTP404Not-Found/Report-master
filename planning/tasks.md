# Report-master 重新規劃開發任務 / Development Tasks

## 相依關係總覽

```
[A1 Outliner] ──┐
                 ├──→ [B1 Confirmation] ──→ [C1 topic-research 更新] ──→ [D1 End-to-end test]
[A2 Strategist 更新] ──┘                     │
                                             ↓
                                     [C2 html_to_docx bold 修復]
```

## 優先矩陣

| 任務 | 影響範圍 | 難度 | 優先 |
|---|---|---|---|
| A1: Outliner workflow | 所有新 report | M | P0 |
| B1: User confirmation | 流程正確性 | S | P0 |
| C1: topic-research web_search | 內容品質 | M | P1 |
| C2: html_to_docx bold fix | 輸出品質 | S | P0 |
| D1: End-to-end smoke × 2 | 系統完整性 | L | P1 |

---

## Phase A：Outline + Confirmation（核心流程）

### A1: `phase-3-outliner` workflow ★★★
**等級**: L  
**預估**: > 4h（需多次迭代）

**做什麼**：
- 新建 `workflows/phase-3-outliner.md`
- 輸入：`0_strategist.md`（含 RQs）
- 輸出：`0_outline.md`（章節藍圖）+ `0_outline_for_review.md`（人性化摘要）
- 每章包含：標題、層級、核心問題、所需資料類型、預估字數
- 流程：讀取 RQs → 規劃章節 → 邏輯順序檢查 → 產出 outline

**DoD**：
- `wc -l workflows/phase-3-outliner.md` > 150
- 包含 Mermaid 流程圖
- 包含 Outline 範例（自然科學報告 + 技術報告各一）
- `git commit` 成功

**交付**：`workflows/phase-3-outliner.md` + `scripts/outliner.py`（CLI helper）

---

### A2: `strategist.md` 更新
**等級**: M  
**預估**: 2–3h

**做什麼**：
- 更新 `workflows/strategist.md`
- 新增「依據 RQs 產出章節藍圖」的前置步驟
- 明確說明：Strategist 輸出 → Outliner 啟動（自動串接）

**DoD**：
- `workflows/strategist.md` 更新，`wc -l` > 200（原為 ~180）
- `git commit` 成功

---

### B1: `user-confirmation` workflow ★★☆
**等級**: S  
**預估**: 1–2h

**做什麼**：
- 新建 `workflows/user-confirmation.md`
- 定義確認格式：`report_output/0_outline_for_review.md` 內容格式
- 定義 `report_output/0_confirmed.json` schema：
  ```json
  {"confirmed": true|false, "user_notes": "...", "timestamp": "ISO8601", "approved_sections": ["ch1","ch2"]}
  ```
- 定義 Main agent 的確認寫入邏輯（Telegram 回覆「OK」→ 寫入 JSON）
- 定義 Executor 的 gate 邏輯（啟動前檢查 `confirmed == true`）

**DoD**：
- `workflows/user-confirmation.md` 新建，`wc -l` > 80
- `0_confirmed.json` schema 清楚定義
- `git commit` 成功

**交付**：`workflows/user-confirmation.md` + 更新 `workflows/executor.md`（加 gate check）

---

## Phase B：Research + 格式化修復

### C1: `topic-research.md` 更新（web_search 整合）★★★
**等級**: M  
**預估**: 3–4h

**做什麼**：
- 更新 `workflows/topic-research.md`
- 新增 `research_content` 子階段：
  - 觸發時機：Executor 執行某章前，該章尚無 `*_research.md`
  - 流程：`outline 讀取 research需求` → `web_search 搜尋` → `整理要點` → `產出 chapter_N_research.md`
- 定義 web_search query 生成邏輯（來自 outline 每章的「所需資料」欄位）
- 新增 `scripts/web_research.py`（web_search CLI wrapper）：
  - `python -m scripts.web_research --query "..." --output chapter_1_research.md`
  - 支援 `--sources 5`（最多5個來源）

**DoD**：
- `workflows/topic-research.md` 更新，`wc -l` > 300（原為 ~250）
- `scripts/web_research.py` 新建，`wc -l` > 100
- `web_search` 整合 smoke test（給 query → 有輸出）
- `git commit` 成功

---

### C2: `html_to_docx_direct.py` bold 修復 ★★☆
**等級**: S  
**預估**: 1–2h

**做什麼**：
- 修復 `scripts/html_to_docx_direct.py`
- **上游修復**：在 `bundle.py` 或轉換流程中加 HTML 清理：
  - 正規表達式：所有游離 `**text**` → `<strong>text</strong>`
  - 位置：在 `bundle.py` 的 HTML 合併階段，或在 `html_to_docx_direct.py` 的 HTML parse 階段
- **下游修復**：確認 `handle_strong()` + `handle_b()` 使用 `bold=True`
- 新建 `tests/test_bold_formatting.py`（3+ 個 cases）：
  - `<strong>text</strong>` → DOCX run `bold=True`
  - `<b>text</b>` → DOCX run `bold=True`
  - 游離 `**text**` → 清理後不殘留

**DoD**：
- `tests/test_bold_formatting.py` 新建，3 個測試全綠
- 全 pytest 全綠（不回歸）
- `git commit` 成功

**交付**：`scripts/html_to_docx_direct.py`（修復）+ `tests/test_bold_formatting.py`（新增）

---

## Phase C：End-to-End 驗證

### D1: 完整 smoke test × 2 examples ★★☆
**等級**: L  
**預估**: 4h+

**做什麼**：
- 更新 `examples/example_1_natural_science.md`（加入 Outline 見證）
- 更新 `examples/example_2_technical_report.md`（加入 Outline 見證）
- 見證完整流程：
  1. Strategist → 產出 `0_strategist.md`
  2. Outliner → 產出 `0_outline.md` + `0_outline_for_review.md`
  3. Main agent 寫入 `0_confirmed.json`（模擬用戶「OK」）
  4. Topic-Research → `web_search` 蒐集資料
  5. Executor → 各章 HTML（帶 research）
  6. Bundle → `report_final.html`
  7. HTML-to-DOCX → `report_final.docx`（無 `**` 殘留）
  8. LivePreview → 預覽產出
  9. Visual-Review → 格式檢查
  10. Generate-Citations → 引用產出
- 更新 `scripts/test_examples.py`（加入 Outline + Confirmation 步驟）
- 更新 `tests/test_examples.py`（確認 outline + confirmed.json 存在）

**DoD**：
- `examples/output_1/` + `examples/output_2/` 都完整產出 `report_final.docx`（無 `**`）
- `examples/output_1/0_outline.md` 存在
- `examples/output_1/0_confirmed.json` 存在
- `examples/output_1/chapter_*_research.md` 存在（至少 2 個 chapters 有 research）
- 全 pytest 全綠
- `git commit` 成功

---

## 突發狀況

| 狀況 | 處理 |
|---|---|
| 用戶回覆「修改需求」 | Outliner 根據 notes 重新規劃 outline，重新進入確認 loop |
| web_search 無結果 | 降級：Executor 使用 LLM 內部知識，章節標註 `[research: insufficient data]` |
| html_to_docx bold 測試 fail | 立即停止，revert + 問 wai |
| Outline 產出章節數 > 10 | Outliner 先問用戶「章節數是否太多？」再繼續 |

## 預估總工時

| Phase | 任務數 | 總工時（sub-agent） |
|---|---|---|
| A：Outline + Confirmation | 3 | 7–9h |
| B：Research + Fix | 2 | 4–6h |
| C：End-to-end | 1 | 4h+ |
| **合計** | **6** | **15–19h** |

---

## 現有 40/40 之外的額外任務

這些是「重新規劃」帶來的新任務（不計入原有 40/40）：

| 任務ID | 名稱 | 等級 | 狀態 |
|---|---|---|---|
| A1 | Outliner workflow | L | 待做 |
| A2 | Strategist 更新 | M | 待做 |
| B1 | User confirmation workflow | S | 待做 |
| C1 | topic-research web_search 整合 | M | 待做 |
| C2 | html_to_docx bold 修復 | S | 待做 |
| D1 | End-to-end smoke × 2 | L | 待做 |

---

## Phase 4: 5-Step Phase Flow 寫入（Pipeline Refinement）

> **對應文件**：`SKILL.md` v1.3 + `planning/skill-update-plan.md` v1
> **引入日期**：2026-06-14
> **wai 確認 5 步驟 phase flow**：2026-06-14 06:30
> **狀態**：規劃完成，待 wai 決策開工

### E1: 5 步驟 phase flow 寫入 SKILL.md
**等級**: S  
**預估**: 1–2h（單一文件改動）

**做什麼**：
- 更新 `SKILL.md` v1.0 → v1.3
- 主要修改點（見 `planning/skill-update-plan.md` Section A.3）：
  - frontmatter description 加入 5 步驟摘要
  - §2 標題改為「Pipeline — 5-Step Phase Flow」+ 插入 §2.0（5 步驟總覽）+ §2.1（feedback routing）
  - §4 改寫為「Step 4 反饋路由（Feedback Routing）」
  - §5 workflow 關係加上 5 步驟歸屬標記
  - §10 失敗指引按 5 步驟重排
  - §11 版本演進新增 v1.3 行
- 既有 §6（兩個 AI 角色）/ §7（lock 引用規則）/ §8（ppt-master 差異）/ §9（Stage 3 驗收）**不動**

**DoD**：
- `wc -l SKILL.md` > 280（原為 279）
- 5 步驟 5 個 H3 子段落都存在（§2.0、§2.1、§2.2）
- §4 表格內含 feedback routing 三分類 + 兜底規則
- §11 v1.3 行存在
- 全 pytest 仍 428 pass（SKILL.md 改動不影響 tests，但 wai 可要求 sub-agent 跑一次確認）
- `git commit` 成功（不 push）

**交付**：更新的 `SKILL.md`（v1.0 → v1.3）

---

### E2: 雙語 README 同步（2026-06-14 新規則）
**等級**: S  
**預估**: 30min–1h

**做什麼**：
- 更新 `README.md`（en）Pipeline 章節為 5 步驟框架
- 更新 `README_zh.md`（zh-TW）對應章節鏡像
- 更新 Progress 表格新增 v1.3 一行（**main agent 責任** — 批次收尾時做；本任務是 sub-agent feature-level 同步）
- 更新 footer 版本號 v1.0 → v1.3

**DoD**：
- README.md 與 README_zh.md 的 Pipeline 章節**雙語內容一致**（無 en-only / zh-only 漂移）
- 雙語都提及 5 步驟 phase flow + feedback routing
- 變更與 E1 commit 配對（不需獨立 commit）

**交付**：`README.md` + `README_zh.md` 更新（與 E1 同 commit）

---

### E3: skill meta 更新（report-master-dev）
**等級**: S  
**預估**: 15min

**做什麼**：
- 更新 `~/.openclaw/workspace/skills/report-master-dev/SKILL.md`
- description 加上 5 步驟 phase flow 摘要
- 新增「v1.3: 5 步驟 phase flow + feedback routing」條目到版本演進（若該檔有版本演進區段；目前無，可加）

**DoD**：
- 描述 < 160 bytes
- 提及 5 步驟 phase flow
- `git commit` 成功（sub-agent 完成 E1+E2+E3 後，由 main agent 批次 push）

**交付**：更新的 skill meta SKILL.md

---

### E4: 既有 6 個任務狀態追溯更新（追溯性維護）
**等級**: S  
**預估**: 15min

**做什麼**（可選，看 wai 決策）：
- 更新 `tasks.md` L155–165 表格的 status 欄位：
  - A1 Outliner workflow: 待做 → ✅ done
  - A2 Strategist 更新: 待做 → ✅ done
  - B1 User confirmation workflow: 待做 → ✅ done
  - C1 topic-research web_search 整合: 待做 → ✅ done
  - C2 html_to_docx bold 修復: 待做 → ✅ done
  - D1 End-to-end smoke × 2: 待做 → ✅ done
- 對應 MEMORY.md「4 大核心問題已修復（2026-06-13 16:48）」
- 同時在 Phase 4 章節加入「已完成工作量」對照（4 大核心問題修復對應 6 個任務全 ✅）

**DoD**：
- tasks.md L155–165 表格 6 個 status 全改為 ✅ done
- 對應 commit hash 填入（從 `git log` 撈）

**交付**：更新的 `tasks.md` 表格

> **建議**：E4 屬追溯性維護，可由 wai 決策是否歸入本次 v1.3 commit，或另開 commit (`docs(report-master): 追溯更新 tasks.md 6 個任務狀態`)。

---

### E5: 5 步驟 phase flow 驗收測試（端到端 smoke）
**等級**: M  
**預估**: 2–3h

**做什麼**（v1.3 完成後，下次報告生成時驗證）：
- 走一次完整 5 步驟流程，產出 `examples/output_3/`（或更新 `output_1` / `output_2`）
- 驗證：
  - Step 1 topic-research 整合是否順暢
  - Step 2 資料源是否真實 pin 進 prompt
  - Step 3 Outliner 產出是否合用
  - Step 4 feedback routing 三分類是否正確觸發
  - Step 5 export 是否乾淨
- 更新 `tests/test_workflow_docs.py` 加入「5 步驟 phase flow 存在於 SKILL.md」測試（可選）

**DoD**：
- 端到端生成 1 份新 example 報告
- 5 步驟 log 都有對應輸出
- 全 pytest 仍 428+ pass
- `git commit` 成功

**交付**：`examples/output_3/` + 可能更新 `tests/test_workflow_docs.py`

> **不列入 v1.3 必做**：E5 是 v1.3 之後的驗收，可延後到下次實際使用時做。

---

### Phase 4 依賴關係

```
E1 (SKILL.md 更新)
 ├── E2 (雙語 README 同步)   ← 配對 commit
 ├── E3 (skill meta 更新)     ← 可與 E1+E2 同 commit
 └── E4 (追溯性維護)          ← 可選；wai 決策

E5 (端到端驗收)  ← 延後到 v1.3 之後首次使用時
```

### Phase 4 預估總工時

| Task | 等級 | 工時 |
|------|------|------|
| E1 | S | 1–2h |
| E2 | S | 30min–1h |
| E3 | S | 15min |
| E4 | S | 15min（可選） |
| E5 | M | 2–3h（延後） |
| **合計（必做）** | | **2–3.5h** |
| **合計（含 E4 + E5）** | | **4.5–6.5h** |
