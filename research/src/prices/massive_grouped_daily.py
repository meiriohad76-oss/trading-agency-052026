from __future__ import annotations

import os
import ssl
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import import_module
from typing import Self, cast

import httpx
import pandas as pd

from agency.provenance import SourceTier, VerificationLevel

DEFAULT_MASSIVE_BASE_URL = "https://api.polygon.io"
GROUPED_DAILY_PATH_TEMPLATE = "/v2/aggs/grouped/locale/us/market/stocks/{day}"


@dataclass(frozen=True)
class MassiveGroupedDailyConfig:
    api_key: str
    base_url: str = DEFAULT_MASSIVE_BASE_URL
    adjusted: bool = True
    timeout_seconds: float = 60.0

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

    def grouped_url(self, day: date) -> str:
        path = GROUPED_DAILY_PATH_TEMPLATE.format(day=day.isoformat())
        return f"{self.base_url.rstrip('/')}{path}"


async def pull_massive_grouped_daily(
    *,
    day: date,
    tickers: Iterable[str],
    config: MassiveGroupedDailyConfig,
    transport: httpx.AsyncBaseTransport | None = None,
    fetched_at: datetime | None = None,
) -> pd.DataFrame:
    requested = {ticker.upper() for ticker in tickers}
    if not requested:
        return pd.DataFrame()
    payload = await _download_grouped_daily(day, config, transport=transport)
    return normalize_massive_grouped_daily(
        day=day,
        rows=_results(payload),
        tickers=requested,
        source_url=config.grouped_url(day),
        fetched_at=fetched_at or datetime.now(UTC),
    )


def normalize_massive_grouped_daily(
    *,
    day: date,
    rows: list[Mapping[str, object]],
    tickers: set[str],
    source_url: str,
    fetched_at: datetime,
) -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    if raw.empty:
        return pd.DataFrame()
    missing = {"T", "o", "h", "l", "c", "v"}.difference(raw.columns)
    if missing:
        raise ValueError(f"Massive grouped daily rows missing column(s): {sorted(missing)}")
    frame = raw.copy()
    frame["ticker"] = frame["T"].astype(str).str.upper()
    frame = frame[frame["ticker"].isin(tickers)]
    if frame.empty:
        return pd.DataFrame()
    for source, target in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        frame[target] = pd.to_numeric(frame[source], errors="coerce")
    frame = frame.dropna(how="all", subset=["open", "high", "low", "close"])
    if frame.empty:
        return pd.DataFrame()
    frame["date"] = day
    frame["year"] = day.year
    frame["adj_close"] = frame["close"]
    frame["volume"] = pd.to_numeric(frame["v"], errors="coerce").fillna(0).astype("int64")
    frame["dividend"] = 0.0
    frame["split_factor"] = 1.0
    frame["fetched_at"] = fetched_at
    frame["source"] = "massive"
    frame["source_tier"] = SourceTier.MARKET_DATA.value
    frame["source_url"] = source_url
    frame["timestamp_observed"] = fetched_at
    frame["timestamp_as_of"] = day
    frame["freshness"] = "FRESH"
    frame["confidence"] = 0.9
    frame["verification_level"] = VerificationLevel.CONFIRMED.value
    frame["source_id"] = frame["ticker"].map(lambda ticker: f"massive-grouped:{ticker}:{day}")
    return frame


async def _download_grouped_daily(
    day: date,
    config: MassiveGroupedDailyConfig,
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> Mapping[str, object]:
    async with httpx.AsyncClient(
        timeout=config.timeout_seconds,
        transport=transport,
        verify=_verify_context(),
    ) as client:
        response = await client.get(
            config.grouped_url(day),
            params={
                "adjusted": str(config.adjusted).lower(),
                "apiKey": config.api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, Mapping):
        raise TypeError("Massive grouped daily response must be a JSON object")
    return cast(Mapping[str, object], payload)


def _results(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = payload.get("results", [])
    if not isinstance(value, list):
        raise TypeError("Massive grouped daily results must be a list")
    rows: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("Massive grouped daily rows must be JSON objects")
        rows.append(cast(Mapping[str, object], item))
    return rows


def _verify_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
