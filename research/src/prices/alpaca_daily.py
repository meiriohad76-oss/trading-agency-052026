from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Self, cast

import httpx
import pandas as pd
from prices.storage import DateRange
from prices.types import Downloader

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, instrumented_call

DEFAULT_ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
DEFAULT_ALPACA_FEED = "iex"
DEFAULT_ALPACA_ADJUSTMENT = "all"
BARS_PATH = "/v2/stocks/bars"


@dataclass(frozen=True)
class AlpacaDailyConfig:
    api_key: str
    secret_key: str
    base_url: str = DEFAULT_ALPACA_DATA_BASE_URL
    feed: str = DEFAULT_ALPACA_FEED
    adjustment: str = DEFAULT_ALPACA_ADJUSTMENT
    limit: int = 10_000
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(
        cls,
        *,
        feed: str | None = None,
        adjustment: str | None = None,
        base_url: str | None = None,
    ) -> Self:
        api_key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        data_base_url = base_url or os.environ.get("ALPACA_DATA_BASE_URL")
        return cls(
            api_key=api_key,
            secret_key=secret_key,
            base_url=data_base_url or DEFAULT_ALPACA_DATA_BASE_URL,
            feed=(feed or os.environ.get("ALPACA_DATA_FEED") or DEFAULT_ALPACA_FEED),
            adjustment=(
                adjustment
                or os.environ.get("ALPACA_DATA_ADJUSTMENT")
                or DEFAULT_ALPACA_ADJUSTMENT
            ),
        )

    @property
    def bars_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{BARS_PATH}"


def build_alpaca_downloader(
    config: AlpacaDailyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Downloader:
    async def download(ticker: str, requested: DateRange) -> pd.DataFrame:
        async def call() -> pd.DataFrame:
            return await _download_alpaca_history(
                ticker,
                requested,
                config,
                transport=transport,
            )

        wrapped = await instrumented_call(
            call,
            source="alpaca",
            source_tier=SourceTier.MARKET_DATA,
            source_id=f"{ticker}:{requested.start.isoformat()}:{requested.end.isoformat()}",
            verification_level=VerificationLevel.CONFIRMED,
            freshness_domain=FreshnessDomain.PRICING,
            timestamp_as_of=_as_utc(requested.end),
            confidence=_confidence(config.feed),
            source_url=config.bars_url,
        )
        return wrapped.value

    return download


def normalize_alpaca_bars(ticker: str, raw: pd.DataFrame, *, fetched_at: datetime) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    missing = {"t", "o", "h", "l", "c", "v"}.difference(frame.columns)
    if missing:
        raise ValueError(f"alpaca bars missing column(s): {sorted(missing)}")

    frame["date"] = pd.to_datetime(frame["t"], utc=True).dt.date
    requested_start = raw.attrs.get("requested_start")
    requested_end = raw.attrs.get("requested_end")
    if isinstance(requested_start, date) and isinstance(requested_end, date):
        frame = frame[(frame["date"] >= requested_start) & (frame["date"] <= requested_end)]
    if frame.empty:
        return pd.DataFrame()

    feed = str(raw.attrs.get("feed", DEFAULT_ALPACA_FEED))
    source_url = str(raw.attrs.get("source_url", f"{DEFAULT_ALPACA_DATA_BASE_URL}{BARS_PATH}"))
    frame["open"] = pd.to_numeric(frame["o"], errors="coerce")
    frame["high"] = pd.to_numeric(frame["h"], errors="coerce")
    frame["low"] = pd.to_numeric(frame["l"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["c"], errors="coerce")
    frame = frame.dropna(how="all", subset=["open", "high", "low", "close"])
    if frame.empty:
        return pd.DataFrame()

    frame["ticker"] = ticker.upper()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    frame["adj_close"] = frame["close"]
    frame["volume"] = pd.to_numeric(frame["v"], errors="coerce").fillna(0).astype("int64")
    frame["dividend"] = 0.0
    frame["split_factor"] = 1.0
    frame["fetched_at"] = fetched_at
    frame["source"] = "alpaca"
    frame["source_tier"] = SourceTier.MARKET_DATA.value
    frame["source_url"] = source_url
    frame["timestamp_observed"] = fetched_at
    frame["timestamp_as_of"] = frame["date"]
    frame["freshness"] = "STALE"
    frame["confidence"] = _confidence(feed)
    frame["verification_level"] = VerificationLevel.CONFIRMED.value
    frame["source_id"] = frame["date"].map(lambda value: f"alpaca:{feed}:{ticker.upper()}:{value}")
    return frame


async def _download_alpaca_history(
    ticker: str,
    requested: DateRange,
    config: AlpacaDailyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> pd.DataFrame:
    rows: list[Mapping[str, object]] = []
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=config.timeout_seconds, transport=transport) as client:
        while True:
            params = _request_params(ticker, requested, config, page_token=page_token)
            response = await client.get(config.bars_url, params=params, headers=_headers(config))
            response.raise_for_status()
            payload = _json_mapping(response)
            rows.extend(_bars_for_ticker(payload, ticker))
            page_token = _next_page_token(payload)
            if page_token is None:
                break
    return _raw_frame(rows, ticker=ticker, requested=requested, config=config)


def _request_params(
    ticker: str,
    requested: DateRange,
    config: AlpacaDailyConfig,
    *,
    page_token: str | None,
) -> dict[str, str]:
    params = {
        "symbols": ticker.upper(),
        "timeframe": "1Day",
        "start": _rfc3339_day(requested.start),
        "end": _rfc3339_day(requested.end + timedelta(days=1)),
        "adjustment": config.adjustment,
        "feed": config.feed,
        "limit": str(config.limit),
    }
    if page_token is not None:
        params["page_token"] = page_token
    return params


def _headers(config: AlpacaDailyConfig) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": config.api_key,
        "APCA-API-SECRET-KEY": config.secret_key,
    }


def _json_mapping(response: httpx.Response) -> Mapping[str, object]:
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TypeError("Alpaca response must be a JSON object")
    return cast(Mapping[str, object], payload)


def _bars_for_ticker(payload: Mapping[str, object], ticker: str) -> list[Mapping[str, object]]:
    bars_payload = payload.get("bars")
    if isinstance(bars_payload, Mapping):
        values = bars_payload.get(ticker.upper(), bars_payload.get(ticker.lower(), []))
    else:
        values = bars_payload
    if values is None:
        return []
    if not isinstance(values, list):
        raise TypeError("Alpaca bars payload must be a list")
    rows: list[Mapping[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise TypeError("Alpaca bar rows must be JSON objects")
        rows.append(cast(Mapping[str, object], value))
    return rows


def _next_page_token(payload: Mapping[str, object]) -> str | None:
    value = payload.get("next_page_token")
    return value if isinstance(value, str) and value else None


def _raw_frame(
    rows: list[Mapping[str, object]],
    *,
    ticker: str,
    requested: DateRange,
    config: AlpacaDailyConfig,
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame.attrs["ticker"] = ticker.upper()
    frame.attrs["feed"] = config.feed
    frame.attrs["source_url"] = config.bars_url
    frame.attrs["requested_start"] = requested.start
    frame.attrs["requested_end"] = requested.end
    return frame


def _confidence(feed: str) -> float:
    return 0.95 if feed.lower() == "sip" else 0.85


def _rfc3339_day(value: date) -> str:
    return f"{value.isoformat()}T00:00:00Z"


def _as_utc(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)
