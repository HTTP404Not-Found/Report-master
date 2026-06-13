"""scripts/report_lock.py — report_lock.md 讀寫與 schema 驗證。

對應 `docs/report_lock_schema.md` v1：
- 讀寫 YAML frontmatter + Markdown 註解（保留註解）
- 對 required 欄位做 schema 驗證
- 缺 required 欄位 → raise LockMissingFieldsError

required 欄位清單（17 個）：
  fonts.cjk, fonts.latin
  formatting.{cover,toc,title,h1,h2,h3,body,table,caption}
  page_size, margins, line_spacing, language_variant,
  citation_style, output.docx_engine
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/report_lock.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 PyYAML，請先 `pip install pyyaml`") from e


# ─── 例外 ────────────────────────────────────────────────────────────

class LockError(Exception):
    """所有 lock 例外的基底類型。"""


class LockMissingFieldsError(LockError):
    """缺少 required 欄位。"""

    def __init__(self, missing: List[str]):
        self.missing = missing
        lines = ["[BLOCKING] report_lock.md 缺少以下 required 欄位："]
        for name in missing:
            lines.append(f"  - {name}")
        lines.append("請補齊後重跑 Stage 1。")
        super().__init__("\n".join(lines))


class LockFormatError(LockError):
    """report_lock.md 格式錯誤（無 frontmatter、frontmatter 不合法）。"""


# ─── Required 欄位定義（17 個）────────────────────────────────────────

REQUIRED_FIELDS: List[str] = [
    "fonts.cjk",
    "fonts.latin",
    "formatting.cover",
    "formatting.toc",
    "formatting.title",
    "formatting.h1",
    "formatting.h2",
    "formatting.h3",
    "formatting.body",
    "formatting.table",
    "formatting.caption",
    "page_size",
    "margins",
    "line_spacing",
    "language_variant",
    "citation_style",
    "output.docx_engine",
]

# 預設 formatting 值（用於 generate_lock_template）
DEFAULT_FORMATTING: Dict[str, Dict[str, Any]] = {
    "cover": {"font_size": 22, "bold": True, "align": "center"},
    "toc": {"font_size": 20},
    "title": {"font_size": 22, "bold": True, "align": "center"},
    "h1": {"font_size": 18, "bold": True},
    "h2": {"font_size": 16, "bold": True},
    "h3": {"font_size": 14, "bold": True},
    "body": {"font_size": 12, "line_spacing": 1.5},
    "table": {"font_size": 12},
    "caption": {"font_size": 10, "align": "center"},
}


# ─── Frontmatter 解析（不用 python-frontmatter，避免額外依賴）────────

FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<yaml>.*?)\n---\s*\n?(?P<body>.*)",
    re.DOTALL,
)


def parse_lock_content(content: str) -> tuple[Dict[str, Any], str]:
    """解析 report_lock.md 內容，回傳 (YAML dict, Markdown body)。"""
    m = FRONTMATTER_RE.match(content)
    if not m:
        raise LockFormatError(
            "report_lock.md 缺少 YAML frontmatter（需以 --- 開頭）。"
        )
    yaml_text = m.group("yaml")
    body = m.group("body")
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise LockFormatError(f"YAML 解析失敗：{e}") from e
    if not isinstance(data, dict):
        raise LockFormatError("YAML frontmatter 必須是 mapping（鍵值對）。")
    return data, body


def serialize_lock_content(data: Dict[str, Any], body: str) -> str:
    """序列化為 report_lock.md 字串（YAML frontmatter + body）。"""
    yaml_text = yaml.safe_dump(
        data, allow_unicode=True, default_flow_style=False, sort_keys=False
    )
    # body 確保以 \n 結尾
    if body and not body.endswith("\n"):
        body += "\n"
    return f"---\n{yaml_text}---\n{body}"


# ─── Schema 驗證 ─────────────────────────────────────────────────────

def validate_lock(data: Dict[str, Any]) -> None:
    """驗證 lock 資料是否符合 schema。缺 required 欄位 → raise。"""
    missing: List[str] = []
    for field in REQUIRED_FIELDS:
        if not _get_nested(data, field):
            missing.append(field)
    if missing:
        raise LockMissingFieldsError(missing)


def _get_nested(data: Dict[str, Any], dotted_key: str) -> Any:
    """從巢狀 dict 取得 dot-separated key 的值。"""
    parts = dotted_key.split(".")
    cur: Any = data
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


# ─── 讀寫 ────────────────────────────────────────────────────────────

def read_lock(path: Union[str, Path]) -> Dict[str, Any]:
    """從檔案讀取 lock，回傳 YAML dict（不驗證）。"""
    p = Path(path)
    if not p.exists():
        raise LockFormatError(f"找不到 lock 檔：{p}")
    data, _body = parse_lock_content(p.read_text(encoding="utf-8"))
    return data


def read_lock_with_body(path: Union[str, Path]) -> tuple[Dict[str, Any], str]:
    """從檔案讀取 lock，回傳 (YAML dict, Markdown body)。"""
    p = Path(path)
    if not p.exists():
        raise LockFormatError(f"找不到 lock 檔：{p}")
    return parse_lock_content(p.read_text(encoding="utf-8"))


def write_lock(
    path: Union[str, Path],
    data: Dict[str, Any],
    body: Optional[str] = None,
) -> None:
    """寫入 lock 到檔案（保留或建立 body）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = "# report_lock.md\n\n> 機器執行合同\n"
    content = serialize_lock_content(data, body)
    p.write_text(content, encoding="utf-8")


def read_and_validate(path: Union[str, Path]) -> Dict[str, Any]:
    """讀取 lock 並驗證 schema；缺欄位 raise。"""
    data = read_lock(path)
    validate_lock(data)
    return data


# ─── 模板產生 ────────────────────────────────────────────────────────

def generate_lock_template(template: str = "academic") -> Dict[str, Any]:
    """產生 lock 模板 dict（17 個 required 欄位全填）。"""
    if template not in ("academic", "business", "spec", "gov", "custom"):
        raise LockFormatError(f"未知 template：{template}")

    # 預設值依 template 略不同
    line_spacing = {
        "academic": 1.5,    # APA 預設雙倍行距的折衷
        "business": 1.0,
        "spec": 1.0,
        "gov": 1.5,
        "custom": 1.5,
    }[template]

    page_size = {
        "academic": "A4",
        "business": "A4",
        "spec": "A4",
        "gov": "A4",
        "custom": "A4",
    }[template]

    citation_style = {
        "academic": "APA",
        "business": "none",
        "spec": "IEEE",
        "gov": "GBC",
        "custom": "APA",
    }[template]

    data: Dict[str, Any] = {
        "schema_version": 1,
        "template": template,
        "fonts": {
            "cjk": "標楷體",
            "latin": "Times New Roman",
        },
        "formatting": dict(DEFAULT_FORMATTING),
        "page_size": page_size,
        "margins": {"top": "2.5cm", "bottom": "2.5cm", "left": "3cm", "right": "2cm"},
        "line_spacing": line_spacing,
        "language_variant": "zh-TW",
        "citation_style": citation_style,
        "output": {
            "docx_engine": "pandoc",
            "embed_fonts": True,
            "tagged_pdf": False,
        },
        "metadata": {
            "title": "",
            "author": "",
            "date": "",
            "abstract": "",
        },
        "sections": [],
        "assets": {
            "csl_file": "APA.csl",
            "bib_file": "references.bib",
        },
    }
    return data


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="report-master lock",
        description="report_lock.md 讀寫與驗證",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="驗證現有 lock 檔")
    p_validate.add_argument("path", type=Path)

    p_template = sub.add_parser("template", help="產生 lock 模板到 stdout")
    p_template.add_argument(
        "--type", default="academic",
        choices=["academic", "business", "spec", "gov", "custom"],
    )
    p_template.add_argument("--output", "-o", type=Path, default=None)

    args = parser.parse_args()

    if args.cmd == "validate":
        try:
            read_and_validate(args.path)
        except LockMissingFieldsError as e:
            print(str(e), file=sys.stderr)
            return 2
        except LockFormatError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"✅ lock 通過 schema 驗證：{args.path}")
        return 0

    if args.cmd == "template":
        data = generate_lock_template(args.type)
        body = (
            "# report_lock.md\n\n"
            f"> 機器執行合同（template: {args.type}）\n"
            "> 產生時間：自動\n\n"
            "⚠️  修改前請同步 SPEC.md §3.4.1 與 docs/report_lock_schema.md。\n"
        )
        content = serialize_lock_content(data, body)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
            print(f"✅ 已寫入：{args.output}")
        else:
            print(content)
        return 0

    return 0  # 不會到這


if __name__ == "__main__":
    sys.exit(_cli())
