"""scripts/source_to_md/md_normalizer.py — Markdown 變體統一化。

對應 `tasks.md` T1-6：
- 統一 line endings（CRLF / CR → LF）
- 移除 UTF-8 BOM
- 統一 frontmatter（YAML 在 `---` 之間）
- 統一 trailing whitespace / 多餘空行
- normalize 標題、列表前綴

公開 API：
  normalize(text: str) -> str       # 文字
  normalize_file(path) -> str       # 讀檔並回傳 normalized 文字
  write_normalized(path, text) -> None  # 寫檔
  extract_frontmatter(text) -> (dict, body)  # 解析 frontmatter
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Any

# 允許 CLI 直接執行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 PyYAML，請先 `pip install pyyaml`") from e


# ─── 正則 ────────────────────────────────────────────────────────────

# Frontmatter
FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<yaml>.*?)\n---\s*\n?(?P<body>.*)",
    re.DOTALL,
)

# 標題前綴空白（標準化為 `# ` 後只一個空白）
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+", re.MULTILINE)

# 多個連續空行（3+ → 2）
MULTI_BLANK_LINES_RE = re.compile(r"\n{3,}")

# 行尾 whitespace
TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)

# CRLF / CR
CRLF_RE = re.compile(r"\r\n")
CR_RE = re.compile(r"\r(?!\n)")


# ─── 公開 API ────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """統一化 Markdown 文字。

    步驟：
    1. 移除 UTF-8 BOM
    2. CRLF / CR → LF
    3. 移除行尾 whitespace
    4. 多個空行 → 最多 2 個（即 1 個段落分隔）
    5. 標題前綴統一 `# ` 格式（單一空白）
    6. frontmatter 邊界統一（檔首 `---` 必須在第 1 行）
    """
    # 1. BOM
    if text.startswith("\ufeff"):
        text = text[1:]

    # 2. line endings
    text = CRLF_RE.sub("\n", text)
    text = CR_RE.sub("\n", text)

    # 3. trailing whitespace
    text = TRAILING_WS_RE.sub("", text)

    # 4. 多餘空行（3+ → 2）
    text = MULTI_BLANK_LINES_RE.sub("\n\n", text)

    # 5. heading prefix normalize：#  # → # （僅留單一空白）
    text = HEADING_RE.sub(lambda m: m.group(1) + " ", text)

    # 6. frontmatter 統一（若有 frontmatter，確保開頭無空行）
    fm_match = FRONTMATTER_RE.match(text)
    if fm_match:
        yaml_text = fm_match.group("yaml")
        body = fm_match.group("body")
        # 確保 body 開頭只有 1 個空行（即 body 不以空行開頭）
        body = body.lstrip("\n")
        # body 末尾確保一個換行
        if body and not body.endswith("\n"):
            body += "\n"
        text = f"---\n{yaml_text}\n---\n{body}"

    # 7. 檔首不應有空行
    text = text.lstrip("\n")

    # 8. 確保檔案以單一換行結尾
    if text and not text.endswith("\n"):
        text += "\n"

    return text


def normalize_file(path: Union[str, Path]) -> str:
    """讀檔並回傳 normalized 文字（不寫回）。"""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    return normalize(raw)


def write_normalized(path: Union[str, Path], text: str) -> None:
    """寫入 normalized 文字到檔案。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(normalize(text), encoding="utf-8")


def extract_frontmatter(
    text: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """提取 frontmatter（YAML dict 與 body）。

    若無 frontmatter → (None, 原始 text)。
    若 frontmatter 解析失敗 → (None, 原始 text)。
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    yaml_text = m.group("yaml")
    body = m.group("body")
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    return data, body


def has_frontmatter(text: str) -> bool:
    """檢查是否有合法 frontmatter。"""
    data, _ = extract_frontmatter(text)
    return data is not None


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        prog="md-normalizer",
        description="Markdown 變體統一化",
    )
    parser.add_argument("input", type=Path, help="輸入檔案")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="輸出檔案（不指定則輸出到 stdout）",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="只檢查是否需要 normalize，不輸出",
    )
    args = parser.parse_args()

    raw = args.input.read_text(encoding="utf-8")
    normalized = normalize(raw)

    if args.check:
        if raw == normalized:
            print(f"✅ 已 normalize：{args.input}")
            return 0
        print(f"⚠️  需要 normalize：{args.input}")
        return 1

    if args.output:
        args.output.write_text(normalized, encoding="utf-8")
        print(f"✅ 已寫入：{args.output}")
    else:
        sys.stdout.write(normalized)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
