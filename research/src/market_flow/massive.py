from __future__ import annotations

import os
import ssl
import sys
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Self, cast
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from providers.massive_limits import MassiveApiLimiter

from agency.provenance import SourceTier, VerificationLevel

from .classification import classify_trades
from .storage import (
    DateRange,
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
ProgressCallback = Callable[[Mapping[str, object]], None]


@dataclass(frozen=True)
class MassiveTradesConfig:
    api_key: str
    base_url: str = DEFAULT_MASSIVE_BASE_URL
    limit: int = 50_000
    max_pages_per_day: int | None = None
    order: TradeOrder = "asc"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        limit: int = 50_000,
        max_pages_per_day: int | None = None,
        order: TradeOrder | None = None,
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
            order=order or _trade_order_from_env(),
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
    last_page_results_count: int = 0
    row_count_verified: bool = False


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
    quota = limiter or MassiveApiLimiter.from_env(disabled=transport is not None)
    async with httpx.AsyncClient(
        timeout=config.timeout_seconds,
        transport=transport,
        verify=_verify_context(),
    ) as client:
        for ticker in sorted({item.upper() for item in tickers}):
            try:
                raw, ticker_coverage = await _download_ticker(
                    client,
                    ticker,
                    requested,
                    config,
                    quota,
                    progress_callback=progress_callback,
                )
                normalized = normalize_massive_trades(
                    ticker,
                    raw,
                    fetched_at=fetched_at,
                    source_url=config.trades_url(ticker),
                )
            except Exception as exc:
                issues.append({"ticker": ticker, "reason": str(exc)})
                _emit_failed_ticker_progress(
                    progress_callback,
                    ticker=ticker,
                    requested=requested,
                    reason=str(exc),
                )
                continue
            coverage.extend(ticker_coverage)
            if not normalized.empty:
                rows_written += write_stock_trade_frame(trade_root, normalized)
            update_stock_trade_coverage_metadata(trade_root, ticker_coverage)
            _emit_durable_coverage_progress(progress_callback, ticker_coverage)
    write_manifest(
        manifest_path,
        trade_root,
        fetched_at=fetched_at,
        requested=requested,
        issues=issues,
        source_url=config.base_url,
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
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    rows: list[Mapping[str, object]] = []
    coverage: list[dict[str, object]] = []
    current = requested.start
    while current <= requested.end:
        try:
            downloaded = await _download_day(
                client,
                ticker,
                current,
                config,
                limiter,
                progress_callback=progress_callback,
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
                    "order": config.order,
                    "limit": config.limit,
                    "reason": str(exc)[:240],
                }
            )
        else:
            rows.extend(downloaded.rows)
            coverage.append(
                {
                    "ticker": ticker,
                    "trade_date": current.isoformat(),
                    "coverage_status": "complete" if downloaded.complete else "partial",
                    "complete": downloaded.complete,
                    "downloaded_row_count": len(downloaded.rows),
                    "pages_downloaded": downloaded.pages_downloaded,
                    "max_pages_per_day": config.max_pages_per_day,
                    "order": config.order,
                    "limit": config.limit,
                    "last_page_results_count": downloaded.last_page_results_count,
                    "row_count_verified": downloaded.row_count_verified,
                }
            )
        current += timedelta(days=1)
    return pd.DataFrame(rows), coverage


async def _download_day(
    client: httpx.AsyncClient,
    ticker: str,
    trade_date: date,
    config: MassiveTradesConfig,
    limiter: MassiveApiLimiter,
    *,
    progress_callback: ProgressCallback | None = None,
) -> DownloadedTradeDay:
    rows: list[Mapping[str, object]] = []
    url = config.trades_url(ticker)
    params = _params(trade_date, config)
    pages = 0
    last_page_results_count = 0
    while True:
        await limiter.acquire(endpoint="stock_trades", ticker=ticker)
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = _json_mapping(response)
        page_rows = _results(payload)
        last_page_results_count = _results_count(payload, page_rows)
        rows.extend(page_rows)
        pages += 1
        _emit_progress(
            progress_callback,
            ticker=ticker,
            trade_date=trade_date,
            pages_downloaded=pages,
            rows_downloaded=len(rows),
            complete=False,
            status="running",
        )
        next_url = _next_url(payload)
        if next_url is None:
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=len(rows),
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
                last_page_results_count=last_page_results_count,
                row_count_verified=row_count_verified,
            )
        if config.max_pages_per_day is not None and pages >= config.max_pages_per_day:
            _emit_progress(
                progress_callback,
                ticker=ticker,
                trade_date=trade_date,
                pages_downloaded=pages,
                rows_downloaded=len(rows),
                complete=False,
                status="downloaded_partial",
            )
            return DownloadedTradeDay(
                ticker,
                trade_date,
                rows,
                pages,
                complete=False,
                last_page_results_count=last_page_results_count,
                row_count_verified=False,
            )
        url = next_url
        params = {"apiKey": config.api_key} if "apiKey=" not in next_url else {}


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    ticker: str,
    trade_date: date,
    pages_downloaded: int,
    rows_downloaded: int,
    complete: bool,
    status: str,
) -> None:
    if callback is None:
        return
    callback(
        {
            "schema_version": "0.1.0",
            "ticker": ticker.upper(),
            "trade_date": trade_date.isoformat(),
            "pages_downloaded": pages_downloaded,
            "rows_downloaded": rows_downloaded,
            "complete": complete,
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )


def _params(trade_date: date, config: MassiveTradesConfig) -> dict[str, str]:
    start = datetime.combine(trade_date, time.min, tzinfo=MARKET_TIMEZONE).astimezone(UTC)
    end = (
        datetime.combine(trade_date + timedelta(days=1), time.min, tzinfo=MARKET_TIMEZONE)
        .astimezone(UTC)
    )
    return {
        "timestamp.gte": start.isoformat().replace("+00:00", "Z"),
        "timestamp.lt": end.isoformat().replace("+00:00", "Z"),
        "order": config.order,
        "sort": "timestamp",
        "limit": str(config.limit),
        "apiKey": config.api_key,
    }


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


def _next_url(payload: Mapping[str, object]) -> str | None:
    value = payload.get("next_url")
    return value if isinstance(value, str) and value else None


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
