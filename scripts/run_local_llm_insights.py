from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from agency.runtime.local_llm import (  # noqa: E402
    DEFAULT_INPUT_ROOT,
    DEFAULT_OUTPUT_ROOT,
    LocalLlmConfig,
    generate_local_llm_insights,
)


async def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    args = _parse_args()
    result = await generate_local_llm_insights(
        input_root=args.input_root,
        output_root=args.output_root,
        config=LocalLlmConfig.from_env(),
        tickers=args.ticker,
        max_tickers=args.max_tickers,
    )
    print(
        f"{result.get('status_label')}: "
        f"{result.get('ticker_count', 0)} ticker insight(s); "
        f"wrote {args.output_root}"
    )
    return 0 if str(result.get("status")) in {"completed", "disabled"} else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Raspberry Pi/Open WebUI local LLM advisory insight worker.",
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--ticker", action="append", help="Limit to one ticker; repeatable.")
    parser.add_argument("--max-tickers", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
