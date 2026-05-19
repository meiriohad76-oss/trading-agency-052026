from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from providers.massive_limits import current_usage  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    print(json.dumps(current_usage(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
