from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from market_flow.massive import MassiveTradesConfig, pull_massive_trades  # noqa: E402
from market_flow.storage import DateRange  # noqa: E402
from prices.puller import universe_tickers  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    config = MassiveTradesConfig.from_env(base_url=args.massive_base_url)
    tickers = tuple(args.ticker or universe_tickers(args.universe_path))
    summary = asyncio.run(
        pull_massive_trades(
            tickers=tickers,
            requested=DateRange(args.start, args.end),
            trade_root=args.trade_root,
            manifest_path=args.manifest_path,
            config=config,
        )
    )
    print(json.dumps(summary.__dict__, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Massive stock trades.")
    parser.add_argument("--start", type=_date, default=date.today())
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--ticker", action="append", help="Ticker to refresh; repeatable.")
    parser.add_argument("--massive-base-url")
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument(
        "--trade-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "stock_trades",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "stock_trades.json",
    )
    return parser.parse_args()


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
