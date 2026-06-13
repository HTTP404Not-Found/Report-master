"""scripts/outliner.py — Report-master D1 Stage 1.5 Outliner (D1 新流程)。

對應 `tasks.md` A1 與 `workflows/strategist.md` v1.1（Section Blueprint 流程）。

用途：
  - 讀 `0_strategist.md`（Strategist intent brief，含 topic/audience/章節草案）
  - 產出 `0_outline.md`（Section Blueprint：每章含標題、層級、核心問題、
    所需資料類型、預估字數、頁數）
  - 同時產出 `lock.md`（讓 Stage 2 Executor 可直接消費）

CLI：
  python -m scripts.outliner \\
      --strategist examples/output_1/0_strategist.md \\
      --output examples/output_1/0_outline.md
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.report_lock import (  # noqa: E402
    LockFormatError,
    LockMissingFieldsError,
    read_and_validate,
    serialize_lock_content,
    validate_lock,
    write_lock,
)
from scripts.strategist import (  # noqa: E402
    StrategistError,
    TEMPLATE_METADATA,
    build_lock_template,
)


# ─── 例外 ────────────────────────────────────────────────────────────

class OutlinerError(Exception):
    """Outliner 例外基底。"""


class IntentBriefMissingError(OutlinerError):
    """0_strategist.md 不存在或不可讀。"""


# ─── 解析 0_strategist.md ─────────────────────────────────────────────

_SECTION_RE = re.compile(
    r"^\d+\.\s+\*\*(?P<title>[^*]+)\*\*（(?P<words>\d+)\s*字）\s*$",
    re.MULTILINE,
)
_GOAL_RE = re.compile(r"^\s+-\s+目標：(?P<goal>.+?)\s*$", re.MULTILINE)
_TEMPLATE_RE = re.compile(
    r"\*\*template\*\*：`(?P<template>[^`]+)`",
)
_TOPIC_RE = re.compile(r"\*\*主題（topic）\*\*：(?P<topic>.+)")
_AUDIENCE_RE = re.compile(r"\*\*目標讀者（audience）\*\*：(?P<audience>.+)")
_TITLE_RE = re.compile(r"\*\*預期標題\*\*：(?P<title>.+)")


def parse_intent_brief(path: Path) -> Dict[str, Any]:
    """解析 0_strategist.md，回傳結構化 dict。

    Returns:
        {
            "topic": str,
            "audience": str,
            "title": str,
            "template": str,
            "sections": [{"title", "words", "goal"}, ...],
        }
    """
    if not path.exists():
        raise IntentBriefMissingError(f"找不到 intent brief：{path}")
    text = path.read_text(encoding="utf-8")

    topic_m = _TOPIC_RE.search(text)
    audience_m = _AUDIENCE_RE.search(text)
    title_m = _TITLE_RE.search(text)
    template_m = _TEMPLATE_RE.search(text)

    if not topic_m or not audience_m:
        raise OutlinerError(
            f"intent brief 缺少 topic/audience 標頭：{path}"
        )

    sections: List[Dict[str, Any]] = []
    for m in _SECTION_RE.finditer(text):
        title = m.group("title").strip()
        words = int(m.group("words"))
        goal = "（未指定）"
        rest = text[m.end():]
        gm = _GOAL_RE.search(rest)
        if gm:
            goal = gm.group("goal").strip()
        sections.append({"title": title, "words": words, "goal": goal})

    if not sections:
        raise OutlinerError(
            f"intent brief 沒解析到章節（檢查標記格式）：{path}"
        )

    return {
        "topic": topic_m.group("topic").strip(),
        "audience": audience_m.group("audience").strip(),
        "title": (title_m.group("title").strip() if title_m else topic_m.group("topic").strip()),
        "template": (template_m.group("template").strip() if template_m else "academic"),
        "sections": sections,
    }


# ─── 產出 0_outline.md ───────────────────────────────────────────────

def build_outline_markdown(parsed: Dict[str, Any]) -> str:
    """把 parsed intent 轉成 Section Blueprint Markdown。"""
    sections = parsed["sections"]
    total_words = sum(s["words"] for s in sections)
    page_estimate = max(1, round(total_words / 500))

    lines: List[str] = []
    lines.append(f"# 0_outline.md — Section Blueprint")
    lines.append("")
    lines.append(f"> 產生時間：{datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"> 產出者：Outliner CLI（scripts/outliner.py，D1 新流程）")
    lines.append(f"> 對應 workflow：`workflows/strategist.md` v1.1")
    lines.append("")
    lines.append("## 1. 報告基本資訊")
    lines.append("")
    lines.append(f"- **標題**：{parsed['title']}")
    lines.append(f"- **主題**：{parsed['topic']}")
    lines.append(f"- **目標讀者**：{parsed['audience']}")
    lines.append(f"- **範本**：{parsed['template']}")
    lines.append(f"- **章節數**：{len(sections)}")
    lines.append(f"- **總預估字數**：~{total_words} 字")
    lines.append(f"- **總預估頁數**：~{page_estimate} 頁（500 字/頁粗估）")
    lines.append("")
    lines.append("## 2. 章節藍圖（Section Blueprint）")
    lines.append("")
    lines.append("| # | 章節標題 | 層級 | 預估字數 | 預估頁數 | 對應 RQ |")
    lines.append("|---|---------|------|---------|---------|--------|")
    for i, sec in enumerate(sections, 1):
        rq_id = f"RQ{i}"
        page_per_sec = max(1, round(sec["words"] / 500))
        lines.append(f"| {i} | {sec['title']} | H1 | {sec['words']} | ~{page_per_sec} | {rq_id} |")
    lines.append("")
    lines.append("## 3. 各章細節")
    lines.append("")
    for i, sec in enumerate(sections, 1):
        rq_id = f"RQ{i}"
        page_per_sec = max(1, round(sec["words"] / 500))
        data_type = _guess_data_type(sec["title"])
        lines.append(f"### {i}. {sec['title']}（{sec['words']} 字 / ~{page_per_sec} 頁）")
        lines.append("")
        lines.append(f"- **層級**：H1（章）")
        lines.append(f"- **核心問題（RQ）**：{rq_id}：{sec['goal']}")
        lines.append(f"- **所需資料類型**：{data_type}")
        lines.append(f"- **目標讀者契合度**：內容須以「{parsed['audience']}」能消化的深度撰寫")
        lines.append(f"- **預期圖表**：0~2 張（依章節性質）")
        lines.append(f"- **預期引用密度**：~2~4 條/千字（{parsed['template']} 範本基準）")
        lines.append("")

    lines.append("## 4. 給 Executor 的交付清單")
    lines.append("")
    lines.append("- 對應 `lock.md` 已產出（17 個 required 欄位齊備）")
    lines.append("- 各章 HTML 將由 Executor 逐節生成 → `section_N.html`")
    lines.append("- Topic-Research 將在每章 HTML 生成前先產 `chapter_N_research.md`")
    lines.append("- Bundle 後產出 `report_final.html` → `report_final.docx`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*0_outline.md — 自動產生；下一步：User Confirmation Loop*")
    lines.append("")
    return "\n".join(lines)


def _guess_data_type(section_title: str) -> str:
    """依章節標題推測所需資料類型。"""
    title = section_title.lower()
    if "緒論" in title or "背景" in title or "前言" in title:
        return "研究背景文獻 + 領域趨勢"
    if "文獻" in title or "相關工作" in title or "review" in title:
        return "同領域期刊 / 會議論文 + 引用網絡"
    if "方法" in title or "設計" in title or "method" in title:
        return "技術架構圖 + 演算法描述 + 工具/函式庫清單"
    if "結果" in title or "實驗" in title or "評估" in title or "result" in title:
        return "實驗數據 + 統計圖表 + benchmark 比較"
    if "討論" in title or "結論" in title or "conclusion" in title:
        return "綜合分析 + 限制 + 未來工作"
    if "摘要" in title or "abstract" in title:
        return "全篇濃縮（300 字內）"
    if "api" in title or "規格" in title or "spec" in title:
        return "API 表格 + 程式碼範例 + 型別定義"
    if "實作" in title or "implementation" in title:
        return "關鍵程式碼 + 部署流程 + 設定檔"
    return "概念性敘述 + 必要時的圖表佐證"


# ─── 產出 lock.md ───────────────────────────────────────────────────

def build_lock_for_executor(parsed: Dict[str, Any], output_dir: Path) -> Path:
    """根據 parsed intent 產出合法 lock.md。"""
    template = parsed["template"]
    if template not in TEMPLATE_METADATA:
        template = "academic"

    sections = []
    for i, sec in enumerate(parsed["sections"], 1):
        sections.append({
            "path": f"section_{i}.html",
            "title": sec["title"],
        })

    lock_data = build_lock_template(
        template=template,
        metadata_overrides={
            "title": parsed["title"],
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        sections_override=sections,
    )

    body = (
        f"# report_lock.md\n\n"
        f"> 機器執行合同（template: {template}）\n"
        f"> 產生時間：{datetime.now().isoformat(timespec='seconds')}\n"
        f"> 產出者：Outliner CLI（scripts/outliner.py；D1 新流程）\n\n"
        f"⚠️  修改前請同步 SPEC.md §3.4.1 與 docs/report_lock_schema.md。\n"
    )
    content = serialize_lock_content(lock_data, body)
    lock_path = output_dir / "lock.md"
    lock_path.write_text(content, encoding="utf-8")
    return lock_path


# ─── 主要 API ───────────────────────────────────────────────────────

def run_outliner(
    strategist_path: Path,
    outline_output: Path,
    *,
    lock_output: Optional[Path] = None,
) -> Tuple[Path, Optional[Path]]:
    """跑 Outliner：讀 intent → 寫 outline + lock。"""
    parsed = parse_intent_brief(strategist_path)
    md = build_outline_markdown(parsed)
    outline_output.parent.mkdir(parents=True, exist_ok=True)
    outline_output.write_text(md, encoding="utf-8")

    if lock_output is None:
        lock_output = outline_output.parent / "lock.md"
    lock_path = build_lock_for_executor(parsed, lock_output.parent)
    if lock_output != lock_path:
        lock_output.write_text(lock_path.read_text(encoding="utf-8"), encoding="utf-8")
        lock_path = lock_output
    return outline_output, lock_path


# ─── CLI ────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master outliner",
        description="Stage 1.5 Outliner（D1 新流程）：intent brief → outline + lock",
    )
    parser.add_argument(
        "--strategist", "-s",
        type=Path,
        required=True,
        help="0_strategist.md 路徑（Strategist 產出）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="0_outline.md 輸出路徑（會自動寫同目錄的 lock.md）",
    )
    parser.add_argument(
        "--lock-output", "-l",
        type=Path,
        default=None,
        help="lock.md 輸出路徑（省略則寫到 outline 同目錄）",
    )
    args = parser.parse_args()

    try:
        outline_path, lock_path = run_outliner(
            strategist_path=args.strategist,
            outline_output=args.output,
            lock_output=args.lock_output,
        )
    except (IntentBriefMissingError, OutlinerError, StrategistError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    print(f"✅ outline 已寫入：{outline_path}")
    if lock_path:
        print(f"✅ lock 已寫入：{lock_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
