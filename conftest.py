"""conftest.py — pytest 設定。

確保 `scripts` package 可被 import（即使從根目錄或子目錄執行 pytest）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 把 project root 加到 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
