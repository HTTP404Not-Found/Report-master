# Report-master 系統重新規劃背景

## 現有系統問題（4個根本缺陷）
1. 沒有內容編排規劃：Strategist 沒有章節藍圖能力
2. 沒有用户確認環節：pipeline 沒有停等確認就直接執行
3. 沒有網路搜尋拓展：沒有 web_search 能力補充内容
4. DOCX 殘留 `**` 格式：Markdown bold 没有轉成真正 Word 粗體

## 現有 Phase 3 架構（已完工 40/40）
- Strategist / Executor / topic-research / create-template / resume-execute
- generate-citations / live-preview / visual-review / revise / error-handling
- technical-design / docs-and-rules / examples × 2 / CI

## 規劃目標
重新設計 Phase 3+ 的 user-facing workflow，加入：
- 章節藍圖（Outline）規劃階段
- 使用者確認 loop（停等 user input）
- 網路研究整合（web_search + 內容拓展）
- 乾淨的 DOCX 輸出（無殘留 Markdown 語法）
