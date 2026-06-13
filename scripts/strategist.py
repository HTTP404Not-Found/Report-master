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


# ─── 新流程：intent 模式（topic + audience → 0_strategist.md）────────

# 章節藍圖的範本選擇啟發（依 topic 與 audience 推測 template）
_TOPIC_TO_TEMPLATE_HINTS: List[Dict[str, Any]] = [
    {
        "match": ["影像", "醫學", "醫療", "clinical", "diagnosis", "deep learning"],
        "template": "academic",
        "sections": [
            {"title": "緒論", "goal": "說明研究背景、動機與問題意識", "words": 1500},
            {"title": "文獻回顧", "goal": "回顧 AI 醫學影像相關研究", "words": 1800},
            {"title": "研究方法", "goal": "資料來源、模型架構、評估指標", "words": 1500},
            {"title": "實驗結果", "goal": "呈現模型表現與統計分析", "words": 1800},
            {"title": "討論與結論", "goal": "限制、未來工作、臨床意義", "words": 1400},
        ],
    },
    {
        "match": ["系統", "spec", "架構", "architecture", "api"],
        "template": "spec",
        "sections": [
            {"title": "摘要", "goal": "系統目標與貢獻", "words": 800},
            {"title": "背景與動機", "goal": "現有痛點與設計取捨", "words": 1200},
            {"title": "相關工作", "goal": "同類系統比較", "words": 1200},
            {"title": "系統設計", "goal": "架構、模組、API", "words": 1800},
            {"title": "實作與實驗", "goal": "關鍵實作與量化結果", "words": 1500},
            {"title": "結論與未來工作", "goal": "限制與後續規劃", "words": 800},
        ],
    },
]


def _guess_template_and_sections(topic: str, audience: str) -> Dict[str, Any]:
    """依 topic 與 audience 推測 template 與章節藍圖（啟發式）。"""
    topic_lower = (topic or "").lower()
    audience_lower = (audience or "").lower()
    for hint in _TOPIC_TO_TEMPLATE_HINTS:
        for kw in hint["match"]:
            if kw.lower() in topic_lower:
                return {
                    "template": hint["template"],
                    "sections": list(hint["sections"]),
                }
    # 啟發失敗：依 audience 推
    if "工程" in audience or "技術" in audience or "team" in audience_lower:
        return {
            "template": "spec",
            "sections": [
                {"title": "摘要", "goal": "系統目標與貢獻", "words": 800},
                {"title": "背景", "goal": "領域現況", "words": 1200},
                {"title": "系統設計", "goal": "架構與 API", "words": 1800},
                {"title": "實作", "goal": "關鍵實作細節", "words": 1500},
                {"title": "結論", "goal": "總結與後續工作", "words": 800},
            ],
        }
    return {
        "template": "academic",
        "sections": [
            {"title": "緒論", "goal": "研究背景與動機", "words": 1500},
            {"title": "文獻回顧", "goal": "相關研究", "words": 1800},
            {"title": "方法", "goal": "研究方法", "words": 1500},
            {"title": "結果", "goal": "實驗結果", "words": 1800},
            {"title": "結論", "goal": "結論與未來工作", "words": 1200},
        ],
    }


def build_intent_brief(
    topic: str,
    audience: str,
    *,
    title: str = "",
    constraints: Optional[List[str]] = None,
) -> str:
    """產出 0_strategist.md 的內容（Markdown 字串）。

    這是 D1 新流程的「Strategist intent brief」：
      - 收斂使用者口語需求為「報告意圖」
      - 不直接產 lock（那是 Outliner 的工作）
      - 給 Outliner 當輸入
    """
    guess = _guess_template_and_sections(topic, audience)
    template = guess["template"]
    sections = guess["sections"]
    title_final = title.strip() or topic.strip()
    constraints = constraints or []

    sections_md = []
    for i, sec in enumerate(sections, 1):
        sections_md.append(f"{i}. **{sec['title']}**（{sec['words']} 字）")
        sections_md.append(f"   - 目標：{sec['goal']}")
        sections_md.append("")

    constraints_md = "\n".join(f"- {c}" for c in constraints) if constraints else "- （無額外限制）"

    body = f"""# 0_strategist.md — Strategist Intent Brief

> 產生時間：{datetime.now().isoformat(timespec='seconds')}
> 產出者：Strategist CLI（intent 模式，D1 新流程）
> 對應 workflow：`workflows/strategist.md` v1.1（Section Blueprint 流程）

## 1. 使用者意圖

- **主題（topic）**：{topic}
- **目標讀者（audience）**：{audience}
- **預期標題**：{title_final}

## 2. 推測的範本

- **template**：`{template}`（依 topic / audience 啟發式推測，可由 Outliner 覆寫）

## 3. 章節藍圖（Section Blueprint 草案）

{chr(10).join(sections_md)}

## 4. 限制與偏好

{constraints_md}

## 5. 給 Outliner 的交接資訊

- 依上述章節藍圖展開為 `0_outline.md`（每章含核心問題、所需資料類型、預估字數）
- 同時產出 `lock.md`（讓 Executor 可直接消費）
- Audience 需在每章「目標」中明確提及
- 若 topic 有歧義，Outliner 可微調章節數量（建議維持 5~6 章）

---

*0_strategist.md — 自動產生；下一步：Outliner*
"""
    return body


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    # 不使用 argparse subparsers（避免「給 --list 時 subparser 互斥」的問題）
    # 改為單一 parser 路由：
    #   有 --topic / --audience → intent 模式
    #   其他 → lock 模式（舊行為）
    parser = argparse.ArgumentParser(
        prog="report-master strategist",
        description="Stage 1 Strategist CLI helper（10 Confirmations + lock 範本 + intent 模式）",
    )
    parser.add_argument(
        "--topic", default=None,
        help="intent 模式：報告主題（例：「AI在醫學影像診斷的應用」）",
    )
    parser.add_argument(
        "--audience", default=None,
        help="intent 模式：目標讀者（例：「醫學研究人員」）",
    )
    parser.add_argument(
        "--constraint", action="append", default=[],
        help="intent 模式：額外限制（可重複）",
    )
    parser.add_argument(
        "--template", "-t",
        choices=SUPPORTED_TEMPLATES,
        default="academic",
        help="lock 模式：範本類型（預設 academic）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="lock 模式：輸出 lock 檔路徑 / intent 模式：輸出目錄",
    )
    parser.add_argument(
        "--spec-output", "-s",
        type=Path,
        default=None,
        help="lock 模式：額外輸出 report_spec.md 檔路徑",
    )
    parser.add_argument(
        "--title",
        default="",
        help="lock 模式：報告標題 / intent 模式：報告標題（省略則用 topic）",
    )
    parser.add_argument(
        "--validate", "-V",
        type=Path,
        default=None,
        help="lock 模式：驗證現有 lock 檔（與 --template 互斥）",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="lock 模式：列出支援的範本與 10 Confirmations 問題",
    )
    args = parser.parse_args()

    # 路由：intent vs lock
    if args.topic is not None or args.audience is not None:
        # intent 模式：需要 topic + audience + output
        if args.topic is None or args.audience is None:
            print("[BLOCKING] intent 模式需要 --topic 與 --audience", file=sys.stderr)
            return 2
        if args.output is None:
            print("[BLOCKING] intent 模式需要 --output（輸出目錄）", file=sys.stderr)
            return 2
        return _cli_intent(args)
    return _cli_lock(args)


def _cli_intent(args: argparse.Namespace) -> int:
    """intent 子命令：寫出 0_strategist.md。"""
    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "0_strategist.md"
    content = build_intent_brief(
        topic=args.topic,
        audience=args.audience,
        title=getattr(args, "title", "") or "",
        constraints=getattr(args, "constraint", []) or [],
    )
    target.write_text(content, encoding="utf-8")
    print(f"✅ intent brief 已寫入：{target}")
    print(f"   topic    : {args.topic}")
    print(f"   audience : {args.audience}")
    return 0


def _cli_lock(args: argparse.Namespace) -> int:
    """lock 子命令：舊版行為。"""
    if getattr(args, "list", False):
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
