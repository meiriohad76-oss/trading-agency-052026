from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.batch import DATASETS, RefreshBatchConfig, run_refresh_batch  # noqa: E402
from data_refresh.live_config import RefreshConfigOverrides, load_refresh_config  # noqa: E402
from data_refresh.market_batching import build_market_aware_batch_plan  # noqa: E402
from data_refresh.types import ExtractionMode, StockTradesOrder  # noqa: E402

LANE_MODEL_DATASET_MESSAGE = (
    "Market-aware planning produced only Massive lane-owned raw endpoint(s). "
    "Run them through the scheduler work queue / Massive Lane Orchestrator so "
    "lane budgets, manifests, freshness SLAs, and dashboard progress stay authoritative."
)


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    overrides = _load_overrides(args.config)
    config = _batch_config(args, overrides)
    if args.market_aware:
        config = _market_aware_config(config, config_path=args.config, now_text=args.now)
        if not config.datasets:
            print(f"Data refresh batch blocked; {LANE_MODEL_DATASET_MESSAGE}")
            return 2
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
    parser.add_argument(
        "--subscription-email-config",
        type=Path,
        help="Local config for paid subscription email agents.",
    )
    parser.add_argument("--sec-user-agent", help="SEC-compliant User-Agent override.")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--include-etfs", action=argparse.BooleanOptionalAction)
    parser.add_argument("--refresh", action=argparse.BooleanOptionalAction)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction)
    parser.add_argument("--market-data-provider", choices=("yfinance", "alpaca", "massive"))
    parser.add_argument("--market-data-feed")
    parser.add_argument("--market-data-adjustment")
    parser.add_argument("--market-data-base-url")
    parser.add_argument("--massive-base-url")
    parser.add_argument("--stock-trades-start", type=_date)
    parser.add_argument("--stock-trades-end", type=_date)
    parser.add_argument("--stock-trades-limit", type=int)
    parser.add_argument("--stock-trades-max-pages-per-day", type=int)
    parser.add_argument("--stock-trades-order", choices=("asc", "desc"))
    parser.add_argument("--extraction-mode", choices=("auto", "baseline", "incremental", "force"))
    parser.add_argument(
        "--market-aware",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run only the datasets appropriate for the current market phase.",
    )
    parser.add_argument("--now", help="ISO datetime override for market-aware planning.")
    parser.add_argument("--sec-company-facts-max-age-days", type=int)
    parser.add_argument("--sec-form4-max-age-days", type=int)
    parser.add_argument("--sec-13f-max-age-days", type=int)
    parser.add_argument("--news-rss-max-age-minutes", type=int)
    parser.add_argument("--subscription-email-max-age-minutes", type=int)
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
        subscription_email_config=(
            args.subscription_email_config or overrides.subscription_email_config
        ),
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
        stock_trades_start=args.stock_trades_start or overrides.stock_trades_start,
        stock_trades_end=args.stock_trades_end or overrides.stock_trades_end,
        stock_trades_limit=_int_setting(
            args.stock_trades_limit,
            overrides.stock_trades_limit,
            50_000,
        ),
        stock_trades_max_pages_per_day=_optional_limit_setting(
            args.stock_trades_max_pages_per_day,
            overrides.stock_trades_max_pages_per_day,
        ),
        stock_trades_order=cast(
            StockTradesOrder,
            _setting(
                args.stock_trades_order,
                overrides.stock_trades_order,
                os.environ.get("MASSIVE_STOCK_TRADES_ORDER"),
                "asc",
            ),
        ),
        extraction_mode=cast(
            ExtractionMode,
            _setting(
                args.extraction_mode,
                overrides.extraction_mode,
                os.environ.get("DATA_REFRESH_EXTRACTION_MODE"),
                "auto",
            ),
        ),
        sec_company_facts_max_age_days=_int_setting(
            args.sec_company_facts_max_age_days,
            overrides.sec_company_facts_max_age_days,
            7,
        ),
        sec_form4_max_age_days=_int_setting(
            args.sec_form4_max_age_days,
            overrides.sec_form4_max_age_days,
            1,
        ),
        sec_13f_max_age_days=_int_setting(
            args.sec_13f_max_age_days,
            overrides.sec_13f_max_age_days,
            45,
        ),
        news_rss_max_age_minutes=_int_setting(
            args.news_rss_max_age_minutes,
            overrides.news_rss_max_age_minutes,
            30,
        ),
        subscription_email_max_age_minutes=_int_setting(
            args.subscription_email_max_age_minutes,
            overrides.subscription_email_max_age_minutes,
            10,
        ),
    )


def _market_aware_config(
    config: RefreshBatchConfig,
    *,
    config_path: Path | None,
    now_text: str | None,
) -> RefreshBatchConfig:
    now = _parse_datetime(now_text) if now_text else datetime.now(UTC)
    plan = build_market_aware_batch_plan(
        config,
        lanes=_runtime_lanes(config_path),
        now=now,
    )
    dataset_rows = _mapping_rows(plan.get("datasets"))
    rows = [
        row
        for row in dataset_rows
        if row.get("batch_action") == "run_now"
    ]
    rows = _generic_batch_rows(rows, plan=plan)
    if not rows:
        rows = _generic_batch_rows(
            [
                row
                for row in dataset_rows
                if row.get("batch_action") == "skip"
                or row.get("extraction_action") == "skip"
            ],
            plan=plan,
        )
    stock_row = _dataset_row(rows, "stock_trades")
    ticker_row = stock_row or (rows[0] if len(rows) == 1 else {})
    max_tickers = _market_aware_max_tickers(ticker_row)
    tickers = _market_aware_tickers(ticker_row, config, max_tickers=max_tickers)
    return replace(
        config,
        datasets=tuple(str(row["dataset"]) for row in rows if isinstance(row.get("dataset"), str)),
        tickers=tickers,
        stock_trades_start=_optional_date_text(stock_row.get("start"))
        or config.stock_trades_start,
        stock_trades_end=_optional_date_text(stock_row.get("end")) or config.stock_trades_end,
    )


def _generic_batch_rows(
    rows: list[dict[str, object]],
    *,
    plan: dict[str, object],
) -> list[dict[str, object]]:
    lane_owned = _lane_owned_raw_datasets(plan)
    return [
        row
        for row in rows
        if str(row.get("dataset") or "") not in lane_owned
    ]


def _lane_owned_raw_datasets(plan: dict[str, object]) -> set[str]:
    massive = plan.get("massive_orchestrator")
    if not isinstance(massive, dict):
        return set()
    owned: set[str] = set()
    for row in _mapping_rows(massive.get("lanes")):
        if row.get("creates_massive_request") is not True:
            continue
        action = str(row.get("batch_action") or "")
        if action in {"disabled"}:
            continue
        dataset = str(row.get("raw_source_dataset") or row.get("dataset") or "")
        if dataset:
            owned.add(dataset)
    return owned


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


def _int_setting(cli_value: int | None, config_value: int | None, default: int) -> int:
    for value in (cli_value, config_value):
        if value is not None:
            return value
    return default


def _optional_limit_setting(cli_value: int | None, config_value: int | None) -> int | None:
    for value in (cli_value, config_value):
        if value is not None:
            return None if value < 1 else value
    return None


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


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed.astimezone(UTC)


def _runtime_lanes(config_path: Path | None) -> tuple[str, ...]:
    if config_path is None or not config_path.is_file():
        return ()
    try:
        payload = load_refresh_config(config_path, repo_root=ROOT)
    except (OSError, ValueError, TypeError):
        return ()
    return payload.runtime_signals


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _dataset_row(
    rows: list[dict[str, object]],
    dataset: str,
) -> dict[str, object]:
    for row in rows:
        if row.get("dataset") == dataset:
            return row
    return {}


def _market_aware_tickers(
    row: dict[str, object],
    config: RefreshBatchConfig,
    *,
    max_tickers: int | None,
) -> tuple[str, ...]:
    if not row:
        return config.tickers
    values = row.get("tickers")
    if not isinstance(values, list):
        return config.tickers
    tickers = sorted({str(value).upper().strip() for value in values if str(value).strip()})
    if max_tickers is not None and max_tickers > 0:
        tickers = tickers[:max_tickers]
    return tuple(tickers) or config.tickers


def _market_aware_max_tickers(row: dict[str, object]) -> int | None:
    if not row:
        return None
    value = row.get("max_tickers_per_batch")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _optional_date_text(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
