"""scripts/project_manager.py — 專案初始化。

對應 `tasks.md` T1-2、T0-5。
- init_project(path, template)：建立目錄樹 + 產 lock 模板 + 產 glossary 空檔
- CLI：`python scripts/project_manager.py init <path> [--type academic|...]`

目錄樹（對應 SPEC §4 + architecture.md）：
  <project>/
  ├── report_lock.md          (template 產出)
  ├── report_spec.md          (空白範本)
  ├── glossary.md             (≥3 條範例)
  ├── assets/                 (圖片、SVG、PNG)
  ├── report_output/          (Stage 2 輸出)
  ├── exports/                (Stage 3 輸出)
  ├── backup/                 (Stage 3 存檔)
  ├── csl/                    (引用樣式)
  ├── bib/                    (BibTeX)
  └── examples/               (本地參考)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 允許 CLI 直接執行（`python scripts/project_manager.py`）
# 把 project root 加到 sys.path，讓 `from scripts.config import ...` 可用
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.config import Config, FontNotFoundError  # noqa: E402
from scripts.report_lock import (  # noqa: E402
    generate_lock_template,
    serialize_lock_content,
)


# ─── 專案目錄樹 ──────────────────────────────────────────────────────

PROJECT_SUBDIRS = [
    "assets",
    "report_output",
    "exports",
    "backup",
    "csl",
    "bib",
    "examples",
]


# ─── glossary 預設內容（≥3 條範例，見 docs/glossary.md §4）─────────

DEFAULT_GLOSSARY_MD = """# glossary.md

> 預設術語表範例 — 請依專案實際內容編輯。
> 對應 docs/glossary.md。

## 條目

### 1. MarkDown
- **術語**：Markdown
- **定義**：輕量標記語言，使用易讀易寫的純文字格式。
- **譯名**：Markdown（不譯，保留原文）
- **首次出現**：§1.1
- **同義詞**：md、MD、Markdown 格式

### 2. Pipeline
- **術語**：Pipeline
- **定義**：資料由輸入到輸出所經過的處理階段鏈。
- **譯名**：管線 / 流水線
- **首次出現**：§1.2
- **同義詞**：管線、流水線、處理流程

### 3. Anti-drift Mechanism
- **術語**：Anti-drift Mechanism
- **定義**：防止長篇內容隨生成過程產生累積偏差的機制。
- **譯名**：防漂移機制
- **首次出現**：§2.3
- **同義詞**：防漂移、防 drift、漂移防禦
"""


# ─── report_spec.md 空白範本 ─────────────────────────────────────────

DEFAULT_SPEC_MD = """# report_spec.md

> 人類可讀章節大綱 — Stage 1 產出。
> 對應 SPEC.md §3.4.1 與 docs/report_lock_schema.md。

## 報告基本資訊

- **標題**：（待填）
- **副標題**：（待填）
- **作者**：（待填）
- **日期**：（待填）

## 章節大綱

（請列出章節、章節編號、預期內容、預期圖表）

例：
1. **第一章 緒論**
   - 1.1 研究背景
   - 1.2 研究目的
   - 1.3 章節安排
2. **第二章 文獻探討**
   - 2.1 國內外相關研究
   - 2.2 理論基礎

## 預期圖表清單

- Figure 1：（說明）
- Figure 2：（說明）
- Table 1：（說明）

## 附錄

（如需要）

## 引用 / 參考文獻

- 引用格式：（依 report_lock.md 的 citation_style）
- 預期引用條目數：（估計）
"""


# ─── init_project() ──────────────────────────────────────────────────

def init_project(
    path: Path,
    template: str = "academic",
    config: Optional[Config] = None,
    skip_font_check: bool = False,
) -> Path:
    """初始化專案：建目錄樹 + 產 lock 模板 + 產 glossary + 產 spec 空白範本。

    Args:
        path: 專案根目錄（不存在會自動建立）
        template: 範本類型 (academic/business/spec/gov/custom)
        config: 已初始化的 Config（None 時自動建一個，會 fail-fast 字體檢查）
        skip_font_check: True 時跳過字體檢查（測試用）

    Returns:
        專案根目錄的絕對路徑

    Raises:
        FontNotFoundError: 字體缺失
        FileExistsError: 專案目錄已存在且有內容（不會覆蓋現有檔案）
    """
    project_path = Path(path).resolve()

    # 字體檢查（除非 skip 或已有 config）
    if config is None and not skip_font_check:
        try:
            config = Config(project_root=project_path, skip_font_check=False)
        except FontNotFoundError:
            raise  # 讓例外繼續傳遞

    # 建立目錄
    if project_path.exists() and any(project_path.iterdir()):
        existing = sorted(p.name for p in project_path.iterdir())
        raise FileExistsError(
            f"專案目錄已存在且有內容：{project_path}\n"
            f"現有項目：{existing}\n"
            f"請刪除內容或指定空目錄。"
        )
    project_path.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_SUBDIRS:
        (project_path / sub).mkdir(parents=True, exist_ok=True)

    # 產 report_lock.md 模板
    lock_data = generate_lock_template(template)
    lock_body = (
        f"# report_lock.md\n\n"
        f"> 機器執行合同\n"
        f"> 範本：{template}\n"
        f"> 產生時間：{datetime.now().isoformat(timespec='seconds')}\n\n"
        f"⚠️  修改前請同步 SPEC.md §3.4.1 與 docs/report_lock_schema.md。\n"
    )
    lock_content = serialize_lock_content(lock_data, lock_body)
    (project_path / "report_lock.md").write_text(lock_content, encoding="utf-8")

    # 產 glossary.md（≥3 條範例）
    (project_path / "glossary.md").write_text(DEFAULT_GLOSSARY_MD, encoding="utf-8")

    # 產 report_spec.md 空白範本
    (project_path / "report_spec.md").write_text(DEFAULT_SPEC_MD, encoding="utf-8")

    # 產 README.md（專案說明）
    readme = _build_project_readme(template, project_path.name)
    (project_path / "README.md").write_text(readme, encoding="utf-8")

    # 產 .env.example（從 docs/.env.example 複製）
    docs_env_example = Path(__file__).parent.parent / "docs" / ".env.example"
    if docs_env_example.exists():
        project_env_example = project_path / ".env.example"
        if not project_env_example.exists():
            project_env_example.write_text(
                docs_env_example.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

    return project_path


def _build_project_readme(template: str, name: str) -> str:
    """建立專案 README。"""
    return f"""# {name}

> Report-master 專案（template: {template}）

## 結構

```
{name}/
├── report_lock.md       ← 機器執行合同（schema 見 docs/report_lock_schema.md）
├── report_spec.md       ← 章節大綱（人類可讀）
├── glossary.md          ← 術語表
├── assets/              ← 圖片、SVG、PNG
├── report_output/       ← Stage 2 HTML 輸出
├── exports/             ← Stage 3 PDF + DOCX 輸出
├── backup/              ← Stage 3 存檔
├── csl/                 ← CSL 引用樣式
├── bib/                 ← BibTeX 資料庫
└── examples/            ← 本地參考範例
```

## 使用流程

```bash
# Stage 1: 規劃（補齊 report_lock.md 與 report_spec.md）
# Stage 2: 生成（待 Track B 補上 report_gen.py）
# Stage 3: 工程轉換（待 Track B 補上 html_to_*.py）
```

## 字體設定

請確認 `fonts/` bundle 可用，或在本專案 `.env` 設定：

```
REPORT_MASTER_CJK_FONT=/path/to/標楷體.ttf
REPORT_MASTER_LATIN_FONT=/path/to/times.ttf
```

詳見 `../fonts/README.md`。
"""


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master init",
        description="Report-master 專案初始化",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化新專案")
    p_init.add_argument("path", type=Path, help="專案根目錄（不存在會自動建）")
    p_init.add_argument(
        "template_pos", nargs="?", default=None,
        choices=["academic", "business", "spec", "gov", "custom"],
        help="範本類型（可作第二個 positional；與 --type 二擇一）",
    )
    p_init.add_argument(
        "--type", "-t", default=None,
        choices=["academic", "business", "spec", "gov", "custom"],
        help="範本類型（預設 academic）",
    )
    p_init.add_argument(
        "--skip-font-check", action="store_true",
        help="跳過字體檢查（CI / 測試環境）",
    )

    args = parser.parse_args()

    if args.cmd == "init":
        template = args.template_pos or args.type or "academic"
        try:
            result = init_project(
                args.path,
                template=template,
                skip_font_check=args.skip_font_check,
            )
        except FontNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        except FileExistsError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 3
        print(f"✅ 專案已初始化：{result}")
        print(f"   範本：{template}")
        print(f"   檔案：report_lock.md / glossary.md / report_spec.md / README.md")
        print(f"   目錄：{', '.join(PROJECT_SUBDIRS)}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
