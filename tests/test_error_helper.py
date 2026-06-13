"""tests/test_error_helper.py — scripts/error_helper.py + workflows/error-handling.md 測試。

DoD 對應 `tasks.md` T3-12：
1. 載入 `workflows/error-handling.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex `` ```mermaid ``）
3. CLI `--error-file` 不 crash（給一個假的 error log）
4. error 分類正確（LOCK_MISMATCH / API_ERROR / UNKNOWN）

設計：4 必要 + 3 補充 = 7 cases（含 LOCK_MISMATCH 自動修復 + LOCK append）
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from scripts.error_helper import (
    EXIT_ARG_ERROR,
    EXIT_NEEDS_MANUAL,
    EXIT_RESOLVED,
    ALL_ERROR_TYPES,
    ERROR_API_ERROR,
    ERROR_FONT_MISSING,
    ERROR_LOCK_MISMATCH,
    ERROR_PARSE_ERROR,
    ERROR_SECTION_MISSING,
    ERROR_UNKNOWN,
    ClassificationResult,
    ErrorClassifier,
    ErrorContext,
    ErrorHelper,
    ErrorHelperArgError,
    ErrorReporter,
    ErrorResolver,
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    format_report_for_cli,
)
from scripts.report_lock import read_lock_with_body, write_lock
from scripts.strategist import build_lock_template


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "error-handling.md"
EXECUTOR_MD = PROJECT_ROOT / "references" / "executor-base.md"
REVISE_MD = PROJECT_ROOT / "workflows" / "revise.md"
RESUME_MD = PROJECT_ROOT / "workflows" / "resume-execute.md"
REPORT_LOCK_PY = PROJECT_ROOT / "scripts" / "report_lock.py"


# 模擬 traceback 樣本（給 classifier / integration test 用）
API_ERROR_TRACEBACK = """\
Traceback (most recent call last):
  File "scripts/executor.py", line 245, in run_section
    html = call_llm(prompt)
  File "scripts/executor.py", line 198, in _call_llm
    response = openai.ChatCompletion.create(...)
openai.error.RateLimitError: Rate limit reached for gpt-4 in organization org-abc123
"""

LOCK_MISMATCH_TRACEBACK = """\
Traceback (most recent call last):
  File "scripts/delta_checker.py", line 88, in check_lock
    raise LockMismatchError("lock_signature 不一致: a1b2c3d4 → ff9988aa")
LockMismatchError: lock_signature 不一致: a1b2c3d4 → ff9988aa
"""

PARSE_ERROR_TRACEBACK = """\
Traceback (most recent call last):
  File "scripts/executor.py", line 198, in _call_llm
    response = openai.ChatCompletion.create(...)
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
The HTML response is missing <!DOCTYPE> declaration.
"""

FONT_MISSING_TRACEBACK = """\
Traceback (most recent call last):
  File "scripts/html_to_pdf.py", line 122, in render
    doc = weasyprint.HTML(string=html).write_pdf()
  File "/usr/lib/python3/dist-packages/weasyprint/__init__.py", line 1234, in write_pdf
    document.render(font_config=font_config)
weasyprint.text.WeasyPrintError: font-family '標楷體' not found
"""

UNKNOWN_TRACEBACK = """\
Traceback (most recent call last):
  File "scripts/foo.py", line 1, in <module>
SomeWeirdUndocumentedError: nothing matched
"""

SECTION_MISSING_TRACEBACK = """\
Traceback (most recent call last):
  File "scripts/report_gen.py", line 88, in bundle_html
    html = section_path.read_text()
FileNotFoundError: [Errno 2] No such file or directory: 'report_output/section_3.html'
"""


@pytest.fixture
def tmp_error_log(tmp_path: Path) -> Path:
    """寫一份假的 error log（API_ERROR 範例）。"""
    log = tmp_path / "executor_stderr.log"
    log.write_text(API_ERROR_TRACEBACK, encoding="utf-8")
    return log


@pytest.fixture
def tmp_lock_for_append(tmp_path: Path) -> Path:
    """產生一份合法的 lock 給 ErrorReporter.append_to_lock 用。"""
    lock = build_lock_template(
        "academic",
        metadata_overrides={"title": "T3-12 Error Helper Test"},
    )
    lock["sections"] = lock["sections"][:3]
    # 清掉 errors（若有）
    lock.setdefault("metadata", {}).pop("errors", None)
    lock_path = tmp_path / "report_lock.md"
    write_lock(lock_path, lock, body="# error helper test\n")
    return lock_path


# ─── Test 1（必要）: 載入 workflows/error-handling.md frontmatter 不 crash ──

def test_workflow_md_frontmatter_loads():
    """載入 workflows/error-handling.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "error-handling.md 應以 frontmatter 開頭"

    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "error-handling", "name 應為 'error-handling'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert str(fm.get("version")) == "1.0", "version 應為 1.0"

    # DoD 1：行數 > 100
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"

    # 額外：應引用 executor-base.md / revise.md / report_lock.py
    assert "executor-base" in content, "error-handling.md 應引用 references/executor-base.md"
    assert "revise.md" in content or "revise" in content, "應提及 revise workflow"
    assert "report_lock" in content, "應引用 scripts/report_lock.py"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/error-handling.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")

    pattern = re.compile(r"^```mermaid\s*$", re.MULTILINE)
    matches = pattern.findall(content)
    assert len(matches) >= 1, "workflow 應含至少 1 個 mermaid 區塊"

    m = re.search(r"```mermaid\s*\n(?P<body>.*?)\n```", content, re.DOTALL)
    assert m is not None, "應有完整 mermaid 區塊（``` 閉合）"
    mermaid_body = m.group("body")
    assert "flowchart" in mermaid_body or "graph" in mermaid_body, (
        "Mermaid 區塊應含 flowchart 或 graph 關鍵字"
    )
    # 額外：flowchart 應含「Detect」「Classify」「Resolve」「Report」關鍵字（error-handling 主題）
    keywords = ["Detect", "Classify", "Resolve", "Report"]
    found = sum(1 for kw in keywords if kw in mermaid_body)
    assert found >= 3, f"Mermaid 應含 error-handling 主題關鍵字，找到 {found}/{len(keywords)}"


# ─── Test 3（必要）: CLI --error-file 不 crash ──────────────────────

def test_error_helper_cli_error_file(tmp_error_log: Path, tmp_path: Path):
    """`python -m scripts.error_helper --error-file <p>` 不 crash + 印出分類結果。"""
    log = tmp_error_log
    report_path = tmp_path / "error_report.md"
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.error_helper",
            "--error-file", str(log),
            "--source", "scripts.executor",
            "--section", "3",
            "--report", str(report_path),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    # CLI 預期 exit code = 1（needs_manual；因為 API_ERROR 無法自動修復）
    assert result.returncode == EXIT_NEEDS_MANUAL, (
        f"CLI 應回傳 needs_manual（exit={EXIT_NEEDS_MANUAL}），"
        f"實際={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # 應有分類結果
    assert "API_ERROR" in result.stdout, "stdout 應含 API_ERROR 分類"
    assert "Error Helper" in result.stdout, "stdout 應含 CLI 標題"
    assert "next action" in result.stdout.lower(), "stdout 應含 next-action 建議"

    # error_report.md 應被產出
    assert report_path.exists(), f"error_report.md 應寫到 {report_path}"
    report_content = report_path.read_text(encoding="utf-8")
    assert "Error Type" in report_content
    assert "API_ERROR" in report_content


def test_error_helper_cli_argument_error_no_flags(tmp_path: Path):
    """`python -m scripts.error_helper`（無 flag）應回傳 argument error（exit=2）。"""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.error_helper"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == EXIT_ARG_ERROR, (
        f"CLI 應回傳 arg error（exit={EXIT_ARG_ERROR}），實際={result.returncode}"
    )
    # argparse 預設會印 usage + error message
    assert "error" in result.stderr.lower() or "必須" in result.stderr or "required" in result.stderr.lower()


def test_error_helper_cli_argument_error_missing_file(tmp_path: Path):
    """`python -m scripts.error_helper --error-file /nonexistent` 應回傳 exit=2。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.error_helper",
            "--error-file", "/tmp/does_not_exist_xyzzy.log",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == EXIT_ARG_ERROR, (
        f"CLI 應回傳 arg error（exit={EXIT_ARG_ERROR}），實際={result.returncode}"
    )
    assert "不存在" in result.stderr or "不存在" in result.stdout


# ─── Test 4（必要）: error 分類正確 ────────────────────────────────

def test_classify_lock_mismatch():
    """lock_signature 不一致 → LOCK_MISMATCH（BLOCKING）。"""
    ctx = ErrorContext.from_text(LOCK_MISMATCH_TRACEBACK)
    cls = ErrorClassifier().classify(ctx)
    assert isinstance(cls, ClassificationResult)
    assert cls.error_type == ERROR_LOCK_MISMATCH, (
        f"應分類為 LOCK_MISMATCH，實際 {cls.error_type}"
    )
    assert cls.severity == SEVERITY_BLOCKING
    assert cls.needs_manual is True
    assert cls.confidence >= 0.7


def test_classify_api_error():
    """openai.RateLimitError → API_ERROR（BLOCKING）。"""
    ctx = ErrorContext.from_text(API_ERROR_TRACEBACK)
    cls = ErrorClassifier().classify(ctx)
    assert cls.error_type == ERROR_API_ERROR
    assert cls.severity == SEVERITY_BLOCKING


def test_classify_unknown():
    """沒對應規則的 exception → UNKNOWN（BLOCKING, confidence=0）。"""
    ctx = ErrorContext.from_text(UNKNOWN_TRACEBACK)
    cls = ErrorClassifier().classify(ctx)
    assert cls.error_type == ERROR_UNKNOWN
    assert cls.severity == SEVERITY_BLOCKING
    assert cls.confidence == 0.0
    assert cls.needs_manual is True


def test_classify_font_missing():
    """weasyprint font error → FONT_MISSING（BLOCKING）。"""
    ctx = ErrorContext.from_text(FONT_MISSING_TRACEBACK)
    cls = ErrorClassifier().classify(ctx)
    assert cls.error_type == ERROR_FONT_MISSING
    assert cls.severity == SEVERITY_BLOCKING


def test_classify_parse_error():
    """JSONDecodeError + missing <!DOCTYPE> → PARSE_ERROR（warning）。"""
    ctx = ErrorContext.from_text(PARSE_ERROR_TRACEBACK)
    cls = ErrorClassifier().classify(ctx)
    assert cls.error_type == ERROR_PARSE_ERROR
    assert cls.severity == SEVERITY_WARNING


def test_classify_section_missing():
    """section_N.html FileNotFoundError → SECTION_MISSING（warning）。"""
    ctx = ErrorContext.from_text(SECTION_MISSING_TRACEBACK)
    cls = ErrorClassifier().classify(ctx)
    assert cls.error_type == ERROR_SECTION_MISSING
    assert cls.severity == SEVERITY_WARNING


# ─── Test 5（補充）: LOCK_MISMATCH 自動修復（reload lock + 寫 signature） ─

def test_resolve_lock_mismatch_writes_signature(tmp_lock_for_append: Path):
    """LOCK_MISMATCH 自動修復：reload lock + 寫 lock_signature 回 progress。"""
    lock_path = tmp_lock_for_append
    ctx = ErrorContext.from_text(LOCK_MISMATCH_TRACEBACK)
    ctx.lock_path = str(lock_path)
    cls = ErrorClassifier().classify(ctx)
    assert cls.error_type == ERROR_LOCK_MISMATCH

    res = ErrorResolver(retry_count=3).resolve(ctx, cls)
    # LOCK_MISMATCH 即使自動修復也仍 needs_manual（最終決定權在 user）
    assert res.needs_manual is True
    # 至少要 reload lock 成功
    assert any(a.result == "success" and "reload" in a.action for a in res.attempts), (
        f"應有 reload 成功的 attempt，實際 attempts={[a.to_dict() for a in res.attempts]}"
    )

    # 驗證 lock 確實被寫了 lock_signature
    data, _ = read_lock_with_body(str(lock_path))
    sig = data.get("metadata", {}).get("progress", {}).get("lock_signature")
    assert sig is not None, "lock_signature 應被寫入 lock.metadata.progress"
    assert len(sig) == 12, f"signature 應為 12 字 hex，實際 {sig}"


# ─── Test 6（補充）: ErrorReporter 寫 lock.errors[] ───────────────

def test_reporter_appends_to_lock_errors(tmp_lock_for_append: Path):
    """ErrorReporter.append_to_lock 應把錯誤 append 到 lock.metadata.errors[]。"""
    lock_path = tmp_lock_for_append
    ctx = ErrorContext.from_text(API_ERROR_TRACEBACK, section_index=3)
    ctx.lock_path = str(lock_path)
    ctx.source = "scripts.executor"
    cls = ErrorClassifier().classify(ctx)
    reporter = ErrorReporter()

    ok = reporter.append_to_lock(cls, ctx)
    assert ok is True, "append_to_lock 應回傳 True"

    # 驗證 errors[] 被加入
    data, _ = read_lock_with_body(str(lock_path))
    errors = data.get("metadata", {}).get("errors", [])
    assert len(errors) >= 1, f"errors[] 應至少 1 筆，實際 {len(errors)}"
    last = errors[-1]
    assert last["error_type"] == ERROR_API_ERROR
    assert last["severity"] == SEVERITY_BLOCKING
    assert last["source"] == "scripts.executor"
    assert "timestamp" in last
    assert last["resolved"] is False


# ─── Test 7（補充 / integration）: ErrorHelper.handle_traceback 端到端 ─

def test_error_helper_integration_handle_traceback(tmp_path: Path):
    """ErrorHelper.handle_traceback 端到端：
    給一段模擬 traceback → 分類正確 + 產出 error_report.md。
    """
    report_path = tmp_path / "error_report.md"
    helper = ErrorHelper(retry_count=2, report_path=report_path)

    report = helper.handle_traceback(
        API_ERROR_TRACEBACK,
        source="scripts.executor",
        section_index=3,
    )
    assert report.classification.error_type == ERROR_API_ERROR
    assert report.classification.severity == SEVERITY_BLOCKING
    assert report.resolution.resolved is False
    assert report.resolution.needs_manual is True
    # retry-count=2 → 至少 2 個 retry attempts + 1 個 switch model skipped
    retry_attempts = [a for a in report.resolution.attempts if "retry" in a.action]
    assert len(retry_attempts) == 2, f"retry-count=2 應有 2 個 retry attempts，實際 {len(retry_attempts)}"

    # report_markdown 應含必要區塊
    md = report.report_markdown
    assert "# Error Report" in md
    assert "API_ERROR" in md
    assert "## 自動修復嘗試" in md
    assert "## 建議 next action" in md
    assert "Rate limit reached for gpt-4" in md

    # error_report.md 應被寫到磁碟
    assert Path(report.report_path).exists()
    assert Path(report.report_path).read_text(encoding="utf-8") == md


def test_error_helper_integration_json_output(tmp_path: Path):
    """ErrorHelper 支援 JSON 序列化（給 main agent / CI 用）。"""
    report_path = tmp_path / "error_report.md"
    helper = ErrorHelper(report_path=report_path)
    report = helper.handle_traceback(
        LOCK_MISMATCH_TRACEBACK,
        source="scripts.delta_checker",
    )
    d = report.to_dict()
    json_str = json.dumps(d, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["classification"]["error_type"] == ERROR_LOCK_MISMATCH
    assert parsed["classification"]["severity"] == SEVERITY_BLOCKING
    assert "report_markdown" not in parsed  # to_dict 不包含完整 markdown（避免太長）
    assert parsed["report_path"] == str(report_path)


def test_format_report_for_cli_basic():
    """format_report_for_cli 應印出人類可讀摘要（給 CLI 使用）。"""
    ctx = ErrorContext.from_text(API_ERROR_TRACEBACK, section_index=3)
    cls = ErrorClassifier().classify(ctx)
    res = ErrorResolver(retry_count=1).resolve(ctx, cls)
    from scripts.error_helper import ErrorReport
    report = ErrorReport(
        context=ctx,
        classification=cls,
        resolution=res,
        report_markdown="# x",
        report_path="report_output/error_report.md",
    )
    out = format_report_for_cli(report)
    assert "Error Helper" in out
    assert "API_ERROR" in out
    assert "BLOCKING" in out
    assert "next action" in out.lower() or "建議" in out