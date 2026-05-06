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

from sec.client import SecClient, SecClientConfig  # noqa: E402
from sec.form13f import pull_form13f  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull SEC 13F holdings for selected filers.")
    parser.add_argument("--start", type=_date, default=date(2019, 1, 1))
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--filer-ciks", nargs="+", required=True)
    parser.add_argument("--cusip-map", type=Path, required=True)
    parser.add_argument("--sec-user-agent", default=None)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "sec_13f",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "sec_13f.json",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    config = SecClientConfig(user_agent=_user_agent(args.sec_user_agent))
    cusip_to_ticker = json.loads(args.cusip_map.read_text(encoding="utf-8"))

    async def run() -> object:
        async with SecClient(config) as client:
            return await pull_form13f(
                filer_ciks=args.filer_ciks,
                client=client,
                data_root=args.data_root,
                manifest_path=args.manifest_path,
                start=args.start,
                end=args.end,
                cusip_to_ticker=cusip_to_ticker,
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
