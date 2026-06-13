"""scripts/create_template.py — Report-master template-creation workflow CLI helper.

對應 `workflows/create-template.md` v1.0 + `tasks.md` T3-4。

用途：
- 接收 template name + description
- 跑 Discovery 階段（LLM 提問 → 產 discovery_answers.yaml）
- 跑 Generation 階段（呼叫 build_template.build() → reference.docx）
- 跑 Validation 階段（python-docx + docx_validator 驗字體）
- 跑 Documentation 階段（產 README.md + lock_template.md）

LLM 介面：
- 讀 env：LLM_API_URL / LLM_API_KEY / LLM_MODEL（optional）
- 未設定 → 走 StubLLM（回傳 canned response）
- 設定 → 用 requests 呼叫 OpenAI-compatible chat completions API

CLI：
    python -m scripts.create_template --name "tech-blog-post" \\
      --description "公司內部 tech blog post"
    python -m scripts.create_template --name "..." --cover-title "..." \\
      --cover-line "..." --cover-line "..."
    python -m scripts.create_template --name "..." \\
      --discovery-file templates/<name>/discovery_answers.yaml

Return code：
    0 = 成功（三件組齊備 + validation PASS）
    1 = python-docx 未安裝 / build_template 失敗
    2 = Validation 失敗（字體不符 / docx 損壞）
    3 = Documentation 失敗（lock_template.md 缺欄位）
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

# 允許 CLI 直接執行（`python scripts/create_template.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.build_template import (  # noqa: E402
    DEFAULT_CJK_FONT,
    DEFAULT_LATIN_FONT,
    BODY_LINE_SPACING,
    BODY_SIZE_PT,
    CAPTION_SIZE_PT,
    HEADING_SIZES_PT,
    TITLE_SIZE_PT,
    BuildTemplateError,
    build as build_template,
)


# ─── 例外 ────────────────────────────────────────────────────────────

class CreateTemplateError(Exception):
    """create_template 例外基底。"""


class DiscoveryError(CreateTemplateError):
    """Discovery 階段失敗（LLM / YAML 解析）。"""


class ValidationError(CreateTemplateError):
    """Validation 階段失敗（字體不符 / docx 損壞）。"""


class DocumentationError(CreateTemplateError):
    """Documentation 階段失敗（lock_template.md 缺欄位）。"""


# ─── 資料結構 ────────────────────────────────────────────────────────

@dataclass
class DiscoveryAnswers:
    """Discovery 階段產出的 7 題答案。"""
    q1_audience: str = "（未指定）"
    q2_use_case: str = "（未指定）"
    q3_sections: List[str] = field(default_factory=list)
    q4_fonts_cjk: str = DEFAULT_CJK_FONT
    q4_fonts_latin: str = DEFAULT_LATIN_FONT
    q4_fonts_override: bool = False
    q5_cover_enabled: bool = True
    q5_cover_elements: List[str] = field(default_factory=list)
    q6_toc_enabled: bool = False
    q6_toc_numbered: bool = False
    q7_citation_style: str = "none"
    q8_expected_pages: str = "5-10"
    q8_expected_words: str = "2000-5000"

    def to_yaml_dict(self) -> Dict[str, Any]:
        return {
            "template_answers": {
                "q1_audience": self.q1_audience,
                "q2_use_case": self.q2_use_case,
                "q3_sections": list(self.q3_sections),
                "q4_fonts": {
                    "cjk": self.q4_fonts_cjk,
                    "latin": self.q4_fonts_latin,
                    "override": self.q4_fonts_override,
                },
                "q5_cover": {
                    "enabled": self.q5_cover_enabled,
                    "elements": list(self.q5_cover_elements),
                },
                "q6_toc": {
                    "enabled": self.q6_toc_enabled,
                    "numbered": self.q6_toc_numbered,
                },
                "q7_citation_style": self.q7_citation_style,
                "q8_expected_length": {
                    "pages": self.q8_expected_pages,
                    "words": self.q8_expected_words,
                },
            }
        }

    def to_yaml(self) -> str:
        """序列化為 YAML 字串（手動，避免額外依賴 ruamel/pyyaml 強制 import）。"""
        d = self.to_yaml_dict()
        return _simple_yaml_dump(d)


def _simple_yaml_dump(d: Dict[str, Any], indent: int = 0) -> str:
    """最小 YAML 序列化器（支援 dict / list / str / bool；足以序列化 DiscoveryAnswers）。

    不引入 PyYAML / ruamel 強制依賴；環境已有 PyYAML 時仍可正常運作。
    """
    lines: List[str] = []
    pad = "  " * indent
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_simple_yaml_dump(v, indent + 1))
            elif isinstance(v, dict):
                lines.append(f"{pad}{k}: {{}}")
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{pad}{k}: []")
                else:
                    # 單行 list 形式（每元素短字串）
                    items = ", ".join(_yaml_scalar(x) for x in v)
                    lines.append(f"{pad}{k}: [{items}]")
            elif isinstance(v, bool):
                lines.append(f"{pad}{k}: {'true' if v else 'false'}")
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
    elif isinstance(d, list):
        for item in d:
            if isinstance(item, dict):
                first_key = True
                for k, v in item.items():
                    prefix = f"{pad}- " if first_key else f"{pad}  "
                    first_key = False
                    if isinstance(v, (dict, list)) and v:
                        lines.append(f"{prefix}{k}:")
                        lines.append(_simple_yaml_dump({"": v}, indent + 2).lstrip())
                    elif isinstance(v, dict):
                        lines.append(f"{prefix}{k}: {{}}")
                    elif isinstance(v, list):
                        if not v:
                            lines.append(f"{prefix}{k}: []")
                        else:
                            items = ", ".join(_yaml_scalar(x) for x in v)
                            lines.append(f"{prefix}{k}: [{items}]")
                    elif isinstance(v, bool):
                        lines.append(f"{prefix}{k}: {'true' if v else 'false'}")
                    else:
                        lines.append(f"{prefix}{k}: {_yaml_scalar(v)}")
    return "\n".join(lines)


def _yaml_scalar(v: Any) -> str:
    """序列化為 YAML scalar（必要時加引號）。"""
    s = str(v)
    # 含特殊字元 → 加雙引號
    if any(c in s for c in [":", "#", "&", "*", "!", "|", ">", "%", "@", "`", "\n", '"', "'"]):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


# ─── LLM 介面（stub + real） ────────────────────────────────────────

class BaseLLM:
    def generate_discovery(self, description: str, name: str) -> DiscoveryAnswers:
        raise NotImplementedError


class StubLLM(BaseLLM):
    """Stub LLM — 不打 API，回傳 canned response。

    用於：
    - 測試（無網路）
    - 離線開發
    - 環境未設 LLM_API_URL / LLM_API_KEY 時的 fallback
    """

    def generate_discovery(self, description: str, name: str) -> DiscoveryAnswers:
        # Stub: 根據 description 與 name 給出合理 canned response
        return DiscoveryAnswers(
            q1_audience=f"[STUB] {description} 的目標讀者（請替換為真實答案）",
            q2_use_case=f"[STUB] {description} 的使用場景（請替換為真實答案）",
            q3_sections=["標題", "作者", "日期", "Tags", "摘要", "正文", "參考連結"],
            q4_fonts_cjk=DEFAULT_CJK_FONT,
            q4_fonts_latin=DEFAULT_LATIN_FONT,
            q4_fonts_override=False,
            q5_cover_enabled=True,
            q5_cover_elements=["Title", "Author", "Date", "Tags"],
            q6_toc_enabled=False,
            q6_toc_numbered=False,
            q7_citation_style="none",
            q8_expected_pages="5-10",
            q8_expected_words="2000-5000",
        )


class HTTPLLM(BaseLLM):
    """真實 LLM — 透過 HTTP 呼叫 OpenAI-compatible chat completions API。

    環境變數：
        LLM_API_URL   — e.g. https://api.openai.com/v1/chat/completions
        LLM_API_KEY   — e.g. sk-xxxxx
        LLM_MODEL     — e.g. gpt-4o-mini（optional，預設 gpt-4o-mini）
        LLM_TIMEOUT   — 逾時秒數（optional，預設 30）
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

    def generate_discovery(self, description: str, name: str) -> DiscoveryAnswers:
        import json
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise DiscoveryError(
                "需要 `requests` 套件才能呼叫 HTTP LLM；請 `pip install requests`"
            ) from e

        if not self.api_url or not self.api_key:
            raise DiscoveryError(
                "LLM_API_URL / LLM_API_KEY 未設定；請設定環境變數或走 StubLLM"
            )

        prompt = (
            f"你是一個文件範本設計師。使用者要建立的新 template 用於：「{description}」\n"
            "請依序回答以下 7 個結構問題，每題一行：\n"
            "Q1: 目標讀者是？\nQ2: 文件用途與場景？\nQ3: 必要段落結構（逗號分隔）？\n"
            "Q4: 字體偏好（沿用 = CJK 標楷體 / Latin Times New Roman）？\n"
            "Q5: 是否要封面？封面元素為何？\n"
            "Q6: 是否要目錄？是否需要章節編號？\nQ7: 引用風格？\n"
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一個專業文件範本設計師。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.5,
        }
        try:
            resp = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            raise DiscoveryError(f"LLM API 呼叫失敗：{e}") from e

        # 解析 LLM 回應（啟發式：抓 Q1~Q7 開頭行）
        return self._parse_discovery_text(content, description, name)

    def _parse_discovery_text(self, text: str, description: str, name: str) -> DiscoveryAnswers:
        r"""從 LLM 純文字回應解析出 DiscoveryAnswers。

        啟發式：抓 Q\d: 開頭的行，提取冒號後的內容。
        若 LLM 直接吐 YAML，會另外處理（簡化版只支援純文字）。
        """
        answers = DiscoveryAnswers()
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            m = re.match(r"^Q(\d)\s*[:：]\s*(.+)$", line)
            if not m:
                continue
            qnum = int(m.group(1))
            value = m.group(2).strip()
            if qnum == 1:
                answers.q1_audience = value
            elif qnum == 2:
                answers.q2_use_case = value
            elif qnum == 3:
                answers.q3_sections = [s.strip() for s in value.split(",") if s.strip()]
            elif qnum == 4:
                # 簡化：若提到「沿用」就不 override
                answers.q4_fonts_override = "改" in value or "override" in value.lower()
            elif qnum == 5:
                answers.q5_cover_enabled = "是" in value or "yes" in value.lower() or "true" in value.lower()
                # 抓 [..] 列表
                bracket = re.search(r"\[([^\]]+)\]", value)
                if bracket:
                    answers.q5_cover_elements = [s.strip() for s in bracket.group(1).split(",") if s.strip()]
            elif qnum == 6:
                answers.q6_toc_enabled = "是" in value or "yes" in value.lower() or "true" in value.lower()
                answers.q6_toc_numbered = "編號" in value or "numbered" in value.lower()
            elif qnum == 7:
                # 簡化：第一個 token 作為 citation_style
                token = value.split()[0].strip(".,;:")
                answers.q7_citation_style = token if token else "none"
        # 若 LLM 完全沒回答 → fallback 到 stub
        if answers.q1_audience == "（未指定）":
            return StubLLM().generate_discovery(description, name)
        return answers


def get_llm() -> BaseLLM:
    """依環境變數選擇 LLM 實作。"""
    if os.environ.get("LLM_API_URL") and os.environ.get("LLM_API_KEY"):
        try:
            return HTTPLLM()
        except Exception:
            return StubLLM()
    return StubLLM()


# ─── Discovery 階段 ──────────────────────────────────────────────────

def run_discovery(
    description: str,
    name: str,
    discovery_file: Optional[Path] = None,
    llm: Optional[BaseLLM] = None,
) -> DiscoveryAnswers:
    """跑 Discovery 階段。

    若給 discovery_file → 讀 YAML；否則 → 呼叫 LLM。

    Args:
        description: template 用途描述
        name: template name
        discovery_file: 已存在的 discovery_answers.yaml（可選）
        llm: 自訂 LLM 實例（測試用）

    Returns:
        DiscoveryAnswers

    Raises:
        DiscoveryError: 解析失敗 / 描述為空
    """
    if not description or not description.strip():
        raise DiscoveryError("description 不可為空")
    if not name or not name.strip():
        raise DiscoveryError("name 不可為空")

    if discovery_file and discovery_file.exists():
        return _load_discovery_yaml(discovery_file)

    llm_impl = llm or get_llm()
    return llm_impl.generate_discovery(description=description, name=name)


def _load_discovery_yaml(path: Path) -> DiscoveryAnswers:
    """從 YAML 檔載入 DiscoveryAnswers。

    支援兩種解析路徑：
    1. PyYAML（若環境有）
    2. 簡單 regex 解析（fallback；足夠應付 to_yaml() 格式）
    """
    text = path.read_text(encoding="utf-8")
    answers = DiscoveryAnswers()
    # 簡單 regex 解析：抓 qX_xxx: value
    pattern = re.compile(r"^\s*q(\d+)_(\w+)\s*:\s*(.+)$", re.MULTILINE)
    for m in pattern.finditer(text):
        qnum = int(m.group(1))
        key = m.group(2)
        value = m.group(3).strip()
        # 移除引號
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if qnum == 1 and key == "audience":
            answers.q1_audience = value
        elif qnum == 2 and key == "use_case":
            answers.q2_use_case = value
        elif qnum == 3 and key == "sections":
            answers.q3_sections = [s.strip().strip('"').strip("'") for s in value.strip("[]").split(",") if s.strip()]
        elif qnum == 4 and key == "cjk":
            answers.q4_fonts_cjk = value
        elif qnum == 4 and key == "latin":
            answers.q4_fonts_latin = value
        elif qnum == 4 and key == "override":
            answers.q4_fonts_override = value.lower() == "true"
        elif qnum == 5 and key == "enabled":
            answers.q5_cover_enabled = value.lower() == "true"
        elif qnum == 5 and key == "elements":
            answers.q5_cover_elements = [s.strip().strip('"').strip("'") for s in value.strip("[]").split(",") if s.strip()]
        elif qnum == 6 and key == "enabled":
            answers.q6_toc_enabled = value.lower() == "true"
        elif qnum == 6 and key == "numbered":
            answers.q6_toc_numbered = value.lower() == "true"
        elif qnum == 7 and key == "citation_style":
            answers.q7_citation_style = value
        elif qnum == 8 and key == "pages":
            answers.q8_expected_pages = value
        elif qnum == 8 and key == "words":
            answers.q8_expected_words = value
    return answers


# ─── Generation 階段 ────────────────────────────────────────────────

def run_generation(
    name: str,
    discovery: DiscoveryAnswers,
    cover_title: Optional[str] = None,
    cover_lines: Optional[List[str]] = None,
    output_root: Optional[Path] = None,
) -> Path:
    """跑 Generation 階段：呼叫 build_template.build()。

    Args:
        name: template name
        discovery: DiscoveryAnswers
        cover_title: 自訂封面標題（覆寫 discovery 預設）
        cover_lines: 自訂封面內文（覆寫 discovery 預設）
        output_root: 輸出根目錄（預設為專案 templates/）

    Returns:
        reference.docx 的 Path

    Raises:
        BuildTemplateError: python-docx 未安裝 / type 不合法
        CreateTemplateError: 輸出失敗
    """
    root = output_root or _PROJECT_ROOT / "templates"
    out_dir = root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "reference.docx"

    # 從 discovery 衍生 cover_lines（若使用者沒覆寫）
    if cover_lines is None and discovery.q5_cover_enabled:
        cover_lines = []
        if discovery.q5_cover_elements:
            for elem in discovery.q5_cover_elements:
                cover_lines.append(f"{elem}: <請填寫 {elem}>")
        cover_lines.append("")
        cover_lines.append("（請將此段刪除後插入正式內容）")

    if cover_title is None and discovery.q5_cover_enabled:
        cover_title = name  # default: template name 作為封面標題

    try:
        build_template(
            output_path=out_path,
            type="custom",  # 一律 custom（最通用）
            cover_title=cover_title,
            cover_lines=cover_lines,
            cjk_font=discovery.q4_fonts_cjk or DEFAULT_CJK_FONT,
            latin_font=discovery.q4_fonts_latin or DEFAULT_LATIN_FONT,
        )
    except BuildTemplateError:
        raise
    except Exception as e:
        raise CreateTemplateError(f"Generation 失敗：{e}") from e

    return out_path


# ─── Validation 階段 ────────────────────────────────────────────────

def run_validation(reference_path: Path) -> Dict[str, Any]:
    """跑 Validation 階段：python-docx round-trip + docx_validator 字體檢查。

    Args:
        reference_path: reference.docx 的 Path

    Returns:
        結構化報告 dict，含 passed / checks / issues

    Raises:
        ValidationError: 任一檢查 fail
    """
    report: Dict[str, Any] = {
        "passed": True,
        "checks": [],
        "issues": [],
    }

    # Check 1: 檔案存在且 > 1KB
    if not reference_path.exists():
        raise ValidationError(f"reference.docx 不存在：{reference_path}")
    size = reference_path.stat().st_size
    if size <= 1024:
        report["passed"] = False
        report["issues"].append(f"reference.docx size={size} bytes <= 1024（產物太小）")
        report["checks"].append({"name": "file_size", "passed": False, "size": size})
    else:
        report["checks"].append({"name": "file_size", "passed": True, "size": size})

    # Check 2: python-docx 可開啟
    try:
        from docx import Document
        doc = Document(str(reference_path))
        normal_font = doc.styles["Normal"].font.name
        report["checks"].append({
            "name": "python_docx_roundtrip",
            "passed": True,
            "normal_font": normal_font,
        })
        if normal_font != DEFAULT_LATIN_FONT:
            report["passed"] = False
            report["issues"].append(
                f"Normal ascii font = {normal_font!r}, expected {DEFAULT_LATIN_FONT!r}"
            )
            report["checks"].append({
                "name": "latin_font_normal",
                "passed": False,
                "actual": normal_font,
                "expected": DEFAULT_LATIN_FONT,
            })
        else:
            report["checks"].append({
                "name": "latin_font_normal",
                "passed": True,
                "actual": normal_font,
            })
    except ImportError as e:
        raise ValidationError(f"python-docx 未安裝：{e}") from e
    except Exception as e:
        report["passed"] = False
        report["issues"].append(f"python-docx 開啟失敗：{e}")
        report["checks"].append({"name": "python_docx_roundtrip", "passed": False, "error": str(e)})

    # Check 3: docx_validator（如環境有就跑；沒有就跳過，但記錄）
    try:
        from scripts.docx_validator import validate_docx
        rep = validate_docx(str(reference_path))
        report["checks"].append({
            "name": "docx_validator",
            "passed": rep.passed,
            "issues_count": len(rep.issues),
        })
        if not rep.passed:
            report["passed"] = False
            report["issues"].extend([str(i) for i in rep.issues])
    except ImportError:
        report["checks"].append({
            "name": "docx_validator",
            "passed": None,  # 跳過
            "skipped": "docx_validator 未 import（測試可選）",
        })
    except Exception as e:
        report["checks"].append({
            "name": "docx_validator",
            "passed": False,
            "error": str(e),
        })

    if not report["passed"]:
        raise ValidationError(
            "[BLOCKING] reference.docx 驗證失敗：\n  - " + "\n  - ".join(report["issues"])
        )

    return report


# ─── Documentation 階段 ──────────────────────────────────────────────

# Lock schema required fields（對齊 docs/report_lock_schema.md §2；17 個）
_LOCK_REQUIRED_FIELDS = [
    "schema_version", "fonts", "formatting", "page_size", "margins",
    "line_spacing", "language_variant", "citation_style", "output",
]


def run_documentation(
    name: str,
    description: str,
    discovery: DiscoveryAnswers,
    reference_path: Path,
    output_root: Optional[Path] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Path]:
    """跑 Documentation 階段：產 README.md + lock_template.md。

    Args:
        name: template name
        description: template 用途描述
        discovery: DiscoveryAnswers
        reference_path: 已產出的 reference.docx 路徑
        output_root: 輸出根目錄（預設為專案 templates/）
        timestamp: 時間戳記字串（測試可用固定值）

    Returns:
        dict，含 'readme' / 'lock_template' / 'discovery_yaml' 的 Path

    Raises:
        DocumentationError: lock_template.md 缺欄位 / 寫入失敗
    """
    root = output_root or _PROJECT_ROOT / "templates"
    out_dir = root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or datetime.now().isoformat(timespec="seconds")

    # ─── A. discovery_answers.yaml ───
    discovery_path = out_dir / "discovery_answers.yaml"
    discovery_path.write_text(discovery.to_yaml(), encoding="utf-8")

    # ─── B. README.md ───
    readme_path = out_dir / "README.md"
    readme_content = _render_readme(name, description, discovery, ts)
    readme_path.write_text(readme_content, encoding="utf-8")

    # ─── C. lock_template.md ───
    lock_path = out_dir / "lock_template.md"
    lock_content = _render_lock_template(name, description, discovery, ts)
    lock_path.write_text(lock_content, encoding="utf-8")

    # ─── 驗 lock_template.md 必備欄位 ───
    missing = _validate_lock_template_fields(lock_content)
    if missing:
        raise DocumentationError(
            f"[BLOCKING] lock_template.md 缺以下 required 欄位：{missing}"
        )

    return {
        "readme": readme_path,
        "lock_template": lock_path,
        "discovery_yaml": discovery_path,
        "reference_docx": reference_path,
    }


def _render_readme(name: str, description: str, discovery: DiscoveryAnswers, ts: str) -> str:
    """產出 README.md 內容。"""
    label = name.replace("-", " ").replace("_", " ").title()
    lines: List[str] = []
    lines.append(f"# templates/{name}/ — {label}")
    lines.append("")
    lines.append(f"> 對應 `workflows/create-template.md` v1.0")
    lines.append(f"> 產生時間：{ts}")
    lines.append(f"> 來源描述：{description}")
    lines.append("")
    lines.append("## 用途")
    lines.append("")
    lines.append(f"{description}")
    lines.append("")
    lines.append(f"- **目標讀者**：{discovery.q1_audience}")
    lines.append(f"- **使用場景**：{discovery.q2_use_case}")
    lines.append(f"- **預期長度**：{discovery.q8_expected_pages} 頁 / {discovery.q8_expected_words} 字")
    lines.append("")
    lines.append("## 字體鎖死規則")
    lines.append("")
    lines.append(f"- CJK：**{discovery.q4_fonts_cjk}**")
    lines.append(f"- Latin：**{discovery.q4_fonts_latin}**")
    lines.append(f"- 章節樣式：H1={HEADING_SIZES_PT[1]}pt / H2={HEADING_SIZES_PT[2]}pt / H3={HEADING_SIZES_PT[3]}pt（皆粗體）")
    lines.append(f"- Normal：{BODY_SIZE_PT}pt / 行距 {BODY_LINE_SPACING}")
    lines.append(f"- Caption：{CAPTION_SIZE_PT}pt / 置中")
    lines.append(f"- Title：{TITLE_SIZE_PT}pt / 粗體 / 置中（封面用）")
    lines.append("")
    lines.append("## 如何產生 reference.docx")
    lines.append("")
    lines.append("```bash")
    lines.append("python -m scripts.build_template \\")
    lines.append(f"  --output templates/{name}/reference.docx \\")
    lines.append("  --type custom \\")
    lines.append(f"  --cover-title \"{label}\" \\")
    if discovery.q5_cover_elements:
        for elem in discovery.q5_cover_elements:
            lines.append(f"  --cover-line \"{elem}: <請填寫>\" \\")
    lines.append(f"  --cjk-font \"{discovery.q4_fonts_cjk}\" \\")
    lines.append(f"  --latin-font \"{discovery.q4_fonts_latin}\"")
    lines.append("```")
    lines.append("")
    lines.append("或用本 workflow 的 CLI helper：")
    lines.append("")
    lines.append("```bash")
    lines.append(f"python -m scripts.create_template --name \"{name}\" \\")
    lines.append(f"  --description \"{description}\"")
    lines.append("```")
    lines.append("")
    lines.append("## 客製化")
    lines.append("")
    lines.append(f"要改字體/字級/封面，改 `templates/{name}/lock_template.md` 後重跑")
    lines.append(f"`scripts.create_template` 即可。")
    lines.append("")
    lines.append("## 與 Report-master 主流程的整合")
    lines.append("")
    lines.append("此 template 對應 Strategist 的 `metadata.type`：" + name)
    lines.append("")
    lines.append(f"```bash")
    lines.append(f"# 用此 template 套用樣式")
    lines.append(f"python -m scripts.html_to_docx report_output/_bundle.html \\")
    lines.append(f"  -o exports/report.docx \\")
    lines.append(f"  --reference-doc=templates/{name}/reference.docx")
    lines.append("```")
    lines.append("")
    lines.append(f"或設環境變數 `REPORT_MASTER_REFERENCE_DOCX=templates/{name}/reference.docx`。")
    lines.append("")
    return "\n".join(lines)


def _render_lock_template(name: str, description: str, discovery: DiscoveryAnswers, ts: str) -> str:
    """產出 lock_template.md 內容（YAML frontmatter + Markdown 註解）。"""
    lines: List[str] = []
    lines.append("---")
    lines.append(f"# 給 Strategist 讀的「範本契約」")
    lines.append(f"# 對應 docs/report_lock_schema.md；專注於「這個 template 變體的 default 設定」")
    lines.append("schema_version: 1")
    lines.append(f"template: {name}")
    lines.append("fonts:")
    lines.append(f"  cjk: {discovery.q4_fonts_cjk}")
    lines.append(f"  latin: {discovery.q4_fonts_latin}")
    lines.append("formatting:")
    lines.append("  cover: {font_size: 22, bold: true, align: center}")
    lines.append("  toc: {font_size: 20}")
    lines.append("  title: {font_size: 22, bold: true, align: center}")
    lines.append("  h1: {font_size: 18, bold: true}")
    lines.append("  h2: {font_size: 16, bold: true}")
    lines.append("  h3: {font_size: 14, bold: true}")
    lines.append("  body: {font_size: 12, line_spacing: 1.5}")
    lines.append("  table: {font_size: 12}")
    lines.append("  caption: {font_size: 10, align: center}")
    lines.append("page_size: A4")
    lines.append("margins: {top: 2.5cm, bottom: 2.5cm, left: 3cm, right: 2cm}")
    lines.append(f"line_spacing: {BODY_LINE_SPACING}")
    lines.append("language_variant: zh-TW")
    lines.append(f"citation_style: {discovery.q7_citation_style}")
    lines.append("output:")
    lines.append("  docx_engine: pandoc")
    lines.append("  embed_fonts: true")
    lines.append("template_metadata:")
    lines.append(f"  label: \"{name}\"")
    lines.append(f"  audience: \"{discovery.q1_audience}\"")
    lines.append(f"  use_case: \"{discovery.q2_use_case}\"")
    lines.append(f"  expected_pages: \"{discovery.q8_expected_pages}\"")
    lines.append(f"  toc_enabled: {'true' if discovery.q6_toc_enabled else 'false'}")
    lines.append(f"  cover_enabled: {'true' if discovery.q5_cover_enabled else 'false'}")
    lines.append("---")
    lines.append("")
    lines.append(f"# lock_template.md — {name}")
    lines.append("")
    lines.append(f"> 機器可讀範本契約；Strategist 在產 report_lock.md 時可參考本檔。")
    lines.append(f"> 產生時間：{ts}")
    lines.append(f"> 來源描述：{description}")
    lines.append("")
    lines.append("## 17 required 欄位（對齊 docs/report_lock_schema.md §2）")
    lines.append("")
    for field_name in _LOCK_REQUIRED_FIELDS:
        lines.append(f"- `{field_name}`")
    lines.append("")
    return "\n".join(lines)


def _validate_lock_template_fields(content: str) -> List[str]:
    """驗證 lock_template.md 是否含 17 個 required 欄位（frontmatter 內）。"""
    missing: List[str] = []
    # 抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    if not m:
        return ["frontmatter 區塊未正確閉合"]
    fm_text = m.group("yaml")
    for field_name in _LOCK_REQUIRED_FIELDS:
        # 簡單 regex：找頂層 key
        pattern = re.compile(rf"^{re.escape(field_name)}\s*:", re.MULTILINE)
        if not pattern.search(fm_text):
            missing.append(field_name)
    return missing


# ─── 主流程 ──────────────────────────────────────────────────────────

def run_create_template(
    name: str,
    description: str,
    *,
    cover_title: Optional[str] = None,
    cover_lines: Optional[List[str]] = None,
    discovery_file: Optional[Path] = None,
    output_root: Optional[Path] = None,
    skip_validation: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """跑完整 create-template workflow（4 階段）。

    Args:
        name: template name（不允許含 '/' '\\' '..'）
        description: template 用途描述
        cover_title: 自訂封面標題
        cover_lines: 自訂封面內文（list of strings）
        discovery_file: 已存在的 discovery_answers.yaml
        output_root: 輸出根目錄（測試可用 tmp_path）
        skip_validation: 跳過 Validation 階段（debug 用）
        verbose: 印進度訊息

    Returns:
        dict 含 'name' / 'discovery' / 'reference_docx' / 'readme' / 'lock_template'
        / 'discovery_yaml' / 'validation_report'

    Raises:
        CreateTemplateError: 任一階段失敗
    """
    # 0. 檢查 name 合法性
    if not name or not name.strip():
        raise CreateTemplateError("name 不可為空")
    if any(c in name for c in ("/", "\\", "..", " ", "\t", "\n")):
        raise CreateTemplateError(
            f"name 不可含 '/' '\\' '..' 或空白；got: {name!r}"
        )

    root = output_root or _PROJECT_ROOT / "templates"

    # 1. Discovery
    if verbose:
        print(f"🔍 Discovery 階段：{description[:50]}...")
    discovery = run_discovery(
        description=description,
        name=name,
        discovery_file=discovery_file,
    )

    # 2. Generation
    if verbose:
        print(f"🏗️  Generation 階段：呼叫 build_template.build()...")
    reference_path = run_generation(
        name=name,
        discovery=discovery,
        cover_title=cover_title,
        cover_lines=cover_lines,
        output_root=root,
    )

    # 3. Validation
    validation_report: Dict[str, Any] = {"passed": True, "skipped": False}
    if not skip_validation:
        if verbose:
            print(f"✅ Validation 階段：python-docx + docx_validator...")
        try:
            validation_report = run_validation(reference_path)
        except ValidationError as e:
            raise CreateTemplateError(f"Validation 失敗：{e}") from e
    else:
        validation_report["skipped"] = True
        if verbose:
            print("⏭️  Validation 階段：跳過（--skip-validation）")

    # 4. Documentation
    if verbose:
        print(f"📝 Documentation 階段：README + lock_template...")
    docs = run_documentation(
        name=name,
        description=description,
        discovery=discovery,
        reference_path=reference_path,
        output_root=root,
    )

    if verbose:
        print(f"✅ create-template workflow 完成：")
        print(f"   📁 {docs['reference_docx']}")
        print(f"   📁 {docs['readme']}")
        print(f"   📁 {docs['lock_template']}")
        print(f"   📁 {docs['discovery_yaml']}")
        print(f"   🧪 Validation: {'PASS' if validation_report['passed'] else 'FAIL'}")

    return {
        "name": name,
        "description": description,
        "discovery": discovery,
        "reference_docx": docs["reference_docx"],
        "readme": docs["readme"],
        "lock_template": docs["lock_template"],
        "discovery_yaml": docs["discovery_yaml"],
        "validation_report": validation_report,
    }


# ─── CLI ─────────────────────────────────────────────────────────────

def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.create_template",
        description=(
            "建立 report-master 新 document template。\n"
            "跑 Discovery → Generation → Validation → Documentation，"
            "產 reference.docx + README.md + lock_template.md。"
        ),
    )
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="template name（將作為 templates/<name>/ 子目錄名）",
    )
    parser.add_argument(
        "--description", "-d",
        required=True,
        help="template 用途描述（給 Discovery 階段用）",
    )
    parser.add_argument(
        "--cover-title",
        default=None,
        help="自訂封面標題（覆寫 Discovery 預設）",
    )
    parser.add_argument(
        "--cover-line",
        action="append",
        default=None,
        help="自訂封面內文一行（可重複；覆寫 Discovery 預設）",
    )
    parser.add_argument(
        "--discovery-file",
        default=None,
        help="已存在的 discovery_answers.yaml（跳過 LLM Discovery）",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="輸出根目錄（預設為專案 templates/；測試可用 tmp path）",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="跳過 Validation 階段（debug 用）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="安靜模式（不印進度訊息）",
    )

    args = parser.parse_args(argv)

    try:
        result = run_create_template(
            name=args.name,
            description=args.description,
            cover_title=args.cover_title,
            cover_lines=args.cover_line,
            discovery_file=Path(args.discovery_file) if args.discovery_file else None,
            output_root=Path(args.output_root) if args.output_root else None,
            skip_validation=args.skip_validation,
            verbose=not args.quiet,
        )
        print(f"✅ create-template 完成：templates/{args.name}/")
        return 0
    except CreateTemplateError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except BuildTemplateError as e:
        print(f"❌ build_template 失敗：{e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"❌ Validation 失敗：{e}", file=sys.stderr)
        return 2
    except DocumentationError as e:
        print(f"❌ Documentation 失敗：{e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(_main())
