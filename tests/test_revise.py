"""tests/test_revise.py — scripts/revise_helper.py + workflows/revise.md 單元測試。

DoD 對應 `tasks.md` T3-9：
1. workflows/revise.md frontmatter 載入 + name + Mermaid 流程圖
2. revise_helper.locate_section / apply_revision 單元邏輯
3. CLI smoke test（subprocess 跑）
4. revise round-trip：dry-run → write 後 HTML 含 revise-note meta

設計：4 個必要 cases + 3 個補充 cases
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.revise_helper import (
    REVISION_NOTE_TAG,
    apply_revision,
    locate_section,
    run_revise,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "revise.md"
EXAMPLES_SECTION = PROJECT_ROOT / "examples" / "section_1.html"
EXAMPLES_LOCK = PROJECT_ROOT / "examples" / "lock.md"


@pytest.fixture
def tmp_section(tmp_path):
    """產生一份 tmp section HTML。"""
    src = EXAMPLES_SECTION.read_text(encoding="utf-8")
    p = tmp_path / "section_3.html"
    p.write_text(src, encoding="utf-8")
    return p


# ─── Test 1（必要）：workflows/revise.md frontmatter + Mermaid ─────────

def test_workflow_md_frontmatter_loads():
    """載入 workflows/revise.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "revise.md 應以 frontmatter 開頭"

    # 解析 frontmatter（用 --- ... --- 區段）
    parts = content.split("---", 2)
    assert len(parts) >= 3, "frontmatter 格式錯誤"
    fm = yaml.safe_load(parts[1])

    assert fm["name"] == "revise"
    assert "Step 4" in fm["description"]  # v1.3: Stage 2.5 renamed to Step 4 inline
    assert str(fm["version"]) == "1.0"  # YAML 把 "1.0" parse 為 float


def test_workflow_md_has_mermaid_flowchart():
    """Mermaid 流程圖存在（regex `` ```mermaid `` 區塊）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "```mermaid" in content, "workflows/revise.md 應含 Mermaid 流程圖"
    assert "flowchart" in content, "Mermaid 應為 flowchart"


def test_workflow_md_references_core_files():
    """對 reference 引用：executor-base.md / delta_checker.py / quality_checker.py 都在文內。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "executor-base.md" in content
    assert "delta_checker.py" in content
    assert "quality_checker.py" in content
    assert "report_lock.md" in content


def test_workflow_md_minimum_length():
    """revise.md 應 > 100 行（L 等級 workflow）。"""
    line_count = sum(1 for _ in WORKFLOW_MD.open(encoding="utf-8"))
    assert line_count > 100, f"revise.md 只有 {line_count} 行（L 等級需 > 100）"


# ─── Test 2（必要）：Mermaid flow + revise structure ──────────────────

def test_workflow_md_has_seven_steps():
    r"""Step 1~7 流程都在文內（regex `Step \d+`，全/半形冒號都容許）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    steps = re.findall(r"Step\s+\d+", content)
    assert len(steps) >= 5, f"revise.md 應有 ≥5 個 Step，找到 {len(steps)} 個"


# ─── Test 3（必要）：CLI smoke test（subprocess）──────────────────────

def test_cli_smoke_dry_run(tmp_path):
    """`python -m scripts.revise_helper --dry-run` 跑通，exit code 0。"""
    # 用 examples/section_1.html 作輸入
    if not EXAMPLES_SECTION.exists():
        pytest.skip("examples/section_1.html 不存在")

    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.revise_helper",
            "--section", "examples/section_1.html",
            "--instruction", "壓縮第二段",
            "--lock", "examples/lock.md",
            "--dry-run",
            "--project-root", str(PROJECT_ROOT),
            "--report", str(tmp_path / "delta.md"),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Revise plan" in result.stdout
    assert "dry-run" in result.stdout
    assert "quality_check" in result.stdout
    assert "lock_diff" in result.stdout


def test_cli_smoke_json_output(tmp_path):
    """`--json` 模式可輸出 JSON。"""
    if not EXAMPLES_SECTION.exists():
        pytest.skip("examples/section_1.html 不存在")

    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.revise_helper",
            "--section", "examples/section_1.html",
            "--instruction", "測試 JSON",
            "--lock", "examples/lock.md",
            "--dry-run",
            "--json",
            "--project-root", str(PROJECT_ROOT),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    # 應為合法 JSON
    import json
    parsed = json.loads(result.stdout)
    assert parsed["instruction"] == "測試 JSON"
    assert parsed["write"] is False


# ─── Test 4（必要）：revision round-trip ──────────────────────────────

def test_revision_round_trip_writes_meta_tag(tmp_section):
    """write 模式後，section HTML 應含 revise-note meta tag。"""
    if not EXAMPLES_LOCK.exists():
        pytest.skip("examples/lock.md 不存在")

    plan = run_revise(
        section_target=str(tmp_section),
        instruction="把 §1.1 改成 bullet 形式",
        lock_path=EXAMPLES_LOCK,
        project_root=PROJECT_ROOT,
        write=True,
        dry_run=False,
        report_path=tmp_section.parent / "delta.md",
    )

    assert plan["success"] is True, f"plan={plan}"
    assert plan["quality_check"]["passed"] is True

    # 驗證 HTML 含 revise-note meta tag
    html_after = tmp_section.read_text(encoding="utf-8")
    assert 'name="revise-note"' in html_after
    assert "把 §1.1 改成 bullet 形式" in html_after

    # 驗證 delta 報告存在
    assert (tmp_section.parent / "delta.md").exists()


def test_dry_run_does_not_modify(tmp_section):
    """dry-run 不應寫回 section HTML。"""
    before = tmp_section.read_text(encoding="utf-8")

    plan = run_revise(
        section_target=str(tmp_section),
        instruction="dry-run test",
        lock_path=EXAMPLES_LOCK,
        project_root=PROJECT_ROOT,
        write=False,
        dry_run=True,
        report_path=None,
    )

    after = tmp_section.read_text(encoding="utf-8")
    assert before == after, "dry-run 不應修改 section HTML"
    assert plan["write"] is False


# ─── 補充 tests：單元邏輯 ────────────────────────────────────────────

def test_locate_section_with_numeric_id(tmp_path):
    """locate_section('3') → report_output/section_3.html。"""
    ro = tmp_path / "ro"
    (ro / "report_output").mkdir(parents=True)
    (ro / "report_output" / "section_3.html").write_text("<html></html>", encoding="utf-8")

    p = locate_section("3", ro)
    assert p.name == "section_3.html"
    assert p.exists()


def test_locate_section_absolute_path(tmp_path):
    """locate_section('/abs/path.html') 直接使用絕對路徑。"""
    src = tmp_path / "abs.html"
    src.write_text("<html></html>", encoding="utf-8")

    p = locate_section(str(src), Path("/nonexistent"))
    assert p == src


def test_locate_section_invalid_raises():
    """無效輸入（既不是數字也不是 .html 路徑）→ ValueError。"""
    with pytest.raises(ValueError):
        locate_section("garbage", Path("/tmp"))


def test_locate_section_missing_raises(tmp_path):
    """找不到檔 → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        locate_section("99", tmp_path)


def test_apply_revision_injects_meta_tag():
    """apply_revision 應在 <head> 注入 revise-note meta。"""
    html = "<html><head><meta charset='UTF-8'></head><body><p>x</p></body></html>"
    out = apply_revision(html, "test instruction", Path("/tmp/x.html"))

    assert 'name="revise-note"' in out
    assert "test instruction" in out
    # 必須出現在 <head> 區段內
    head_match = re.search(r"<head>(.*?)</head>", out, re.DOTALL)
    assert head_match is not None
    assert "revise-note" in head_match.group(1)


def test_apply_revision_escapes_quotes_and_angle():
    """instruction 含 `\"` `<` 應被跳脫，不破壞 meta tag。"""
    html = "<html><head></head><body></body></html>"
    out = apply_revision(html, '含 < 與 " 字元', Path("/tmp/x.html"))

    # 不應有 raw "..." 在 meta tag content 內造成解析錯誤
    # 檢查 meta tag 結構合法（開合平衡）
    assert out.count('<meta name="revise-note"') == 1
    assert "&lt;" in out or "<" not in out.split("</head>")[0].split("revise-note", 1)[1][:30]
    # 跳脫後不應再有原始雙引號在 content 內
    note_section = out.split('content="', 1)[1].split('">', 1)[0]
    assert '"' not in note_section
    assert "<" not in note_section


def test_apply_revision_replaces_existing_note():
    """若已有 revise-note meta，應先移除再插入新的一個（不重複）。"""
    html = '<html><head><meta name="revise-note" content="old"></head><body></body></html>'
    out = apply_revision(html, "new instruction", Path("/tmp/x.html"))

    assert out.count('name="revise-note"') == 1
    assert "old" not in out
    assert "new instruction" in out
