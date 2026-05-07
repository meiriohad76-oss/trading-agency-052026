from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast

import pandas as pd

from agency.provenance import SourceTier, VerificationLevel, compute_freshness

Downloader = Callable[[str], Awaitable[pd.DataFrame]]


async def yfinance_options_downloader(ticker: str) -> pd.DataFrame:
    return await asyncio.to_thread(_download_options, ticker)


def normalize_options(ticker: str, raw: pd.DataFrame, *, fetched_at: datetime) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    frame.columns = [_normalize_column(column) for column in frame.columns]
    frame = frame.rename(
        columns={
            "lastprice": "last_price",
            "openinterest": "open_interest",
            "impliedvolatility": "implied_volatility",
            "inthemoney": "in_the_money",
        }
    )
    frame["ticker"] = ticker.upper()
    frame["snapshot_date"] = fetched_at.date()
    for column in ("volume", "open_interest"):
        frame[column] = (
            pd.to_numeric(_column(frame, column, 0), errors="coerce").fillna(0).astype("int64")
        )
    for column in ("strike", "last_price", "bid", "ask", "implied_volatility"):
        frame[column] = pd.to_numeric(_column(frame, column, 0.0), errors="coerce").fillna(0.0)
    if "in_the_money" not in frame.columns:
        frame["in_the_money"] = False
    frame["source"] = "yfinance"
    frame["source_tier"] = SourceTier.MARKET_DATA.value
    frame["source_url"] = f"https://finance.yahoo.com/quote/{ticker.upper()}/options"
    frame["timestamp_observed"] = fetched_at
    frame["timestamp_as_of"] = fetched_at
    frame["freshness"] = compute_freshness(fetched_at, "pricing", now=fetched_at).value
    frame["confidence"] = 0.65
    frame["verification_level"] = VerificationLevel.CONFIRMED.value
    frame["source_id"] = frame.apply(_source_id, axis=1)
    return frame


def _download_options(ticker: str) -> pd.DataFrame:
    yfinance = cast(Any, importlib.import_module("yfinance"))
    ticker_obj = yfinance.Ticker(ticker)
    frames: list[pd.DataFrame] = []
    for expiration in ticker_obj.options:
        chain = ticker_obj.option_chain(expiration)
        frames.append(_typed_chain(chain.calls, expiration, "call"))
        frames.append(_typed_chain(chain.puts, expiration, "put"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _typed_chain(frame: pd.DataFrame, expiration: str, option_type: str) -> pd.DataFrame:
    output = frame.copy()
    output["expiration"] = expiration
    output["option_type"] = option_type
    return output


def _source_id(row: pd.Series) -> str:
    return (
        f"yfinance-options:{row['ticker']}:{row['snapshot_date']}:{row['expiration']}:"
        f"{row['option_type']}:{row['strike']}"
    )


def _normalize_column(column: object) -> str:
    return str(column).strip().replace(" ", "_").replace("-", "_").lower()


def _column(frame: pd.DataFrame, column: str, default: float | int) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([default for _ in range(len(frame))], index=frame.index)
