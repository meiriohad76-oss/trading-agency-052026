from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from agency.runtime.local_llm import check_local_llm_health  # noqa: E402


async def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    result = await check_local_llm_health()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if str(result.get("status")) in {"ready", "disabled"} else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
