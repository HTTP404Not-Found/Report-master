"""tests/test_project_manager.py — scripts/project_manager.py 單元測試。

DoD 對應 `tasks.md` T1-2：
- init_project 建立正確目錄樹
- report_lock.md 模板含 17 個 required 欄位
- glossary.md ≥ 3 條
- FileExistsError 在目錄有內容時 raise
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.project_manager import (
    PROJECT_SUBDIRS,
    init_project,
)
from scripts.report_lock import REQUIRED_FIELDS, read_lock, validate_lock


@pytest.fixture
def fake_fonts(tmp_path: Path, monkeypatch) -> Path:
    """建立假字體檔並透過 monkeypatch 設到 env。"""
    cjk = tmp_path / "cjk.ttf"
    latin = tmp_path / "latin.ttf"
    cjk.write_bytes(b"\x00\x01\x00\x00")
    latin.write_bytes(b"\x00\x01\x00\x00")
    monkeypatch.setenv("REPORT_MASTER_CJK_FONT", str(cjk))
    monkeypatch.setenv("REPORT_MASTER_LATIN_FONT", str(latin))
    return tmp_path


@pytest.fixture
def project_root(fake_fonts: Path, tmp_path: Path) -> Path:
    """建立一個含 SPEC.md 的假專案根目錄。"""
    root = tmp_path / "project_root"
    root.mkdir()
    (root / "SPEC.md").write_text("# fake\n", encoding="utf-8")
    return root


# ─── 測試：init_project 成功建立 ─────────────────────────────────────

class TestInitProject:

    def test_creates_project_dir(self, tmp_path: Path):
        """應建立專案目錄。"""
        target = tmp_path / "new-project"
        result = init_project(
            target, template="academic", skip_font_check=True,
        )
        assert result.exists()
        assert result.is_dir()

    def test_creates_subdirs(self, tmp_path: Path):
        """應建立所有子目錄。"""
        target = tmp_path / "new-project"
        init_project(target, template="academic", skip_font_check=True)
        for sub in PROJECT_SUBDIRS:
            assert (target / sub).exists(), f"missing {sub}"
            assert (target / sub).is_dir(), f"{sub} not a dir"

    def test_creates_lock_file(self, tmp_path: Path):
        """應產 report_lock.md。"""
        target = tmp_path / "new-project"
        init_project(target, template="academic", skip_font_check=True)
        assert (target / "report_lock.md").exists()

    def test_creates_glossary_file(self, tmp_path: Path):
        """應產 glossary.md 且 ≥ 3 條目。"""
        target = tmp_path / "new-project"
        init_project(target, template="academic", skip_font_check=True)
        assert (target / "glossary.md").exists()
        content = (target / "glossary.md").read_text(encoding="utf-8")
        assert content.count("### ") >= 3, "glossary.md 至少要有 3 條"

    def test_creates_spec_file(self, tmp_path: Path):
        """應產 report_spec.md 空白範本。"""
        target = tmp_path / "new-project"
        init_project(target, template="academic", skip_font_check=True)
        assert (target / "report_spec.md").exists()

    def test_creates_readme(self, tmp_path: Path):
        """應產 README.md。"""
        target = tmp_path / "new-project"
        init_project(target, template="academic", skip_font_check=True)
        assert (target / "README.md").exists()


# ─── 測試：lock 模板內容 ──────────────────────────────────────────────

class TestLockTemplate:

    @pytest.fixture
    def initialized(self, tmp_path: Path) -> Path:
        target = tmp_path / "locked-project"
        init_project(target, template="academic", skip_font_check=True)
        return target

    def test_lock_passes_validation(self, initialized: Path):
        """產出的 lock 應通過 schema 驗證。"""
        data = read_lock(initialized / "report_lock.md")
        validate_lock(data)  # 不 raise

    def test_lock_has_all_required_fields(self, initialized: Path):
        """17 個 required 欄位全在。"""
        data = read_lock(initialized / "report_lock.md")
        for field in REQUIRED_FIELDS:
            parts = field.split(".")
            cur = data
            for p in parts:
                assert isinstance(cur, dict), f"{field}: not a dict at {p}"
                assert p in cur, f"{field}: missing key {p}"
                cur = cur[p]
            assert cur, f"{field}: empty value"

    def test_lock_fonts_locked(self, initialized: Path):
        """fonts.cjk = 標楷體、fonts.latin = Times New Roman（鎖死）。"""
        data = read_lock(initialized / "report_lock.md")
        assert data["fonts"]["cjk"] == "標楷體"
        assert data["fonts"]["latin"] == "Times New Roman"

    def test_lock_academic_defaults(self, initialized: Path):
        """academic template 預設值合理。"""
        data = read_lock(initialized / "report_lock.md")
        assert data["citation_style"] == "APA"
        assert data["page_size"] == "A4"
        assert data["language_variant"] == "zh-TW"
        assert data["output"]["docx_engine"] == "pandoc"

    def test_lock_business_template_differs(self, tmp_path: Path):
        """business template 與 academic 預設值不同。"""
        target = tmp_path / "biz-project"
        init_project(target, template="business", skip_font_check=True)
        data = read_lock(target / "report_lock.md")
        assert data["citation_style"] == "none"
        assert data["line_spacing"] == 1.0

    def test_lock_gov_template(self, tmp_path: Path):
        """gov template 預設 GBC 引用。"""
        target = tmp_path / "gov-project"
        init_project(target, template="gov", skip_font_check=True)
        data = read_lock(target / "report_lock.md")
        assert data["citation_style"] == "GBC"


# ─── 測試：錯誤情境 ───────────────────────────────────────────────────

class TestInitProjectErrors:

    def test_existing_nonempty_dir_raises(self, tmp_path: Path):
        """已存在且有內容的目錄應 raise FileExistsError。"""
        target = tmp_path / "existing"
        target.mkdir()
        (target / "something.txt").write_text("data")
        with pytest.raises(FileExistsError):
            init_project(target, template="academic", skip_font_check=True)

    def test_existing_empty_dir_succeeds(self, tmp_path: Path):
        """已存在但空目錄應成功。"""
        target = tmp_path / "empty"
        target.mkdir()
        result = init_project(target, template="academic", skip_font_check=True)
        assert result == target.resolve()

    def test_invalid_template_raises(self, tmp_path: Path):
        """未知 template 應 raise。"""
        from scripts.report_lock import LockFormatError
        target = tmp_path / "bad"
        with pytest.raises(LockFormatError):
            init_project(target, template="nonexistent", skip_font_check=True)

    def test_missing_fonts_raises(self, tmp_path: Path, monkeypatch):
        """缺字體時應 raise FontNotFoundError。"""
        from scripts.config import FontNotFoundError
        target = tmp_path / "no-fonts"
        # 不設任何 font env → fc-list 也不會自動找到
        monkeypatch.delenv("REPORT_MASTER_CJK_FONT", raising=False)
        monkeypatch.delenv("REPORT_MASTER_LATIN_FONT", raising=False)
        with pytest.raises(FontNotFoundError):
            init_project(target, template="academic", skip_font_check=False)

    def test_skip_font_check_does_not_check(self, tmp_path: Path, monkeypatch):
        """skip_font_check=True 時不檢查字體。"""
        target = tmp_path / "skip-font"
        monkeypatch.delenv("REPORT_MASTER_CJK_FONT", raising=False)
        monkeypatch.delenv("REPORT_MASTER_LATIN_FONT", raising=False)
        result = init_project(target, template="academic", skip_font_check=True)
        assert result.exists()


# ─── 測試：CLI ────────────────────────────────────────────────────────

class TestInitCLI:

    def test_cli_init_creates_project(self, tmp_path: Path, monkeypatch, capsys):
        """CLI init 應能建立專案。"""
        from scripts.project_manager import _cli
        target = tmp_path / "cli-project"
        monkeypatch.setattr(
            "sys.argv",
            ["project_manager.py", "init", str(target),
             "--skip-font-check", "--type", "academic"],
        )
        rc = _cli()
        assert rc == 0
        assert (target / "report_lock.md").exists()

    def test_cli_init_existing_dir_fails(self, tmp_path: Path, monkeypatch, capsys):
        """CLI init 對已存在目錄應 exit code 3。"""
        from scripts.project_manager import _cli
        target = tmp_path / "preexist"
        target.mkdir()
        (target / "file.txt").write_text("x")
        monkeypatch.setattr(
            "sys.argv",
            ["project_manager.py", "init", str(target), "--skip-font-check"],
        )
        rc = _cli()
        assert rc == 3
