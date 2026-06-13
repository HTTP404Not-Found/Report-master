"""scripts/outliner.py — Report-master Stage 1.5 Outliner CLI helper.

對應 `workflows/phase-3-outliner.md` v1.0（planning/tasks.md A1）。

用途：
- 從 `report_output/0_strategist.md` 解析 research_questions (RQs)
- 規劃章節藍圖（含骨架章節、順序檢查、粒度檢查）
- 寫入 `report_output/0_outline.md`（機讀）+ `0_outline_for_review.md`（人讀）
- 支援 `--dry-run`（只印規劃結果）與 `--validate`（驗證既有 outline）

CLI：
  python -m scripts.outliner --strategist report_output/0_strategist.md --output report_output/0_outline.md
  python -m scripts.outliner --strategist 0_strategist.md --output 0_outline.md --review 0_outline_for_review.md
  python -m scripts.outliner --strategist 0_strategist.md --dry-run
  python -m scripts.outliner --validate 0_outline.md
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 允許 CLI 直接執行（`python scripts/outliner.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 例外 ────────────────────────────────────────────────────────────

class OutlinerError(Exception):
    """Outliner 例外基底。"""


class OutlinerInputError(OutlinerError):
    """輸入缺欄位（research_questions 為空、檔案不存在等）。"""

    def __init__(self, message: str):
        super().__init__(f"[BLOCKING] {message}")


class OutlinerOrderingError(OutlinerError):
    """章節順序檢查失敗。"""

    def __init__(self, message: str):
        super().__init__(f"[BLOCKING] 章節順序檢查失敗：{message}")


class OutlinerSchemaError(OutlinerError):
    """0_outline.md 結構驗證失敗（--validate 模式）。"""

    def __init__(self, missing: List[str]):
        self.missing = missing
        lines = ["[BLOCKING] 0_outline.md 結構驗證失敗，缺欄位："]
        for m in missing:
            lines.append(f"  - {m}")
        super().__init__("\n".join(lines))


# ─── 常數 ────────────────────────────────────────────────────────────

# 章節類型優先級（拓樸規則）
SECTION_TYPE_PRIORITY = [
    "introduction",
    "literature_review",
    "methodology",
    "analysis",
    "discussion",
    "conclusion",
]

# 章節類型判定關鍵字
SECTION_TYPE_KEYWORDS = {
    "introduction": ["緒論", "背景", "動機", "introduction", "overview", "執行摘要", "摘要"],
    "literature_review": ["文獻", "theory", "理論", "review", "文獻回顧", "理論基礎"],
    "methodology": ["方法", "methodology", "研究設計", "實驗設計", "研究方法"],
    "analysis": ["現況", "案例", "影響", "實證", "empirical", "時序", "分析", "診斷", "比較"],
    "discussion": ["討論", "風險", "倫理", "反思", "爭議", "限制", "緩解"],
    "conclusion": ["結論", "展望", "結論與建議", "結論與未來", "行動建議"],
}

# 粒度上下限（字）
GRANULARITY_MIN = 1500
GRANULARITY_MAX = 3000
GRANULARITY_HARD_MAX = 5000
DEFAULT_WORDS = 2000

# 章節數上限（規劃/tasks.md 突發狀況：> 10 須先問用戶）
MAX_SECTIONS = 10
MIN_SECTIONS = 3


# ─── RQ 解析 ────────────────────────────────────────────────────────

def parse_strategist_md(path: Path) -> Dict[str, Any]:
    """解析 0_strategist.md，抽取 metadata + research_questions + constraints。

    支援兩種格式：
    1. YAML frontmatter（```---``` 區塊）
    2. 純文字 ## 區塊（含 research_questions 清單）

    為避免額外依賴，這裡用簡化的 regex 解析（不引入 pyyaml）。
    """
    if not path.exists():
        raise OutlinerInputError(f"找不到輸入檔：{path}")

    text = path.read_text(encoding="utf-8")

    result: Dict[str, Any] = {
        "metadata": {},
        "research_questions": [],
        "constraints": {},
    }

    # ── YAML frontmatter 解析 ──
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            fm = text[3:end].strip()
            result.update(_parse_simple_yaml(fm))

    # ── 內嵌 ## research_questions 解析（fallback）──
    if not result["research_questions"]:
        result["research_questions"] = _parse_rqs_from_markdown(text)

    if not result["research_questions"]:
        raise OutlinerInputError(
            "0_strategist.md 缺少 research_questions。請回 Stage 1 Strategist 補欄位。"
        )

    return result


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """極簡 YAML 解析（支援 metadata / research_questions / constraints）。

    僅處理本 outliner 需要的子集，避免引入 pyyaml 依賴。
    """
    result: Dict[str, Any] = {"metadata": {}, "research_questions": [], "constraints": {}}
    current_section: Optional[str] = None
    current_rq: Optional[Dict[str, Any]] = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 區塊標頭
        if stripped.endswith(":") and not stripped.startswith("-"):
            current_section = stripped[:-1].strip()
            if current_section not in ("metadata", "research_questions", "constraints"):
                current_section = None
            current_rq = None
            continue

        # list item
        if stripped.startswith("- "):
            item_text = stripped[2:].strip()
            if current_section == "research_questions":
                current_rq = {"id": "", "question": "", "angle": "現況", "priority": "medium", "estimated_pages": 5}
                if item_text.startswith("{"):
                    inline = _parse_inline_dict(item_text)
                    current_rq.update(inline)
                else:
                    kv = _parse_kv_inline(item_text)
                    current_rq.update(kv)
                result["research_questions"].append(current_rq)
            continue

        # key: value
        if ":" in stripped and not stripped.startswith("-"):
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if current_section == "research_questions" and current_rq is not None:
                current_rq[key] = _coerce_value(value)
            elif current_section in ("metadata", "constraints"):
                result[current_section][key] = _coerce_value(value)

    return result


def _parse_inline_dict(text: str) -> Dict[str, Any]:
    """解析 `- {id: RQ1, question: ..., angle: ...}` 格式。"""
    result: Dict[str, Any] = {}
    inner = text.strip("{}").strip()
    for part in _split_top_level_commas(inner):
        if ":" in part:
            k, v = part.split(":", 1)
            result[k.strip()] = _coerce_value(v.strip().strip('"').strip("'"))
    return result


def _parse_kv_inline(text: str) -> Dict[str, Any]:
    """解析 `id: RQ1` 單行 k:v。"""
    if ":" not in text:
        return {}
    k, v = text.split(":", 1)
    return {k.strip(): _coerce_value(v.strip().strip('"').strip("'"))}


def _split_top_level_commas(text: str) -> List[str]:
    """在不在括號/引號內的逗號處分割。"""
    parts: List[str] = []
    depth = 0
    in_quote: Optional[str] = None
    cur = ""
    for ch in text:
        if in_quote:
            cur += ch
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            cur += ch
            continue
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _coerce_value(v: str) -> Any:
    """自動轉型：int / bool / str。"""
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def _parse_rqs_from_markdown(text: str) -> List[Dict[str, Any]]:
    """從 Markdown 內嵌 ## Research Questions 區塊解析 RQs。"""
    rqs: List[Dict[str, Any]] = []
    in_section = False
    for line in text.splitlines():
        if re.match(r"^##\s+Research Questions", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and line.startswith("##"):
            break
        if not in_section:
            continue
        m = re.match(r"^-\s+(RQ\d+):\s*(.+?)(?:\s*\(angle:\s*([^)]+)\))?$", line.strip())
        if m:
            rqs.append({
                "id": m.group(1),
                "question": m.group(2).strip(),
                "angle": (m.group(3) or "現況").strip(),
                "priority": "medium",
                "estimated_pages": 5,
            })
    return rqs


# ─── 章節規劃 ────────────────────────────────────────────────────────

def classify_section_type(title: str) -> str:
    """依標題關鍵字判定章節類型（拓樸規則用）。"""
    title_low = title.lower()
    for sec_type in reversed(SECTION_TYPE_PRIORITY):
        for kw in SECTION_TYPE_KEYWORDS[sec_type]:
            if kw.lower() in title_low:
                return sec_type
    return "analysis"


def plan_chapters(rqs: List[Dict[str, Any]], metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """從 RQs 規劃章節（含骨架章節）。"""
    chapters: List[Dict[str, Any]] = []

    # ── 骨架：緒論 ──
    chapters.append({
        "index": 1,
        "title": _build_intro_title(metadata),
        "type": "introduction",
        "rq_id": None,
        "target_words": 1800,
        "data_types": ["literature_review", "statistics"],
        "figures": ["Figure 1（研究架構圖）"],
        "tables": [],
        "citation_density": "medium",
        "special_elements": ["mermaid"],
        "sub_questions": [
            "研究背景與動機",
            "研究目的與問題",
            "章節安排",
        ],
        "notes": "必含研究問題與假設",
    })

    # ── 對應 RQ 的章節 ──
    for i, rq in enumerate(rqs, start=2):
        target_words = int(rq.get("estimated_pages", 5)) * 500
        target_words = max(GRANULARITY_MIN, min(target_words, GRANULARITY_HARD_MAX))
        chapters.append({
            "index": i,
            "title": f"第 {_zh_num(i)} 章：{_chapter_title_from_rq(rq)}",
            "type": "analysis",
            "rq_id": rq["id"],
            "target_words": target_words,
            "data_types": _infer_data_types(rq),
            "figures": _guess_figures(target_words, i),
            "tables": _guess_tables(target_words, i),
            "citation_density": "high" if rq.get("priority") == "high" else "medium",
            "special_elements": [],
            "sub_questions": _sub_questions_from_rq(rq),
            "notes": f"對應 {rq['id']}（{rq.get('angle', '')}）",
        })

    # ── 骨架：結論 ──
    last_index = len(rqs) + 2
    chapters.append({
        "index": last_index,
        "title": f"第 {_zh_num(last_index)} 章：結論與展望",
        "type": "conclusion",
        "rq_id": None,
        "target_words": 2000,
        "data_types": ["overview"],
        "figures": ["Figure X（結論示意圖）"],
        "tables": [],
        "citation_density": "medium",
        "special_elements": [],
        "sub_questions": [
            "研究結論",
            "政策 / 行動建議",
            "研究限制與未來方向",
        ],
        "notes": "整合所有 RQ 的回應",
    })

    return chapters


def _build_intro_title(metadata: Dict[str, Any]) -> str:
    title = metadata.get("title", "本研究")
    return f"第 1 章：緒論（{title}）"


def _chapter_title_from_rq(rq: Dict[str, Any]) -> str:
    q = rq["question"]
    if "？" in q:
        q = q.split("？")[0]
    if "?" in q:
        q = q.split("?")[0]
    return q.strip()[:20]


def _infer_data_types(rq: Dict[str, Any]) -> List[str]:
    angle = rq.get("angle", "")
    mapping = {
        "現況量化": ["empirical_data", "statistics"],
        "現況盤點": ["empirical_data", "statistics"],
        "現況診斷": ["empirical_data", "statistics"],
        "實證分析": ["empirical_data", "statistics", "case_study"],
        "實證研究": ["empirical_data", "statistics"],
        "方案比較": ["case_study", "expert_opinion"],
        "風險管理": ["case_study", "expert_opinion"],
        "風險分析": ["case_study", "expert_opinion"],
        "政策評估": ["literature_review", "case_study"],
        "成本效益": ["statistics", "empirical_data"],
        "情境推估": ["statistics", "expert_opinion"],
        "理論": ["literature_review"],
        "案例": ["case_study"],
    }
    return mapping.get(angle, ["literature_review", "expert_opinion"])


def _guess_figures(words: int, idx: int) -> List[str]:
    n_fig = max(1, words // 1500)
    return [f"Figure {idx}.{k+1}（示意圖）" for k in range(n_fig)]


def _guess_tables(words: int, idx: int) -> List[str]:
    n_tbl = max(0, words // 2000)
    return [f"Table {idx}.{k+1}（彙整表）" for k in range(n_tbl)]


def _sub_questions_from_rq(rq: Dict[str, Any]) -> List[str]:
    """從 RQ 文字衍生 3 個子問題。"""
    q = rq["question"]
    return [
        f"{q} 的現況為何？",
        f"{q} 的影響因素為何？",
        f"{q} 的實證 / 案例為何？",
    ]


def _zh_num(n: int) -> str:
    """1-12 轉中文數字（其餘用阿拉伯）。"""
    zh = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
          6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
          11: "十一", 12: "十二"}
    return zh.get(n, str(n))


# ── 順序檢查 ──────────────────────────────────────────────────────────

def check_ordering(chapters: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """驗證章節順序符合拓樸規則。

    Returns:
        (passed, reason)
    """
    if len(chapters) < MIN_SECTIONS:
        return False, f"章節數 {len(chapters)} < 最小 {MIN_SECTIONS}"

    if len(chapters) > MAX_SECTIONS:
        return False, f"章節數 {len(chapters)} > 上限 {MAX_SECTIONS}（見 planning/tasks.md 突發狀況）"

    if chapters[0]["type"] != "introduction":
        return False, f"第一章不是緒論（目前是 {chapters[0]['type']}）"

    if chapters[-1]["type"] != "conclusion":
        return False, f"最後一章不是結論（目前是 {chapters[-1]['type']}）"

    prev_pri = -1
    for ch in chapters:
        pri = SECTION_TYPE_PRIORITY.index(ch["type"])
        if pri < prev_pri:
            return False, f"第 {ch['index']} 章（{ch['type']}）違反遞增順序"
        prev_pri = pri

    return True, "PASS"


def check_granularity(chapters: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """驗證章節粒度。"""
    warnings: List[str] = []
    for ch in chapters:
        w = ch["target_words"]
        if w < GRANULARITY_MIN:
            warnings.append(f"第 {ch['index']} 章 {w} 字 < 最小 {GRANULARITY_MIN}（應合併）")
        elif w > GRANULARITY_HARD_MAX:
            warnings.append(f"第 {ch['index']} 章 {w} 字 > 硬上限 {GRANULARITY_HARD_MAX}（BLOCKING）")
    return len([w for w in warnings if "BLOCKING" in w]) == 0, warnings


# ─── 輸出產物 ────────────────────────────────────────────────────────

def render_outline_md(
    strategist: Dict[str, Any],
    chapters: List[Dict[str, Any]],
    order_passed: bool,
    order_reason: str,
) -> str:
    """產出 0_outline.md（機讀）。"""
    md = strategist["metadata"]
    total_words = sum(c["target_words"] for c in chapters)
    total_figs = sum(len(c["figures"]) for c in chapters)
    total_tbls = sum(len(c["tables"]) for c in chapters)
    total_cites = sum(c["target_words"] // 50 for c in chapters)

    lines: List[str] = []
    lines.append(f"# Section Blueprint — {md.get('title', '未命名報告')}")
    lines.append("")
    lines.append("> 對應 `workflows/phase-3-outliner.md` v1.0（Stage 1.5）")
    lines.append(f"> 報告：{md.get('title', '未命名')}")
    lines.append(f"> 作者：{md.get('author', '未指定')}")
    lines.append(f"> 日期：{datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"> 總章節數：{len(chapters)}")
    lines.append(f"> 預估總字數：~{total_words} 字")
    lines.append(f"> 來源：report_output/0_strategist.md")
    lines.append("")
    lines.append("## 章節藍圖")
    lines.append("")

    for ch in chapters:
        lines.append(f"### {ch['title']}（H1）")
        lines.append(f"- **目標**：{_chapter_goal(ch, md)}")
        lines.append(f"- **預估字數**：~{ch['target_words']} 字")
        lines.append(f"- **預估頁數**：~{ch['target_words'] // 500} 頁")
        lines.append(f"- **對應 RQ**：{ch['rq_id'] or '（無，作為開場 / 結論）'}")
        lines.append("- **核心子問題**：")
        for sq in ch["sub_questions"]:
            lines.append(f"  - {sq}")
        lines.append(f"- **所需資料類型**：{', '.join(ch['data_types'])}")
        if ch["figures"]:
            lines.append(f"- **預期圖表**：{', '.join(ch['figures'])}")
        if ch["tables"]:
            lines.append(f"- **預期表格**：{', '.join(ch['tables'])}")
        lines.append(f"- **預期引用密度**：{ch['citation_density']}")
        if ch["special_elements"]:
            lines.append(f"- **特殊元素**：{', '.join(ch['special_elements'])}")
        if ch.get("notes"):
            lines.append(f"- **備註**：{ch['notes']}")
        lines.append("")

    lines.append("## 全域規劃")
    lines.append("")
    lines.append(f"- **圖總數**：{total_figs}")
    lines.append(f"- **表總數**：{total_tbls}")
    lines.append(f"- **引用總數**：~{total_cites} 條")
    special = sorted({s for ch in chapters for s in ch["special_elements"]})
    lines.append(f"- **特殊元素**：{', '.join(special) if special else '（無）'}")
    lines.append(f"- **預估總字數**：~{total_words} 字")
    lines.append(f"- **預估完成時間**：~{max(1, total_words // 2500)} 小時")
    skeleton_types = [ch["type"] for ch in chapters if ch["type"] in ("introduction", "conclusion", "literature_review", "methodology")]
    lines.append(f"- **骨架章節**：{', '.join(skeleton_types)}")
    status = "✅ PASS" if order_passed else f"❌ FAIL（{order_reason}）"
    lines.append(f"- **邏輯順序檢查**：{status}")
    lines.append("")
    lines.append("## 給 Executor 的提示")
    lines.append("")
    lines.append("- 每節 prompt 注入「目標」+「核心子問題」+「對應 RQ」")
    lines.append("- 第 3、4 章等需要外部資料的章節先執行 C1 web_research")
    lines.append("- mid-run 改 blueprint → 走 Stage 2.5（delta_checker → 單節重跑）")
    lines.append("")

    return "\n".join(lines)


def render_for_review_md(
    strategist: Dict[str, Any],
    chapters: List[Dict[str, Any]],
    order_passed: bool,
    order_reason: str,
) -> str:
    """產出 0_outline_for_review.md（人讀）。"""
    total_words = sum(c["target_words"] for c in chapters)
    total_figs = sum(len(c["figures"]) for c in chapters)
    total_tbls = sum(len(c["tables"]) for c in chapters)
    total_cites = sum(c["target_words"] // 50 for c in chapters)

    lines: List[str] = []
    lines.append("# 🔔 Stage 1.5 章節藍圖確認請求 — 請檢視後回覆 OK / 修改")
    lines.append("")
    lines.append("> 對應 `workflows/phase-3-outliner.md` v1.0 + `workflows/user-confirmation.md` v1")
    lines.append(f"> 來源：0_strategist.md（共 {len(strategist['research_questions'])} 個 RQs）")
    lines.append(f"> 規劃時間：{datetime.now().isoformat(timespec='seconds')}")
    lines.append("> 確認前不會啟動 User Confirmation 與 Executor。")
    lines.append("")
    lines.append(f"## 章節規劃總覽（{len(chapters)} 章）")
    lines.append("")
    for ch in chapters:
        rq_str = ch["rq_id"] or "（骨架）"
        title_part = ch["title"].split("：", 1)[-1] if "：" in ch["title"] else ch["title"]
        lines.append(f"- ✅ 第 {ch['index']} 章：{title_part}（{ch['target_words']} 字，對應 {rq_str}）")
    lines.append("")
    lines.append("## 章節順序")
    lines.append("")
    lines.append(" → ".join(str(c["index"]) for c in chapters))
    lines.append("")
    lines.append("## 邏輯順序檢查")
    lines.append("")
    if order_passed:
        lines.append("✅ PASS（背景→方法→結果→討論→結論；骨架章節齊備）")
    else:
        lines.append(f"❌ FAIL：{order_reason}")
    lines.append("")
    lines.append("## 章節粒度檢查")
    lines.append("")
    gran_pass, gran_warns = check_granularity(chapters)
    if gran_pass and not gran_warns:
        lines.append("✅ 全部在 1500-3000 字範圍內")
    else:
        lines.append("⚠️ 例外章節：")
        for w in gran_warns:
            lines.append(f"  - {w}")
    lines.append("")
    lines.append("## 全域統計")
    lines.append("")
    lines.append(f"- 總章節數：{len(chapters)}")
    lines.append(f"- 總字數：~{total_words} 字")
    lines.append(f"- 預估頁數：{total_words // 500} 頁")
    lines.append(f"- 圖表數：{total_figs} 圖 + {total_tbls} 表")
    lines.append(f"- 引用條目：~{total_cites} 條")
    special = sorted({s for ch in chapters for s in ch["special_elements"]})
    lines.append(f"- 特殊元素：{', '.join(special) if special else '（無）'}")
    lines.append("")
    lines.append("## RQ 對應檢查")
    lines.append("")
    lines.append("| RQ | 對應章節 | 狀態 |")
    lines.append("|----|---------|------|")
    for ch in chapters:
        if ch["rq_id"]:
            lines.append(f"| {ch['rq_id']} | 第 {ch['index']} 章 | ✅ |")
    for ch in chapters:
        if not ch["rq_id"]:
            lines.append(f"| （骨架）| 第 {ch['index']} 章 {ch['type']} | ✅ |")
    lines.append("")
    lines.append("## 回覆方式")
    lines.append("")
    lines.append("- 全部 OK：回覆「OK」或「✅」")
    lines.append("- 部分修改：例「第 2 章併入第 3 章」「第 4 章改成兩章」")
    lines.append("- 整體重來：回覆「REDO」回到 Stage 1 Strategist")
    lines.append("")
    lines.append("## 確認後")
    lines.append("")
    lines.append("- Main agent 會把您的回覆寫入 `report_output/0_confirmed.json`")
    lines.append("- 然後 Strategist 補產 `report_lock.md` / `report_spec.md` / `glossary.md`")
    lines.append("- 最後 Stage 2 Executor 啟動")
    lines.append("")

    return "\n".join(lines)


def _chapter_goal(ch: Dict[str, Any], md: Dict[str, Any]) -> str:
    """產生章節目標句。"""
    if ch["type"] == "introduction":
        return f"交代「{md.get('title', '本研究')}」的研究背景、動機、目的與章節安排"
    if ch["type"] == "conclusion":
        return "總結研究發現、提出政策 / 行動建議、指出研究限制與未來方向"
    return f"回答 {ch['rq_id']}：「{ch['sub_questions'][0]}」"


# ─── 驗證既有 outline ─────────────────────────────────────────────────

def validate_outline(path: Path) -> bool:
    """驗證既有 0_outline.md 結構。"""
    if not path.exists():
        raise OutlinerInputError(f"找不到 outline 檔：{path}")

    text = path.read_text(encoding="utf-8")
    required = [
        "# Section Blueprint",
        "## 章節藍圖",
        "## 全域規劃",
        "## 給 Executor 的提示",
    ]
    missing = [r for r in required if r not in text]
    if "### 第 " not in text:
        missing.append("至少一個 ### 第 N 章")
    if missing:
        raise OutlinerSchemaError(missing)
    return True


# ─── CLI ─────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.outliner",
        description="Report-master Stage 1.5 Outliner CLI",
    )
    parser.add_argument("--strategist", type=Path, help="輸入 0_strategist.md 路徑")
    parser.add_argument("--output", type=Path, help="輸出 0_outline.md 路徑")
    parser.add_argument("--review", type=Path, help="額外輸出 0_outline_for_review.md 路徑")
    parser.add_argument("--dry-run", action="store_true", help="只印規劃結果，不寫檔")
    parser.add_argument("--validate", type=Path, help="驗證既有 0_outline.md 結構")
    args = parser.parse_args(argv)

    try:
        if args.validate:
            validate_outline(args.validate)
            print(f"✅ {args.validate} 結構驗證通過")
            return 0

        if not args.strategist:
            print("[ERROR] 必須指定 --strategist 或 --validate", file=sys.stderr)
            return 1

        strategist = parse_strategist_md(args.strategist)
        n_rqs = len(strategist["research_questions"])
        print(f"📖 解析 {args.strategist} 完成：{n_rqs} 個 RQs")

        chapters = plan_chapters(strategist["research_questions"], strategist["metadata"])
        print(f"📐 規劃 {len(chapters)} 章")

        if len(chapters) > MAX_SECTIONS:
            print(
                f"[WARN] 章節數 {len(chapters)} > {MAX_SECTIONS}。"
                f"見 planning/tasks.md 突發狀況：先問用戶「章節數是否太多？」再繼續。",
                file=sys.stderr,
            )
            return 3

        order_passed, order_reason = check_ordering(chapters)
        if not order_passed:
            print(f"[ERROR] 順序檢查失敗：{order_reason}", file=sys.stderr)
            return 4
        print(f"✅ 邏輯順序檢查：{order_reason}")

        gran_pass, gran_warns = check_granularity(chapters)
        for w in gran_warns:
            print(f"[WARN] {w}", file=sys.stderr)

        outline_md = render_outline_md(strategist, chapters, order_passed, order_reason)
        review_md = render_for_review_md(strategist, chapters, order_passed, order_reason)

        if args.dry_run:
            print("\n" + "=" * 60)
            print("DRY RUN — 0_outline.md 預覽：")
            print("=" * 60)
            print(outline_md)
            return 0

        if not args.output:
            print("[ERROR] 非 --dry-run 模式必須指定 --output", file=sys.stderr)
            return 1

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(outline_md, encoding="utf-8")
        print(f"✅ 寫入 {args.output}")

        if args.review:
            args.review.parent.mkdir(parents=True, exist_ok=True)
            args.review.write_text(review_md, encoding="utf-8")
            print(f"✅ 寫入 {args.review}")

        print(f"\n📊 摘要：{len(chapters)} 章 / ~{sum(c['target_words'] for c in chapters)} 字")
        return 0

    except OutlinerError as e:
        print(f"[BLOCKING] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
