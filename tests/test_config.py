"""tests/test_config.py — scripts/config.py 單元測試。

DoD 對應 `tasks.md` T1-1：覆蓋 OK / 缺字體 / 缺 key 三情境。
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from scripts import config as cfg_mod
from scripts.config import (
    Config,
    FontNotFoundError,
    MissingConfigError,
    reset_default_config,
)


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """建立一個假專案根目錄，含 SPEC.md 標記。"""
    (tmp_path / "SPEC.md").write_text("# fake spec\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """產生一個 .env 檔。"""
    env_path = tmp_path / ".env"
    env_path.write_text(
        textwrap.dedent("""
            REPORT_MASTER_CJK_FONT=/fake/cjk.ttf
            REPORT_MASTER_CJK_FONT_NAME=標楷體
            REPORT_MASTER_LATIN_FONT=/fake/latin.ttf
            REPORT_MASTER_LATIN_FONT_NAME=Times New Roman
            REPORT_MASTER_LANGUAGE_VARIANT=zh-TW
        """).strip(),
        encoding="utf-8",
    )
    return env_path


# ─── 測試：OK 情境 ────────────────────────────────────────────────────

class TestConfigOK:
    """OK 情境：.env 設定完整 + 字體存在。"""

    def test_loads_env_file(self, tmp_path: Path, tmp_project: Path):
        """應載入 .env 並合併到 config。"""
        # 在 tmp_project 同層放 .env 讓 Config 可找到
        env = tmp_path / ".env"
        env.write_text(
            "REPORT_MASTER_LANGUAGE_VARIANT=zh-CN\n",
            encoding="utf-8",
        )
        c = Config(project_root=tmp_project, skip_font_check=True)
        assert c.get("language_variant") == "zh-CN"

    def test_default_values_present(self, tmp_project: Path):
        """預設值應在。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        assert c.get("cjk_font_name") == "標楷體"
        assert c.get("latin_font_name") == "Times New Roman"
        assert c.get("language_variant") == "zh-TW"

    def test_get_with_default(self, tmp_project: Path):
        """get(key, default) 在 key 缺失時回傳 default。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        assert c.get("nonexistent.key", default="fallback") == "fallback"

    def test_dot_notation(self, tmp_project: Path):
        """'fonts.cjk' 應被正規化為 cjk_font_path。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        # 即使沒設，也應該能拿到 default 的 key 名
        assert c.get("fonts.cjk.name") == "標楷體"

    def test_has_method(self, tmp_project: Path):
        """has() 對存在的 default 應回 True。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        assert c.has("cjk_font_name") is True
        assert c.has("nonexistent.key") is False

    def test_system_env_takes_precedence_in_chain(self, tmp_project: Path, monkeypatch):
        """system env 應先載入，user/project 後讀會覆蓋。"""
        monkeypatch.setenv("REPORT_MASTER_LANGUAGE_VARIANT", "en-US")
        c = Config(project_root=tmp_project, skip_font_check=True)
        assert c.get("language_variant") == "en-US"

    def test_all_returns_dict(self, tmp_project: Path):
        """all() 應回 dict。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        all_values = c.all()
        assert isinstance(all_values, dict)
        assert "cjk_font_name" in all_values


# ─── 測試：缺字體情境 ────────────────────────────────────────────────

class TestConfigMissingFonts:
    """缺字體情境：必須 raise FontNotFoundError 含明確訊息。"""

    def test_missing_fonts_raises(self, tmp_project: Path):
        """預設無字體、預設無 env 時應 raise。"""
        # 完全乾淨環境（無 user env、無 project env、無字體）
        # 透過 skip_font_check=False 強制檢查
        with pytest.raises(FontNotFoundError) as exc_info:
            Config(project_root=tmp_project, skip_font_check=False)
        msg = str(exc_info.value)
        assert "CJK" in msg or "標楷體" in msg
        assert "Latin" in msg or "Times New Roman" in msg
        assert "BLOCKING" in msg

    def test_missing_only_cjk_raises(self, tmp_project: Path, monkeypatch, tmp_path: Path):
        """只有 CJK 缺失時也應 raise（兩個都檢查）。"""
        # 模擬存在 Latin 字體
        fake_latin = tmp_path / "latin.ttf"
        fake_latin.write_bytes(b"\x00\x01\x00\x00")  # fake binary
        monkeypatch.setenv("REPORT_MASTER_LATIN_FONT", str(fake_latin))

        with pytest.raises(FontNotFoundError) as exc_info:
            Config(project_root=tmp_project, skip_font_check=False)
        # 應只列 CJK 缺失
        missing = exc_info.value.missing
        assert len(missing) == 1
        assert "CJK" in missing[0]["role"]

    def test_skip_font_check_does_not_raise(self, tmp_project: Path):
        """skip_font_check=True 時即使無字體也不 raise。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        # 不 raise；cjk_font_path 可能自動偵測到或為空字串
        assert c is not None

    def test_check_fonts_returns_list(self, tmp_project: Path):
        """check_fonts() 不 raise，回傳 list。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        missing = c.check_fonts()
        # 沒設 env 且 fc-list 可能找不到 → 應該是 list
        assert isinstance(missing, list)


# ─── 測試：缺 key 情境 ───────────────────────────────────────────────

class TestConfigMissingKey:
    """缺 key 情境：必須 raise MissingConfigError。"""

    def test_missing_key_raises(self, tmp_project: Path):
        """get() 不帶 default 且 key 缺失時 raise。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        with pytest.raises(MissingConfigError) as exc_info:
            c.get("totally.fake.key")
        assert "totally.fake.key" in str(exc_info.value)
        assert "BLOCKING" in str(exc_info.value)

    def test_missing_key_attribute(self, tmp_project: Path):
        """例外應帶有 .key 屬性。"""
        c = Config(project_root=tmp_project, skip_font_check=True)
        with pytest.raises(MissingConfigError) as exc_info:
            c.get("some.missing.key")
        assert exc_info.value.key == "some.missing.key"


# ─── 測試：模組級 helper ──────────────────────────────────────────────

class TestModuleLevelHelper:
    """模組級 get() helper。"""

    def test_module_get_works(self, tmp_project: Path, monkeypatch):
        """get() helper 應能用。"""
        reset_default_config()
        monkeypatch.chdir(tmp_project)
        # skip_font_check=True → 不 raise
        monkeypatch.setattr(cfg_mod, "_default_config", None)
        monkeypatch.setattr(
            cfg_mod, "_detect_project_root",
            lambda: tmp_project,
        )
        # 透過 Config(skip_font_check=True) 注入
        cfg_mod._default_config = Config(
            project_root=tmp_project,
            skip_font_check=True,
        )
        try:
            # 預設 DEFAULTS 有 language_variant
            val = cfg_mod.get("language_variant")
            assert val == "zh-TW"
        finally:
            reset_default_config()


# ─── 測試：CLI ────────────────────────────────────────────────────────

class TestConfigCLI:
    """CLI 行為。"""

    def test_cli_check_exit_code_on_missing_fonts(
        self, tmp_project: Path, capsys, monkeypatch
    ):
        """CLI check 在缺字體時應 exit code 2。"""
        from scripts.config import _cli
        monkeypatch.setattr("sys.argv", ["config.py", "check"])
        with pytest.raises(SystemExit) as exc_info:
            _cli()
        assert exc_info.value.code == 2

    def test_cli_get_existing_key(
        self, tmp_project: Path, capsys, monkeypatch
    ):
        """CLI get 對存在的 key 應輸出 value。"""
        from scripts.config import _cli
        monkeypatch.setattr(
            "sys.argv",
            ["config.py", "get", "cjk_font_name", "--skip-font-check"],
        )
        rc = _cli()
        assert rc == 0
        out = capsys.readouterr().out
        assert "標楷體" in out
