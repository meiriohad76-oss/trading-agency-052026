from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pandas as pd
from prices.storage import DateRange

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, instrumented_call

Downloader = Callable[[str, DateRange], Awaitable[pd.DataFrame]]


async def yfinance_downloader(ticker: str, requested: DateRange) -> pd.DataFrame:
    async def call() -> pd.DataFrame:
        return await asyncio.to_thread(_download_history, ticker, requested)

    wrapped = await instrumented_call(
        call,
        source="yfinance",
        source_tier=SourceTier.MARKET_DATA,
        source_id=f"{ticker}:{requested.start.isoformat()}:{requested.end.isoformat()}",
        verification_level=VerificationLevel.CONFIRMED,
        freshness_domain=FreshnessDomain.PRICING,
        timestamp_as_of=_as_utc(requested.end),
        confidence=0.8,
        source_url=f"https://finance.yahoo.com/quote/{ticker}/history",
    )
    return wrapped.value


def normalize_history(ticker: str, raw: pd.DataFrame, *, fetched_at: datetime) -> pd.DataFrame:
    if raw.empty:
        return _empty()
    frame = raw.copy().reset_index()
    frame.columns = [_normalize_column(column) for column in frame.columns]
    frame = frame.rename(
        columns={
            "adj close": "adj_close",
            "stock splits": "split_factor",
            "dividends": "dividend",
        }
    )
    if "date" not in frame.columns:
        frame = frame.rename(columns={frame.columns[0]: "date"})
    for column in ("dividend", "split_factor", "adj_close"):
        if column not in frame.columns:
            frame[column] = 0.0 if column != "adj_close" else frame["close"]
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.dropna(how="all", subset=["open", "high", "low", "close"])
    if frame.empty:
        return _empty()
    frame["ticker"] = ticker.upper()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    frame["volume"] = frame["volume"].fillna(0).astype("int64")
    frame["dividend"] = frame["dividend"].fillna(0.0).astype("float64")
    frame["split_factor"] = frame["split_factor"].fillna(0.0).replace(0.0, 1.0).astype("float64")
    frame["fetched_at"] = fetched_at
    frame["source"] = "yfinance"
    frame["source_tier"] = SourceTier.MARKET_DATA.value
    frame["source_url"] = f"https://finance.yahoo.com/quote/{ticker.upper()}/history"
    frame["timestamp_observed"] = fetched_at
    frame["timestamp_as_of"] = frame["date"]
    frame["freshness"] = "STALE"
    frame["confidence"] = 0.8
    frame["verification_level"] = VerificationLevel.CONFIRMED.value
    frame["source_id"] = frame["date"].map(lambda value: f"yfinance:{ticker.upper()}:{value}")
    return frame


def _download_history(ticker: str, requested: DateRange) -> pd.DataFrame:
    yfinance = cast(Any, importlib.import_module("yfinance"))
    history = yfinance.Ticker(ticker).history(
        start=requested.start.isoformat(),
        end=(requested.end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=True,
    )
    return cast(pd.DataFrame, history)


def _normalize_column(column: object) -> str:
    if isinstance(column, tuple):
        column = column[0]
    return str(column).strip().lower()


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def _as_utc(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)
