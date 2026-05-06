from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from prices.puller import pull_prices, universe_tickers  # noqa: E402
from prices.sector_etfs import include_sector_etfs  # noqa: E402
from prices.storage import DateRange  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull daily OHLCV bars from yfinance.")
    parser.add_argument("--start", type=_date, default=date(2019, 1, 1))
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--include-etfs", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument(
        "--price-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "prices_daily",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "prices_daily.json",
    )
    args = parser.parse_args()

    tickers = args.tickers or universe_tickers(args.universe_path)
    if args.include_etfs:
        tickers = include_sector_etfs(tickers)
    summary = asyncio.run(
        pull_prices(
            tickers=tickers,
            requested=DateRange(args.start, args.end),
            price_root=args.price_root,
            manifest_path=args.manifest_path,
            refresh=args.refresh,
            workers=args.workers,
        )
    )
    print(json.dumps(summary.__dict__, sort_keys=True))
    return 0


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
