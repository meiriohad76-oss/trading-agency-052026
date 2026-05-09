from __future__ import annotations

import os
import ssl
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, Self, cast

import httpx
import pandas as pd

from agency.provenance import SourceTier, VerificationLevel

from .classification import classify_trades
from .storage import DateRange, write_manifest, write_stock_trade_frame

DEFAULT_MASSIVE_BASE_URL = "https://api.polygon.io"
TRADES_PATH_TEMPLATE = "/v3/trades/{ticker}"
DELAYED_DATA_LAG = timedelta(minutes=15)


@dataclass(frozen=True)
class MassiveTradesConfig:
    api_key: str
    base_url: str = DEFAULT_MASSIVE_BASE_URL
    limit: int = 50_000
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls, *, base_url: str | None = None) -> Self:
        api_key = os.environ.get("MASSIVE_API_KEY", "").strip() or os.environ.get(
            "POLYGON_API_KEY",
            "",
        ).strip()
        if not api_key:
            raise ValueError("MASSIVE_API_KEY or POLYGON_API_KEY must be set")
        return cls(
            api_key=api_key,
            base_url=base_url or os.environ.get("MASSIVE_BASE_URL") or DEFAULT_MASSIVE_BASE_URL,
        )

    def trades_url(self, ticker: str) -> str:
        return f"{self.base_url.rstrip('/')}{TRADES_PATH_TEMPLATE.format(ticker=ticker.upper())}"


@dataclass(frozen=True)
class MassiveTradesSummary:
    tickers_requested: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_massive_trades(
    *,
    tickers: Sequence[str],
    requested: DateRange,
    trade_root: Path,
    manifest_path: Path,
    config: MassiveTradesConfig,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> MassiveTradesSummary:
    fetched_at = _utc_now(clock)
    frames: list[pd.DataFrame] = []
    issues: list[dict[str, str]] = []
    async with httpx.AsyncClient(
        timeout=config.timeout_seconds,
        transport=transport,
        verify=_verify_context(),
    ) as client:
        for ticker in sorted({item.upper() for item in tickers}):
            try:
                raw = await _download_ticker(client, ticker, requested, config)
                normalized = normalize_massive_trades(
                    ticker,
                    raw,
                    fetched_at=fetched_at,
                    source_url=config.trades_url(ticker),
                )
            except Exception as exc:
                issues.append({"ticker": ticker, "reason": str(exc)})
                continue
            if not normalized.empty:
                frames.append(normalized)
    rows_written = 0
    if frames:
        rows_written = write_stock_trade_frame(trade_root, pd.concat(frames, ignore_index=True))
    write_manifest(
        manifest_path,
        trade_root,
        fetched_at=fetched_at,
        requested=requested,
        issues=issues,
        source_url=config.base_url,
    )
    return MassiveTradesSummary(len(set(tickers)), rows_written, issues)


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
) -> pd.DataFrame:
    rows: list[Mapping[str, object]] = []
    current = requested.start
    while current <= requested.end:
        rows.extend(await _download_day(client, ticker, current, config))
        current += timedelta(days=1)
    return pd.DataFrame(rows)


async def _download_day(
    client: httpx.AsyncClient,
    ticker: str,
    trade_date: date,
    config: MassiveTradesConfig,
) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    url = config.trades_url(ticker)
    params = _params(trade_date, config)
    while True:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = _json_mapping(response)
        rows.extend(_results(payload))
        next_url = _next_url(payload)
        if next_url is None:
            return rows
        url = next_url
        params = {"apiKey": config.api_key} if "apiKey=" not in next_url else {}


def _params(trade_date: date, config: MassiveTradesConfig) -> dict[str, str]:
    start = datetime.combine(trade_date, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    return {
        "timestamp.gte": start.isoformat().replace("+00:00", "Z"),
        "timestamp.lt": end.isoformat().replace("+00:00", "Z"),
        "order": "asc",
        "sort": "timestamp",
        "limit": str(config.limit),
        "apiKey": config.api_key,
    }


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


def _next_url(payload: Mapping[str, object]) -> str | None:
    value = payload.get("next_url")
    return value if isinstance(value, str) and value else None


def _normalize_raw_row(ticker: str, row: Mapping[str, object]) -> dict[str, object]:
    trade_ts = _timestamp(_first(row, "sip_timestamp", "y", "timestamp", "t"))
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
        return pd.to_datetime(int(value), unit="ns", utc=True)
    if isinstance(value, str) and value.isdigit():
        return pd.to_datetime(int(value), unit="ns", utc=True)
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
