# Report-master 系統重新規劃 / System Redesign Brief

## 問題陳述

Report-master 現有 Phase 3 workflow 存在 4 個根本缺陷，導致無法實際生成高品質研究報告：

| 缺陷 | 影響 |
|---|---|
| 沒有內容編排規劃 | Strategist 只收集主題，沒有「章節藍圖」輸出；Executor 不知道每章該寫什麼 |
| 沒有用户確認環節 | Strategist 輸出未經確認就進入執行階段；用戶最後看到的是成品而非他們要的內容 |
| 沒有網路搜尋拓展 | 章節內容依賴 LLM 自行推估，沒有事實查證 / 數據補充 |
| DOCX 殘留 `**` 格式 | 輸出 Word 文件仍有 Markdown bold 語法殘留，格式崩壞 |

## 專案目標

### MVP 範圍（必做）
1. **Outline Workflow**（`phase-3-outliner`）：Strategist 完成主題分析後，新增「章節藍圖」階段，輸出 `report_output/0_outline.md`，明確定義：
   - 各章節標題、層級、每章核心問題
   - 每章需要的資料類型（文獻 / 數據 / 案例）
   - 章節之間的邏輯順序與過渡
2. **User Confirmation Loop**：Outline 完成後**停等用戶確認**，產出 `report_output/0_outline_for_review.md`，收到「OK」才進入執行
3. **Content Research Integration**：在 Executor 執行每章前，自動呼叫 `topic-research` + `web_search` 拓展內容
4. **DOCX Clean Output**：修復 `html_to_docx_direct.py` 的 `<strong>` / `<b>` → 真正 Word bold，確保 `**` 不出現在最終文件

### 進階功能（選做）
- 即時進度追蹤（`report_output/progress.json`）
- 多輪修訂循环（用户可在任何階段喊停要求修訂）
- 自動引用格式檢查（Generate-Citations 與實際內文的一致性）

### Out of Scope
- Phase 0 / Phase 1 / Phase 2 的底層 pipeline（HTML→MD→DOCX 核心已穩定）
- Track A / Track B 的單元測試重構
- 非 python-docx 的輸出格式（LaTeX、ODT）

## 技術選型

| 元件 | 選擇 | 原因 |
|---|---|---|
| 確認機制 | `report_output/0_confirmed.json` 檔案開關 | 簡單、無狀態、可擴展成 API |
| 網路搜尋 | `web_search` tool（已存在） | 符合現有 OpenClaw tool 架構 |
| 章節藍圖格式 | Markdown table + 結構化 frontmatter | 可讀、可 version control |
| DOCX bold 修復 | `python-docx` API `bold=True` | 現有 html_to_docx_direct.py 已用 python-docx |
| 用戶輸入介面 | Telegram 回覆 + `report_output/` 檔案 | 符合 WAI 的使用情境 |

## 成功指標

| 指標 | 測量方式 |
|---|---|
| Outline 產生率 | 100% 的 report 請求都產出 `0_outline.md` |
| 確認率 | 每個 outline 都經過用户確認（`0_confirmed.json` 存在） |
| 搜尋覆蓋率 | 每個 research query 章節都有對應的 `*_research.md` |
| DOCX 乾淨度 | 最終 `.docx` 內文無 `**`、`__`、`##` 等 Markdown 語法 |
| 格式正確率 | DOCX 的 `<strong>` → Word bold 轉換 100% 正確 |

## 時間規劃

| 階段 | 里程碑 |
|---|---|
| Phase A | Outline workflow + user confirmation（2–3 個 sub-agent tasks） |
| Phase B | Content research integration + web_search（1–2 個 sub-agent tasks） |
| Phase C | DOCX bold fix + test_bold_formatting.py（1 個 sub-agent task） |
| Phase D | End-to-end smoke test × 2 examples（1 個 sub-agent task） |
