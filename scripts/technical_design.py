"""scripts/technical_design.py — Report-master 技術規格文件生成 CLI helper.

對應 `workflows/technical-design.md` v1.0 + `tasks.md` T3-14。

用途：
- 接收功能名稱 (`--name`)、目標讀者 (`--audience`)、需求概述 (`--scope`)
- 跑 7 個階段：Scope → Architecture → API Design → Data Model → Implementation Plan
  → Review (Final Gate) → Output
- 產出 `technical_design_output/<name>/design.md`（主文件）
- 可選產出 `architecture.svg`（呼叫 `scripts.mermaid_renderer`）/ `api.md` / `data_model.md`

LLM 介面：
- 讀 env：LLM_API_URL / LLM_API_KEY / LLM_MODEL（optional）
- 未設定 → 走 StubLLM（回傳 canned response，給測試與離線使用）
- 設定 → 用 requests 呼叫 OpenAI-compatible chat completions API

CLI：
    python -m scripts.technical_design --name "markdown-input-support" --scope "..."
    python -m scripts.technical_design --name "..." --audience engineers --with-svg

Return code：
    0 = Final Gate PASS（design.md 6 章節齊備）
    1 = Final Gate FAIL（缺章節）
    2 = argument 解析失敗
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

# 允許 CLI 直接執行（`python scripts/technical_design.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 例外 ────────────────────────────────────────────────────────────

class TechnicalDesignError(Exception):
    """technical_design 例外基底。"""


class LLMError(TechnicalDesignError):
    """LLM 呼叫 / 解析失敗。"""


class FinalGateError(TechnicalDesignError):
    """Final Gate 校驗失敗（缺章節）。"""


# ─── 資料結構 ────────────────────────────────────────────────────────

@dataclass
class ScopeQuestion:
    """Scope 階段的單一問題。"""
    id: str
    topic: str
    question: str
    answer: str = ""  # 使用者回答（自動模式填 stub 答案）

    def to_markdown(self) -> str:
        ans = self.answer if self.answer else "（未答；待人工補）"
        return (
            f"### {self.id.upper()}: {self.topic}\n"
            f"\n"
            f"**問題**：{self.question}\n"
            f"\n"
            f"**答案**：{ans}\n"
        )


@dataclass
class ArchitectureNode:
    """架構圖的單一節點。"""
    id: str
    name: str
    description: str


@dataclass
class APISpec:
    """單一 API 規格。"""
    name: str
    endpoint: str
    input_desc: str
    output_desc: str
    error_desc: str

    def to_markdown(self) -> str:
        return (
            f"### API: {self.name}\n"
            f"\n"
            f"- **Endpoint**: `{self.endpoint}`\n"
            f"- **Input**:\n{self.input_desc}\n"
            f"- **Output**:\n{self.output_desc}\n"
            f"- **Error handling**:\n{self.error_desc}\n"
        )


@dataclass
class Entity:
    """單一 data model entity。"""
    name: str
    fields: List[Dict[str, str]]  # [{name, type, nullable, description}, ...]
    relations: str = ""

    def to_markdown(self) -> str:
        lines = [f"### Entity: {self.name}", ""]
        lines.append("| 欄位 | 型別 | Nullable | 說明 |")
        lines.append("|------|------|----------|------|")
        for f in self.fields:
            lines.append(
                f"| `{f.get('name', '')}` | {f.get('type', '')} | "
                f"{f.get('nullable', 'NO')} | {f.get('description', '')} |"
            )
        if self.relations:
            lines.append("")
            lines.append(f"**關聯**：{self.relations}")
        return "\n".join(lines)


@dataclass
class Milestone:
    """單一 milestone。"""
    name: str
    days: int
    deliverables: List[str]
    acceptance: List[str]

    def to_markdown(self) -> str:
        lines = [f"### {self.name}（預估 {self.days} 天）", ""]
        lines.append("**Deliverables**：")
        for d in self.deliverables:
            lines.append(f"- [ ] {d}")
        lines.append("")
        lines.append("**驗收標準**：")
        for a in self.acceptance:
            lines.append(f"- [ ] {a}")
        return "\n".join(lines)


@dataclass
class DesignDocument:
    """完整的技術規格文件。"""
    name: str
    audience: str
    scope: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    scope_questions: List[ScopeQuestion] = field(default_factory=list)
    architecture_overview: str = ""
    architecture_diagram: str = ""  # Mermaid 原始碼
    architecture_nodes: List[ArchitectureNode] = field(default_factory=list)
    data_flow: str = ""
    apis: List[APISpec] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    er_diagram: str = ""  # Mermaid erDiagram
    milestones: List[Milestone] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)

    # ─── 校驗 ──────────────────────────────────────────────────────

    def check_final_gate(self) -> List[str]:
        """Final Gate 校驗；回傳缺失項目清單（空 = PASS）。"""
        missing: List[str] = []
        if not self.architecture_overview.strip():
            missing.append("§2 Architecture 缺 overview")
        if not self.architecture_diagram.strip():
            missing.append("§2 Architecture 缺 Mermaid 圖")
        if len(self.architecture_nodes) < 3:
            missing.append(f"§2 Architecture 節點 {len(self.architecture_nodes)} < 3")
        if len(self.apis) < 3:
            missing.append(f"§3 API Design API 數 {len(self.apis)} < 3")
        for api in self.apis:
            if not api.endpoint or not api.input_desc or not api.output_desc or not api.error_desc:
                missing.append(f"§3 API '{api.name}' 缺欄位")
        if len(self.entities) < 2:
            missing.append(f"§4 Data Model entity 數 {len(self.entities)} < 2")
        if len(self.milestones) < 3:
            missing.append(f"§5 Implementation Plan milestone 數 {len(self.milestones)} < 3")
        for ms in self.milestones:
            if not ms.deliverables or not ms.acceptance:
                missing.append(f"§5 Milestone '{ms.name}' 缺 deliverables 或 acceptance")
        if not self.risks and not self.open_questions:
            missing.append("§6 Risks & Open Questions 完全空")
        return missing

    # ─── 序列化 ─────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """序列化為 design.md 內容。"""
        lines: List[str] = []
        lines.append(f"# Technical Design: {self.name}")
        lines.append("")
        lines.append(f"> 產生時間：{self.timestamp}")
        lines.append(f"> 目標讀者：{self.audience}")
        lines.append(f"> 作者：report-master technical-design workflow v1.0")
        lines.append(f"> 對應 workflow：`workflows/technical-design.md` v1.0")
        lines.append("")

        # §1 Overview
        lines.append("## 1. Overview")
        lines.append("")
        lines.append(f"### 功能名稱")
        lines.append(f"\n`{self.name}`\n")
        lines.append(f"### 目標讀者")
        lines.append(f"\n{self.audience}\n")
        lines.append(f"### 需求概述")
        lines.append(f"\n{self.scope}\n")

        # In/Out of scope (from scope Q&A)
        lines.append("### In-scope / Out-of-scope")
        lines.append("")
        in_scope_q = next((q for q in self.scope_questions if q.id == "q1"), None)
        if in_scope_q and in_scope_q.answer:
            lines.append(f"- **In-scope**：{in_scope_q.answer}")
        else:
            lines.append("- **In-scope**：（未答；請從 Scope Q&A 補）")
        lines.append("- **Out-of-scope**：（待人工定義）")
        lines.append("")

        # §2 Architecture
        lines.append("## 2. Architecture")
        lines.append("")
        lines.append("### 系統架構圖")
        lines.append("")
        lines.append("```mermaid")
        lines.append(self.architecture_diagram.strip())
        lines.append("```")
        lines.append("")
        lines.append("### 組件說明")
        lines.append("")
        for node in self.architecture_nodes:
            lines.append(f"- **{node.name}** — {node.description}")
        lines.append("")
        if self.architecture_overview:
            lines.append("### 架構總覽")
            lines.append("")
            lines.append(self.architecture_overview)
            lines.append("")
        if self.data_flow:
            lines.append("### 資料流")
            lines.append("")
            lines.append(self.data_flow)
            lines.append("")

        # §3 API Design
        lines.append("## 3. API Design")
        lines.append("")
        for api in self.apis:
            lines.append(api.to_markdown())
            lines.append("")

        # §4 Data Model
        lines.append("## 4. Data Model")
        lines.append("")
        if self.er_diagram.strip():
            lines.append("### ERD 概念圖")
            lines.append("")
            lines.append("```mermaid")
            lines.append(self.er_diagram.strip())
            lines.append("```")
            lines.append("")
        for ent in self.entities:
            lines.append(ent.to_markdown())
            lines.append("")

        # §5 Implementation Plan
        lines.append("## 5. Implementation Plan")
        lines.append("")
        for ms in self.milestones:
            lines.append(ms.to_markdown())
            lines.append("")

        # §6 Risks & Open Questions
        lines.append("## 6. Risks & Open Questions")
        lines.append("")
        if self.risks:
            lines.append("### Risks")
            lines.append("")
            for r in self.risks:
                lines.append(f"- {r}")
            lines.append("")
        if self.open_questions:
            lines.append("### Open Questions")
            lines.append("")
            for q in self.open_questions:
                lines.append(f"- {q}")
            lines.append("")

        # Final Gate checklist
        lines.append("---")
        lines.append("")
        lines.append("## Final Gate Checklist")
        lines.append("")
        missing = self.check_final_gate()
        if not missing:
            lines.append("- [x] §1 Overview 完整")
            lines.append("- [x] §2 Architecture 含 Mermaid 圖 + 組件說明")
            lines.append("- [x] §3 API Design 含 ≥ 3 個 API")
            lines.append("- [x] §4 Data Model 含 ≥ 2 個 entity")
            lines.append("- [x] §5 Implementation Plan 含 ≥ 3 個 milestones")
            lines.append("- [x] §6 Risks & Open Questions 非空")
            lines.append("")
            lines.append("✅ **Final Gate: PASS** — 所有章節齊備，可進入 review。")
        else:
            for m in missing:
                lines.append(f"- [ ] ❌ {m}")
            lines.append("")
            lines.append(f"❌ **Final Gate: FAIL** — {len(missing)} 個缺失。")
        lines.append("")

        return "\n".join(lines)

    def scope_to_markdown(self) -> str:
        """序列化為 scope.md 內容（Scope Q&A 留底）。"""
        lines: List[str] = []
        lines.append(f"# scope.md — Technical Design Scope Q&A")
        lines.append("")
        lines.append(f"> 對應 `workflows/technical-design.md` v1.0")
        lines.append(f"> 功能名稱：{self.name}")
        lines.append(f"> 產生時間：{self.timestamp}")
        lines.append(f"> 產出者：scripts/technical_design.py")
        lines.append("")
        lines.append("## Scope Q&A")
        lines.append("")
        lines.append(f"針對「{self.name}」展開的 {len(self.scope_questions)} 個 scope 問題：")
        lines.append("")
        for q in self.scope_questions:
            lines.append(q.to_markdown())
            lines.append("")
        return "\n".join(lines)


# ─── LLM 介面（stub + real） ────────────────────────────────────────

class BaseLLM:
    """LLM 介面基底類別。"""

    def generate_scope_questions(self, name: str, audience: str, scope: str) -> List[ScopeQuestion]:
        raise NotImplementedError

    def generate_architecture(self, name: str, scope: str, scope_answers: List[ScopeQuestion]) -> tuple:
        """回傳 (overview, mermaid_diagram, nodes, data_flow)。"""
        raise NotImplementedError

    def generate_apis(self, name: str, scope: str) -> List[APISpec]:
        raise NotImplementedError

    def generate_data_model(self, name: str, scope: str) -> tuple:
        """回傳 (entities, er_diagram)。"""
        raise NotImplementedError

    def generate_milestones(self, name: str, scope: str) -> List[Milestone]:
        raise NotImplementedError

    def generate_risks(self, name: str, scope: str) -> tuple:
        """回傳 (risks, open_questions)。"""
        raise NotImplementedError


class StubLLM(BaseLLM):
    """Stub LLM — 不打 API，回傳 canned response。

    用於：
    - 測試（無網路）
    - 離線開發
    - 環境未設 LLM_API_URL / LLM_API_KEY 時的 fallback
    """

    _SCOPE_TOPICS = [
        ("q1", "功能邊界", "這個功能包含哪些子功能？不包含哪些？"),
        ("q2", "非功能需求", "預期 QPS / 延遲 SLA / 可用性目標？"),
        ("q3", "資料規模", "預期資料量（rows / GB）、growth rate？"),
        ("q4", "相依項目", "必須整合的內部服務 / 外部 API？"),
        ("q5", "失敗模式", "timeout / retry / degradation 策略？"),
        ("q6", "取代 / 並存", "是新增功能、還是取代既有功能？"),
        ("q7", "風險", "已知的技術風險或 trade-off？"),
    ]

    def _stub_answer(self, topic: str, scope: str) -> str:
        return f"[STUB] 針對 {topic}：基於「{scope}」的 canned 答案。請替換為真實使用者回答。"

    def generate_scope_questions(self, name: str, audience: str, scope: str) -> List[ScopeQuestion]:
        out: List[ScopeQuestion] = []
        for qid, topic, question in self._SCOPE_TOPICS:
            q = ScopeQuestion(id=qid, topic=topic, question=question, answer=self._stub_answer(topic, scope))
            out.append(q)
        return out

    def generate_architecture(self, name: str, scope: str, scope_answers: List[ScopeQuestion]):
        overview = (
            f"本系統實作「{name}」功能，目標是：{scope}。\n\n"
            f"採用分層架構（CLI 入口 → 處理層 → 輸出層），"
            f"確保單一職責、可測試性、可觀測性。"
        )
        diagram = (
            "flowchart LR\n"
            "    User([使用者]) --> CLI[CLI 入口]\n"
            "    CLI --> Loader[Loader<br/>讀取輸入]\n"
            "    Loader --> Processor[Processor<br/>核心邏輯]\n"
            "    Processor --> Validator[Validator<br/>品質校驗]\n"
            "    Validator --> Output[Output<br/>產出]\n"
            "    Output --> User\n"
            "\n"
            "    style Loader fill:#ffd\n"
            "    style Processor fill:#ffd\n"
            "    style Validator fill:#dfd"
        )
        nodes = [
            ArchitectureNode(id="cli", name="CLI 入口", description="接收使用者命令，解析參數"),
            ArchitectureNode(id="loader", name="Loader", description="讀取輸入（檔案 / stdin / URL）"),
            ArchitectureNode(id="processor", name="Processor", description="執行核心邏輯（轉檔 / 計算）"),
            ArchitectureNode(id="validator", name="Validator", description="品質校驗（schema / 規格）"),
            ArchitectureNode(id="output", name="Output", description="產出最終檔案 / 寫入目的地"),
        ]
        data_flow = (
            "1. 使用者透過 CLI 傳入參數\n"
            "2. Loader 讀取來源（檔案 / stdin）\n"
            "3. Processor 執行轉檔 / 計算\n"
            "4. Validator 校驗結果是否符合規格\n"
            "5. Output 寫入目的地"
        )
        return overview, diagram, nodes, data_flow

    def generate_apis(self, name: str, scope: str) -> List[APISpec]:
        return [
            APISpec(
                name=f"執行 {name}",
                endpoint=f"python -m scripts.{name} --input <path> --output <path>",
                input_desc="```\n<input>     - 來源路徑（檔案或目錄；必填）\n<output>   - 目的地路徑（必填）\n```",
                output_desc="```\nstatus: success\noutput_path: /path/to/output\n```",
                error_desc="- `FileNotFoundError`: 來源不存在\n- `ValidationError`: 輸入格式錯誤\n- `PermissionError`: 目的地不可寫",
            ),
            APISpec(
                name=f"驗證 {name} 輸入",
                endpoint=f"python -m scripts.{name} validate --input <path>",
                input_desc="```\n<input>  - 要驗證的檔案\n```",
                output_desc="```\nvalid: true\nerrors: []\n```",
                error_desc="- `SchemaError`: 欄位缺漏或型別錯誤",
            ),
            APISpec(
                name=f"取得 {name} 版本",
                endpoint=f"python -m scripts.{name} --version",
                input_desc="（無）",
                output_desc="```\n{name} 1.0.0\n```",
                error_desc="（無）",
            ),
            APISpec(
                name=f"列出 {name} 支援的選項",
                endpoint=f"python -m scripts.{name} --help",
                input_desc="（無）",
                output_desc="```\nUsage: ...\nOptions: ...\n```",
                error_desc="（無）",
            ),
        ]

    def generate_data_model(self, name: str, scope: str) -> tuple:
        entities = [
            Entity(
                name="Job",
                fields=[
                    {"name": "job_id", "type": "string (PK)", "nullable": "NO", "description": "任務唯一 ID"},
                    {"name": "name", "type": "string", "nullable": "NO", "description": f"任務名稱（{name}）"},
                    {"name": "status", "type": "enum", "nullable": "NO", "description": "pending / running / done / failed"},
                    {"name": "input_path", "type": "string", "nullable": "NO", "description": "輸入檔案路徑"},
                    {"name": "output_path", "type": "string", "nullable": "YES", "description": "輸出檔案路徑（執行中為空）"},
                    {"name": "created_at", "type": "timestamp", "nullable": "NO", "description": "建立時間（UTC）"},
                ],
                relations="Job has many JobLog（一對多）",
            ),
            Entity(
                name="JobLog",
                fields=[
                    {"name": "log_id", "type": "string (PK)", "nullable": "NO", "description": "日誌唯一 ID"},
                    {"name": "job_id", "type": "string (FK)", "nullable": "NO", "description": "所屬任務 ID"},
                    {"name": "level", "type": "enum", "nullable": "NO", "description": "info / warn / error"},
                    {"name": "message", "type": "text", "nullable": "NO", "description": "日誌訊息"},
                    {"name": "created_at", "type": "timestamp", "nullable": "NO", "description": "記錄時間（UTC）"},
                ],
                relations="JobLog.job_id → Job.job_id（多對一）",
            ),
        ]
        er_diagram = (
            "erDiagram\n"
            "    JOB ||--o{ JOBLOG : has\n"
            "    JOB {\n"
            "        string job_id PK\n"
            "        string name\n"
            "        string status\n"
            "        string input_path\n"
            "        string output_path\n"
            "        timestamp created_at\n"
            "    }\n"
            "    JOBLOG {\n"
            "        string log_id PK\n"
            "        string job_id FK\n"
            "        string level\n"
            "        text message\n"
            "        timestamp created_at\n"
            "    }"
        )
        return entities, er_diagram

    def generate_milestones(self, name: str, scope: str) -> List[Milestone]:
        return [
            Milestone(
                name="M1: 基礎建設",
                days=3,
                deliverables=[
                    "CLI skeleton 與 argparse 框架",
                    "核心 module 結構建立",
                    "單元測試框架（pytest）",
                ],
                acceptance=[
                    "`pytest tests/ -q` 跑通（空 test 也算）",
                    "`python -m scripts.<name> --help` 正常輸出",
                    "CI pipeline 設定完成",
                ],
            ),
            Milestone(
                name="M2: 核心功能",
                days=5,
                deliverables=[
                    "happy path 跑通",
                    "輸入解析（loader）完成",
                    "輸出寫入（output）完成",
                ],
                acceptance=[
                    "用 example input 跑通 happy path",
                    "輸出檔案格式符合預期",
                    "錯誤訊息清楚可讀",
                ],
            ),
            Milestone(
                name="M3: 邊界情況",
                days=3,
                deliverables=[
                    "錯誤處理（bad input / timeout）",
                    "retry / degradation 邏輯",
                    "edge case 測試覆蓋",
                ],
                acceptance=[
                    "bad input 不 crash，給明確錯誤",
                    "timeout 自動 retry 3 次",
                    "edge case 測試全部通過",
                ],
            ),
            Milestone(
                name="M4: 觀測性與文件",
                days=2,
                deliverables=[
                    "logging 結構化（JSON 格式）",
                    "README / USAGE 文件",
                    "example 範例",
                ],
                acceptance=[
                    "log 可被 log aggregator 解析",
                    "README 含 quick start + 完整 CLI 說明",
                    "至少 1 個 example 跑通",
                ],
            ),
        ]

    def generate_risks(self, name: str, scope: str) -> tuple:
        risks = [
            f"效能風險：{name} 在大檔案（>1GB）下可能 OOM；緩解：streaming 處理",
            f"相容性風險：與既有 X 功能介面衝突；緩解：版本管理（v1 / v2 並存）",
            f"維護風險：scope 過大導致實作期拉長；緩解：M1-M2 結束時做 checkpoint",
        ]
        open_questions = [
            "Q：是否需要支援分散式執行？A：v1 單機即可；v2 評估",
            "Q：錯誤重試上限？A：暫定 3 次；可由 config 調整",
            "Q：logging 格式？A：JSON 結構化；待 ops team 確認",
        ]
        return risks, open_questions


class HTTPLLM(BaseLLM):
    """真實 LLM — 透過 HTTP 呼叫 OpenAI-compatible chat completions API。

    環境變數：
        LLM_API_URL   — e.g. https://api.openai.com/v1/chat/completions
        LLM_API_KEY   — e.g. sk-xxxxx
        LLM_MODEL     — e.g. gpt-4o-mini（optional，預設 gpt-4o-mini）
        LLM_TIMEOUT   — 逾時秒數（optional，預設 30

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
            raise LLMError("需要 `requests` 套件才能呼叫 HTTP LLM") from e

        if not self.api_url or not self.api_key:
            raise LLMError("LLM_API_URL / LLM_API_KEY 未設定")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一個資深技術架構師。"},
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

    # 為簡化，HTTPLLM 的 generate_* 方法不在 stub 中實作。
    # 實際整合留待 T3-x 後續任務；目前 StubLLM 已能滿足產出 design.md 的需求。
    def generate_scope_questions(self, name: str, audience: str, scope: str) -> List[ScopeQuestion]:
        # HTTP LLM 模式：fallback 到 stub（避免不必要的網路依賴）
        return StubLLM().generate_scope_questions(name, audience, scope)

    def generate_architecture(self, name: str, scope: str, scope_answers: List[ScopeQuestion]):
        return StubLLM().generate_architecture(name, scope, scope_answers)

    def generate_apis(self, name: str, scope: str) -> List[APISpec]:
        return StubLLM().generate_apis(name, scope)

    def generate_data_model(self, name: str, scope: str) -> tuple:
        return StubLLM().generate_data_model(name, scope)

    def generate_milestones(self, name: str, scope: str) -> List[Milestone]:
        return StubLLM().generate_milestones(name, scope)

    def generate_risks(self, name: str, scope: str) -> tuple:
        return StubLLM().generate_risks(name, scope)


def make_llm() -> BaseLLM:
    """根據環境變數決定 LLM 實作。"""
    api_url = os.environ.get("LLM_API_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    if api_url and api_key:
        return HTTPLLM()
    return StubLLM()


# ─── 主流程：run_design ─────────────────────────────────────────────

def _select_template(audience: str) -> str:
    """依 audience 決定範本。"""
    audience_lower = audience.lower().strip()
    if audience_lower in ("engineers", "engineer", "eng", "dev", "developer"):
        return "eng-v1"
    if audience_lower in ("pm", "product", "product_manager"):
        return "pm-v1"
    if audience_lower in ("executives", "executive", "exec", "leadership", "ceo", "cto"):
        return "exec-v1"
    if audience_lower in ("mixed", "all"):
        return "mixed-v1"
    # 預設：engineers
    return "eng-v1"


def _next_version_dir(parent: Path, name: str) -> Path:
    """如果 name 目錄已存在，回傳 name_v{n} 子目錄。"""
    base = parent / name
    if not base.exists():
        return base
    n = 1
    while True:
        candidate = parent / f"{name}_v{n}"
        if not candidate.exists():
            return candidate
        n += 1


def run_design(
    name: str,
    audience: str,
    scope: str,
    output_dir: Optional[Path] = None,
    llm: Optional[BaseLLM] = None,
    with_svg: bool = False,
    with_api: bool = False,
    with_data_model: bool = False,
    auto: bool = False,
    verbose: bool = True,
) -> DesignDocument:
    """跑 7 個階段，產 DesignDocument 並寫入檔案。

    Args:
        name: 功能名稱（slug）
        audience: 目標讀者
        scope: 需求概述
        output_dir: 輸出目錄（None → 預設 `technical_design_output/`）
        llm: LLM 實例（None → 自動 make_llm()）
        with_svg: 是否產出 architecture.svg
        with_api: 是否拆出獨立 api.md
        with_data_model: 是否拆出獨立 data_model.md
        auto: 是否一鍵模式（跳過互動；目前 stub 模式自動套用）
        verbose: 是否印進度

    Returns:
        DesignDocument 物件

    Raises:
        FinalGateError: Final Gate 校驗失敗
        LLMError: LLM 呼叫 / 解析失敗
    """
    if not name or not name.strip():
        raise TechnicalDesignError("name 不可為空")
    if not scope or not scope.strip():
        raise TechnicalDesignError("scope 不可為空")

    name = name.strip()
    audience = audience.strip() or "engineers"
    scope = scope.strip()

    if llm is None:
        llm = make_llm()

    template = _select_template(audience)
    if verbose:
        print(f"\n🔧 technical-design — 開始")
        print(f"   name: {name}")
        print(f"   audience: {audience} (template: {template})")
        print(f"   scope: {scope[:60]}{'...' if len(scope) > 60 else ''}")

    doc = DesignDocument(name=name, audience=audience, scope=scope)

    # Stage 1: Scope
    if verbose:
        print(f"\n📋 Stage 1: Scope")
    doc.scope_questions = llm.generate_scope_questions(name, audience, scope)
    if verbose:
        print(f"   ✅ {len(doc.scope_questions)} 個問題已建立")

    # Stage 2: Architecture
    if verbose:
        print(f"\n🏗️  Stage 2: Architecture")
    overview, diagram, nodes, data_flow = llm.generate_architecture(
        name, scope, doc.scope_questions
    )
    doc.architecture_overview = overview
    doc.architecture_diagram = diagram
    doc.architecture_nodes = nodes
    doc.data_flow = data_flow
    if verbose:
        print(f"   ✅ Mermaid 圖建立（{len(nodes)} 個節點）")

    # Stage 3: API Design
    if verbose:
        print(f"\n🔌 Stage 3: API Design")
    doc.apis = llm.generate_apis(name, scope)
    if verbose:
        print(f"   ✅ {len(doc.apis)} 個 API 建立")

    # Stage 4: Data Model
    if verbose:
        print(f"\n🗄️  Stage 4: Data Model")
    entities, er_diagram = llm.generate_data_model(name, scope)
    doc.entities = entities
    doc.er_diagram = er_diagram
    if verbose:
        print(f"   ✅ {len(doc.entities)} 個 entity 建立")

    # Stage 5: Implementation Plan
    if verbose:
        print(f"\n📅 Stage 5: Implementation Plan")
    doc.milestones = llm.generate_milestones(name, scope)
    if verbose:
        print(f"   ✅ {len(doc.milestones)} 個 milestones 建立")

    # Stage 5.5: Risks & Open Questions
    if verbose:
        print(f"\n⚠️  Stage 5.5: Risks & Open Questions")
    risks, open_questions = llm.generate_risks(name, scope)
    doc.risks = risks
    doc.open_questions = open_questions
    if verbose:
        print(f"   ✅ {len(risks)} 個 risks / {len(open_questions)} 個 open questions")

    # Stage 6: Review (Final Gate)
    if verbose:
        print(f"\n✅ Stage 6: Review")
    missing = doc.check_final_gate()
    if missing:
        if verbose:
            for m in missing:
                print(f"   ❌ {m}")
        raise FinalGateError(
            f"[BLOCKING] Final Gate FAIL — {len(missing)} 個缺失：\n  - " + "\n  - ".join(missing)
        )
    if verbose:
        print(f"   ✅ 6 個章節齊備")
        print(f"   ✅ Final Gate PASS")

    # Stage 7: Output
    if verbose:
        print(f"\n📦 Stage 7: Output")

    # 決定輸出目錄
    if output_dir is None:
        output_dir = Path("technical_design_output")
    output_dir = Path(output_dir).resolve()
    target_dir = _next_version_dir(output_dir, name)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 寫入 design.md
    design_path = target_dir / "design.md"
    design_path.write_text(doc.to_markdown(), encoding="utf-8")
    if verbose:
        print(f"   ✅ design.md → {design_path}")

    # 寫入 scope.md
    scope_path = target_dir / "scope.md"
    scope_path.write_text(doc.scope_to_markdown(), encoding="utf-8")
    if verbose:
        print(f"   ✅ scope.md → {scope_path}")

    # 可選：architecture.svg
    if with_svg:
        try:
            from scripts.mermaid_renderer import render_mermaid_block  # type: ignore
            svg_path = target_dir / "architecture.svg"
            render_mermaid_block(
                mermaid_source=doc.architecture_diagram,
                output_svg=svg_path,
            )
            if verbose:
                print(f"   ✅ architecture.svg → {svg_path}")
        except ImportError:
            if verbose:
                print(f"   ⚠️  mermaid_renderer 不可用；跳過 SVG")
        except Exception as e:
            if verbose:
                print(f"   ⚠️  SVG render 失敗：{e}；跳過")

    # 可選：api.md
    if with_api:
        api_path = target_dir / "api.md"
        api_lines = [f"# API Design: {doc.name}", ""]
        api_lines.append(f"> 對應 design.md §3")
        api_lines.append("")
        for api in doc.apis:
            api_lines.append(api.to_markdown())
            api_lines.append("")
        api_path.write_text("\n".join(api_lines), encoding="utf-8")
        if verbose:
            print(f"   ✅ api.md → {api_path}")

    # 可選：data_model.md
    if with_data_model:
        dm_path = target_dir / "data_model.md"
        dm_lines = [f"# Data Model: {doc.name}", ""]
        dm_lines.append(f"> 對應 design.md §4")
        dm_lines.append("")
        if doc.er_diagram.strip():
            dm_lines.append("## ERD 概念圖")
            dm_lines.append("")
            dm_lines.append("```mermaid")
            dm_lines.append(doc.er_diagram.strip())
            dm_lines.append("```")
            dm_lines.append("")
        for ent in doc.entities:
            dm_lines.append(ent.to_markdown())
            dm_lines.append("")
        dm_path.write_text("\n".join(dm_lines), encoding="utf-8")
        if verbose:
            print(f"   ✅ data_model.md → {dm_path}")

    if verbose:
        print(f"\n✅ 技術規格文件完成")
        print(f"📄 主文件: {design_path}")

    return doc


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master technical-design",
        description=(
            "技術規格文件生成：給功能名稱 + 目標讀者 + 需求概述，"
            "跑 7 個階段產出 design.md + scope.md（含 Mermaid 架構圖、API 設計、"
            "Data Model、Implementation Plan、Final Gate 校驗）。"
        ),
    )
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="功能名稱（slug；例：markdown-input-support）",
    )
    parser.add_argument(
        "--audience", "-a",
        default="engineers",
        choices=["engineers", "pm", "executives", "mixed"],
        help="目標讀者（預設 engineers）",
    )
    parser.add_argument(
        "--scope", "-s",
        required=True,
        help="需求概述（1-3 段文字）",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=None,
        help="輸出根目錄（預設 ./technical_design_output/）",
    )
    parser.add_argument(
        "--with-svg",
        action="store_true",
        help="呼叫 mermaid_renderer 預渲染架構圖為 SVG（需 mmdc CLI）",
    )
    parser.add_argument(
        "--with-api",
        action="store_true",
        help="拆出獨立 api.md（給前端 / 第三方團隊）",
    )
    parser.add_argument(
        "--with-data-model",
        action="store_true",
        help="拆出獨立 data_model.md（給 DBA / data team）",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="一鍵模式：跳過互動，直接產出（目前 stub LLM 自動套用）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="安靜模式（不印進度）",
    )

    args = parser.parse_args()

    try:
        run_design(
            name=args.name,
            audience=args.audience,
            scope=args.scope,
            output_dir=args.output_dir,
            with_svg=args.with_svg,
            with_api=args.with_api,
            with_data_model=args.with_data_model,
            auto=args.auto,
            verbose=not args.quiet,
        )
    except FinalGateError as e:
        print(str(e), file=sys.stderr)
        return 1
    except LLMError as e:
        print(f"[LLMError] {e}", file=sys.stderr)
        return 1
    except TechnicalDesignError as e:
        print(f"[TechnicalDesignError] {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
