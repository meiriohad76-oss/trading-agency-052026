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
from sec.company_facts import pull_company_facts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull SEC company facts for universe tickers.")
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--as-of", type=_date, default=date.today())
    parser.add_argument(
        "--include-inactive-universe",
        action="store_true",
        help="Use every ticker in universe_membership.parquet instead of only active rows.",
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sec-user-agent", default=None)
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=ROOT / "research" / "data" / "raw" / "sec" / "companyfacts",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "sec_company_facts",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "sec_company_facts.json",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    tickers = args.tickers or universe_tickers(
        args.universe_path,
        as_of=args.as_of,
        active_only=not args.include_inactive_universe,
    )
    config = SecClientConfig(user_agent=_user_agent(args.sec_user_agent))

    async def run() -> object:
        async with SecClient(config) as client:
            return await pull_company_facts(
                tickers=tickers,
                client=client,
                raw_root=args.raw_root,
                data_root=args.data_root,
                manifest_path=args.manifest_path,
                refresh=args.refresh,
            )

    print(json.dumps(asyncio.run(run()).__dict__, sort_keys=True))
    return 0


def _user_agent(value: str | None) -> str:
    user_agent = value or os.environ.get("SEC_USER_AGENT", "")
    if user_agent.strip() == "":
        raise SystemExit("SEC_USER_AGENT is required, e.g. 'Trading Agency admin@example.com'")
    return user_agent


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
