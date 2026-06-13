# glossary.md — 術語表範本

> 對應 SPEC.md §6.1 R3（敘事 drift 防禦）+ `tasks.md` T0-3
> Executor 每節開始前**先讀這份**，確保術語譯名一致。

---

## 1. 格式

每條術語條目結構：

| 欄位 | 必填 | 說明 |
|------|------|------|
| **術語** | ✅ | 原文（英文 / 中文） |
| **定義** | ✅ | 一句話定義 |
| **譯名** | ✅ | 約定譯法（若為英文術語） |
| **首次出現** | optional | 章節 ID，例如 `§2.1` |
| **同義詞** | optional | 可替換的詞彙（用於敘事一致檢查） |

格式：Markdown 條目列表 / YAML frontmatter（兩者皆可，見範例）。

---

## 2. Markdown 範本

```markdown
# glossary.md

> 範例學術論文 — 術語表
> 產生時間：2026-06-13

## 條目

### 1. Large Language Model
- **術語**：Large Language Model (LLM)
- **定義**：基於 transformer 架構、在大規模文本上預訓練的語言模型。
- **譯名**：大型語言模型
- **首次出現**：§2.1
- **同義詞**：大語言模型、大型語言模型（LLM）、大型語言模型

### 2. Retrieval-Augmented Generation
- **術語**：Retrieval-Augmented Generation (RAG)
- **定義**：結合資訊檢索與生成式模型的技術框架。
- **譯名**：檢索增強生成
- **首次出現**：§2.2
- **同義詞**：RAG、檢索增強生成

### 3. Neural Network
- **術語**：Neural Network
- **定義**：受人腦結構啟發的計算模型，由多層神經元組成。
- **譯名**：神經網路
- **首次出現**：§2.3
- **同義詞**：神經網路、神經網絡、人工神經網路
```

---

## 3. YAML 範本

若要機器讀寫，可在 frontmatter 用 YAML：

```yaml
---
glossary_version: 1
project: demo-academic
entries:
  - term: Large Language Model
    abbr: LLM
    definition: 基於 transformer 架構、在大規模文本上預訓練的語言模型。
    translation: 大型語言模型
    first_seen: §2.1
    synonyms:
      - 大語言模型
      - 大型語言模型（LLM）
  - term: Retrieval-Augmented Generation
    abbr: RAG
    definition: 結合資訊檢索與生成式模型的技術框架。
    translation: 檢索增強生成
    first_seen: §2.2
    synonyms:
      - RAG
      - 檢索增強生成
  - term: Neural Network
    definition: 受人腦結構啟發的計算模型，由多層神經元組成。
    translation: 神經網路
    first_seen: §2.3
    synonyms:
      - 神經網路
      - 神經網絡
      - 人工神經網路
---

# glossary.md

（YAML 為主，Markdown 為人類可讀版本）
```

---

## 4. ≥3 條範例（必填，給 `project_manager.py` 當預設內容）

以下是**強制預設**的 3 條範例，新專案初始化時寫入 `glossary.md`，使用者可在 Stage 1 編輯：

### 範例 1：MarkDown
- **術語**：Markdown
- **定義**：輕量標記語言，使用易讀易寫的純文字格式。
- **譯名**：Markdown（不譯，保留原文）
- **首次出現**：§1.1
- **同義詞**：md、MD、Markdown 格式

### 範例 2：Pipeline
- **術語**：Pipeline
- **定義**：資料由輸入到輸出所經過的處理階段鏈。
- **譯名**：管線 / 流水線
- **首次出現**：§1.2
- **同義詞**：管線、流水線、處理流程

### 範例 3：Anti-drift Mechanism
- **術語**：Anti-drift Mechanism
- **定義**：防止長篇內容隨生成過程產生累積偏差的機制。
- **譯名**：防漂移機制
- **首次出現**：§2.3
- **同義詞**：防漂移、防 drift、漂移防禦

---

## 5. Executor 引用規則

```
1. 每節開始前，Executor 讀 glossary.md
2. 對節內所有術語，優先使用「譯名」；若無譯名則用原文
3. 若節內出現「同義詞」清單中任一詞，需在 quality_checker 報告中標記
4. 若新增術語（節內首次出現），更新 first_seen 並標記為「新增」
```

---

## 6. 與 SPEC.md / quality_checker 的關係

- **SPEC.md §6.1 R3**：glossary.md + 每節重讀 + cross-ref 驗證
- **quality_checker.py**：掃描節內首次出現的術語是否在 glossary 中；若無則 WARN（不 BLOCKING，因允許新增）

---

*glossary.md v1 — 對應 SPEC.md v0.3 §6.1 R3, 2026-06-13*
