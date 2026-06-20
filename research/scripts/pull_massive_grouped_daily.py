from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.massive_lane_manifest import (  # noqa: E402
    manifest_path_for_lane,
    write_lane_manifest,
)
from pit.exceptions import DataNotAvailableAt  # noqa: E402
from pit.loader import PITLoader  # noqa: E402
from prices.massive_daily import (  # noqa: E402
    MassiveDailyConfig,
    build_massive_downloader,
    normalize_massive_bars,
)
from prices.massive_grouped_daily import (  # noqa: E402
    MassiveGroupedDailyConfig,
    pull_massive_grouped_daily,
)
from prices.puller import pull_prices, universe_tickers  # noqa: E402
from prices.sector_etfs import include_sector_etfs  # noqa: E402
from prices.storage import (  # noqa: E402
    DateRange,
    existing_dates_for_ticker,
    write_manifest,
    write_price_frame,
)

DAILY_BARS_LANE_ID = "massive_daily_bars"
DAILY_AGGS_FALLBACK_LOOKBACK_DAYS = 7
HISTORY_BOOTSTRAP_LOOKBACK_DAYS = 370
MIN_HISTORY_OBSERVATIONS = 40


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Pull one Massive grouped daily bar snapshot.")
    parser.add_argument("--date", type=_date, required=True)
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--include-etfs", action="store_true")
    parser.add_argument(
        "--massive-base-url",
        default=None,
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
        "--parquet-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet",
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=ROOT / "research" / "data" / "manifests",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "prices_daily.json",
    )
    parser.add_argument(
        "--lane-id",
        default=DAILY_BARS_LANE_ID,
        help="Massive raw lane that owns this grouped-daily pull.",
    )
    parser.add_argument(
        "--lane-manifest-path",
        type=Path,
        default=None,
        help="Optional explicit lane-level manifest path.",
    )
    parser.add_argument(
        "--history-lookback-days",
        type=int,
        default=HISTORY_BOOTSTRAP_LOOKBACK_DAYS,
        help=(
            "Calendar-day window to keep available for daily-bar signals. "
            "The lane bootstraps missing history only for tickers below the "
            "minimum observation threshold."
        ),
    )
    parser.add_argument(
        "--min-history-observations",
        type=int,
        default=MIN_HISTORY_OBSERVATIONS,
        help=(
            "Minimum local daily observations required before skipping the "
            "per-ticker historical bootstrap."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent per-ticker Massive aggregate downloads for history bootstrap.",
    )
    parser.add_argument(
        "--skip-history-bootstrap",
        action="store_true",
        help="Only write the latest grouped daily snapshot; intended for narrow diagnostics.",
    )
    args = parser.parse_args()
    _validate_lane_invocation(args)
    tickers = _normalize_tickers(args.tickers or _active_universe_tickers(args))
    if args.include_etfs:
        tickers = include_sector_etfs(tickers)
    config = MassiveGroupedDailyConfig.from_env(base_url=args.massive_base_url)
    fetched_at = datetime.now(UTC)
    frame = asyncio.run(
        pull_massive_grouped_daily(
            day=args.date,
            tickers=tickers,
            config=config,
            fetched_at=fetched_at,
        )
    )
    frame = asyncio.run(
        _fill_grouped_daily_missing_tickers(
            day=args.date,
            tickers=tickers,
            grouped_frame=frame,
            fetched_at=fetched_at,
            daily_downloader=build_massive_downloader(
                MassiveDailyConfig.from_env(base_url=args.massive_base_url)
            ),
        )
    )
    rows_written = write_price_frame(args.price_root, frame)
    history_summary = None
    history_issues: list[dict[str, str]] = []
    history_start = _history_start(args.date, args.history_lookback_days)
    if not args.skip_history_bootstrap:
        history_tickers = _tickers_needing_history(
            args.price_root,
            tickers,
            end=args.date,
            lookback_days=args.history_lookback_days,
            min_observations=args.min_history_observations,
        )
        if history_tickers:
            history_summary = asyncio.run(
                pull_prices(
                    tickers=history_tickers,
                    requested=DateRange(history_start, args.date),
                    price_root=args.price_root,
                    manifest_path=args.manifest_path,
                    refresh=False,
                    workers=args.workers,
                    downloader=build_massive_downloader(
                        MassiveDailyConfig.from_env(base_url=args.massive_base_url)
                    ),
                    normalizer=normalize_massive_bars,
                    source="massive",
                    source_url=config.base_url,
                    clock=lambda: fetched_at,
                )
            )
            rows_written += history_summary.rows_written
            history_issues = history_summary.issues
    coverage = _daily_lane_coverage(tickers, frame, requested_day=args.date)
    missing = [
        str(row["ticker"])
        for row in coverage
        if row.get("complete") is not True
    ]
    issues = [{"ticker": ticker, "reason": "no_daily_bar_available"} for ticker in missing]
    issues.extend(history_issues)
    coverage = _annotate_history_coverage(
        args.price_root,
        coverage,
        end=args.date,
        lookback_days=args.history_lookback_days,
        min_observations=args.min_history_observations,
    )
    insufficient_history = [
        str(row["ticker"])
        for row in coverage
        if int(row.get("history_observation_count") or 0) < args.min_history_observations
    ]
    issues.extend(
        {
            "ticker": ticker,
            "reason": "insufficient_daily_history",
            "detail": (
                f"fewer than {args.min_history_observations} daily observations are available "
                f"inside the {args.history_lookback_days}-calendar-day signal window"
            ),
        }
        for ticker in insufficient_history
        if ticker not in missing
    )
    write_manifest(
        args.manifest_path,
        args.price_root,
        fetched_at=fetched_at,
        requested=DateRange(history_start, args.date),
        issues=issues,
        source="massive",
        source_url=config.base_url,
    )
    write_lane_manifest(
        args.lane_manifest_path or manifest_path_for_lane(ROOT, args.lane_id),
        lane_id=args.lane_id,
        dataset="prices_daily",
        raw_source_dataset="prices_daily",
        fetched_at=fetched_at,
        requested_start=history_start,
        requested_end=args.date,
        tickers=tickers,
        row_count=rows_written,
        source_manifest=args.manifest_path,
        status="complete" if not issues else "partial",
        issues=issues,
        coverage=coverage,
        request_budget_label=(
            "1 grouped-daily request per market date plus per-ticker daily aggregate "
            "requests only while historical signal coverage is below threshold"
        ),
        merge_existing=True,
    )
    print(
        json.dumps(
            {
                "date": args.date.isoformat(),
                "history_start": history_start.isoformat(),
                "tickers_requested": len({ticker.upper() for ticker in tickers}),
                "rows_returned": len(frame),
                "rows_written": rows_written,
                "history_tickers_downloaded": (
                    history_summary.tickers_requested if history_summary is not None else 0
                ),
                "history_rows_written": (
                    history_summary.rows_written if history_summary is not None else 0
                ),
                "issues": issues,
            },
            sort_keys=True,
        )
    )
    return 0


async def _fill_grouped_daily_missing_tickers(
    *,
    day: date,
    tickers: Sequence[str],
    grouped_frame: pd.DataFrame,
    fetched_at: datetime,
    daily_downloader: Callable[[str, DateRange], Awaitable[pd.DataFrame]] | None = None,
) -> pd.DataFrame:
    requested = _normalize_tickers(tickers)
    if not requested:
        return grouped_frame
    returned = (
        {str(ticker).upper() for ticker in grouped_frame["ticker"]}
        if "ticker" in grouped_frame.columns
        else set()
    )
    missing = [ticker for ticker in requested if ticker not in returned]
    if not missing:
        return grouped_frame
    downloader = daily_downloader or build_massive_downloader(MassiveDailyConfig.from_env())
    requested_range = DateRange(day - timedelta(days=DAILY_AGGS_FALLBACK_LOOKBACK_DAYS), day)
    repaired: list[pd.DataFrame] = []
    for ticker in missing:
        raw = await downloader(ticker, requested_range)
        normalized = normalize_massive_bars(ticker, raw, fetched_at=fetched_at)
        if not normalized.empty:
            repaired.append(normalized)
    if not repaired:
        return grouped_frame
    frames = [grouped_frame, *repaired] if not grouped_frame.empty else repaired
    return pd.concat(frames, ignore_index=True)


def _daily_lane_coverage(
    tickers: Sequence[str],
    frame: pd.DataFrame,
    *,
    requested_day: date,
) -> list[dict[str, object]]:
    requested = _normalize_tickers(tickers)
    available_dates: dict[str, set[date]] = {ticker: set() for ticker in requested}
    if not frame.empty and {"ticker", "date"}.issubset(frame.columns):
        rows = frame[["ticker", "date"]].copy()
        rows["ticker"] = rows["ticker"].astype(str).str.upper()
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce").dt.date
        for ticker, group in rows.dropna(subset=["date"]).groupby("ticker"):
            if ticker in available_dates:
                available_dates[ticker].update(group["date"].tolist())
    coverage: list[dict[str, object]] = []
    for ticker in requested:
        dates = available_dates[ticker]
        if requested_day in dates:
            coverage.append(
                {
                    "ticker": ticker,
                    "coverage_status": "complete",
                    "complete": True,
                    "bar_date": requested_day.isoformat(),
                    "requested_date": requested_day.isoformat(),
                }
            )
        elif dates:
            latest = max(dates)
            coverage.append(
                {
                    "ticker": ticker,
                    "coverage_status": "latest_available",
                    "complete": True,
                    "bar_date": latest.isoformat(),
                    "requested_date": requested_day.isoformat(),
                    "detail": (
                        "Grouped daily omitted the requested date; per-ticker daily "
                        "aggs supplied the latest available prior bar."
                    ),
                }
            )
        else:
            coverage.append(
                {
                    "ticker": ticker,
                    "coverage_status": "missing",
                    "complete": False,
                    "requested_date": requested_day.isoformat(),
                }
            )
    return coverage


def _tickers_needing_history(
    price_root: Path,
    tickers: Sequence[str],
    *,
    end: date,
    lookback_days: int,
    min_observations: int,
) -> list[str]:
    if lookback_days < 1:
        raise ValueError("history-lookback-days must be >= 1")
    if min_observations < 1:
        raise ValueError("min-history-observations must be >= 1")
    start = _history_start(end, lookback_days)
    needed: list[str] = []
    for ticker in _normalize_tickers(tickers):
        count = _history_observation_count(price_root, ticker, start=start, end=end)
        if count < min_observations:
            needed.append(ticker)
    return needed


def _annotate_history_coverage(
    price_root: Path,
    coverage: list[dict[str, object]],
    *,
    end: date,
    lookback_days: int,
    min_observations: int,
) -> list[dict[str, object]]:
    start = _history_start(end, lookback_days)
    output: list[dict[str, object]] = []
    for row in coverage:
        current = dict(row)
        ticker = str(current.get("ticker") or "").upper()
        count = _history_observation_count(price_root, ticker, start=start, end=end)
        current["history_window_start"] = start.isoformat()
        current["history_window_end"] = end.isoformat()
        current["history_observation_count"] = count
        current["history_required_observation_count"] = min_observations
        current["history_complete"] = count >= min_observations
        output.append(current)
    return output


def _history_observation_count(
    price_root: Path,
    ticker: str,
    *,
    start: date,
    end: date,
) -> int:
    dates = existing_dates_for_ticker(price_root, ticker)
    return sum(1 for observed in dates if start <= observed <= end)


def _history_start(end: date, lookback_days: int) -> date:
    return end - timedelta(days=max(lookback_days, 1) - 1)


def _normalize_tickers(tickers: Sequence[str]) -> list[str]:
    return sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _validate_lane_invocation(args: argparse.Namespace) -> None:
    if str(args.lane_id or "") != DAILY_BARS_LANE_ID:
        raise SystemExit(
            "pull_massive_grouped_daily.py may only write the "
            "massive_daily_bars lane manifest."
        )
    if not args.tickers:
        raise SystemExit(
            "Explicit --tickers values are required. The scheduler work queue / "
            "Massive Lane Orchestrator must control daily-bar lane scope."
        )


def _active_universe_tickers(args: argparse.Namespace) -> list[str]:
    loader = PITLoader(
        parquet_root=args.parquet_root,
        manifest_root=args.manifest_root,
        today=date.today,
    )
    try:
        return sorted(loader.universe_members(args.date))
    except DataNotAvailableAt:
        return universe_tickers(args.universe_path)


if __name__ == "__main__":
    raise SystemExit(main())
