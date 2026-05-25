"""Trading agency package."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESEARCH_SRC = _REPO_ROOT / "research" / "src"
if _RESEARCH_SRC.exists() and str(_RESEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_SRC))
