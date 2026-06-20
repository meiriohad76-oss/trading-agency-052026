from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from sec.cik import universe_tickers  # noqa: E402
from sec.client import SecClient, SecClientConfig  # noqa: E402
from sec.form4 import pull_form4  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull SEC Form 4 filings for universe tickers.")
    parser.add_argument("--start", type=_date, default=date(2019, 1, 1))
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument(
        "--include-inactive-universe",
        action="store_true",
        help="Use every ticker in universe_membership.parquet instead of only active rows as of --end.",
    )
    parser.add_argument("--sec-user-agent", default=None)
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "sec_form4",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "sec_form4.json",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    tickers = args.tickers or universe_tickers(
        args.universe_path,
        as_of=args.end,
        active_only=not args.include_inactive_universe,
    )
    config = SecClientConfig(user_agent=_user_agent(args.sec_user_agent))

    async def run() -> object:
        async with SecClient(config) as client:
            return await pull_form4(
                tickers=tickers,
                client=client,
                data_root=args.data_root,
                manifest_path=args.manifest_path,
                start=args.start,
                end=args.end,
            )

    print(json.dumps(asyncio.run(run()).__dict__, sort_keys=True))
    return 0


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _user_agent(value: str | None) -> str:
    user_agent = value or os.environ.get("SEC_USER_AGENT", "")
    if user_agent.strip() == "":
        raise SystemExit("SEC_USER_AGENT is required, e.g. 'Trading Agency admin@example.com'")
    return user_agent


if __name__ == "__main__":
    raise SystemExit(main())
