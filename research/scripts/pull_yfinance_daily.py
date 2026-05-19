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

from prices.alpaca_daily import (  # noqa: E402
    DEFAULT_ALPACA_ADJUSTMENT,
    DEFAULT_ALPACA_DATA_BASE_URL,
    DEFAULT_ALPACA_FEED,
    AlpacaDailyConfig,
    build_alpaca_downloader,
    normalize_alpaca_bars,
)
from prices.massive_daily import (  # noqa: E402
    DEFAULT_MASSIVE_BASE_URL,
    MassiveDailyConfig,
    build_massive_downloader,
    normalize_massive_bars,
)
from prices.puller import pull_prices, universe_tickers  # noqa: E402
from prices.sector_etfs import include_sector_etfs  # noqa: E402
from prices.storage import DateRange  # noqa: E402
from prices.types import Downloader, HistoryNormalizer  # noqa: E402
from prices.yfinance_daily import normalize_history, yfinance_downloader  # noqa: E402

ProviderParts = tuple[Downloader, HistoryNormalizer, str, str]


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Pull daily OHLCV bars from market data.")
    parser.add_argument("--start", type=_date, default=date(2019, 1, 1))
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--include-etfs", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--provider",
        choices=("yfinance", "alpaca", "massive"),
        default=os.environ.get("MARKET_DATA_PROVIDER", "yfinance").lower(),
        help="Daily stock bar provider.",
    )
    parser.add_argument(
        "--alpaca-feed",
        default=os.environ.get("ALPACA_DATA_FEED", DEFAULT_ALPACA_FEED),
    )
    parser.add_argument(
        "--alpaca-adjustment",
        default=os.environ.get("ALPACA_DATA_ADJUSTMENT", DEFAULT_ALPACA_ADJUSTMENT),
    )
    parser.add_argument(
        "--alpaca-data-base-url",
        default=os.environ.get("ALPACA_DATA_BASE_URL", DEFAULT_ALPACA_DATA_BASE_URL),
    )
    parser.add_argument(
        "--massive-base-url",
        default=os.environ.get("MASSIVE_BASE_URL", DEFAULT_MASSIVE_BASE_URL),
    )
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
    downloader, normalizer, source, source_url = _provider_parts(args)

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
            downloader=downloader,
            normalizer=normalizer,
            source=source,
            source_url=source_url,
        )
    )
    print(json.dumps(summary.__dict__, sort_keys=True))
    return 0


def _provider_parts(args: argparse.Namespace) -> ProviderParts:
    provider = str(args.provider).lower()
    if provider == "yfinance":
        return yfinance_downloader, normalize_history, "yfinance", "https://finance.yahoo.com"
    if provider == "alpaca":
        alpaca_config = AlpacaDailyConfig.from_env(
            feed=str(args.alpaca_feed),
            adjustment=str(args.alpaca_adjustment),
            base_url=str(args.alpaca_data_base_url),
        )
        return (
            build_alpaca_downloader(alpaca_config),
            normalize_alpaca_bars,
            "alpaca",
            alpaca_config.bars_url,
        )
    if provider == "massive":
        massive_config = MassiveDailyConfig.from_env(base_url=str(args.massive_base_url))
        return (
            build_massive_downloader(massive_config),
            normalize_massive_bars,
            "massive",
            massive_config.base_url,
        )
    raise ValueError(f"unsupported market data provider: {provider}")


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
