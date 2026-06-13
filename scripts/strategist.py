"""scripts/strategist.py — Report-master Stage 1 Strategist CLI helper.

對應 `references/strategist.md` v1 + `tasks.md` T3-1。

用途：
- 從範本產生 `report_lock.md`（對齊 `scripts/project_manager.py` 的 5 種類型）
- 載入 / 驗證 / 序列化 lock
- CLI：`python -m scripts.strategist --template <type> --output <path>`

5 種範本：
  academic — 學術論文（line_spacing=1.5, citation_style=APA）   ✅ 完整
  business — 商業提案（line_spacing=1.0, citation_style=none）   🚧 TODO placeholder
  spec     — 技術規格（line_spacing=1.0, citation_style=IEEE）   🚧 TODO placeholder
  gov      — 政府公文（line_spacing=1.5, citation_style=GBC）    🚧 TODO placeholder
  custom   — 自訂類型（line_spacing=1.5, citation_style=APA）    🚧 TODO placeholder

每個範本產出的 lock 都必須通過 `scripts.report_lock.validate_lock()`。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允許 CLI 直接執行（`python scripts/strategist.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.report_lock import (  # noqa: E402
    DEFAULT_FORMATTING,
    LockMissingFieldsError,
    generate_lock_template,
    read_and_validate,
    serialize_lock_content,
    validate_lock,
)


# ─── 例外 ────────────────────────────────────────────────────────────

class StrategistError(Exception):
    """Strategist 例外基底。"""


class StrategistIncompleteError(StrategistError):
    """Strategist 因資料不完整而拒絕產出 lock（10 Confirmations 未完成）。"""

    def __init__(self, missing_questions: List[str]):
        self.missing_questions = missing_questions
        lines = ["[BLOCKING] Strategist 10 Confirmations 未完成："]
        for q in missing_questions:
            lines.append(f"  - {q}")
        lines.append("請依序回答 Q1~Q10 後重跑。")
        super().__init__("\n".join(lines))


# ─── 支援的範本 ──────────────────────────────────────────────────────

SUPPORTED_TEMPLATES: List[str] = ["academic", "business", "spec", "gov", "custom"]

# 已完工的範本（其他為 placeholder）
COMPLETED_TEMPLATES: List[str] = ["academic"]


# ─── 範本 metadata（給 report_spec.md 用） ──────────────────────────

TEMPLATE_METADATA: Dict[str, Dict[str, Any]] = {
    "academic": {
        "label": "學術論文",
        "line_spacing": 1.5,
        "page_size": "A4",
        "citation_style": "APA",
        "language_variant": "zh-TW",
        "default_sections": [
            {"path": "report_output/section_1.html", "title": "第一章 緒論"},
            {"path": "report_output/section_2.html", "title": "第二章 文獻探討"},
            {"path": "report_output/section_3.html", "title": "第三章 方法論"},
            {"path": "report_output/section_4.html", "title": "第四章 結果"},
            {"path": "report_output/section_5.html", "title": "第五章 結論與建議"},
        ],
        "completed": True,
    },
    "business": {
        "label": "商業提案",
        "line_spacing": 1.0,
        "page_size": "A4",
        "citation_style": "none",
        "language_variant": "zh-TW",
        "default_sections": [
            {"path": "report_output/section_1.html", "title": "執行摘要"},
            {"path": "report_output/section_2.html", "title": "市場分析"},
            {"path": "report_output/section_3.html", "title": "解決方案"},
        ],
        "completed": False,  # TODO
    },
    "spec": {
        "label": "技術規格",
        "line_spacing": 1.0,
        "page_size": "A4",
        "citation_style": "IEEE",
        "language_variant": "zh-TW",
        "default_sections": [
            {"path": "report_output/section_1.html", "title": "概述"},
            {"path": "report_output/section_2.html", "title": "系統架構"},
            {"path": "report_output/section_3.html", "title": "API 規格"},
        ],
        "completed": False,  # TODO
    },
    "gov": {
        "label": "政府公文",
        "line_spacing": 1.5,
        "page_size": "A4",
        "citation_style": "GBC",
        "language_variant": "zh-TW",
        "default_sections": [
            {"path": "report_output/section_1.html", "title": "主旨"},
            {"path": "report_output/section_2.html", "title": "說明"},
            {"path": "report_output/section_3.html", "title": "辦法"},
        ],
        "completed": False,  # TODO
    },
    "custom": {
        "label": "自訂類型",
        "line_spacing": 1.5,
        "page_size": "A4",
        "citation_style": "APA",
        "language_variant": "zh-TW",
        "default_sections": [
            {"path": "report_output/section_1.html", "title": "章節一"},
            {"path": "report_output/section_2.html", "title": "章節二"},
            {"path": "report_output/section_3.html", "title": "章節三"},
        ],
        "completed": False,  # TODO
    },
}


# ─── build_lock_template（主要 API） ─────────────────────────────────

def build_lock_template(
    template: str = "academic",
    metadata_overrides: Optional[Dict[str, Any]] = None,
    sections_override: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """根據範本產出 lock dict（17 個 required 欄位齊備 + 通過 validate_lock）。

    Args:
        template: 範本名（academic / business / spec / gov / custom）
        metadata_overrides: 覆寫 metadata（title / author / date / abstract）
        sections_override: 覆寫 sections list（每個含 path + title）

    Returns:
        完整的 lock dict

    Raises:
        StrategistError: template 不支援
    """
    if template not in SUPPORTED_TEMPLATES:
        raise StrategistError(
            f"不支援的範本：{template}；"
            f"可用：{', '.join(SUPPORTED_TEMPLATES)}"
        )

    # 用 report_lock.py 既有函式建基底（含 17 個 required 欄位）
    data = generate_lock_template(template)

    # 套用範本 metadata
    tmpl_meta = TEMPLATE_METADATA[template]
    data["page_size"] = tmpl_meta["page_size"]
    data["line_spacing"] = tmpl_meta["line_spacing"]
    data["citation_style"] = tmpl_meta["citation_style"]
    data["language_variant"] = tmpl_meta["language_variant"]

    # sections（若沒 override，用範本預設）
    if sections_override is not None:
        data["sections"] = sections_override
    else:
        data["sections"] = list(tmpl_meta["default_sections"])

    # metadata overrides
    if metadata_overrides:
        for k, v in metadata_overrides.items():
            if k in data["metadata"]:
                data["metadata"][k] = v

    # 若 template 還沒完工，加 TODO 標記在 metadata（但 schema 仍完整通過）
    if not tmpl_meta["completed"]:
        todo_note = (
            f"[TODO] {template} 範本為 placeholder；"
            f"完整 sections / metadata 待 T3-x 任務補完。"
        )
        if data["metadata"].get("abstract"):
            data["metadata"]["abstract"] = f"{data['metadata']['abstract']}\n\n{todo_note}"
        else:
            data["metadata"]["abstract"] = todo_note

    # 保險：再校驗一次（確保 17 欄位齊備）
    validate_lock(data)
    return data


# ─── 10 Confirmations 結構（給 reference 用 + 測試用） ───────────────

CONFIRMATION_QUESTIONS: List[Dict[str, str]] = [
    {"id": "Q1", "key": "metadata.type", "text": "報告類型與目標讀者"},
    {"id": "Q2", "key": "metadata.title", "text": "標題 + 副標題"},
    {"id": "Q3", "key": "page_layout", "text": "page_size + margins + line_spacing"},
    {"id": "Q4", "key": "fonts", "text": "字體鎖死確認（CJK=標楷體 / Latin=Times New Roman）"},
    {"id": "Q5", "key": "citation_style", "text": "引用風格"},
    {"id": "Q6", "key": "sections", "text": "章節大綱（≥ 3 個 H1）"},
    {"id": "Q7", "key": "spec_metadata", "text": "預期頁數 + 圖表數"},
    {"id": "Q8", "key": "special_elements", "text": "特殊元素需求（mermaid / katex / code block）"},
    {"id": "Q9", "key": "source_materials", "text": "來源材料（PDF / DOCX / URL / MD / 手寫）"},
    {"id": "Q10", "key": "output_format", "text": "交付格式（PDF only / DOCX only / 兩者）"},
]


def list_confirmations() -> List[Dict[str, str]]:
    """回傳 10 個確認問題清單（給 CLI 列出用 + 測試用）。"""
    return list(CONFIRMATION_QUESTIONS)


# ─── report_spec.md 範本產生 ─────────────────────────────────────────

DEFAULT_SPEC_MD = """# report_spec.md

> 人類可讀章節大綱 — Stage 1 Strategist 產出。
> 對應 SPEC.md §3.4.1 + `references/strategist.md`。

## 報告基本資訊

- **標題**：{title}
- **副標題**：（待填）
- **作者**：（待填）
- **日期**：{date}

## 章節大綱

{sections}

## 預期圖表清單

- Figure 1：（待 Stage 2 Executor 填）
- Figure 2：（待 Stage 2 Executor 填）
- Table 1：（待 Stage 2 Executor 填）

## 預期頁數 / 字數

- 頁數：（待 Stage 2 結束後由 export_checker 統計）
- 字數：（待 Stage 2 結束後由 quality_checker 統計）

## 引用 / 參考文獻

- 引用格式：{citation_style}
- 預期引用條目數：（待 Stage 1 末補）
"""


def build_report_spec(
    template: str = "academic",
    title: str = "",
    sections: Optional[List[Dict[str, str]]] = None,
) -> str:
    """產出 report_spec.md 內容（Markdown 字串）。"""
    if template not in SUPPORTED_TEMPLATES:
        raise StrategistError(f"不支援的範本：{template}")

    tmpl_meta = TEMPLATE_METADATA[template]
    if sections is None:
        sections = tmpl_meta["default_sections"]

    today = datetime.now().strftime("%Y-%m-%d")
    sections_md_lines = []
    for i, sec in enumerate(sections, 1):
        sections_md_lines.append(f"{i}. **{sec['title']}**")
        sections_md_lines.append(f"   - 對應檔案：`{sec['path']}`")
        sections_md_lines.append(f"   - 子節：（待 Stage 2 補）")
        sections_md_lines.append("")
    sections_md = "\n".join(sections_md_lines)

    content = DEFAULT_SPEC_MD.format(
        title=title or f"（{tmpl_meta['label']}）",
        date=today,
        sections=sections_md,
        citation_style=tmpl_meta["citation_style"],
    )
    return content


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master strategist",
        description="Stage 1 Strategist CLI helper（10 Confirmations + lock 範本）",
    )
    parser.add_argument(
        "--template", "-t",
        choices=SUPPORTED_TEMPLATES,
        default="academic",
        help="範本類型（預設 academic）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="輸出 lock 檔路徑（省略則印到 stdout）",
    )
    parser.add_argument(
        "--spec-output", "-s",
        type=Path,
        default=None,
        help="額外輸出 report_spec.md 檔路徑",
    )
    parser.add_argument(
        "--title",
        default="",
        help="報告標題（覆寫 metadata.title）",
    )
    parser.add_argument(
        "--validate", "-V",
        type=Path,
        default=None,
        help="驗證現有 lock 檔（與 --template 互斥）",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出支援的範本與 10 Confirmations 問題",
    )

    args = parser.parse_args()

    if args.list:
        print("=== 支援的範本 ===")
        for t in SUPPORTED_TEMPLATES:
            mark = "✅" if t in COMPLETED_TEMPLATES else "🚧"
            label = TEMPLATE_METADATA[t]["label"]
            print(f"  {mark} {t} — {label}")
        print()
        print("=== 10 Confirmations ===")
        for q in CONFIRMATION_QUESTIONS:
            print(f"  {q['id']}: {q['text']} → {q['key']}")
        return 0

    if args.validate is not None:
        try:
            data = read_and_validate(args.validate)
        except LockMissingFieldsError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"✅ lock 通過 schema 驗證：{args.validate}")
        print(f"   template: {data.get('template', '?')}")
        print(f"   title: {data.get('metadata', {}).get('title', '?')}")
        return 0

    # 產出 lock
    metadata_overrides = {}
    if args.title:
        metadata_overrides["title"] = args.title

    data = build_lock_template(args.template, metadata_overrides=metadata_overrides)

    body = (
        f"# report_lock.md\n\n"
        f"> 機器執行合同（template: {args.template}）\n"
        f"> 產生時間：{datetime.now().isoformat(timespec='seconds')}\n"
        f"> 產出者：Strategist CLI (scripts/strategist.py)\n\n"
        f"⚠️  修改前請同步 SPEC.md §3.4.1 與 docs/report_lock_schema.md。\n"
    )
    content = serialize_lock_content(data, body)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"✅ lock 已寫入：{args.output}")
    else:
        print(content)

    if args.spec_output:
        spec = build_report_spec(
            template=args.template,
            title=args.title or data["metadata"].get("title", ""),
        )
        args.spec_output.parent.mkdir(parents=True, exist_ok=True)
        args.spec_output.write_text(spec, encoding="utf-8")
        print(f"✅ spec 已寫入：{args.spec_output}")

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
