"""scripts/topic_research.py — Report-master no-source workflow CLI helper.

對應 `workflows/topic-research.md` v1.0 + `tasks.md` T3-3。

用途：
- 接收單一 topic 字串（無 PDF / DOCX / URL / MD 等 source materials）
- 跑 Research 階段：LLM 初步研究 → 產 3-5 個 sub-questions
- 跑 Outline 階段：sub-questions → 5-7 個 H1 章節
- 寫入 `report_output/research_notes.md`

LLM 介面：
- 讀 env：LLM_API_URL / LLM_API_KEY / LLM_MODEL（optional）
- 未設定 → 走 StubLLM（回傳 canned response，給測試與離線使用）
- 設定 → 用 requests 呼叫 OpenAI-compatible chat completions API

CLI：
    python -m scripts.topic_research --topic "生成式 AI 對教育的影響"
    python -m scripts.topic_research --topic "..." --output ./custom_dir/

Return code：
    0 = 成功
    1 = LLM 失敗（網路 / API error / parse error）
    2 = 產出驗證失敗（sub-questions < 3、outline < 5 章）
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允許 CLI 直接執行（`python scripts/topic_research.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 例外 ────────────────────────────────────────────────────────────

class TopicResearchError(Exception):
    """topic_research 例外基底。"""


class LLMError(TopicResearchError):
    """LLM 呼叫 / 解析失敗。"""


class ResearchValidationError(TopicResearchError):
    """產出不符合最低品質要求（sub-questions < 3、outline 章節 < 3）。"""


# ─── 資料結構 ────────────────────────────────────────────────────────

@dataclass
class SubQuestion:
    """單一 sub-question（Research 階段產出）。"""
    id: str
    question: str
    angle: str  # 理論 / 實務 / 影響 / 案例 / 未來 / 其他

    def to_markdown(self) -> str:
        return (
            f"### {self.id.upper()}: {self.question}\n"
            f"- **面向**：{self.angle}\n"
            f"- **簡述**：（待 Stage 2 Executor 補）\n"
        )


@dataclass
class OutlineSection:
    """單一 H1 章節（Outline 階段產出）。"""
    index: int
    title: str
    path: str
    sub_question_id: Optional[str] = None  # 對應的 sub-question；None 表示緒論 / 結論

    def to_markdown(self, level: int = 1) -> str:
        bullet = "#" * level
        sq_note = f"（對應 sub-question：{self.sub_question_id}）" if self.sub_question_id else "（作為開場）" if self.index == 1 else "（作為收束）"
        return f"{bullet} **{self.title}**{sq_note}"


@dataclass
class ResearchNotes:
    """topic-research 完整產出（聚合結構）。"""
    topic: str
    sub_questions: List[SubQuestion] = field(default_factory=list)
    outline: List[OutlineSection] = field(default_factory=list)
    suggested_type: str = "academic"
    suggested_citation_style: str = "APA"
    source_materials: str = "llm_research"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # ─── 驗證 ──────────────────────────────────────────────────────

    def validate(self, min_sub_questions: int = 3, min_outline: int = 3) -> None:
        """驗證 research_notes 是否符合最低品質要求。

        Args:
            min_sub_questions: 最低 sub-question 數（預設 3，對應 Q6 BLOCKING 條件）
            min_outline: 最低 H1 章節數（預設 3）

        Raises:
            ResearchValidationError: 任何一項未達標
        """
        problems: List[str] = []
        if len(self.sub_questions) < min_sub_questions:
            problems.append(
                f"sub-questions={len(self.sub_questions)} < {min_sub_questions}（深度不足）"
            )
        if len(self.outline) < min_outline:
            problems.append(
                f"outline 章節={len(self.outline)} < {min_outline}（結構不足）"
            )
        # 檢查 sub-question id 唯一
        sq_ids = [sq.id for sq in self.sub_questions]
        if len(sq_ids) != len(set(sq_ids)):
            problems.append(f"sub-question id 重複：{sq_ids}")
        # 檢查 outline 標題非空
        for sec in self.outline:
            if not sec.title or not sec.title.strip():
                problems.append(f"outline index={sec.index} 標題為空")
        if problems:
            raise ResearchValidationError(
                "[BLOCKING] research_notes 驗證失敗：\n  - " + "\n  - ".join(problems)
            )

    # ─── 序列化 ─────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """序列化為 research_notes.md 內容。"""
        lines: List[str] = []
        lines.append("# research_notes.md — Topic Research 階段產物")
        lines.append("")
        lines.append(f"> 對應 `workflows/topic-research.md` v1.0")
        lines.append(f"> 主題：{self.topic}")
        lines.append(f"> 產生時間：{self.timestamp}")
        lines.append(f"> 產出者：scripts/topic_research.py")
        lines.append("")

        # Sub-questions
        lines.append("## Sub-questions")
        lines.append("")
        lines.append(f"針對「{self.topic}」展開的 {len(self.sub_questions)} 個 sub-questions：")
        lines.append("")
        for sq in self.sub_questions:
            lines.append(sq.to_markdown())
            lines.append("")

        # Outline
        lines.append("## Outline")
        lines.append("")
        lines.append(f"對應的章節大綱（H1）：")
        lines.append("")
        for sec in self.outline:
            sq_note = (
                f"   - 對應 sub-question：{sec.sub_question_id}"
                if sec.sub_question_id
                else f"   - 對應 sub-question：（{'開場' if sec.index == 1 else '收束'}）"
            )
            lines.append(f"{sec.index}. **{sec.title}**")
            lines.append(f"   - 對應檔案：`{sec.path}`")
            lines.append(sq_note)
            lines.append("")

        # 預期頁數
        lines.append("## 預期頁數 / 字數")
        lines.append("")
        lines.append(f"- 頁數：30-50 頁（粗估）")
        lines.append(f"- 字數：~15000 字")
        lines.append("")

        # 給 Strategist 的提示
        lines.append("## 給 Strategist 的提示")
        lines.append("")
        lines.append(f"- 報告類型：建議 `{self.suggested_type}`")
        lines.append(f"- 引用風格：建議 `{self.suggested_citation_style}`")
        lines.append(f"- 來源材料：`source.materials: {self.source_materials}`")
        lines.append(f"- 註：Strategist 10 Confirmations 仍需依序回答，topic-research 只給方向不定細節")
        lines.append("")

        return "\n".join(lines)


# ─── LLM 介面（stub + real） ────────────────────────────────────────

class BaseLLM:
    """LLM 介面基底類別。"""

    def generate_sub_questions(self, topic: str, n: int = 5) -> List[SubQuestion]:
        """產出 n 個 sub-questions。"""
        raise NotImplementedError

    def generate_outline(
        self,
        topic: str,
        sub_questions: List[SubQuestion],
        n_sections: int = 5,
    ) -> List[OutlineSection]:
        """產出 n_sections 個 H1 章節。"""
        raise NotImplementedError


class StubLLM(BaseLLM):
    """Stub LLM — 不打 API，回傳 canned response。

    用於：
    - 測試（無網路）
    - 離線開發
    - 環境未設 LLM_API_URL / LLM_API_KEY 時的 fallback
    """

    _CANNED_ANGLES = ["理論", "實務", "影響", "案例", "未來"]

    def generate_sub_questions(self, topic: str, n: int = 5) -> List[SubQuestion]:
        # Stub: 固定回傳 3 個 sub-questions（保證 ≥ 3，滿足 BLOCKING 條件）
        actual_n = max(n, 3)
        actual_n = min(actual_n, len(self._CANNED_ANGLES))
        questions: List[SubQuestion] = []
        for i in range(actual_n):
            qid = f"q{i+1}"
            angle = self._CANNED_ANGLES[i]
            question = f"[STUB] {topic} 的 {angle} 面向探討（請替換為真實 sub-question）"
            questions.append(SubQuestion(id=qid, question=question, angle=angle))
        return questions

    def generate_outline(
        self,
        topic: str,
        sub_questions: List[SubQuestion],
        n_sections: int = 5,
    ) -> List[OutlineSection]:
        # Stub: 固定產出 5 章 outline
        actual_n = max(n_sections, 3)
        sections: List[OutlineSection] = []
        for i in range(actual_n):
            if i == 0:
                title = "第一章 緒論"
                sq_id = None
            elif i == actual_n - 1:
                title = f"第{_to_chinese_num(i+1)}章 結論與未來展望"
                sq_id = None
            else:
                # 中間章節：對應 sub-questions[i-1]
                sq = sub_questions[i - 1] if i - 1 < len(sub_questions) else None
                if sq:
                    title = f"第{_to_chinese_num(i+1)}章 {sq.angle}面向分析"
                    sq_id = sq.id
                else:
                    title = f"第{_to_chinese_num(i+1)}章 延伸討論"
                    sq_id = None
            sections.append(
                OutlineSection(
                    index=i + 1,
                    title=title,
                    path=f"report_output/section_{i+1}.html",
                    sub_question_id=sq_id,
                )
            )
        return sections


def _to_chinese_num(n: int) -> str:
    """1-10 轉中文數字（章節編號用）。"""
    mapping = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
    return mapping.get(n, str(n))


class HTTPLLM(BaseLLM):
    """真實 LLM — 透過 HTTP 呼叫 OpenAI-compatible chat completions API。

    環境變數：
        LLM_API_URL   — e.g. https://api.openai.com/v1/chat/completions
        LLM_API_KEY   — e.g. sk-xxxxx
        LLM_MODEL     — e.g. gpt-4o-mini（optional，預設 gpt-4o-mini）
        LLM_TIMEOUT   — 逾時秒數（optional，預設 30）

    注意：若環境無 `requests` 套件 → raise LLMError（不自動降級 StubLLM，由 caller 決定）
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_TIMEOUT = 30

    def __init__(self) -> None:
        self.api_url = os.environ.get("LLM_API_URL", "")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", self.DEFAULT_MODEL)
        try:
            self.timeout = int(os.environ.get("LLM_TIMEOUT", str(self.DEFAULT_TIMEOUT)))
        except ValueError:
            self.timeout = self.DEFAULT_TIMEOUT

    def _call(self, prompt: str) -> str:
        import json
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise LLMError(
                "需要 `requests` 套件才能呼叫 HTTP LLM；請 `pip install requests`"
            ) from e

        if not self.api_url or not self.api_key:
            raise LLMError(
                "LLM_API_URL / LLM_API_KEY 未設定；請設定環境變數或走 StubLLM"
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一個專業研究助理。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                self.api_url, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except Exception as e:
            raise LLMError(f"HTTP 呼叫失敗：{e}") from e

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, ValueError, IndexError) as e:
            raise LLMError(f"回應解析失敗：{e}") from e

    def generate_sub_questions(self, topic: str, n: int = 5) -> List[SubQuestion]:
        prompt = (
            f"請針對主題「{topic}」產出 {n} 個 sub-questions。\n"
            f"每個 sub-question 應：\n"
            f"- 具體、可回答\n"
            f"- 涵蓋不同面向（理論 / 實務 / 影響 / 案例 / 未來）\n"
            f"- 適合 1-2 段 Markdown 文字回答\n\n"
            f"輸出格式（YAML）：\n"
            f"```yaml\n"
            f"sub_questions:\n"
            f"  - id: q1\n"
            f"    question: ...\n"
            f"    angle: 理論\n"
            f"```\n"
        )
        raw = self._call(prompt)
        return self._parse_sub_questions_yaml(raw)

    def _parse_sub_questions_yaml(self, raw: str) -> List[SubQuestion]:
        """從 LLM 輸出解析 sub_questions YAML。失敗則 raise LLMError。"""
        # 簡單實作：找 ```yaml ... ``` 區塊；用 PyYAML 解析
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise LLMError("需要 PyYAML 才能解析 LLM 輸出") from e

        m = re.search(r"```yaml\s*\n(.*?)```", raw, re.DOTALL)
        if not m:
            raise LLMError(f"LLM 輸出找不到 YAML 區塊：{raw[:200]}")
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError as e:
            raise LLMError(f"YAML 解析失敗：{e}") from e

        sq_list = data.get("sub_questions", [])
        if not sq_list:
            raise LLMError("LLM 輸出沒有 sub_questions 欄位")
        out: List[SubQuestion] = []
        for item in sq_list:
            out.append(
                SubQuestion(
                    id=str(item.get("id", f"q{len(out)+1}")),
                    question=str(item.get("question", "")),
                    angle=str(item.get("angle", "其他")),
                )
            )
        return out

    def generate_outline(
        self,
        topic: str,
        sub_questions: List[SubQuestion],
        n_sections: int = 5,
    ) -> List[OutlineSection]:
        # 簡化版：固定 prompt + parse（不在這個 task 強求完美 LLM 整合）
        prompt = (
            f"請根據以下 sub-questions，產出 {n_sections} 個 H1 章節：\n\n"
            f"主題：{topic}\n\n"
            f"Sub-questions：\n"
            + "\n".join([f"- {sq.id}: {sq.question}" for sq in sub_questions])
            + "\n\n輸出格式（YAML）：\n```yaml\noutline:\n  - title: 第一章 xxx\n    sub_question: q1\n```\n"
        )
        raw = self._call(prompt)
        return self._parse_outline_yaml(raw, n_sections)

    def _parse_outline_yaml(self, raw: str, n_sections: int) -> List[OutlineSection]:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise LLMError("需要 PyYAML") from e

        m = re.search(r"```yaml\s*\n(.*?)```", raw, re.DOTALL)
        if not m:
            raise LLMError(f"LLM 輸出找不到 YAML 區塊：{raw[:200]}")
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError as e:
            raise LLMError(f"YAML 解析失敗：{e}") from e

        out: List[OutlineSection] = []
        for i, item in enumerate(data.get("outline", []), 1):
            out.append(
                OutlineSection(
                    index=i,
                    title=str(item.get("title", f"第{_to_chinese_num(i)}章 標題待定")),
                    path=f"report_output/section_{i}.html",
                    sub_question_id=item.get("sub_question"),
                )
            )
        return out


def make_llm() -> BaseLLM:
    """根據環境變數決定 LLM 實作。"""
    api_url = os.environ.get("LLM_API_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    if api_url and api_key:
        return HTTPLLM()
    return StubLLM()


# ─── 主流程：run_research ───────────────────────────────────────────

def run_research(
    topic: str,
    output_dir: Path,
    llm: Optional[BaseLLM] = None,
    n_sub_questions: int = 5,
    n_sections: int = 5,
    min_sub_questions: int = 3,
    min_outline: int = 3,
    verbose: bool = True,
) -> ResearchNotes:
    """跑 Research + Outline 兩階段，產 ResearchNotes 並寫入檔案。

    Args:
        topic: 主題字串（不可空）
        output_dir: 寫入目錄（會自動建立 `report_output/` 子目錄）
        llm: LLM 實例（None → 自動 make_llm()）
        n_sub_questions: 期望 sub-questions 數（LLM 可能回傳較少）
        n_sections: 期望 outline 章節數
        min_sub_questions: 驗證最低 sub-questions 數
        min_outline: 驗證最低 outline 章節數
        verbose: 是否印進度

    Returns:
        ResearchNotes 物件

    Raises:
        ResearchValidationError: 產出未達標
        LLMError: LLM 呼叫 / 解析失敗
    """
    if not topic or not topic.strip():
        raise TopicResearchError("topic 不可為空")

    if llm is None:
        llm = make_llm()

    notes = ResearchNotes(topic=topic.strip())

    # Stage 1: Research
    if verbose:
        print(f"🔍 Research 階段：對「{topic}」展開 sub-questions ...")
    notes.sub_questions = llm.generate_sub_questions(topic, n=n_sub_questions)
    if verbose:
        print(f"   產出 {len(notes.sub_questions)} 個 sub-questions")

    # Stage 2: Outline
    if verbose:
        print(f"📋 Outline 階段：根據 sub-questions 產章節大綱 ...")
    notes.outline = llm.generate_outline(topic, notes.sub_questions, n_sections=n_sections)
    if verbose:
        print(f"   產出 {len(notes.outline)} 個 H1 章節")

    # 驗證
    notes.validate(min_sub_questions=min_sub_questions, min_outline=min_outline)

    # 寫入檔案
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_path = output_dir / "research_notes.md"
    notes_path.write_text(notes.to_markdown(), encoding="utf-8")
    if verbose:
        print(f"✅ Research notes 寫入：{notes_path}")
        print(f"   topic: {topic}")
        print(f"   sub-questions: {len(notes.sub_questions)}")
        print(f"   outline sections: {len(notes.outline)}")

    return notes


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master topic-research",
        description="Stage 0 no-source workflow：給 topic，產 research_notes.md",
    )
    parser.add_argument(
        "--topic", "-t",
        required=True,
        help="主題字串（必填）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("report_output"),
        help="輸出目錄（預設 ./report_output/）",
    )
    parser.add_argument(
        "--n-sub-questions",
        type=int,
        default=5,
        help="期望 sub-questions 數（預設 5）",
    )
    parser.add_argument(
        "--n-sections",
        type=int,
        default=5,
        help="期望 outline 章節數（預設 5）",
    )
    parser.add_argument(
        "--min-sub-questions",
        type=int,
        default=3,
        help="驗證最低 sub-questions 數（預設 3）",
    )
    parser.add_argument(
        "--min-outline",
        type=int,
        default=3,
        help="驗證最低 outline 章節數（預設 3）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="安靜模式（不印進度）",
    )

    args = parser.parse_args()

    try:
        run_research(
            topic=args.topic,
            output_dir=args.output,
            n_sub_questions=args.n_sub_questions,
            n_sections=args.n_sections,
            min_sub_questions=args.min_sub_questions,
            min_outline=args.min_outline,
            verbose=not args.quiet,
        )
    except ResearchValidationError as e:
        print(str(e), file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"[LLMError] {e}", file=sys.stderr)
        return 1
    except TopicResearchError as e:
        print(f"[TopicResearchError] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
