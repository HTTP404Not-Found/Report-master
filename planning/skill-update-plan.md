# Report-master — 5 步驟 sub-agent phase flow 寫入規劃

> **規劃日期**：2026-06-14 06:33 GMT+8
> **規劃者**：sub-agent (depth 1/1, requester `agent:main:telegram:direct:6793926064`)
> **對應版本**：SKILL.md v1.0 → v1.3（規劃升級）、planning/tasks.md v1.1（40/40 + 6 個重新規劃任務）→ 新增追蹤
> **工作目錄**：`/home/ubuntu/.openclaw/workspace/projects/report-master/`
> **硬約束**：本檔為純規劃，不實際改檔、不 git commit/push、不跑 pytest

---

## 摘要

wai 在 2026-06-14 06:30 確認的 **5 步驟 sub-agent phase flow** 是 Report-master pipeline 的**新上層抽象**。它把現有的 Stage 0 → 1 → 1.5 → 2 → 2.5 → 3 重新收斂成 5 個語意層次更乾淨的 phase，並定義了 phase 之間的 **feedback routing** 規則。

**核心變更**：

- 5 步驟是**上層 user-facing flow**（給 agent / 使用者看的「心智模型」）
- 既有 `Stage X` 編號 + `workflows/*.md` 是**底層實作單元**（給 developer / sub-agent 看的執行步驟）
- 兩者不是取代關係，是**抽象層級關係**：5 步驟 1 對多映射到既有 stages + workflows
- Feedback routing（步驟 4 → 退回步驟 2 / 3）取代舊版「Stage 2.5 改 >30% → 回 Stage 1」的粗略規則

**規劃目標**：

1. 將 5 步驟 phase flow 寫入 `./SKILL.md`（給 sub-agent 看的權威文件）
2. 在 `./planning/tasks.md` 新增追蹤任務
3. 評估是否同步更新 `~/.openclaw/workspace/skills/report-master-dev/SKILL.md`（meta）

---

## Section A: SKILL.md 改動計畫

### A.1 現有 SKILL.md 章節結構概述

當前 `./SKILL.md`（279 行，v1.0，2026-06-13）共 11 個 H2 章節：

| 行號 | 章節 | 內容摘要 | 與 5 步驟關係 |
|------|------|----------|---------------|
| L1–13 | frontmatter | `name` / `description` / `version` 對外觸發詞 | 需更新 description 提及「5-step flow」 |
| L14–32 | §1 何時使用 | 觸發詞 + 反例（ppt-master / 短筆記 / dump） | 不動 |
| L33–80 | §2 Pipeline（Stage 0→3） | ASCII 流程圖 + 4 個 stage 細節 | **核心修改區** — 加入 5 步驟框架或新增 §2.5 |
| L81–120 | §3 與 `scripts/report_gen.py` 呼叫協議 | CLI 三種情境 | 不動 |
| L121–134 | §4 Stage 2.5 迭代觸發條件 | 5 種觸發 + `delta_checker` 行為 | **核心修改區** — 改寫為「5 步驟 feedback routing」 |
| L135–162 | §5 與其他 workflow 關係 | ASCII 圖 + 4 個 workflow 描述 | **小幅修改** — 標註 5 步驟歸屬 |
| L163–203 | §6 兩個 AI 角色 | Strategist / Executor 職責 | 不動（角色定義仍正確） |
| L204–218 | §7 report_lock.md 引用規則 | 必讀 + 缺欄位 BLOCKING | 不動 |
| L219–237 | §8 與 ppt-master 差異 | 對照表 | 不動 |
| L238–253 | §9 Stage 3 驗收 checklist | export_checker 7 項 | 不動 |
| L254–267 | §10 失敗 / 求助指引 | 6 種症狀處理 | **小幅修改** — 對齊 5 步驟框架 |
| L268–278 | §11 版本演進 | v0.0 / v1.0 / v1.1 / v1.2 / v2.0 | **必須更新** — 新增 v1.3 行 |

**結論**：5 步驟 phase flow 的**主要落點**在 §2（pipeline）+ §4（迭代觸發）+ §11（版本演進）+ frontmatter description。次要落點在 §5 / §10 的措辭對齊。

---

### A.2 5 步驟 phase flow 插入位置（具體 line 範圍）

**方案選擇**：不新增獨立章節，而是**重構 §2 + §4**（保留現有編號、章節定位，但內容換骨架）。

理由：

- 既有 §2 是 ASCII 流程圖 + 4 個 stage 細節；5 步驟是 5 個語意層；**stage 細節保留為子段落**，上方加 5 步驟框架
- 既有 §4 是「Stage 2.5 迭代觸發」；5 步驟的 feedback routing **直接取代**此章節
- 新增獨立章節（如「§2.5 5-Step Phase Flow」）會破壞既有 reference 連結（`README.md` 可能有錨點指向 §2 / §4）

#### 具體插入計畫

| 修改位置 | line 範圍（目前） | 動作 | 對應小節草稿 |
|----------|-------------------|------|--------------|
| frontmatter description | L2 | **修改** — 末尾加入「5-step phase flow: 規劃→擴充→編排→確認→格式化」 | A.3.1 |
| §2 標題 | L34 | **修改** — 改為「Pipeline（5-Step Phase Flow: 規劃→擴充→編排→確認→格式化）」 | A.3.2 |
| §2 開頭 | L36–38 | **插入** — 5 步驟框架描述（見 A.3.2 草稿） | A.3.2 |
| §2 流程圖 | L36–78 | **保留** — Stage 0/1/1.5/2/2.5/3 細節，標註對應 5 步驟 | A.3.2 |
| §4 標題 | L121 | **修改** — 改為「Step 4 反饋路由（Feedback Routing）— 取代舊 Stage 2.5」 | A.3.3 |
| §4 表格 | L123–128 | **替換** — feedback routing 三類規則 | A.3.3 |
| §5 標題 / 內容 | L135–162 | **小幅修改** — 4 個 workflow 加上「歸屬 5 步驟」標記 | A.3.4 |
| §10 標題 | L254 | **修改** — 改為「失敗 / 求助指引（依 5 步驟分類）」 | A.3.5 |
| §10 表格 | L256–262 | **小幅重排** — 按 5 步驟分組（規劃失敗 / 擴充失敗 / 編排失敗 / 確認失敗 / 格式化失敗） | A.3.5 |
| §11 表格 | L269–275 | **插入 v1.3 行** | A.3.6 |

---

### A.3 完整 markdown bullets / 段落草稿（可直接 copy-paste）

#### A.3.1 frontmatter description 修改

**原 L2 description**：

```yaml
description: Generate professional PDF + DOCX reports from Markdown / HTML sources via the report-master pipeline. Use when the user asks to "生成報告書", "做 PDF 報告", "做 DOCX 報告", "從 Markdown 出報告", "make a report", "compile report", or wants a structured deliverable (academic paper, business proposal, spec, government document). Runs Stage 0 (source probe) → Stage 1 (lock contract) → Stage 2 (per-section HTML generation + quality gate) → Stage 3 (PDF + DOCX parallel render). Do NOT use for slide decks (use ppt-master) or short notes.
```

**修改後（粗體 = 新增 / 修改）**：

```yaml
description: Generate professional PDF + DOCX reports from Markdown / HTML sources via the report-master pipeline. Use when the user asks to "生成報告書", "做 PDF 報告", "做 DOCX 報告", "從 Markdown 出報告", "make a report", "compile report", or wants a structured deliverable (academic paper, business proposal, spec, government document). **Pipeline 採 5 步驟 phase flow：(1) 規劃+線上補充資料 → (2) 用資料擴充拓展 → (3) 編排內容 → (4) 用戶確認 → (5) 最後編排格式。底層實作為 Stage 0 (source probe) → Stage 1 (lock contract + topic-research) → Stage 1.5 (phase-3-outliner) → Stage 2 (per-section HTML generation + quality gate) → Stage 3 (PDF + DOCX parallel render)。** Do NOT use for slide decks (use ppt-master) or short notes.
```

---

#### A.3.2 §2 標題 + 開頭 5 步驟框架（插入於 L36 之前）

**§2 標題修改**：

```markdown
## 2. Pipeline — 5-Step Phase Flow（規劃→擴充→編排→確認→格式化）
```

**§2 開頭插入（5 步驟總覽）**：

```markdown
### 2.0 5 步驟 phase flow 總覽（給 sub-agent 與使用者的「心智模型」）

Report-master 對外提供 5 步驟 phase flow；底層實作為既有 Stage 0–3 + `workflows/*.md`。所有 sub-agent 在生成 / 修改 / 排錯時，**應以 5 步驟框架思考與溝通**，遇到具體指令再下鑽到對應 stage 與 workflow。

| 步驟 | 語意 | 底層 stage 對應 | 主要 workflow | sub-agent 行為 |
|------|------|----------------|----------------|----------------|
| **1. 規劃 + 線上補充資料** | 收斂使用者意圖 + 同步整合 web research | Stage 0 + Stage 1 | `topic-research`（整合進 planning）、`strategist` | 啟動 topic-research 蒐集 high-level 證據；Strategist 跑 10 Confirmations；**研究綁在規劃裡，不寫完才補** |
| **2. 用資料擴充拓展** | 寫作有憑有據，資料源 pin 進 prompt 可追溯 | Stage 1.5 → Stage 2 | `topic-research`（Content Expansion 子階段）、`executor` | Executor 對每節讀 `chapter_N_research.md`（如缺，自動觸發 topic-research + `web_search` 補足）；**所有資料源在 prompt 中顯式列出** |
| **3. 編排內容** | 結構先定，內容對齊骨架 | Stage 1.5（Outliner） | `phase-3-outliner` | 產出 `0_outline.md`（機讀藍圖）+ `0_outline_for_review.md`（人讀摘要）；每章標題、層級、核心問題、所需資料、預估字數 |
| **4. 用戶確認** | 看到結構 + 內容再確認；DOCX 還沒碰，改起來便宜 | （gate 階段） | `user-confirmation` | 等待使用者回覆「OK / 修改 / REDO」；寫入 `0_confirmed.json`；Executor 啟動前必讀此檔 |
| **5. 最後編排格式** | 純機械 export（DOCX / 粗體修復），內容不再變動 | Stage 2.5 → Stage 3 | `visual-review`（可選）、`html_to_pdf`、`html_to_docx` | 跑 export_checker 7 項驗收；任何內容異動 → 退回步驟 2（嚴禁在 step 5 改字 / 改措辭） |

**底層 Stage 編號 → 5 步驟 映射**：

```
Step 1 (規劃+研究)     = Stage 0 (source probe) + Stage 1 (Strategist) + topic-research 整合
Step 2 (擴充)          = Stage 2 (Executor) + topic-research Content Expansion
Step 3 (編排)          = Stage 1.5 (phase-3-outliner)  ← 注意：可在 Step 2 之前或之後，依「先骨架後肉 / 先肉後整骨」二擇一
Step 4 (確認)          = user-confirmation gate
Step 5 (格式化)        = Stage 2.5 (visual-review 可選) + Stage 3 (html_to_pdf + html_to_docx)
```

> **⚠️ Step 3 在流程中的位置是 wai 須明確決策的開放問題**（見 Section D.1 Q1）：是要「骨架先於肉」（Outliner 早於 Executor）還是「肉先於骨架」（Outliner 校對 Executor 輸出）？

#### 2.1 5 步驟的 Feedback Routing（步驟 4 → 退回規則）

**這段直接接續 2.0 之下，取代舊版 §4 表格。**

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
| Step 5 格式化 | Stage 2.5 + Stage 3 | `visual-review`（可選）、`html_to_pdf`、`html_to_docx` | `report_final.pdf`、`report_final.docx` | 使用者交付 |

---

```

**註**：§2 的原 ASCII 流程圖（L36–78）保留不動，作為底層 Stage 細節。在流程圖上方插入上述 5 步驟框架，**兩個視角並存**：上面是 5 步驟（user-facing），下面是 Stage X（developer-facing）。

---

#### A.3.3 §4 整章改寫（取代舊版「Stage 2.5 迭代觸發條件」）

**§4 新標題**：

```markdown
## 4. Step 4 反饋路由（Feedback Routing）

> 本章取代舊版「Stage 2.5 迭代觸發條件」。5 步驟框架下，**所有使用者回饋走 §2.1 的 feedback routing 三分類**（內容→Step 2、結構→Step 3、文字→Step 4 inline）。
> 舊版「>30% 大改 → 回 Stage 1」規則**保留為兜底**（適用於結構性崩壞或多步驟同時失敗），但**首選**走 feedback routing。
```

**§4 表格（替換 L123–128）**：

```markdown
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
```

---

#### A.3.4 §5 與其他 workflow 關係 — 小幅對齊

**修改 §5 標題**：

```markdown
## 5. 與其他 workflow 的關係（含 5 步驟歸屬標記）
```

**§5 ASCII 圖之後的描述清單（L155–162）修改**：

```markdown
- `topic-research`：Step 1（高層研究）+ Step 2（Content Expansion）— 雙重角色
- `generate-citations`：Step 1 期間呼叫（建立 / 更新 BibTeX + CSL）
- `phase-3-outliner`：**Step 3** 編排核心（吃 RQs → 產 Section Blueprint）
- `user-confirmation`：**Step 4** 確認 gate（讀 outline → 等使用者 → 寫 `0_confirmed.json`）
- `live-preview`：Step 5 期間呼叫（逐節瀏覽器預覽）
- `visual-review`：Step 5 之前可選跑（PDF 截圖自查）
- `revise`：Step 4 inline 反饋（純文字修訂，不退回）
- `resume-execute`：Step 2/3 斷點續傳
```

---

#### A.3.5 §10 失敗 / 求助指引 — 按 5 步驟重排

**§10 新標題**：

```markdown
## 10. 失敗 / 求助指引（依 5 步驟分類）
```

**§10 表格（替換 L256–262）**：

```markdown
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
| **Step 5** | `ExportCheckFailed: page count=0` | weasyprint 渲染失敗；檢查 HTML 結構與字體路徑 |
| **Step 5** | DOCX 內文殘留 `**` | 檢查 `bundle.py` 上游清理 + `html_to_docx` `handle_strong()`（見 C2 bold 修復） |
| **跨步驟** | pytest 任何 fail | 立即停止，問 wai |
| **跨步驟** | git conflict / 多 agent commits 衝突 | main agent resolve，不打斷 sub-agent |
```

---

#### A.3.6 §11 版本演進 — 新增 v1.3

**§11 表格新增 v1.3 行（L270 之後插入）**：

```markdown
| 版本 | 狀態 | 說明 |
|------|------|------|
| v0.0 | done | placeholder |
| v1.0 | done | Track B 完工：report_gen + quality_checker + html_to_* + validators + checkers + renderers + tests + examples |
| v1.1 | done | T3-1 Strategist workflow + T3-2 Executor workflow（逐節 + per-section quality gate） |
| v1.2 | done | Stage 1.5 Outliner 拆分 + User confirmation gate + topic-research v1.1 Content Expansion + DOCX bold 修復（4 大核心問題修復） |
| **v1.3** | **planned** | **5 步驟 sub-agent phase flow 上層抽象（規劃→擴充→編排→確認→格式化）+ feedback routing 三分類（取代舊 Stage 2.5 觸發規則）** |
| v2.0 | TBD | Stage 4 / pipeline-as-service；multi-locale |
```

**§11 表前說明（v1.0 標記更新）**：

```markdown
> **文件版本：v1.3** · 對應 SPEC.md v0.3 + architecture.md v1.0 + planning/skill-update-plan.md v1 · 2026-06-14
> **5 步驟 phase flow** 由 wai 於 2026-06-14 06:30 確認。
> **Reference**：reverse-engineer-ppt-master（相似設計哲學；HTML 中間格式 vs SVG 中間格式）
> **Inherits**：Spec-Lock anti-drift、role specialization (Strategist / Executor)、per-section quality gate、examples as integration tests、5 步驟 phase flow + feedback routing。
```

---

### A.4 跟既有 `workflows/*.md` 的關係 — mapping 表格

5 步驟是**上層 user-facing flow**，`workflows/*.md` 是**底層 steps**。每個 5 步驟可能對應 1–N 個既有 workflow：

| 5 步驟 | 主要 workflow | 次要 workflow | 角色定位 |
|--------|----------------|----------------|----------|
| **Step 1 規劃+研究** | `strategist.md` v1.2 | `topic-research.md` v1.1（前置 high-level 研究） | 上層：意圖收斂 + RQ 訂定；底層：10 Confirmations + 初步研究 |
| **Step 2 擴充** | `executor-base.md`（每節 HTML 生成） | `topic-research.md` v1.1 Content Expansion（per-chapter research） | 上層：資料源 pinned 進 prompt 寫作；底層：逐節 + per-section quality gate |
| **Step 3 編排** | `phase-3-outliner.md` v1.0 | （無） | 上層：結構先定、內容對齊骨架；底層：吃 RQs → 產 0_outline.md |
| **Step 4 確認** | `user-confirmation.md` v1.0 | `revise.md`（Step 4 inline 修訂） | 上層：等使用者回饋 + feedback routing；底層：JSON 旗標 + 單節 HTML 局部修訂 |
| **Step 5 格式化** | `html_to_pdf.py` + `html_to_docx_direct.py` | `visual-review.md`（可選） | 上層：純機械 export；底層：weasyprint + pandoc/python-docx |

**不重組 workflows**：

- 5 步驟是**邏輯層**（phase），既有 workflows 是**實作層**（step）— 兩者**不衝突**
- 5 步驟在 SKILL.md 對 agent 描述「現在在哪一步、要往哪走」；workflows 在 `workflows/*.md` 對 developer 描述「這步具體做什麼」
- `phase-3-outliner.md` 已經有 Step 3 的完整 spec；`user-confirmation.md` 已經有 Step 4 的完整 spec；**無需重組 workflows 內容**
- `topic-research.md` v1.1 已經在「3.5 Content Expansion」標記了它在 Step 2 的角色；**可選小修**：在 frontmatter description 加上「Step 1 (high-level) + Step 2 (per-chapter)」標記

**唯一需要調整的 workflow 標記**（在 §5 草稿已涵蓋）：

- `strategist.md` description 標記「Step 1」
- `topic-research.md` description 標記「Step 1 + Step 2」
- `executor-base.md` description 標記「Step 2」
- `phase-3-outliner.md` description 標記「Step 3」
- `user-confirmation.md` description 標記「Step 4（含 feedback routing）」
- `revise.md` description 標記「Step 4 inline」
- `visual-review.md` description 標記「Step 5（可選）」
- `html_to_pdf` / `html_to_docx_direct` 標記「Step 5」

> **⚠️ 上述 workflow description 標記屬於次要 polish 項，wai 可決策是否要一起做（見 Section D.1 Q2）**。

---

### A.5 是否要新增 chapter / section，還是融入既有章節

**結論：融入既有章節，不新增獨立 chapter**。

理由：

1. **既有 11 個章節已涵蓋所有必要視角**（pipeline / 角色 / lock / 差異 / 驗收 / 求助）；新增獨立 chapter 會造成資訊碎片化
2. **5 步驟的本質是 user-facing 抽象層**；融入 §2（pipeline 主章節）是自然的位置
3. **Feedback routing 取代 §4**（不是新增 §4.5）；章節編號穩定，外部 reference 連結（`README.md` 內的錨點）不破
4. **若新增獨立 chapter**（如「§2.5 5-Step Phase Flow」），會與既有 §2 Stage 0–3 細節**重複** — 兩段都講 pipeline，讀者困惑
5. **版本演進 §11** 是歷史紀錄專區，5 步驟 v1.3 的引入在 §11 已有位置

**唯一可能的新增**（次要）：

- 在 §2 之後、§3 之前**插入「§2.5 5 步驟速查表」**作為 cheat sheet（如果 §2 的內容量太大、讀者跳讀時需要快速對照）

  - **不建議**：會重複 §2.0 表格內容；用 reference 連結（§2.1 / §4.1）即可

---

### A.6 Feedback routing 規則要寫進 SKILL.md 哪裡

**寫入位置**：`§2.1 5 步驟的 Feedback Routing`（緊接 §2.0 5 步驟總覽之後）— 已見 A.3.2 草稿。

**為什麼放在 §2.1 而不是 §4**：

- §2 是 pipeline 主章節；feedback routing 是 5 步驟**邏輯的一部分**（不是附錄）
- §4 改寫為「Step 4 反饋路由（Feedback Routing）」是**標題**層級的對齊，內容與 §2.1 共用同一張表（互相 reference）
- 讀者無論從 §2 還是 §4 進入，都能快速找到 routing 規則

**§4 為何不直接刪除**：

- §4 還有**兜底規則**（§4.2）— 多步驟同時失敗、`lock_signature` 不一致、quality_checker 連續 BLOCKING 等**不屬於三分類**的場景
- 刪除 §4 會失去兜底規則的歸屬位置

**具體段落草稿**：見 A.3.2（A.3.2 末段「2.1 5 步驟的 Feedback Routing」）+ A.3.3（§4 整章改寫）。

---

### A.7 雙語 README 是否要同步（2026-06-14 新規則）

**結論**：**這次規劃不建議同步雙語 README**，但**強烈建議**在後續 v1.3 正式 commit 時同步。

理由：

1. **本次任務性質是「規劃」**（不出 commit），同步 README 屬於實作階段動作
2. **SKILL.md 改動的 5 步驟框架對 README 的影響**：
   - `README.md` 與 `README_zh.md` 的 **Progress 表格**可能需要加 v1.3 一行（但這是 sub-agent 完成 v1.3 commit 時再做）
   - `README.md` 與 `README_zh.md` 的 **Pipeline 章節** 應反映 5 步驟框架（這是 feature-level 變更，依 2026-06-14 wai 新規則應由 sub-agent 配對 commit）
3. **2026-06-14 新規則明確**：「sub-agent 交付新 feature 時，更新 README.md + README_zh.md 中該 feature 的描述、用法、example 引用」— 5 步驟框架**符合**新 feature 定義
4. **README 雙語同步時機**：
   - sub-agent 執行 v1.3 SKILL.md 改動時，**feature-level** 同步 Pipeline 章節 + Progress 表格
   - main agent 批次收尾時，**batch-level** 統一更新 footer 版本號
5. **本次「純規劃」**不做 README 改動 — 留給 v1.3 實作 commit

**如果 wai 堅持這次就同步 README**：

- 在 SKILL.md 改動後，**追加** README.md + README_zh.md 的 Pipeline 章節修訂草稿（在 planning/skill-update-plan.md 中加 Section E）
- 但**仍不實際改檔**（依硬規則）

**具體 README 雙語同步草稿（僅作為後續 v1.3 commit 參考，本次不執行）**：

`README.md` Pipeline 章節應加：

```markdown
## Pipeline — 5-Step Phase Flow

Report-master runs as a 5-step phase flow:

1. **Plan + Research** — Strategist runs 10 Confirmations, converges intent + research questions
2. **Expand with Data** — Executor writes per-section HTML with data sources pinned in prompt
3. **Structure** — Outliner produces Section Blueprint (0_outline.md)
4. **User Confirmation** — explicit human-in-the-loop gate (0_confirmed.json)
5. **Format** — mechanical PDF + DOCX export (no content changes)

Feedback routing: Step 4 rejections route to Step 2 (content), Step 3 (structure), or inline revise.
```

`README_zh.md` 對應章節鏡像翻譯即可。

---

## Section B: planning/tasks.md 改動計畫

### B.1 既有 task status 更新策略

**現狀**：

- `tasks.md` L155–165 列出「現有 40/40 之外的額外任務」表格（A1/A2/B1/C1/C2/D1）— 6 個任務對應 4 大核心問題修復
- 表格 status 欄位都是「**待做**」 — 雖然 MEMORY.md 記錄「4 大核心問題已修復（2026-06-13 16:48）」，`tasks.md` 卻未更新狀態

**更新策略**：**另開新章節**（不更新 6 個舊任務狀態）。

理由：

1. **既有 6 個任務的 status 更新應屬於「v1.2 完工驗收」工作**（2026-06-13 16:48 的 commit 應一起改 tasks.md），這是**追溯性維護**，不是 v1.3 工作範圍
2. **本次 v1.3 規劃的新工作**（5 步驟 + feedback routing 寫入 SKILL.md / tasks.md / skill meta）性質與既有 6 個任務**完全不同**（後者是「4 大核心問題的 workflow 實作」，前者是「上層抽象的文件化」）
3. **另開新章節**（「Phase E: Pipeline Refinement」或「Phase 4: 5-Step Phase Flow Documentation」）— 給 wai 乾淨的決策位置

**建議章節命名**：

| 候選 | 優點 | 缺點 |
|------|------|------|
| **「Phase 4: 5-Step Phase Flow」** | 編號連續；明示是 Phase 3 之後的 refinement | 與既有「Phase A/B/C」命名不一致（既有用 A/B/C/D） |
| **「Phase E: Pipeline Refinement」** | 對齊既有 A/B/C/D 命名 | 「E」容易與既有 D1 (End-to-end) 混淆 |
| **「Phase 4 (Refinement): 5-Step Phase Flow」** | 編號連續 + 對齊命名 | 較長 |
| **「Appendix: 5-Step Phase Flow 寫入」** | 不汙染 Phase A/B/C 結構 | 容易被忽略 |

**wai 須明確決策**（見 Section D.1 Q3）。

**本次規劃採保守策略**：在 `tasks.md` 末尾加 **`## Phase 4: 5-Step Phase Flow 寫入`** 章節（與既有 A/B/C/D 章節結構對齊，編號用 4 表示 refinement 階段），不更動既有 6 個任務的 status。

---

### B.2 新章節「Phase 4: 5-Step Phase Flow 寫入」草稿

**插入位置**：`tasks.md` L165（既有「現有 40/40 之外的額外任務」表格）**之後**。

**完整 markdown（可直接 copy-paste）**：

```markdown
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
```

---

### B.3 既有 task status 要不要更新

**見 B.1 結論**：不更新既有 6 個任務狀態（追溯性維護，屬 E4 範圍，可選）。

**不更新理由**（加強版）：

1. **本次規劃的純度** — wai 給的任務是「5 步驟 phase flow 寫入」，不是「追溯性維護 tasks.md」
2. **既有 6 個任務的狀態更新應綁定當時的 commit**（2026-06-13 16:48 修復 4 大核心問題的那次 commit 應同時改 tasks.md）— 這是過去的疏漏，本次不追溯
3. **若 wai 認為應一起做** — 透過 E4 task 處理（已列在 B.2 Phase 4 草稿）

**替代方案**（若 wai 認為本節太保守）：

- **方案 A**（激進）：本節就把既有 6 個任務的 status 全改為 ✅ done，並把 MEMORY.md 對應的 commit hash 填入
- **方案 B**（保守，本規劃採用）：另開 Phase 4 章節，E4 處理追溯
- **方案 C**（最保守）：完全跳過既有 6 個任務的 status 更新，留給下次 wai 主動要求時

**wai 須明確決策**（見 Section D.1 Q3）。

---

### B.4 Task bullet 草稿（具體可貼的 markdown）

完整草稿見 **B.2**（已含完整 markdown，可直接 copy-paste 到 `tasks.md` 末尾）。

**bullet 風格對齊**：

- 對齊既有 `### A1:` / `### B1:` / `### C1:` / `### C2:` / `### D1:` 格式
- 對齊既有「**等級**:」/「**預估**:」/「**做什麼**:」/「**DoD**:」/「**交付**:」五段式
- 對齊既有「**Phase X 依賴關係**」+「**Phase X 預估總工時**」兩個結尾表格

---

## Section C: skill meta 更新計畫

### C.1 目標檔案

`~/.openclaw/workspace/skills/report-master-dev/SKILL.md`（meta skill — 描述 Report-master Phase 3+ sub-agent 開發 workflow，含批次、DoD、git 規則）

**現有 frontmatter**（L1–5）：

```yaml
---
name: "report-master-dev"
description: "Report-master Phase 3 sub-agent development workflow: batches, DoD, git rules, Phase 3 dependency graph"
---
```

**現有版本演進**：**無獨立版本演進區段**（內容混在 main body）。

---

### C.2 是否要更新 description / version

**結論**：**只更新 description**（不獨立設 version — 此 meta skill 沒有正式的 version 欄位機制，與 project 內 SKILL.md 結構不同）。

**理由**：

1. **description 影響 OpenClaw 觸發判斷** — 5 步驟 phase flow 是新特徵，應在 description 提及以便正確觸發
2. **不獨立設 version 欄位** — 既有 frontmatter 沒有 `version:` 欄位，無對齊慣例；如要加，需評估是否所有 meta skill 都加
3. **內容 body 修改** — 在「Phase 3 依賴關係圖」後面加一段「Phase 4: 5-Step Phase Flow 寫入（v1.3 配套）」指引

---

### C.3 Diff 草稿（具體可貼的 markdown）

**修改 1：frontmatter description（L2）**

**原**：

```yaml
description: "Report-master Phase 3 sub-agent development workflow: batches, DoD, git rules, Phase 3 dependency graph"
```

**新**：

```yaml
description: "Report-master Phase 3+ sub-agent development workflow: batches, DoD, git rules, Phase 3 dependency graph, plus v1.3 5-step phase flow documentation (規劃→擴充→編排→確認→格式化)"
```

**字數檢查**：草稿 145 bytes 為估計值。**實測 195 bytes**（超 160 上限）— sub-agent #2 跑前 byte count 才發現，現場縮寫為 155 bytes 通過。下次規劃 description 要用 `printf '%s' "..." | wc -c` 實際 byte count 驗證，**不要目測 / 不要 trim("看起來差不多")**。

---

**修改 2：main body 新增「5 步驟 phase flow 對 sub-agent 開發的影響」段**

**插入位置**：`## Phase 3 完成後` 之前（L222 之前，依目前檔案結構）

**新增段**：

```markdown
## v1.3 配套：5 步驟 phase flow 文件化

當 wai 指示「5 步驟 phase flow 寫進 SKILL.md」時，sub-agent 應：

### 工作範圍
- 改 `./SKILL.md`（v1.0 → v1.3）— 見 `planning/skill-update-plan.md` Section A
- 改 `./planning/tasks.md`（新增 Phase 4 章節）— 見 Section B
- 改本 meta SKILL.md（description + 5 步驟說明）— 見 Section C
- 改 `./README.md` + `./README_zh.md`（雙語同步，2026-06-14 新規則）— 見 Section A.7

### DoD（v1.3 文件化）
- 5 步驟都在 SKILL.md §2.0 表格中（規劃、擴充、編排、確認、格式化）
- Feedback routing 三分類都在 §2.1 + §4.1 中（內容→Step 2、結構→Step 3、文字→Step 4 inline）
- 既有 pytest 428 pass 不回歸（文件改動理論上不影響 tests）
- README 雙語一致

### Sub-agent 工作模式
- **單 sub-agent** 完成 E1+E2+E3（同批次）
- **不 push** — main agent 統一 push
- **README 同步** = sub-agent 責任（feature-level）

### 不做
- ❌ 不實際改 `workflows/*.md` 的 description（次要 polish，由 wai 決策）
- ❌ 不改既有 6 個 tasks.md 追溯性 status（屬 E4，可選）
- ❌ 不跑 E5 端到端驗收（延後到首次實際使用）
- ❌ 不 push / 不碰 workspace root git
```

---

### C.4 Git 推送策略（屬 main agent 責任，非 sub-agent）

E1+E2+E3 完成後，main agent 批次收尾：

```bash
# E1+E2+E3 同 commit
git add SKILL.md README.md README_zh.md
git commit -m "feat(report-master): v1.3 5-step phase flow + feedback routing (E1+E2)"

# E3 skill meta 與 project 內檔案分屬不同 repo，不綁同 commit
# E3 由 sub-agent 編輯 workspace repo，main agent 統一 push
```

**提醒**：

- `projects/report-master/.git/` 是獨立 repo（HTTP404Not-Found/Report-master）
- `~/.openclaw/workspace/.git/` 是 workspace root repo
- E3 改的是 workspace repo 的 `skills/report-master-dev/SKILL.md`，不歸 Report-master repo
- **兩個 repo 分別 push**，不能混

---

## Section D: 風險 + 開放問題

### D.1 wai 須明確決策的開放問題

| Q# | 問題 | 預設建議 | 影響 |
|----|------|----------|------|
| **Q1** | **Step 3（編排）在流程中的位置**：是「骨架先於肉」（Outliner 早於 Executor，在 Step 1 後 Step 2 前）還是「肉先於骨架」（Outliner 校對 Executor 輸出，在 Step 2 後 Step 4 前）？ | 「骨架先於肉」— 對齊現有 `phase-3-outliner.md` 設計 | 影響 §2.0 表格的 stage 映射說明；影響 E1 草稿的「Step 3 對應 stage 1.5」措辭 |
| **Q2** | **是否要同步修 workflow description 標記**（如 `phase-3-outliner.md` description 加「Step 3」標記）？ | 不做 — 屬次要 polish，留給下次清理 | 影響 E1 範圍；若要做，E1 工時 +30min，且要更新 `tests/test_workflow_docs.py` 確保測試仍綠 |
| **Q3** | **新章節命名**：「Phase 4」/「Phase E」/「Appendix」？ | 「Phase 4: 5-Step Phase Flow 寫入」 | 影響 B.2 草稿的章節標題；屬 cosmetic，但對後續引用一致性有影響 |
| **Q4** | **既有 6 個 tasks.md 任務狀態更新**：本次不做 / 順便做 / 另開 commit 做？ | 另開 commit 做（E4） | 影響 E4 是否列為必做 |
| **Q5** | **雙語 README 同步時機**：本次就同步 / 留給 v1.3 commit 時同步 / 留給下個批次？ | 留給 v1.3 commit 時同步（sub-agent feature-level） | 影響 E2 是否列為必做 |
| **Q6** | **E5 端到端驗收**時機：v1.3 commit 前 / 後？ | 後（首次實際使用時做） | 影響 E5 是否列為必做 |
| **Q7** | **5 步驟 vs 既有 Stage 編號的長期路線**：5 步驟是過渡（v1.3 之後會被取代）還是終態？ | 終態（5 步驟是 user-facing 抽象；Stage X 是 developer-facing 實作，兩者長期共存） | 影響 §2.0 的「底層 Stage 編號 → 5 步驟映射」是否要強化說明 |
| **Q8** | **MEMORY.md 是否同步更新**（加「5 步驟 phase flow 已寫入 SKILL.md v1.3」一行）？ | 是 — 屬 wai MEMORY 維護規則的觸發（wai 顯式決策） | 影響 v1.3 commit 後的 MEMORY.md 更新；本次規劃不實際改 MEMORY.md |

---

### D.2 既有 workflows 衝突 / 重疊分析

**5 步驟 vs 既有 phase-3 / strategist 銜接**：

| workflow | 與 5 步驟關係 | 衝突 / 重疊 |
|----------|----------------|--------------|
| `strategist.md` v1.2 | Step 1 核心 — 收斂意圖 + 產 RQ1…RQn | **無衝突** — Strategist 原本就對應 Step 1；5 步驟強化「研究綁在規劃裡」的語意 |
| `phase-3-outliner.md` v1.0 | Step 3 核心 — 產 0_outline.md | **無衝突** — Outliner 原本就對應 Step 3；5 步驟強化「結構先定、內容對齊骨架」 |
| `user-confirmation.md` v1.0 | Step 4 核心 — 等使用者回饋 | **無衝突** — User confirmation 原本就對應 Step 4；**小補充**：5 步驟新增 feedback routing 三分類，使 Step 4 內部邏輯更清楚 |
| `topic-research.md` v1.1 | Step 1（high-level）+ Step 2（Content Expansion）— 雙重角色 | **無衝突** — topic-research v1.1 已在「3.5 Content Expansion」標記 Step 2 角色；5 步驟只是顯式強調雙重角色 |
| `executor-base.md` | Step 2 核心 — 逐節 HTML 生成 | **無衝突** — Executor 原本就對應 Step 2；5 步驟強化「資料源 pin 進 prompt」 |
| `revise.md` v1.0 | Step 4 inline 修訂（純文字） | **無衝突** — Revise 原本就是 Stage 2.5 局部修訂；5 步驟將其歸入 Step 4 inline feedback routing |
| `visual-review.md` v1.0 | Step 5 可選（PDF 截圖自查） | **無衝突** |
| `error-handling.md` v1.0 | 跨步驟失敗分類 | **無衝突** — 5 步驟是正常流程；error-handling 處理異常 |
| `create-template.md`、`resume-execute.md`、`generate-citations.md`、`live-preview.md`、`technical-design.md`、`docs-and-rules.md` | 既有支援 workflow | **無衝突** — 5 步驟不覆蓋這些 |

**總結**：5 步驟與既有 workflows **無根本衝突**；5 步驟是**新上層抽象**（user-facing），workflows 是**底層實作**（developer-facing）。**重疊部分**（Step 1 ↔ strategist、Step 3 ↔ phase-3-outliner、Step 4 ↔ user-confirmation）是**強化語意**而非取代。

**唯一需注意**：

- `revise.md` 描述中提到「Stage 2.5 revise workflow」— 5 步驟下屬於「Step 4 inline 修訂」— 描述措辭可選修（**wai 決策，見 D.1 Q2**）
- `topic-research.md` 描述中提到「research_content 階段」— 5 步驟下屬於「Step 2 Content Expansion」— 描述措辭可選修

---

### D.3 pytest 風險評估

**目標**：428 pass 維持，**不掛任何測試**。

**改動影響分析**：

| 改動 | 影響 tests 的可能性 | 理由 |
|------|---------------------|------|
| `SKILL.md` frontmatter description 修改 | **極低** | description 是純 metadata，無 test 解析 |
| `SKILL.md` §2 插入 5 步驟框架 | **極低** | SKILL.md 不是 test 解析目標 |
| `SKILL.md` §4 改寫 | **極低** | 同上 |
| `SKILL.md` §5 / §10 / §11 修改 | **極低** | 同上 |
| `README.md` / `README_zh.md` 修改 | **極低** | README 不是 test 解析目標（**確認**：`tests/test_examples.py` 只檢查 example 產出；不檢查 README） |
| `tasks.md` 新增 Phase 4 章節 | **極低** | tasks.md 不是 test 解析目標 |
| `skills/report-master-dev/SKILL.md` description 修改 | **零** | workspace skill meta 不在 `projects/report-master/.venv` 範圍 |

**可能有風險的測試**（需 sub-agent 跑一次確認）：

- `tests/test_workflow_docs.py` — 解析 `workflows/strategist.md` / `user-confirmation.md` / `topic-research.md` 的 frontmatter；**不解析** SKILL.md 也不解析 README，**理論上不受影響**
- `tests/test_web_research.py` — 解析 `workflows/topic-research.md` 含 research_content 階段；**不解析** SKILL.md，**理論上不受影響**

**建議 pytest 流程**（v1.3 commit 時）：

```bash
cd /home/ubuntu/.openclaw/workspace/projects/report-master
.venv/bin/pytest tests/ -q
# 預期：428 pass / 0 fail
```

**如 pytest 失敗**：

- 立即停止，**不 commit**
- revert 所有改動
- 問 wai 決策

**結論**：pytest 風險**極低**，**但 sub-agent 仍須跑一次**確認（wai 可要求）。

---

### D.4 跟 4 大核心問題的相容性

4 大核心問題（2026-06-13 16:48 修復）：

1. **章節藍圖（Outliner workflow）** — `phase-3-outliner.md` v1.0
2. **用戶確認閘道（User confirmation workflow）** — `user-confirmation.md` v1.0
3. **網路研究整合（topic-research + web_search）** — `topic-research.md` v1.1 + `scripts/web_research.py`
4. **DOCX 粗體格式修復（html_to_docx_direct.py）** — `tests/test_bold_formatting.py`

**5 步驟與 4 大核心問題的關係**：

| 5 步驟 | 對應 4 大核心問題 | 整合 or 取代？ |
|--------|-------------------|----------------|
| **Step 1（規劃+研究）** | 問題 3 修復（topic-research v1.1 整合進規劃） | **整合** — 5 步驟將「研究綁在規劃裡」明確化 |
| **Step 2（擴充）** | 問題 3 修復（per-chapter research via web_search） | **整合** — Step 2 強化「資料源 pin 進 prompt 可追溯」 |
| **Step 3（編排）** | 問題 1 修復（章節藍圖 Outliner） | **整合** — Step 3 顯式承擔 Outliner 角色 |
| **Step 4（確認）** | 問題 2 修復（用戶確認閘道） | **整合** — Step 4 顯式承擔 User confirmation 角色 + 新增 feedback routing |
| **Step 5（格式化）** | 問題 4 修復（DOCX 粗體） | **整合** — Step 5 顯式承擔「純機械 export」角色（粗體修復是其中一個子任務） |

**結論**：5 步驟**完全整合** 4 大核心問題，**不取代**任何既有修復。5 步驟是**上層抽象**（user-facing），4 大核心問題修復是**底層實作**（developer-facing）；兩者**長期共存**。

**重要驗證點**（sub-agent 跑 v1.3 commit 時確認）：

- 既有 4 大核心問題的 workflow（`phase-3-outliner.md` / `user-confirmation.md` / `topic-research.md` v1.1 / `html_to_docx_direct.py`）**不修改**
- 既有測試（`tests/test_workflow_docs.py` / `tests/test_web_research.py` / `tests/test_bold_formatting.py`）**全綠**
- MEMORY.md 記載的「4 大核心問題已修復」**持續為真**

---

### D.5 5 步驟的長術語風險

5 步驟的命名（規劃 / 擴充 / 編排 / 確認 / 格式化）對應英文：

- 規劃 = Plan
- 擴充 = Expand (with data)
- 編排 = Structure / Arrange
- 確認 = Confirm
- 格式化 = Format

**風險**：中英對照可能在 SKILL.md / README 雙語 / workflow description 中產生**語意漂移**。

**緩解**：

- SKILL.md 5 步驟表使用**中文為主、英文括號**
- README 雙語各自用在地語言描述（en 用 Plan/Expand/Structure/Confirm/Format；zh 用規劃/擴充/編排/確認/格式化）
- workflow description 維持現有措辭（如 `phase-3-outliner.md` description 仍用 Section Blueprint），不強制對齊 5 步驟英文命名

**wai 可決策**（見 D.1 隱含問題）：5 步驟的**官方英文命名**為何？建議**Plan / Expand / Structure / Confirm / Format** — 簡潔、動詞、與中文對齊。

---

## 附錄：規劃過程檢查清單

- [x] Section A：SKILL.md 改動計畫（含章節結構、插入位置、完整草稿、workflow 關係、章節決策、feedback routing 位置、README 同步建議）
- [x] Section B：planning/tasks.md 改動計畫（含 status 更新策略、新章節草稿、既有 task 處理、bullet 草稿）
- [x] Section C：skill meta 更新計畫（含 diff 草稿、git 推送策略）
- [x] Section D：風險 + 開放問題（含 8 個 wai 須明確決策的 Q、workflow 衝突分析、pytest 風險、4 大核心問題相容性、長術語風險）

**未實際改檔**（依硬規則）：

- [x] 不改 `./SKILL.md`
- [x] 不改 `./planning/tasks.md`
- [x] 不改 `./workflows/*.md`
- [x] 不改 skill meta
- [x] 不 git add / commit / push
- [x] 不跑 pytest
- [x] 不安裝套件 / deploy

---

*規劃文件 v1 · 2026-06-14 06:33 GMT+8 · sub-agent depth 1/1*
