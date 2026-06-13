"""scripts/config.py — Configuration management for Report-master.

對應 SPEC.md §6.1 R6（無 CJK/字體策略）+ `tasks.md` T1-1
提供：
- .env 載入鏈（system → user → project，後者覆蓋前者）
- 字體 fail-fast 檢查（標楷體 + Times New Roman）
- get(key) API（支援巢狀 key，例如 get('fonts.cjk')）
- CLI：`python scripts/config.py check` / `python scripts/config.py get <key>`

設計原則：
- 缺字體時 raise FontNotFoundError（不 fallback）
- 缺 key 時 raise MissingConfigError
- 所有錯誤訊息明確、可行動
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/config.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import dotenv_values
except ImportError as e:  # pragma: no cover - 由 requirements 管理
    raise ImportError(
        "缺少 python-dotenv，請先 `pip install python-dotenv`"
    ) from e


# ─── 例外類型 ────────────────────────────────────────────────────────

class ConfigError(Exception):
    """所有 config 例外的基底類型。"""


class FontNotFoundError(ConfigError):
    """指定的字體檔不存在或不可讀。"""

    def __init__(self, missing: List[Dict[str, str]]):
        self.missing = missing
        lines = ["[BLOCKING] 找不到必要字體："]
        for item in missing:
            lines.append(
                f"  - {item['role']}: {item['font_name']}\n"
                f"      預期路徑：{item['path']}\n"
                f"      修正：見 fonts/README.md 安裝指引，或設定 "
                f"{item['env_path']} / {item['env_name']}"
            )
        super().__init__("\n".join(lines))


class MissingConfigError(ConfigError):
    """指定的設定 key 不存在。"""

    def __init__(self, key: str):
        self.key = key
        super().__init__(
            f"[BLOCKING] 缺少設定：{key}\n"
            f"請在 .env 加入 {key}=...  或參考 docs/.env.example"
        )


# ─── 預設值 ──────────────────────────────────────────────────────────

DEFAULTS: Dict[str, Any] = {
    "report_root": "~/Documents/reports",
    "cjk_font_path": "",      # 空字串 → 由 config 自動偵測（fail-fast）
    "cjk_font_name": "標楷體",
    "latin_font_path": "",
    "latin_font_name": "Times New Roman",
    "csl_file": "APA.csl",
    "bib_file": "references.bib",
    "embed_fonts": "true",
    "tagged_pdf": "false",
    "language_variant": "zh-TW",
    "verbose": "0",
}

# .env key 與內部 key 對映
ENV_KEY_MAP: Dict[str, str] = {
    "REPORT_MASTER_ROOT": "report_root",
    "REPORT_MASTER_CJK_FONT": "cjk_font_path",
    "REPORT_MASTER_CJK_FONT_NAME": "cjk_font_name",
    "REPORT_MASTER_LATIN_FONT": "latin_font_path",
    "REPORT_MASTER_LATIN_FONT_NAME": "latin_font_name",
    "REPORT_MASTER_CSL_FILE": "csl_file",
    "REPORT_MASTER_BIB_FILE": "bib_file",
    "REPORT_MASTER_EMBED_FONTS": "embed_fonts",
    "REPORT_MASTER_TAGGED_PDF": "tagged_pdf",
    "REPORT_MASTER_LANGUAGE_VARIANT": "language_variant",
    "REPORT_MASTER_VERBOSE": "verbose",
}


# ─── 字體自動偵測（fallback 候選）─────────────────────────────────────

CJK_FONT_CANDIDATES: List[str] = [
    # macOS
    "/System/Library/Fonts/Kaiti.ttc",
    "/System/Library/Fonts/STKaiti.ttf",
    "/Library/Fonts/標楷體.ttf",
    # Windows
    "C:\\Windows\\Fonts\\kaiu.ttf",
    "C:\\Windows\\Fonts\\simkai.ttf",
    # Linux - 教育 / 文鼎
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJKtc-Regular.otf",
]

LATIN_FONT_CANDIDATES: List[str] = [
    # macOS
    "/System/Library/Fonts/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Times New Roman.ttf",
    # Windows
    "C:\\Windows\\Fonts\\times.ttf",
    "C:\\Windows\\Fonts\\timesbd.ttf",
    # Linux - 替代
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
]


def _find_existing_font(candidates: List[str]) -> Optional[str]:
    """從候選清單中找第一個存在的字體檔。"""
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _fc_list_match(pattern: str) -> Optional[str]:
    """用 fc-list（若可用）找符合 pattern 的字體路徑。"""
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return None
    try:
        import subprocess
        out = subprocess.run(
            [fc_list, pattern, "file"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            # fc-list 輸出格式：<path>:<colon-separated-fc-data>
            first_line = out.stdout.splitlines()[0]
            return first_line.split(":", 1)[0].strip()
    except Exception:
        pass
    return None


# ─── 主類別：Config ──────────────────────────────────────────────────

class Config:
    """配置管理器（單例）。

    使用：
        cfg = Config(project_root=Path("/path/to/project"))
        cjk_path = cfg.get("cjk_font_path")
    """

    _instance: Optional["Config"] = None

    def __init__(
        self,
        project_root: Optional[Path] = None,
        skip_font_check: bool = False,
    ):
        self.project_root = (project_root or Path.cwd()).resolve()
        self.skip_font_check = skip_font_check
        self._values: Dict[str, Any] = dict(DEFAULTS)

        # .env 載入鏈：system → user → project（後者覆蓋前者）
        self._load_env_chain()

        # 字體 fail-fast（除非顯式 skip）
        if not self.skip_font_check:
            self._check_fonts_or_raise()

        # 自動偵測字體（若未設定）
        if not self._values.get("cjk_font_path"):
            detected = (
                _fc_list_match(":lang=zh-tw|kai|kaiti")
                or _find_existing_font(CJK_FONT_CANDIDATES)
            )
            if detected:
                self._values["cjk_font_path"] = detected
        if not self._values.get("latin_font_path"):
            detected = (
                _fc_list_match(":lang=en|times|liberation serif")
                or _find_existing_font(LATIN_FONT_CANDIDATES)
            )
            if detected:
                self._values["latin_font_path"] = detected

    # ─── 公開 API ──────────────────────────────────────────────────

    def get(self, key: str, default: Optional[str] = None) -> str:
        """取得設定值。

        key 支援 dot notation，例如 'fonts.cjk'（會轉為 cjk_font_path）。
        不存在且未給 default → raise MissingConfigError。
        """
        normalized = self._normalize_key(key)
        if normalized in self._values and self._values[normalized] != "":
            return str(self._values[normalized])
        if default is not None:
            return default
        raise MissingConfigError(key)

    def has(self, key: str) -> bool:
        """檢查 key 是否存在且非空。"""
        normalized = self._normalize_key(key)
        return normalized in self._values and self._values[normalized] != ""

    def all(self) -> Dict[str, str]:
        """回傳所有設定（除 DEFAULTS 之外的 .env 覆蓋）。"""
        return {k: str(v) for k, v in self._values.items()}

    def check_fonts(self) -> List[Dict[str, str]]:
        """檢查字體，回傳缺失清單（不 raise）。"""
        return self._check_fonts()

    # ─── 內部方法 ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_key(key: str) -> str:
        """'fonts.cjk' → 'cjk_font_path'；'cjk_font_name' 不變。"""
        mapping = {
            "fonts.cjk": "cjk_font_path",
            "fonts.cjk.name": "cjk_font_name",
            "fonts.latin": "latin_font_path",
            "fonts.latin.name": "latin_font_name",
            "report.root": "report_root",
            "citation.csl": "csl_file",
            "citation.bib": "bib_file",
            "output.embed_fonts": "embed_fonts",
            "output.tagged_pdf": "tagged_pdf",
            "language.variant": "language_variant",
        }
        return mapping.get(key, key)

    def _load_env_chain(self) -> None:
        """載入 .env 鏈：system → user → project（後者覆蓋前者）。"""
        # 1. system env（最低優先）→ 先放進 _values
        for env_key, internal_key in ENV_KEY_MAP.items():
            if env_key in os.environ and os.environ[env_key]:
                self._values[internal_key] = os.environ[env_key]

        # 2. user env：~/.config/report-master/.env
        user_env = Path.home() / ".config" / "report-master" / ".env"
        if user_env.exists():
            self._merge_env_file(user_env)

        # 3. project env：<project_root>/.env（最高優先，覆蓋以上）
        project_env = self.project_root / ".env"
        if project_env.exists():
            self._merge_env_file(project_env)

    def _merge_env_file(self, env_path: Path) -> None:
        """合併單一 .env 檔的值（後讀覆蓋先讀）。"""
        values = dotenv_values(env_path)
        for env_key, internal_key in ENV_KEY_MAP.items():
            if env_key in values and values[env_key] is not None:
                self._values[internal_key] = values[env_key]

    def _check_fonts(self) -> List[Dict[str, str]]:
        """回傳缺失字體清單（不 raise）。"""
        missing: List[Dict[str, str]] = []

        cjk_path = self._values.get("cjk_font_path", "")
        cjk_name = self._values.get("cjk_font_name", "標楷體")
        if not cjk_path or not Path(cjk_path).exists():
            missing.append({
                "role": "CJK (中文字體)",
                "font_name": cjk_name,
                "path": cjk_path or "(未設定)",
                "env_path": "REPORT_MASTER_CJK_FONT",
                "env_name": "REPORT_MASTER_CJK_FONT_NAME",
            })

        latin_path = self._values.get("latin_font_path", "")
        latin_name = self._values.get("latin_font_name", "Times New Roman")
        if not latin_path or not Path(latin_path).exists():
            missing.append({
                "role": "Latin (英文字體)",
                "font_name": latin_name,
                "path": latin_path or "(未設定)",
                "env_path": "REPORT_MASTER_LATIN_FONT",
                "env_name": "REPORT_MASTER_LATIN_FONT_NAME",
            })

        return missing

    def _check_fonts_or_raise(self) -> None:
        """檢查字體並 raise FontNotFoundError。"""
        missing = self._check_fonts()
        if missing:
            raise FontNotFoundError(missing)


# ─── 模組級單例 helper ───────────────────────────────────────────────

def _detect_project_root() -> Path:
    """從當前位置向上尋找含 SPEC.md 或 .venv 的目錄作為 project root。"""
    p = Path.cwd().resolve()
    for _ in range(8):  # 最多向上 8 層
        if (p / "SPEC.md").exists() or (p / ".venv").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path.cwd().resolve()


_default_config: Optional[Config] = None


def get(key: str, default: Optional[str] = None) -> str:
    """模組級 helper：使用預設 Config 單例。"""
    global _default_config
    if _default_config is None:
        _default_config = Config(project_root=_detect_project_root())
    return _default_config.get(key, default=default)


def reset_default_config() -> None:
    """重置單例（測試用）。"""
    global _default_config
    _default_config = None


# ─── CLI 入口 ────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="report-master config",
        description="Report-master 配置檢查工具",
    )
    parser.add_argument(
        "action", choices=["check", "get", "list"],
        help="check: 字體 + .env 檢查 / get: 取得 key / list: 列出所有",
    )
    parser.add_argument("key", nargs="?", help="要查詢的 key（get 模式）")
    parser.add_argument(
        "--project-root", type=Path, default=None,
        help="專案根目錄（預設自動偵測）",
    )
    parser.add_argument(
        "--skip-font-check", action="store_true",
        help="跳過字體檢查（測試環境用）",
    )
    args = parser.parse_args()

    if args.action == "check":
        # check 模式：即使沒設 --skip-font-check 也手動檢查並回報，不讓例外逃出
        cfg = Config(
            project_root=args.project_root,
            skip_font_check=True,
        )
        missing = cfg.check_fonts()
        if missing and not args.skip_font_check:
            print(FontNotFoundError(missing).args[0], file=sys.stderr)
            sys.exit(2)
        cjk = cfg.get("cjk_font_path", default="(未偵測)")
        latin = cfg.get("latin_font_path", default="(未偵測)")
        print(f"✅ 字體檢查通過（CJK: {cjk}）")
        print(f"✅ 字體檢查通過（Latin: {latin}）")
        return 0

    if args.action == "get":
        if not args.key:
            print("錯誤：get 模式需要 key", file=sys.stderr)
            sys.exit(2)
        cfg = Config(
            project_root=args.project_root,
            skip_font_check=args.skip_font_check,
        )
        try:
            value = cfg.get(args.key)
        except MissingConfigError as e:
            print(str(e), file=sys.stderr)
            sys.exit(2)
        print(f"{args.key} = {value}")
        return 0

    if args.action == "list":
        cfg = Config(
            project_root=args.project_root,
            skip_font_check=args.skip_font_check,
        )
        for k, v in cfg.all().items():
            if v:
                print(f"{k} = {v}")
        return 0

    return 0  # 不會到這


if __name__ == "__main__":
    sys.exit(_cli())
