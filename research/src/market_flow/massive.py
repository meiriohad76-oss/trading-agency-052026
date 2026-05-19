from __future__ import annotations

import asyncio
import os
import re
import ssl
import sys
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Self, cast
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from data_refresh.market_calendar import is_trading_day
from providers.massive_limits import MassiveApiLimiter

from agency.provenance import SourceTier, VerificationLevel

from .classification import classify_trades
from .storage import (
    DateRange,
    coverage_key,
    load_stock_trade_coverage_metadata,
    update_stock_trade_coverage_metadata,
    write_manifest,
    write_stock_trade_frame,
)

DEFAULT_MASSIVE_BASE_URL = "https://api.polygon.io"
TRADES_PATH_TEMPLATE = "/v3/trades/{ticker}"
DELAYED_DATA_LAG = timedelta(minutes=15)
MARKET_TIMEZONE = ZoneInfo("America/New_York")
NANOSECOND_TIMESTAMP_DIGITS = 18
MICROSECOND_TIMESTAMP_DIGITS = 15
MILLISECOND_TIMESTAMP_DIGITS = 12
TimestampUnit = Literal["s", "ms", "us", "ns"]
TradeOrder = Literal["asc", "desc"]
TradeSession = Literal["full_day", "pre_market"]
ProgressCallback = Callable[[Mapping[str, object]], None]
PageWriter = Callable[[str, date, Sequence[Mapping[str, object]]], int]
CoverageWriter = Callable[[Mapping[str, object]], None]
SECRET_QUERY_RE = re.compile(r"(?i)(apiKey|apikey|api_key)=([^&\s'\"\]]+)")


@dataclass(frozen=True)
class MassiveTradesConfig:
    api_key: str
    base_url: str = DEFAULT_MASSIVE_BASE_URL
    limit: int = 50_000
    max_pages_per_day: int | None = None
    max_seconds_per_day: float | None = None
    order: TradeOrder = "asc"
    window_minutes: int | None = None
    trade_session: TradeSession = "full_day"
    resume_partial: bool = True
    timeout_seconds: float = 30.0
    request_retries: int = 2

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        limit: int = 50_000,
        max_pages_per_day: int | None = None,
        max_seconds_per_day: float | None = None,
        order: TradeOrder | None = None,
        window_minutes: int | None = None,
        trade_session: TradeSession | str | None = None,
        resume_partial: bool = True,
    ) -> Self:
        api_key = os.environ.get("MASSIVE_API_KEY", "").strip() or os.environ.get(
            "POLYGON_API_KEY",
            "",
        ).strip()
        if not api_key:
            raise ValueError("MASSIVE_API_KEY or POLYGON_API_KEY must be set")
        return cls(
            api_key=api_key,
            base_url=base_url or os.environ.get("MASSIVE_BASE_URL") or DEFAULT_MASSIVE_BASE_URL,
            limit=limit,
            max_pages_per_day=max_pages_per_day,
            max_seconds_per_day=max_seconds_per_day,
            order=order or _trade_order_from_env(),
            window_minutes=_positive_int(window_minutes),
            trade_session=_trade_session(trade_session),
            resume_partial=resume_partial,
        )

    def trades_url(self, ticker: str) -> str:
        return f"{self.base_url.rstrip('/')}{TRADES_PATH_TEMPLATE.format(ticker=ticker.upper())}"


@dataclass(frozen=True)
class MassiveTradesSummary:
    tickers_requested: int
    rows_written: int
    issues: list[dict[str, str]]
    coverage: list[dict[str, object]]


@dataclass(frozen=True)
class DownloadedTradeDay:
    ticker: str
    trade_date: date
    rows: list[Mapping[str, object]]
    pages_downloaded: int
    complete: bool
    downloaded_row_count: int = 0
    rows_written: int = 0
    last_page_results_count: int = 0
    row_count_verified: bool = False
    stop_reason: str | None = None
    resume_cursor: str | None = None
    coverage_extra: Mapping[str, object] | None = None


async def pull_massive_trades(
    *,
    tickers: Sequence[str],
    requested: DateRange,
    trade_root: Path,
    manifest_path: Path,
    config: MassiveTradesConfig,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
    limiter: MassiveApiLimiter | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MassiveTradesSummary:
    fetched_at = _utc_now(clock)
    issues: list[dict[str, str]] = []
    coverage: list[dict[str, object]] = []
    rows_written = 0
    manifest_rows_accounted = False
    quota = limiter or MassiveApiLimiter.from_env(disabled=transport is not None)

    def persist_page(
        ticker: str,
        trade_date: date,
        page_rows: Sequence[Mapping[str, object]],
    ) -> int:
        if not page_rows:
            return 0
        normalized = normalize_massive_trades(
            ticker,
            pd.DataFrame(page_rows),
            fetched_at=fetched_at,
            source_url=config.trades_url(ticker),
        )
        if normalized.empty:
            return 0
        written = write_stock_trade_frame(trade_root, normalized)
        if written > 0:
            write_manifest(
                manifest_path,
                trade_root,
                fetched_at=fetched_at,
                requested=DateRange(trade_date, trade_date),
                issues=[],
                source_url=config.base_url,
                rows_written_delta=written,
                touched_tickers=(ticker.upper(),),
                incremental=True,
            )
        return written

    def persist_partial_coverage(row: Mapping[str, object]) -> None:
        update_stock_trade_coverage_metadata(trade_root, [row])

    async with httpx.AsyncClient(
        timeout=config.timeout_seconds,
        transport=transport,
        verify=_verify_context(),
    ) as client:
        for ticker in sorted({item.upper() for item in tickers}):
            try:
                raw, ticker_coverage, ticker_rows_written = await _download_ticker(
                    client,
                    ticker,
                    requested,
                    config,
                    quota,
                    progress_callback=progress_callback,
                    page_writer=persist_page,
                    coverage_writer=persist_partial_coverage,
                    coverage_metadata=load_stock_trade_coverage_metadata(trade_root),
                    retain_rows=False,
                )
                rows_written += ticker_rows_written
                manifest_rows_accounted = manifest_rows_accounted or ticker_rows_written > 0
            except Exception as exc:
                reason = redact_sensitive_text(str(exc))
                issues.append({"ticker": ticker, "reason": reason})
                _emit_failed_ticker_progress(
                    progress_callback,
                    ticker=ticker,
                    requested=requested,
                    reason=reason,
                )
                continue
            if not raw.empty:
                normalized = normalize_massive_trades(
                    ticker,
                    raw,
                    fetched_at=fetched_at,
                    source_url=config.trades_url(ticker),
                )
                if not normalized.empty:
                    rows_written += write_stock_trade_frame(trade_root, normalized)
            coverage.extend(ticker_coverage)
            update_stock_trade_coverage_metadata(trade_root, ticker_coverage)
            _emit_durable_coverage_progress(progress_callback, ticker_coverage)
    write_manifest(
        manifest_path,
        trade_root,
        fetched_at=fetched_at,
        requested=requested,
        issues=issues,
        source_url=config.base_url,
        rows_written_delta=0 if manifest_rows_accounted else rows_written,
        touched_tickers=tuple(str(row.get("ticker", "")).upper() for row in coverage),
        incremental=True,
    )
    return MassiveTradesSummary(len(set(tickers)), rows_written, issues, coverage)


def _emit_failed_ticker_progress(
    callback: ProgressCallback | None,
    *,
    ticker: str,
    requested: DateRange,
    reason: str,
) -> None:
    if callback is None:
        return
    current = requested.start
    while current <= requested.end:
        if not is_trading_day(current):
            current += timedelta(days=1)
            continue
        callback(
            {
                "schema_version": "0.1.0",
                "ticker": ticker.upper(),
                "trade_date": current.isoformat(),
                "pages_downloaded": 0,
                "rows_downloaded": 0,
                "complete": False,
                "status": "failed",
                "reason": reason[:240],
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        current += timedelta(days=1)


def _emit_durable_coverage_progress(
    callback: ProgressCallback | None,
    coverage: Sequence[Mapping[str, object]],
) -> None:
    if callback is None:
        return
    for row in coverage:
        status = str(row.get("coverage_status") or row.get("status") or "").lower()
        callback(
            {
                "schema_version": "0.1.0",
                "ticker": str(row.get("ticker", "")).upper(),
                "trade_date": row.get("trade_date"),
                "pages_downloaded": row.get("pages_downloaded", 0),
                "rows_downloaded": row.get("downloaded_row_count", 0),
                "complete": row.get("complete") is True,
                "status": status if status in {"complete", "partial", "failed"} else "partial",
                "durable": True,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )


def normalize_massive_trades(
    ticker: str,
    raw: pd.DataFrame,
    *,
    fetched_at: datetime,
    source_url: str,
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    records = cast(list[Mapping[str, object]], raw.to_dict("records"))
    frame = pd.DataFrame([_normalize_raw_row(ticker, row) for row in records])
    classified = classify_trades(frame)
    if classified.empty:
        return classified
    classified["year"] = pd.to_datetime(classified["trade_ts"], utc=True).dt.year
    classified["source"] = "massive"
    classified["source_tier"] = SourceTier.CONFIRMED_TRADE_PRINT.value
    classified["source_url"] = source_url
    classified["timestamp_observed"] = fetched_at
    classified["timestamp_as_of"] = (
        pd.to_datetime(classified["trade_ts"], utc=True) + DELAYED_DATA_LAG
    )
    classified["freshness"] = "FRESH"
    classified["confidence"] = 0.8
    classified["verification_level"] = VerificationLevel.CONFIRMED.value
    classified["source_id"] = classified.apply(_source_id, axis=1)
    return classified


async def _download_ticker(
    client: httpx.AsyncClient,
    ticker: str,
    requested: DateRange,
    config: MassiveTradesConfig,
    limiter: MassiveApiLimiter,
    *,
    progress_callback: ProgressCallback | None = None,
    page_writer: PageWriter | None = None,
    coverage_writer: CoverageWriter | None = None,
    coverage_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    retain_rows: bool = True,
) -> tuple[pd.DataFrame, list[dict[str, object]], int]:
    rows: list[Mapping[str, object]] = []
    coverage: list[dict[str, object]] = []
    rows_written = 0
    current = requested.start
    while current <= requested.end:
        if not is_trading_day(current):
            current += timedelta(days=1)
            continue
        try:
            downloaded = await _download_day(
                client,
                ticker,
                current,
                config,
                limiter,
                progress_callback=progress_callback,
                page_writer=page_writer,
                coverage_writer=coverage_writer,
                resume_state=(
                    (coverage_metadata or {}).get(coverage_key(ticker, current), {})
                    if config.resume_partial
                    else {}
                ),
                retain_rows=retain_rows,
            )
        except Exception as exc:
            coverage.append(
                {
                    "ticker": ticker,
                    "trade_date": current.isoformat(),
                    "coverage_status": "failed",
                    "complete": False,
                    "downloaded_row_count": 0,
                    "pages_downloaded": 0,
                    "max_pages_per_day": config.max_pages_per_day,
                    "max_seconds_per_day": config.max_seconds_per_day,
                    "order": config.order,
                    "limit": config.limit,
                    "reason": redact_sensitive_text(str(exc))[:240],
                }
            )
        else:
            rows_written += downloaded.rows_written
            if retain_rows:
                rows.extend(downloaded.rows)
            coverage_row: dict[str, object] = {
                "ticker": ticker,
                "trade_date": current.isoformat(),
                "coverage_status": "complete" if downloaded.complete else "partial",
                "complete": downloaded.complete,
                "downloaded_row_count": downloaded.downloaded_row_count,
                "rows_written": downloaded.rows_written,
                "pages_downloaded": downloaded.pages_downloaded,
                "max_pages_per_day": config.max_pages_per_day,
                "max_seconds_per_day": config.max_seconds_per_day,
                "order": config.order,
                "limit": config.limit,
                "last_page_results_count": downloaded.last_page_results_count,
                "row_count_verified": downloaded.row_count_verified,
                "stop_reason": downloaded.stop_reason,
                "resume_cursor": downloaded.resume_cursor,
            }
            if downloaded.coverage_extra:
                coverage_row.update(downloaded.coverage_extra)
            coverage.append(coverage_row)
        current += timedelta(days=1)
    return pd.DataFrame(rows), coverage, rows_written


async def _download_day(
    client: httpx.AsyncClient,
    ticker: str,
    trade_date: date,
    config: MassiveTradesConfig,
    limiter: MassiveApiLimiter,
    *,
    progress_callback: ProgressCallback | None = None,
    page_writer: PageWriter | None = None,
    coverage_writer: CoverageWriter | None = None,
    resume_state: Mapping[str, Any] | None = None,
    retain_rows: bool = True,
) -> DownloadedTradeDay:
    if config.window_minutes is not None:
        return await _download_time_windowed_day(
            client,
            ticker,
            trade_date,
            config,
            limiter,
            progress_callback=progress_callback,
            page_writer=page_writer,
            coverage_writer=coverage_writer,
            resume_state=resume_state,
            retain_rows=retain_rows,
        )
    start, end = _trade_session_window_utc(trade_date, config.trade_session)
    resume = resume_state or {}
    resume_cursor = str(resume.get("resume_cursor") or "").strip()
    return await _download_interval(
        client,
        ticker,
        trade_date,
        start,
        end,
        config,
        limiter,
        progress_callback=progress_callback,
        page_writer=page_writer,
        coverage_writer=coverage_writer,
        resume_cursor=resume_cursor or None,
        initial_downloaded_row_count=(
            _nonnegative_int(resume.get("downloaded_row_count")) if resume_cursor else 0
        ),
        initial_pages_downloaded=(
            _nonnegative_int(resume.get("pages_downloaded")) if resume_cursor else 0
        ),
        max_new_pages=config.max_pages_per_day,
        started_at=datetime.now(UTC),
        retain_rows=retain_rows,
    )


async def _download_time_windowed_day(
    client: httpx.AsyncClient,
    ticker: str,
    trade_date: date,
    config: MassiveTradesConfig,
    limiter: MassiveApiLimiter,
    *,
    progress_callback: ProgressCallback | None = None,
    page_writer: PageWriter | None = None,
    coverage_writer: CoverageWriter | None = None,
    resume_state: Mapping[str, Any] | None = None,
    retain_rows: bool = True,
) -> DownloadedTradeDay:
    if config.window_minutes is None:
        raise ValueError("window_minutes must be configured for time-windowed downloads")
    intervals = _trade_time_windows(
        trade_date,
        config.window_minutes,
        trade_session=config.trade_session,
    )
    all_window_keys = [_window_key(start, end) for start, end in intervals]
    all_window_key_set = set(all_window_keys)
    resume = resume_state or {}
    completed_windows = {
        item for item in _string_list(resume.get("completed_windows")) if item in all_window_key_set
    }
    active_window = str(resume.get("active_window") or "").strip()
    resume_cursor = str(resume.get("resume_cursor") or "").strip()
    if active_window not in all_window_key_set:
        active_window = ""
        resume_cursor = ""

    total_downloaded = (
        _nonnegative_int(resume.get("downloaded_row_count"))
        if completed_windows or resume_cursor
        else 0
    )
    total_pages = (
        _nonnegative_int(resume.get("pages_downloaded"))
        if completed_windows or resume_cursor
        else 0
    )
    rows: list[Mapping[str, object]] = []
    rows_written = 0
    last_page_results_count = 0
    row_count_verified = True
    pages_this_run = 0
    started_at = datetime.now(UTC)

    for window_start, window_end in intervals:
        current_window = _window_key(window_start, window_end)
        if current_window in completed_windows:
            continue
        if config.max_pages_per_day is not None and pages_this_run >= config.max_pages_per_day:
            reason = "max_pages_per_day"
            extra = _window_coverage_extra(
                config=config,
                completed_windows=completed_windows,
                all_window_keys=all_window_keys,
                active_window=current_window,
            )
            _write_partial_coverage(
                coverage_writer,
                ticker=ticker,
                trade_date=trade_date,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                pages_downloaded=total_pages,
                config=config,
                resume_cursor=None,
                status="partial",
                complete=False,
                extra=extra,
            )
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=total_pages,
                rows_downloaded=total_downloaded,
                rows_written=rows_written,
                complete=False,
                status="downloaded_partial",
                reason=reason,
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                total_pages,
                complete=False,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=False,
                stop_reason=reason,
                resume_cursor=None,
                coverage_extra=extra,
            )

        cursor_for_window = resume_cursor if active_window == current_window else None
        initial_window_rows = (
            _nonnegative_int(resume.get("active_window_downloaded_row_count"))
            if cursor_for_window
            else 0
        )
        initial_window_pages = (
            _nonnegative_int(resume.get("active_window_pages_downloaded"))
            if cursor_for_window
            else 0
        )
        remaining_pages = (
            None
            if config.max_pages_per_day is None
            else max(config.max_pages_per_day - pages_this_run, 0)
        )
        try:
            downloaded = await _download_interval(
                client,
                ticker,
                trade_date,
                window_start,
                window_end,
                config,
                limiter,
                progress_callback=progress_callback,
                page_writer=page_writer,
                coverage_writer=None,
                resume_cursor=cursor_for_window,
                initial_downloaded_row_count=initial_window_rows,
                initial_pages_downloaded=initial_window_pages,
                max_new_pages=remaining_pages,
                started_at=started_at,
                retain_rows=retain_rows,
            )
        except Exception as exc:
            if total_downloaded <= 0 and rows_written <= 0 and not completed_windows:
                raise
            reason = redact_sensitive_text(f"request_failed_in_window: {exc}")
            extra = _window_coverage_extra(
                config=config,
                completed_windows=completed_windows,
                all_window_keys=all_window_keys,
                active_window=current_window,
            )
            _write_partial_coverage(
                coverage_writer,
                ticker=ticker,
                trade_date=trade_date,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                pages_downloaded=total_pages,
                config=config,
                resume_cursor=None,
                status="partial",
                complete=False,
                extra=extra,
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                total_pages,
                complete=False,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=False,
                stop_reason=reason[:240],
                resume_cursor=None,
                coverage_extra=extra,
            )

        new_window_rows = max(downloaded.downloaded_row_count - initial_window_rows, 0)
        new_window_pages = max(downloaded.pages_downloaded - initial_window_pages, 0)
        total_downloaded += new_window_rows
        total_pages += new_window_pages
        pages_this_run += new_window_pages
        rows_written += downloaded.rows_written
        last_page_results_count = downloaded.last_page_results_count
        row_count_verified = row_count_verified and downloaded.row_count_verified
        if retain_rows:
            rows.extend(downloaded.rows)
        if not downloaded.complete:
            extra = _window_coverage_extra(
                config=config,
                completed_windows=completed_windows,
                all_window_keys=all_window_keys,
                active_window=current_window,
                active_window_downloaded_row_count=downloaded.downloaded_row_count,
                active_window_pages_downloaded=downloaded.pages_downloaded,
            )
            _write_partial_coverage(
                coverage_writer,
                ticker=ticker,
                trade_date=trade_date,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                pages_downloaded=total_pages,
                config=config,
                resume_cursor=downloaded.resume_cursor,
                status="partial",
                complete=False,
                extra=extra,
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                total_pages,
                complete=False,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=False,
                stop_reason=downloaded.stop_reason,
                resume_cursor=downloaded.resume_cursor,
                coverage_extra=extra,
            )

        completed_windows.add(current_window)
        extra = _window_coverage_extra(
            config=config,
            completed_windows=completed_windows,
            all_window_keys=all_window_keys,
        )
        if len(completed_windows) < len(all_window_keys):
            _write_partial_coverage(
                coverage_writer,
                ticker=ticker,
                trade_date=trade_date,
                downloaded_row_count=total_downloaded,
                rows_written=rows_written,
                pages_downloaded=total_pages,
                config=config,
                resume_cursor=None,
                status="partial",
                complete=False,
                extra=extra,
            )

    extra = _window_coverage_extra(
        config=config,
        completed_windows=completed_windows,
        all_window_keys=all_window_keys,
    )
    return DownloadedTradeDay(
        ticker,
        trade_date,
        rows,
        total_pages,
        complete=True,
        downloaded_row_count=total_downloaded,
        rows_written=rows_written,
        last_page_results_count=last_page_results_count,
        row_count_verified=row_count_verified,
        resume_cursor=None,
        coverage_extra=extra,
    )


async def _download_interval(
    client: httpx.AsyncClient,
    ticker: str,
    trade_date: date,
    window_start: datetime,
    window_end: datetime,
    config: MassiveTradesConfig,
    limiter: MassiveApiLimiter,
    *,
    progress_callback: ProgressCallback | None = None,
    page_writer: PageWriter | None = None,
    coverage_writer: CoverageWriter | None = None,
    resume_cursor: str | None = None,
    initial_downloaded_row_count: int = 0,
    initial_pages_downloaded: int = 0,
    max_new_pages: int | None = None,
    started_at: datetime | None = None,
    retain_rows: bool = True,
) -> DownloadedTradeDay:
    rows: list[Mapping[str, object]] = []
    rows_written = 0
    downloaded_row_count = initial_downloaded_row_count
    pages = initial_pages_downloaded
    new_pages_downloaded = 0
    url = config.trades_url(ticker)
    params = (
        {"cursor": resume_cursor, "apiKey": config.api_key}
        if resume_cursor
        else _params_for_time_window(window_start, window_end, config)
    )
    last_page_results_count = 0
    interval_started_at = started_at or datetime.now(UTC)
    while True:
        await limiter.acquire(endpoint="stock_trades", ticker=ticker)
        try:
            response = await _get_with_transport_retries(client, url, params=params, config=config)
            response.raise_for_status()
        except Exception as exc:
            if downloaded_row_count > 0:
                reason = redact_sensitive_text(f"request_failed_after_partial: {exc}")
                _emit_progress(
                    progress_callback,
                    ticker=ticker,
                    trade_date=trade_date,
                    pages_downloaded=pages,
                    rows_downloaded=downloaded_row_count,
                    rows_written=rows_written,
                    complete=False,
                    status="downloaded_partial",
                    reason=reason,
                )
                return DownloadedTradeDay(
                    ticker,
                    trade_date,
                    rows,
                    pages,
                    complete=False,
                    downloaded_row_count=downloaded_row_count,
                    rows_written=rows_written,
                    last_page_results_count=last_page_results_count,
                    row_count_verified=False,
                    stop_reason=reason[:240],
                    resume_cursor=_cursor_from_next_url(url) or resume_cursor,
                )
            raise
        payload = _json_mapping(response)
        raw_page_rows = _results(payload)
        page_rows, rejected_count = _filter_rows_for_time_window(
            raw_page_rows,
            window_start,
            window_end,
        )
        last_page_results_count = len(page_rows)
        pages += 1
        new_pages_downloaded += 1
        if raw_page_rows and not page_rows:
            reason = _outside_window_reason(
                trade_date,
                window_start,
                window_end,
                partial=False,
            )
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=downloaded_row_count,
                rows_written=rows_written,
                complete=True,
                status="downloaded",
                reason=reason,
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                pages,
                complete=True,
                downloaded_row_count=downloaded_row_count,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=True,
                stop_reason=reason,
                resume_cursor=None,
            )
        downloaded_row_count += len(page_rows)
        if page_writer is not None and page_rows:
            rows_written += page_writer(ticker, trade_date, page_rows)
        if retain_rows:
            rows.extend(page_rows)
        _emit_progress(
            progress_callback,
            ticker=ticker,
            trade_date=trade_date,
            pages_downloaded=pages,
            rows_downloaded=downloaded_row_count,
            rows_written=rows_written,
            complete=False,
            status="running",
        )
        next_url = _next_url(payload)
        next_cursor = _cursor_from_next_url(next_url)
        if rejected_count:
            next_url = None
            next_cursor = None
        _write_partial_coverage(
            coverage_writer,
            ticker=ticker,
            trade_date=trade_date,
            downloaded_row_count=downloaded_row_count,
            rows_written=rows_written,
            pages_downloaded=pages,
            config=config,
            resume_cursor=next_cursor,
            status="partial",
            complete=False,
        )
        if rejected_count:
            reason = _outside_window_reason(
                trade_date,
                window_start,
                window_end,
                partial=True,
            )
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=downloaded_row_count,
                rows_written=rows_written,
                complete=True,
                status="downloaded",
                reason=reason,
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                pages,
                complete=True,
                downloaded_row_count=downloaded_row_count,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=True,
                stop_reason=reason,
                resume_cursor=None,
            )
        if next_url is None:
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=downloaded_row_count,
                rows_written=rows_written,
                complete=False,
                status="downloaded",
            )
            row_count_verified = last_page_results_count < config.limit
            if not row_count_verified:
                warnings.warn(
                    f"pagination_completeness_uncertain: {ticker} {trade_date} ended on"
                    f" exactly {config.limit} rows — possible truncation",
                    stacklevel=2,
                )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                pages,
                complete=True,
                downloaded_row_count=downloaded_row_count,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=row_count_verified,
                resume_cursor=None,
            )
        if _ticker_day_timed_out(interval_started_at, config.max_seconds_per_day):
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=downloaded_row_count,
                rows_written=rows_written,
                complete=False,
                status="downloaded_partial",
                reason="max_seconds_per_day",
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                pages,
                complete=False,
                downloaded_row_count=downloaded_row_count,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=False,
                stop_reason="max_seconds_per_day",
                resume_cursor=next_cursor,
            )
        if max_new_pages is not None and new_pages_downloaded >= max_new_pages:
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=downloaded_row_count,
                rows_written=rows_written,
                complete=False,
                status="downloaded_partial",
                reason="max_pages_per_day",
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                pages,
                complete=False,
                downloaded_row_count=downloaded_row_count,
                rows_written=rows_written,
                last_page_results_count=last_page_results_count,
                row_count_verified=False,
                stop_reason="max_pages_per_day",
                resume_cursor=next_cursor,
            )
        url = next_url
        params = {"apiKey": config.api_key} if "apiKey=" not in next_url else {}


async def _get_with_transport_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str],
    config: MassiveTradesConfig,
) -> httpx.Response:
    attempts = max(config.request_retries, 0) + 1
    last_error: httpx.TransportError | None = None
    for attempt in range(attempts):
        try:
            return await client.get(url, params=params)
        except httpx.TransportError as exc:
            last_error = exc
            if attempt >= attempts - 1:
                break
            await asyncio.sleep(min(2.0 ** attempt, 5.0))
    if last_error is None:
        raise RuntimeError("Massive request failed without an error")
    raise last_error


def redact_sensitive_text(text: str) -> str:
    return SECRET_QUERY_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)


def _ticker_day_timed_out(
    started_at: datetime,
    max_seconds_per_day: float | None,
) -> bool:
    if max_seconds_per_day is None or max_seconds_per_day <= 0:
        return False
    return (datetime.now(UTC) - started_at).total_seconds() >= max_seconds_per_day


def _write_partial_coverage(
    writer: CoverageWriter | None,
    *,
    ticker: str,
    trade_date: date,
    downloaded_row_count: int,
    rows_written: int,
    pages_downloaded: int,
    config: MassiveTradesConfig,
    resume_cursor: str | None,
    status: str,
    complete: bool,
    extra: Mapping[str, object] | None = None,
) -> None:
    if writer is None:
        return
    payload: dict[str, object] = {
        "ticker": ticker.upper(),
        "trade_date": trade_date.isoformat(),
        "coverage_status": status,
        "complete": complete,
        "downloaded_row_count": downloaded_row_count,
        "rows_written": rows_written,
        "pages_downloaded": pages_downloaded,
        "max_pages_per_day": config.max_pages_per_day,
        "max_seconds_per_day": config.max_seconds_per_day,
        "order": config.order,
        "limit": config.limit,
        "resume_cursor": resume_cursor,
    }
    if extra:
        payload.update(extra)
    writer(payload)


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    ticker: str,
    trade_date: date,
    pages_downloaded: int,
    rows_downloaded: int,
    rows_written: int = 0,
    complete: bool,
    status: str,
    reason: str | None = None,
) -> None:
    if callback is None:
        return
    payload = {
        "schema_version": "0.1.0",
        "ticker": ticker.upper(),
        "trade_date": trade_date.isoformat(),
        "pages_downloaded": pages_downloaded,
        "rows_downloaded": rows_downloaded,
        "rows_written": rows_written,
        "complete": complete,
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if reason:
        payload["reason"] = reason[:240]
    callback(payload)


def _params(trade_date: date, config: MassiveTradesConfig) -> dict[str, str]:
    start, end = _trade_date_window_utc(trade_date)
    return _params_for_time_window(start, end, config)


def _params_for_time_window(
    start: datetime,
    end: datetime,
    config: MassiveTradesConfig,
) -> dict[str, str]:
    return {
        "timestamp.gte": str(_epoch_nanoseconds(start)),
        "timestamp.lt": str(_epoch_nanoseconds(end)),
        "order": config.order,
        "sort": "timestamp",
        "limit": str(config.limit),
        "apiKey": config.api_key,
    }


def _trade_date_window_utc(trade_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trade_date, time.min, tzinfo=MARKET_TIMEZONE).astimezone(UTC)
    end = datetime.combine(
        trade_date + timedelta(days=1),
        time.min,
        tzinfo=MARKET_TIMEZONE,
    ).astimezone(UTC)
    return start, end


def _trade_session_window_utc(
    trade_date: date,
    trade_session: TradeSession,
) -> tuple[datetime, datetime]:
    if trade_session == "pre_market":
        start = datetime.combine(trade_date, time(4, 0), tzinfo=MARKET_TIMEZONE)
        end = datetime.combine(trade_date, time(9, 30), tzinfo=MARKET_TIMEZONE)
        return start.astimezone(UTC), end.astimezone(UTC)
    return _trade_date_window_utc(trade_date)


def _trade_time_windows(
    trade_date: date,
    window_minutes: int,
    *,
    trade_session: TradeSession = "full_day",
) -> list[tuple[datetime, datetime]]:
    start, end = _trade_session_window_utc(trade_date, trade_session)
    step = timedelta(minutes=max(window_minutes, 1))
    windows: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        next_end = min(current + step, end)
        windows.append((current, next_end))
        current = next_end
    return windows


def _trade_session(value: TradeSession | str | None) -> TradeSession:
    if value is None or str(value).strip() == "":
        return "full_day"
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"full_day", "pre_market"}:
        return cast(TradeSession, normalized)
    raise ValueError("trade_session must be 'full_day' or 'pre_market'")


def _window_key(start: datetime, end: datetime) -> str:
    return f"{start.isoformat()}/{end.isoformat()}"


def _window_coverage_extra(
    *,
    config: MassiveTradesConfig,
    completed_windows: set[str],
    all_window_keys: Sequence[str],
    active_window: str | None = None,
    active_window_downloaded_row_count: int = 0,
    active_window_pages_downloaded: int = 0,
) -> dict[str, object]:
    ordered_completed = [key for key in all_window_keys if key in completed_windows]
    extra: dict[str, object] = {
        "download_mode": "time_windowed",
        "window_minutes": config.window_minutes,
        "window_count": len(all_window_keys),
        "completed_window_count": len(ordered_completed),
        "completed_windows": ordered_completed,
        "active_window": active_window,
        "active_window_downloaded_row_count": active_window_downloaded_row_count,
        "active_window_pages_downloaded": active_window_pages_downloaded,
    }
    return extra


def _outside_window_reason(
    trade_date: date,
    window_start: datetime,
    window_end: datetime,
    *,
    partial: bool,
) -> str:
    day_start, day_end = _trade_date_window_utc(trade_date)
    if window_start == day_start and window_end == day_end:
        return (
            "page_partially_outside_requested_trade_date"
            if partial
            else "page_outside_requested_trade_date"
        )
    return (
        "page_partially_outside_requested_trade_window"
        if partial
        else "page_outside_requested_trade_window"
    )


def _epoch_nanoseconds(value: datetime) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    return int(timestamp.tz_convert(UTC).value)


def _trade_order_from_env() -> TradeOrder:
    value = os.environ.get("MASSIVE_STOCK_TRADES_ORDER", "asc").strip().lower()
    if value not in {"asc", "desc"}:
        raise ValueError("MASSIVE_STOCK_TRADES_ORDER must be asc or desc")
    return cast(TradeOrder, value)


def _json_mapping(response: httpx.Response) -> Mapping[str, object]:
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TypeError("Massive response must be a JSON object")
    return cast(Mapping[str, object], payload)


def _results(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = payload.get("results", [])
    if not isinstance(value, list):
        raise TypeError("Massive results must be a list")
    rows: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("Massive trade rows must be JSON objects")
        rows.append(cast(Mapping[str, object], item))
    return rows


def _results_count(payload: Mapping[str, object], page_rows: list[Mapping[str, object]]) -> int:
    """Return the results_count from the payload if present, else fall back to len(page_rows)."""
    value = payload.get("results_count")
    if isinstance(value, int):
        return value
    return len(page_rows)


def _filter_rows_for_trade_date(
    page_rows: Sequence[Mapping[str, object]],
    trade_date: date,
) -> tuple[list[Mapping[str, object]], int]:
    start, end = _trade_date_window_utc(trade_date)
    return _filter_rows_for_time_window(page_rows, start, end)


def _filter_rows_for_time_window(
    page_rows: Sequence[Mapping[str, object]],
    start: datetime,
    end: datetime,
) -> tuple[list[Mapping[str, object]], int]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    filtered: list[Mapping[str, object]] = []
    rejected = 0
    for row in page_rows:
        timestamp = _optional_timestamp(_first(row, "sip_timestamp", "y", "timestamp"))
        if timestamp is not None and start_ts <= timestamp < end_ts:
            filtered.append(row)
        else:
            rejected += 1
    return filtered, rejected


def _next_url(payload: Mapping[str, object]) -> str | None:
    value = payload.get("next_url")
    return value if isinstance(value, str) and value else None


def _cursor_from_next_url(value: str | None) -> str | None:
    if not value:
        return None
    query = parse_qs(urlsplit(value).query)
    cursor_values = query.get("cursor", [])
    if not cursor_values:
        return None
    cursor = cursor_values[0].strip()
    return cursor or None


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(round(value), 0)
    return 0


def _positive_int(value: object) -> int | None:
    count = _nonnegative_int(value)
    return count if count > 0 else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _normalize_raw_row(ticker: str, row: Mapping[str, object]) -> dict[str, object]:
    trade_ts = _timestamp(_first(row, "sip_timestamp", "y", "timestamp"))
    participant_ts = _optional_timestamp(_first(row, "participant_timestamp", "t"))
    trf_ts = _optional_timestamp(_first(row, "trf_timestamp", "r"))
    price = _number(_first(row, "price", "p"))
    size = _number(_first(row, "size", "s"))
    return {
        "ticker": ticker.upper(),
        "trade_ts": trade_ts,
        "participant_timestamp": participant_ts,
        "sip_timestamp": trade_ts,
        "trf_timestamp": trf_ts,
        "price": price,
        "size": size,
        "exchange": _text(_first(row, "exchange", "x")),
        "conditions": _conditions(_first(row, "conditions", "c")),
        "correction": _first(row, "correction", "e"),
        "trade_id": _text(_first(row, "id", "i")) or _fallback_trade_id(row),
        "sequence_number": _integer(_first(row, "sequence_number", "q")),
        "tape": _text(_first(row, "tape", "z")),
        "trf_id": _text(_first(row, "trf_id", "f")),
    }


def _first(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _timestamp(value: object) -> pd.Timestamp:
    if _missing(value):
        raise ValueError("timestamp is required")
    if isinstance(value, int | float):
        return pd.to_datetime(int(value), unit=_numeric_timestamp_unit(value), utc=True)
    if isinstance(value, str) and value.isdigit():
        return pd.to_datetime(int(value), unit=_numeric_timestamp_unit(value), utc=True)
    return pd.to_datetime(str(value), utc=True)


def _optional_timestamp(value: object) -> pd.Timestamp | None:
    if _missing(value):
        return None
    return _timestamp(value)


def _number(value: object) -> float:
    if _missing(value):
        return 0.0
    return float(str(value))


def _integer(value: object) -> int:
    if _missing(value):
        return 0
    return int(float(str(value)))


def _numeric_timestamp_unit(value: object) -> TimestampUnit:
    digits = len(str(abs(int(float(str(value))))))
    if digits >= NANOSECOND_TIMESTAMP_DIGITS:
        return "ns"
    if digits >= MICROSECOND_TIMESTAMP_DIGITS:
        return "us"
    if digits >= MILLISECOND_TIMESTAMP_DIGITS:
        return "ms"
    return "s"


def _text(value: object) -> str | None:
    if _missing(value):
        return None
    text = str(value).strip()
    return text or None


def _conditions(value: object) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if _missing(value):
        return ""
    return str(value)


def _fallback_trade_id(row: Mapping[str, object]) -> str:
    return ":".join(str(row.get(key, "")) for key in ("p", "s", "y", "q"))


def _source_id(row: pd.Series) -> str:
    return (
        f"massive:{row['ticker']}:{row['trade_date']}:"
        f"{row['trade_id']}:{row['sequence_number']}"
    )


def _utc_now(clock: Callable[[], datetime] | None) -> datetime:
    value = datetime.now(UTC) if clock is None else clock()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _verify_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
