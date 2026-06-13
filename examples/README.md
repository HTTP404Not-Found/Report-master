# examples/ — Report-master 範例

> 對應 architecture.md §介面定義 + AGENTS.md §4
> Phase 1 範例：最小可跑的 smoke test；Phase 3 計劃擴充至 23+ 完整 example reports。

## 檔案

| 檔案 | 用途 |
|------|------|
| `section_1.html` | 1 節 HTML，符合 `docs/shared-standards.md` 子集 |
| `lock.md` | `report_lock.md` 範例（17 required 欄位齊備） |
| `README.md` | 本檔 |

## Smoke test

```bash
# 確保 venv 內有 weasyprint + pyyaml
.venv/bin/pip install weasyprint pyyaml

# 跑全 pipeline
python -m scripts.report_gen \
  --source examples \
  --output /tmp/rm-test \
  --lock examples/lock.md
```

預期產出：
- `/tmp/rm-test/_bundle.html`（自動 bundle）
- `/tmp/rm-test/report_<timestamp>.pdf`
- `/tmp/rm-test/report_<timestamp>.docx`

最後一條 exit code 為 0 = PASS。

## 在 pytest 內執行

```bash
export PATH=$HOME/.local/pandoc/bin:$PATH   # 若 pandoc 為手動安裝
.venv/bin/pytest tests/ -q
```