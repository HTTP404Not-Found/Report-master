# AGENTS.md — Report-master 入口

> 給 **general AI agent**（含 sub-agent）讀的入口文件。
> 讀完這份就應該知道：要從哪裡看 spec、跑什麼指令、檔案在哪裡。

---

## 1. 這是什麼

**Report-master** = AI-driven 報告書生成系統。輸出格式是 **PDF + DOCX**，不是簡報。
核心精神見 `SPEC.md §1`（概念）、`SPEC.md §2`（設計哲學）。

- 中間格式：**HTML**（LLM 生成最可靠的標記格式）
- 雙交付物：weasyprint → PDF、pandoc → DOCX
- 防 drift：`report_lock.md`（機器可讀執行合同）+ `glossary.md`（術語表）
- 字體鎖死：中 = 標楷體、英 = Times New Roman（不可覆寫）

---

## 2. 先讀這三份，再開工

1. **`SPEC.md`** — 規格書（概念、pipeline、字體與排版硬性規則、風險）
2. **`architecture.md`** — 系統架構（元件清單、Mermaid pipeline 圖、資料流、ADR）
3. **`tasks.md`** — 任務清單 + 里程碑 + 優先級 + 相依關係

`REVIEW.md` 是另一個 senior architect 對 SPEC 的審稿，可讀可不讀。

---

## 3. 讀寫規則

| 規則 | 來源 |
|------|------|
| HTML/CSS 子集（禁用 Grid/Flex/positioning/::before/::after） | `docs/shared-standards.md` |
| `report_lock.md` YAML schema 與 required 欄位 | `docs/report_lock_schema.md` |
| 字體策略（標楷體 + Times New Roman、授權） | `fonts/README.md` + `LICENSES.md` |
| 環境變數命名 | `docs/.env.example` |
| 術語表結構 | `docs/glossary.md` |

---

## 4. 目錄地圖（Track A + B 完工後）

```
projects/report-master/
├── AGENTS.md                  ← 你正在讀這份
├── SKILL.md                   ← 主 workflow authority（Track B）
├── SPEC.md / architecture.md / tasks.md / REVIEW.md
├── docs/                      ← Track A：schema / 標準 / glossary / .env.example
├── fonts/                     ← Track A：README + LICENSES（不內含真字體）
├── scripts/                   ← Track A：config / project_manager / report_lock
│   ├── source_to_md/          ← Track A：pdf_to_md / docx_to_md / url_to_md / md_normalizer
│   ├── report_gen.py          ← Track B
│   ├── quality_checker.py     ← Track B
│   ├── html_to_*.py           ← Track B
│   ├── *_validator.py         ← Track B
│   ├── *_checker.py           ← Track B
│   ├── mermaid_renderer.py    ← Track B
│   ├── katex_renderer.py      ← Track B
│   ├── toc_generator.py       ← Track B
│   └── footnote_manager.py    ← Track B
├── tests/                     ← Track A：test_config / test_project_manager / test_source_to_md
└── examples/                  ← Phase 3 才填，先留空
```

---

## 5. CLI（v0.1）

| 指令 | 用途 |
|------|------|
| `python scripts/project_manager.py init <path> [--type academic|...]` | 初始化專案（建目錄、產 lock 模板） |
| `python scripts/config.py check` | 字體 + .env fail-fast 檢查 |

（其餘指令見 `architecture.md §介面定義`；Track B 補上 `report-master` 統一 CLI。）

---

## 6. Stage 流程（serial pipeline）

```
Stage 0  Format Probe + source_to_md  ← Track A 已就緒
Stage 1  規劃（Strategist + report_lock.md）
Stage 2  生成（Executor 逐節 HTML + per-section quality gate）
Stage 2.5  迭代（v1→review→v2）
Stage 3  工程轉換（PDF + DOCX 平行 + export_checker）
```

---

## 7. 不要做的事

- ❌ 不要 push（Track A / Track B 完成後由 main agent 統一 commit + push）
- ❌ 不要修改 `SPEC.md` / `architecture.md` / `tasks.md` / `REVIEW.md`
- ❌ 不要在 `fonts/` 內含真字體（僅放 README + LICENSES）
- ❌ 不要裝全局 Python package（用 `projects/report-master/.venv`）
- ❌ 不要平行跑 section sub-agent（敘事必漂移）

---

## 8. 報錯 / 求助

- 字體 fail-fast 例外 → 見 `fonts/README.md` 安裝指引
- `report_lock.md` 缺 required 欄位 → BLOCKING，補欄位後重跑
- HTML 含禁用 CSS → BLOCKING，見 `docs/shared-standards.md` 修正

---

*AGENTS.md v0.1 — Track A foundation, 2026-06-13*
