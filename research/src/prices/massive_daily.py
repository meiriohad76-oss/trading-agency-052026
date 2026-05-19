from __future__ import annotations

import os
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import import_module
from typing import Self, cast

import httpx
import pandas as pd
from prices.storage import DateRange
from prices.types import Downloader
from providers.massive_limits import MassiveApiLimiter

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, instrumented_call

DEFAULT_MASSIVE_BASE_URL = "https://api.polygon.io"
AGGS_PATH_TEMPLATE = "/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"


@dataclass(frozen=True)
class MassiveDailyConfig:
    api_key: str
    base_url: str = DEFAULT_MASSIVE_BASE_URL
    adjusted: bool = True
    sort: str = "asc"
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

    def aggs_url(self, ticker: str, requested: DateRange) -> str:
        path = AGGS_PATH_TEMPLATE.format(
            ticker=ticker.upper(),
            start=requested.start.isoformat(),
            end=requested.end.isoformat(),
        )
        return f"{self.base_url.rstrip('/')}{path}"


def build_massive_downloader(
    config: MassiveDailyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    limiter: MassiveApiLimiter | None = None,
) -> Downloader:
    quota = limiter or MassiveApiLimiter.from_env(disabled=transport is not None)

    async def download(ticker: str, requested: DateRange) -> pd.DataFrame:
        async def call() -> pd.DataFrame:
            return await _download_massive_history(
                ticker,
                requested,
                config,
                transport=transport,
                limiter=quota,
            )

        wrapped = await instrumented_call(
            call,
            source="massive",
            source_tier=SourceTier.MARKET_DATA,
            source_id=f"{ticker}:{requested.start.isoformat()}:{requested.end.isoformat()}",
            verification_level=VerificationLevel.CONFIRMED,
            freshness_domain=FreshnessDomain.PRICING,
            timestamp_as_of=_as_utc(requested.end),
            confidence=_confidence(config),
            source_url=config.aggs_url(ticker, requested),
        )
        return wrapped.value

    return download


def normalize_massive_bars(ticker: str, raw: pd.DataFrame, *, fetched_at: datetime) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    missing = {"t", "o", "h", "l", "c", "v"}.difference(frame.columns)
    if missing:
        raise ValueError(f"Massive bars missing column(s): {sorted(missing)}")

    frame["date"] = pd.to_datetime(frame["t"], unit="ms", utc=True).dt.date
    requested_start = raw.attrs.get("requested_start")
    requested_end = raw.attrs.get("requested_end")
    frame.attrs.clear()
    if isinstance(requested_start, date) and isinstance(requested_end, date):
        frame = frame[(frame["date"] >= requested_start) & (frame["date"] <= requested_end)]
    if frame.empty:
        return pd.DataFrame()

    source_url = str(raw.attrs.get("source_url", DEFAULT_MASSIVE_BASE_URL))
    adjusted = bool(raw.attrs.get("adjusted", True))
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
    frame["source"] = "massive"
    frame["source_tier"] = SourceTier.MARKET_DATA.value
    frame["source_url"] = source_url
    frame["timestamp_observed"] = fetched_at
    frame["timestamp_as_of"] = frame["date"]
    frame["freshness"] = "STALE"
    frame["confidence"] = _confidence(MassiveDailyConfig(api_key="local", adjusted=adjusted))
    frame["verification_level"] = VerificationLevel.CONFIRMED.value
    frame["source_id"] = frame["date"].map(lambda value: f"massive:{ticker.upper()}:{value}")
    return frame


async def _download_massive_history(
    ticker: str,
    requested: DateRange,
    config: MassiveDailyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None,
    limiter: MassiveApiLimiter,
) -> pd.DataFrame:
    rows: list[Mapping[str, object]] = []
    url = config.aggs_url(ticker, requested)
    params = _request_params(config)
    async with httpx.AsyncClient(
        timeout=config.timeout_seconds,
        transport=transport,
        verify=_verify_context(),
    ) as client:
        while True:
            await limiter.acquire(endpoint="daily_aggs", ticker=ticker)
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = _json_mapping(response)
            rows.extend(_results(payload))
            next_url = _next_url(payload)
            if next_url is None:
                break
            url = next_url
            params = {"apiKey": config.api_key} if "apiKey=" not in next_url else {}
    return _raw_frame(rows, ticker=ticker, requested=requested, config=config)


def _request_params(config: MassiveDailyConfig) -> dict[str, str]:
    return {
        "adjusted": str(config.adjusted).lower(),
        "sort": config.sort,
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
            raise TypeError("Massive aggregate rows must be JSON objects")
        rows.append(cast(Mapping[str, object], item))
    return rows


def _next_url(payload: Mapping[str, object]) -> str | None:
    value = payload.get("next_url")
    return value if isinstance(value, str) and value else None


def _raw_frame(
    rows: list[Mapping[str, object]],
    *,
    ticker: str,
    requested: DateRange,
    config: MassiveDailyConfig,
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame.attrs["ticker"] = ticker.upper()
    frame.attrs["source_url"] = config.aggs_url(ticker, requested)
    frame.attrs["requested_start"] = requested.start
    frame.attrs["requested_end"] = requested.end
    frame.attrs["adjusted"] = config.adjusted
    return frame


def _confidence(config: MassiveDailyConfig) -> float:
    return 0.9 if config.adjusted else 0.85


def _as_utc(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _verify_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
