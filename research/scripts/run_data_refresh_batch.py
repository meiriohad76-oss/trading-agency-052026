from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.batch import DATASETS, RefreshBatchConfig, run_refresh_batch  # noqa: E402
from data_refresh.live_config import RefreshConfigOverrides, load_refresh_config  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    overrides = _load_overrides(args.config)
    config = _batch_config(args, overrides)
    result = run_refresh_batch(config)
    state = _result_state(failed=result.failed, blocked=result.blocked)
    print(f"Data refresh batch {state}; wrote {config.output_root}")
    if result.failed:
        return 1
    if result.blocked and not args.dry_run:
        return 2
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local research data refresh batch.")
    parser.add_argument("--config", type=Path, help="Optional JSON config file.")
    parser.add_argument("--start", type=_date)
    parser.add_argument("--end", type=_date)
    parser.add_argument("--dataset", choices=DATASETS, action="append")
    parser.add_argument("--ticker", action="append", help="Ticker to refresh; repeatable.")
    parser.add_argument(
        "--rss-feed",
        action="append",
        help="Feed as SOURCE,URL or SOURCE,TICKER,URL.",
    )
    parser.add_argument("--filer-cik", action="append", help="13F filer CIK; repeatable.")
    parser.add_argument("--cusip-map", type=Path, help="JSON map of CUSIP to ticker for 13F rows.")
    parser.add_argument(
        "--activity-alerts-csv",
        type=Path,
        help="Local CSV of paid/confirmed alerts.",
    )
    parser.add_argument("--sec-user-agent", help="SEC-compliant User-Agent override.")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--include-etfs", action=argparse.BooleanOptionalAction)
    parser.add_argument("--refresh", action=argparse.BooleanOptionalAction)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction)
    parser.add_argument("--market-data-provider", choices=("yfinance", "alpaca"))
    parser.add_argument("--market-data-feed")
    parser.add_argument("--market-data-adjustment")
    parser.add_argument("--market-data-base-url")
    parser.add_argument("--massive-base-url")
    parser.add_argument(
        "--output-root",
        type=Path,
    )
    return parser.parse_args()


def _load_overrides(path: Path | None) -> RefreshConfigOverrides:
    if path is None:
        return RefreshConfigOverrides()
    return load_refresh_config(path, repo_root=ROOT)


def _batch_config(
    args: argparse.Namespace,
    overrides: RefreshConfigOverrides,
) -> RefreshBatchConfig:
    sec_user_agent = (
        args.sec_user_agent or overrides.sec_user_agent or os.environ.get("SEC_USER_AGENT")
    )
    if sec_user_agent:
        os.environ["SEC_USER_AGENT"] = sec_user_agent
    provider = _setting(
        args.market_data_provider,
        overrides.market_data_provider,
        os.environ.get("MARKET_DATA_PROVIDER"),
        "yfinance",
    ).lower()
    return RefreshBatchConfig(
        repo_root=ROOT,
        output_root=args.output_root or ROOT / "research" / "results" / "latest-data-refresh",
        start=args.start or overrides.start or date(2019, 1, 1),
        end=args.end or overrides.end or date.today(),
        datasets=tuple(args.dataset or overrides.datasets or DATASETS),
        tickers=tuple(args.ticker or overrides.tickers),
        rss_feeds=tuple(args.rss_feed or overrides.rss_feeds),
        filer_ciks=tuple(args.filer_cik or overrides.filer_ciks),
        cusip_map=args.cusip_map or overrides.cusip_map,
        activity_alerts_csv=args.activity_alerts_csv or overrides.activity_alerts_csv,
        sec_user_agent=sec_user_agent,
        python_executable=sys.executable,
        workers=args.workers or overrides.workers or 1,
        include_etfs=_bool_value(args.include_etfs, overrides.include_etfs, default=True),
        refresh=_bool_value(args.refresh, overrides.refresh, default=False),
        dry_run=_bool_value(args.dry_run, overrides.dry_run, default=False),
        market_data_provider=provider,
        market_data_feed=_setting(
            args.market_data_feed,
            overrides.market_data_feed,
            os.environ.get("ALPACA_DATA_FEED"),
            "iex",
        ),
        market_data_adjustment=_setting(
            args.market_data_adjustment,
            overrides.market_data_adjustment,
            os.environ.get("ALPACA_DATA_ADJUSTMENT"),
            "all",
        ),
        market_data_base_url=_setting(
            args.market_data_base_url,
            overrides.market_data_base_url,
            os.environ.get("ALPACA_DATA_BASE_URL"),
            "https://data.alpaca.markets",
        ),
        market_data_credentials_present=_alpaca_credentials_present(),
        massive_base_url=_setting(
            args.massive_base_url,
            overrides.massive_base_url,
            os.environ.get("MASSIVE_BASE_URL"),
            "https://api.polygon.io",
        ),
        massive_credentials_present=_massive_credentials_present(),
    )


def _bool_value(value: bool | None, override: bool | None, *, default: bool) -> bool:
    if value is not None:
        return value
    if override is not None:
        return override
    return default


def _setting(
    cli_value: str | None,
    config_value: str | None,
    env_value: str | None,
    default: str,
) -> str:
    for value in (cli_value, config_value, env_value):
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def _alpaca_credentials_present() -> bool:
    return bool(
        os.environ.get("ALPACA_API_KEY", "").strip()
        and os.environ.get("ALPACA_SECRET_KEY", "").strip()
    )


def _massive_credentials_present() -> bool:
    return bool(
        os.environ.get("MASSIVE_API_KEY", "").strip()
        or os.environ.get("POLYGON_API_KEY", "").strip()
    )


def _result_state(*, failed: bool, blocked: bool) -> str:
    if failed:
        return "failed"
    if blocked:
        return "blocked"
    return "ready"


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
