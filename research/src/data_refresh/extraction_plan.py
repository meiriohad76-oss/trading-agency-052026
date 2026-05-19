from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd
from data_refresh.market_calendar import classify_market_session
from data_refresh.types import ExtractionAction, RefreshBatchConfig
from market_flow.storage import coverage_key, load_stock_trade_coverage_metadata

TICKER_DATASETS = {"prices_daily", "sec_company_facts", "sec_form4", "stock_trades"}
SPARSE_EVENT_TICKER_DATASETS = {"sec_form4"}
ACTIVE_STOCK_TRADES_PHASES = {"pre_market", "regular_market", "after_hours"}
STOCK_TRADES_ACTIVE_STALE_MINUTES = 5


@dataclass(frozen=True)
class ExtractionDecision:
    dataset: str
    action: ExtractionAction
    reason: str
    tickers: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None
    refresh: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "action": self.action,
            "reason": self.reason,
            "tickers": list(self.tickers),
            "ticker_count": len(self.tickers),
            "start": None if self.start is None else self.start.isoformat(),
            "end": None if self.end is None else self.end.isoformat(),
            "refresh": self.refresh,
        }


def build_extraction_plan(
    config: RefreshBatchConfig,
    *,
    now: datetime | None = None,
) -> tuple[ExtractionDecision, ...]:
    return tuple(
        extraction_decision_for_dataset(config, dataset, now=now)
        for dataset in config.datasets
    )


def extraction_decision_for_dataset(
    config: RefreshBatchConfig,
    dataset: str,
    *,
    now: datetime | None = None,
) -> ExtractionDecision:
    current = now or datetime.now(UTC)
    if config.refresh or config.extraction_mode == "force":
        return _force(dataset, config)
    if config.extraction_mode == "baseline":
        return _baseline_or_skip(config, dataset)

    handlers = {
        "prices_daily": lambda: _prices_decision(config, current),
        "stock_trades": lambda: _stock_trades_decision(config, current),
        "sec_company_facts": lambda: _age_gated_ticker_decision(
            config,
            dataset,
            current,
            max_age=timedelta(days=config.sec_company_facts_max_age_days),
            refresh=True,
        ),
        "sec_form4": lambda: _form4_decision(config, current),
        "sec_13f": lambda: _age_gated_dataset_decision(
            config,
            dataset,
            current,
            max_age=timedelta(days=config.sec_13f_max_age_days),
        ),
        "news_rss": lambda: _age_gated_dataset_decision(
            config,
            dataset,
            current,
            max_age=timedelta(minutes=config.news_rss_max_age_minutes),
        ),
        "subscription_emails": lambda: _age_gated_dataset_decision(
            config,
            dataset,
            current,
            max_age=timedelta(minutes=config.subscription_email_max_age_minutes),
        ),
    }
    return handlers.get(dataset, lambda: _baseline_or_skip(config, dataset))()


def _prices_decision(config: RefreshBatchConfig, now: datetime) -> ExtractionDecision:
    baseline = _baseline_gap(config, "prices_daily")
    if baseline is not None:
        return baseline
    manifest_end = _manifest_date_range_end(config, "prices_daily")
    if manifest_end is not None and manifest_end >= config.end:
        return _skip("prices_daily", "daily price manifest covers the requested window", now)
    tickers, start = _missing_date_updates(
        config,
        "prices_daily",
        "date",
        config.start,
        config.end,
    )
    if tickers:
        return _incremental("prices_daily", tickers, start, config.end)
    return _skip("prices_daily", "daily price baseline already covers the requested window", now)


def _stock_trades_decision(config: RefreshBatchConfig, now: datetime) -> ExtractionDecision:
    baseline = _baseline_gap(config, "stock_trades")
    start = config.stock_trades_start or config.stock_trades_end or config.end
    end = config.stock_trades_end or config.stock_trades_start or config.end
    if baseline is not None:
        return ExtractionDecision(
            "stock_trades",
            "baseline",
            baseline.reason,
            tickers=baseline.tickers,
            start=start,
            end=end,
        )
    session = classify_market_session(now)
    missing_or_failed, partial = _stock_trade_ticker_gap_sets(config, start, end)
    manifest_end = _manifest_date_range_end(config, "stock_trades")
    if manifest_end is None or manifest_end < end:
        update_start = max(start, (manifest_end + timedelta(days=1)) if manifest_end else start)
        return _incremental("stock_trades", _requested_tickers(config), update_start, end)
    if missing_or_failed:
        return ExtractionDecision(
            "stock_trades",
            "incremental",
            f"Massive trade coverage is missing or failed for {len(missing_or_failed)} ticker(s)",
            tickers=missing_or_failed,
            start=start,
            end=end,
        )
    if (
        session.phase in ACTIVE_STOCK_TRADES_PHASES
        and session.market_date >= start
        and session.market_date <= end
        and _stock_trades_is_stale(config, now)
    ):
        tickers = _requested_tickers(config)
        return ExtractionDecision(
            "stock_trades",
            "incremental",
            (
                "current trading-day trade prints need an intraday freshness update; "
                "partial full-depth slices are included for repair"
                if partial
                else "current trading-day trade prints need an intraday freshness update"
            ),
            tickers=tickers,
            start=session.market_date,
            end=session.market_date,
        )
    if partial:
        return ExtractionDecision(
            "stock_trades",
            "incremental",
            f"Massive trade coverage has partial full-depth slices for {len(partial)} ticker(s)",
            tickers=partial,
            start=start,
            end=end,
        )
    return _skip("stock_trades", "Massive trade manifest covers the requested window", now)


def _stock_trades_is_stale(config: RefreshBatchConfig, now: datetime) -> bool:
    max_as_of = _parse_datetime(_manifest(config, "stock_trades").get("max_timestamp_as_of"))
    if max_as_of is None:
        return True
    return now - max_as_of > timedelta(minutes=STOCK_TRADES_ACTIVE_STALE_MINUTES)


def _form4_decision(config: RefreshBatchConfig, now: datetime) -> ExtractionDecision:
    baseline = _baseline_gap(config, "sec_form4")
    if baseline is not None:
        return baseline
    max_date = _max_dataset_date(config, "sec_form4", "filing_date")
    if max_date is not None and max_date < config.end:
        return _incremental(
            "sec_form4",
            _requested_tickers(config),
            max_date + timedelta(days=1),
            config.end,
        )
    age = _manifest_age(config, "sec_form4", now)
    if age is not None and age > timedelta(days=config.sec_form4_max_age_days):
        start = max(config.start, (max_date or config.end) - timedelta(days=7))
        return _incremental("sec_form4", _requested_tickers(config), start, config.end)
    return _skip("sec_form4", "Form 4 baseline is fresh enough; no newer filing window is due", now)


def _age_gated_ticker_decision(
    config: RefreshBatchConfig,
    dataset: str,
    now: datetime,
    *,
    max_age: timedelta,
    refresh: bool,
) -> ExtractionDecision:
    baseline = _baseline_gap(config, dataset)
    if baseline is not None:
        return baseline
    age = _manifest_age(config, dataset, now)
    if age is not None and age <= max_age:
        return _skip(
            dataset,
            f"{dataset} baseline is within the {max_age.days}d freshness window",
            now,
        )
    return ExtractionDecision(
        dataset,
        "incremental",
        f"{dataset} freshness window expired; re-check the configured universe",
        tickers=_requested_tickers(config),
        start=config.start,
        end=config.end,
        refresh=refresh,
    )


def _age_gated_dataset_decision(
    config: RefreshBatchConfig,
    dataset: str,
    now: datetime,
    *,
    max_age: timedelta,
) -> ExtractionDecision:
    baseline = _baseline_gap(config, dataset)
    if baseline is not None:
        return baseline
    age = _manifest_age(config, dataset, now)
    if age is not None and age <= max_age:
        return _skip(
            dataset,
            f"{dataset} was checked recently; skip until its freshness window expires",
            now,
        )
    if dataset in {"news_rss", "subscription_emails"}:
        return ExtractionDecision(
            dataset,
            "incremental",
            f"{dataset} freshness window expired; poll for new source items",
        )
    start = _manifest_max_date(config, dataset)
    update_start = min(start + timedelta(days=1), config.end) if start else config.start
    return _incremental(dataset, (), update_start, config.end)


def _baseline_or_skip(config: RefreshBatchConfig, dataset: str) -> ExtractionDecision:
    baseline = _baseline_gap(config, dataset)
    if baseline is not None:
        return baseline
    return ExtractionDecision(dataset, "skip", f"{dataset} baseline is already present")


def _baseline_gap(config: RefreshBatchConfig, dataset: str) -> ExtractionDecision | None:
    manifest = _manifest(config, dataset)
    tickers = _requested_tickers(config)
    if not manifest or (
        dataset not in SPARSE_EVENT_TICKER_DATASETS
        and int(manifest.get("row_count") or 0) <= 0
    ):
        return ExtractionDecision(
            dataset,
            "baseline",
            f"{dataset} has no local baseline",
            tickers=tickers if dataset in TICKER_DATASETS else (),
            start=config.start if dataset in TICKER_DATASETS else None,
            end=config.end if dataset in TICKER_DATASETS else None,
        )
    if (
        dataset in TICKER_DATASETS
        and dataset not in SPARSE_EVENT_TICKER_DATASETS
        and tickers
    ):
        covered = _covered_tickers(config, dataset, manifest)
        missing = tuple(ticker for ticker in tickers if ticker not in covered)
        if missing:
            return ExtractionDecision(
                dataset,
                "baseline",
                f"{dataset} is missing baseline coverage for {len(missing)} ticker(s)",
                tickers=missing,
                start=config.start,
                end=config.end,
            )
    return None


def _force(dataset: str, config: RefreshBatchConfig) -> ExtractionDecision:
    start = config.start
    end = config.end
    if dataset == "stock_trades":
        start = config.stock_trades_start or config.stock_trades_end or config.end
        end = config.stock_trades_end or config.stock_trades_start or config.end
    return ExtractionDecision(
        dataset,
        "force",
        "forced refresh requested",
        tickers=tuple(ticker.upper() for ticker in config.tickers),
        start=start,
        end=end,
        refresh=True,
    )


def _incremental(
    dataset: str,
    tickers: tuple[str, ...],
    start: date,
    end: date,
) -> ExtractionDecision:
    return ExtractionDecision(
        dataset,
        "incremental",
        "only missing or stale update range should be fetched",
        tickers=tickers,
        start=start,
        end=end,
    )


def _skip(dataset: str, reason: str, _now: datetime | None = None) -> ExtractionDecision:
    return ExtractionDecision(dataset, "skip", reason)


def _missing_date_updates(
    config: RefreshBatchConfig,
    dataset: str,
    column: str,
    start: date,
    end: date,
) -> tuple[tuple[str, ...], date]:
    tickers = _requested_tickers(config)
    if not tickers:
        manifest_end = _manifest_date_range_end(config, dataset)
        if manifest_end is None or manifest_end < end:
            return (), max(start, (manifest_end + timedelta(days=1)) if manifest_end else start)
        return (), start
    missing: list[str] = []
    starts: list[date] = []
    for ticker in tickers:
        bounds = _ticker_date_bounds(config, dataset, ticker, column)
        if bounds is None:
            missing.append(ticker)
            starts.append(start)
            continue
        _, existing_end = bounds
        if existing_end < end:
            missing.append(ticker)
            starts.append(existing_end + timedelta(days=1))
    return tuple(missing), min(starts) if starts else start


def _requested_tickers(config: RefreshBatchConfig) -> tuple[str, ...]:
    if config.tickers:
        return tuple(dict.fromkeys(ticker.upper() for ticker in config.tickers))
    path = config.repo_root / "research" / "data" / "parquet" / "universe_membership.parquet"
    if not path.is_file():
        return ()
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return ()
    if "ticker" not in frame.columns:
        return ()
    if {"start_date", "end_date"}.issubset(frame.columns):
        as_of = pd.Timestamp(config.end)
        start = pd.to_datetime(frame["start_date"], errors="coerce")
        end = pd.to_datetime(frame["end_date"], errors="coerce")
        active = (start.isna() | (start <= as_of)) & (end.isna() | (end > as_of))
        frame = frame[active]
    return tuple(sorted({str(ticker).upper() for ticker in frame["ticker"].dropna().unique()}))


def _manifest(config: RefreshBatchConfig, dataset: str) -> Mapping[str, Any]:
    path = config.repo_root / "research" / "data" / "manifests" / f"{dataset}.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _covered_tickers(
    config: RefreshBatchConfig,
    dataset: str,
    manifest: Mapping[str, Any],
) -> set[str]:
    value = manifest.get("tickers")
    if isinstance(value, list) and value:
        return {str(ticker).upper() for ticker in value if str(ticker).strip()}
    root = config.repo_root / "research" / "data" / "parquet" / dataset
    if not root.exists():
        return set()
    partition_tickers = _covered_partition_tickers(root)
    if partition_tickers:
        return partition_tickers
    tickers: set[str] = set()
    for path in sorted(root.rglob("*.parquet")):
        try:
            frame = pd.read_parquet(path, columns=["ticker"])
        except Exception:
            continue
        tickers.update(str(ticker).upper() for ticker in frame["ticker"].dropna().unique())
    return tickers


def _covered_partition_tickers(root: Path) -> set[str]:
    tickers: set[str] = set()
    for path in root.glob("ticker=*"):
        if not path.is_dir():
            continue
        ticker = path.name.partition("=")[2].strip().upper()
        if ticker:
            tickers.add(ticker)
    return tickers


def _incomplete_stock_trade_tickers(
    config: RefreshBatchConfig,
    start: date,
    end: date,
) -> tuple[str, ...]:
    missing_or_failed, partial = _stock_trade_ticker_gap_sets(config, start, end)
    return (*missing_or_failed, *partial)


def _stock_trade_ticker_gap_sets(
    config: RefreshBatchConfig,
    start: date,
    end: date,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tickers = _requested_tickers(config)
    if not tickers:
        return (), ()
    coverage = load_stock_trade_coverage_metadata(
        config.repo_root / "research" / "data" / "parquet" / "stock_trades"
    )
    trading_days = _trading_dates(start, end)
    if not coverage:
        return (tickers if trading_days else ()), ()
    missing_or_failed: list[str] = []
    partial: list[str] = []
    for ticker in tickers:
        statuses = [
            str(coverage.get(coverage_key(ticker, day), {}).get("coverage_status") or "missing")
            for day in trading_days
        ]
        if not statuses:
            continue
        if any(status in {"missing", "failed"} for status in statuses):
            missing_or_failed.append(ticker)
        elif any(status != "complete" for status in statuses):
            partial.append(ticker)
    return tuple(missing_or_failed), tuple(partial)


def _trading_dates(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _ticker_date_bounds(
    config: RefreshBatchConfig,
    dataset: str,
    ticker: str,
    column: str,
) -> tuple[date, date] | None:
    root = config.repo_root / "research" / "data" / "parquet" / dataset / f"ticker={ticker}"
    return _date_bounds(sorted(root.rglob("*.parquet")), column)


def _max_dataset_date(config: RefreshBatchConfig, dataset: str, column: str) -> date | None:
    root = config.repo_root / "research" / "data" / "parquet" / dataset
    if not root.exists():
        return None
    return _max_date_from_paths(sorted(root.rglob("*.parquet")), column)


def _date_bounds(paths: list[Path], column: str) -> tuple[date, date] | None:
    combined = _combined_dates(paths, column)
    if combined is None:
        return None
    return combined.min(), combined.max()


def _max_date_from_paths(paths: list[Path], column: str) -> date | None:
    combined = _combined_dates(paths, column)
    return None if combined is None else combined.max()


def _combined_dates(paths: list[Path], column: str) -> pd.Series | None:
    dates: list[pd.Series] = []
    for path in paths:
        try:
            frame = pd.read_parquet(path, columns=[column])
        except Exception:
            continue
        if not frame.empty:
            dates.append(pd.to_datetime(frame[column], errors="coerce").dropna().dt.date)
    if not dates:
        return None
    return cast(pd.Series, pd.concat(dates, ignore_index=True))


def _manifest_age(
    config: RefreshBatchConfig,
    dataset: str,
    now: datetime,
) -> timedelta | None:
    fetched_at = _parse_datetime(_manifest(config, dataset).get("fetched_at"))
    if fetched_at is None:
        return None
    return now - fetched_at


def _manifest_max_date(config: RefreshBatchConfig, dataset: str) -> date | None:
    parsed = _parse_datetime(_manifest(config, dataset).get("max_timestamp_as_of"))
    return None if parsed is None else parsed.date()


def _manifest_date_range_end(config: RefreshBatchConfig, dataset: str) -> date | None:
    value = _manifest(config, dataset).get("date_range")
    if not isinstance(value, Mapping):
        return None
    end = value.get("end")
    return date.fromisoformat(str(end)) if end else None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or value.strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
