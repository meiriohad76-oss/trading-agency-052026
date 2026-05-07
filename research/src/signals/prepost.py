from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from signals._common import positive_float, score_dict, zscore

DEFAULT_LOOKBACK_DAYS = 10


class PrePostLoader(Protocol):
    def prepost_bars(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...


def prepost_gap_score(
    as_of: date,
    universe: set[str],
    loader: PrePostLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a PIT-safe extended-hours gap-and-volume pressure score."""
    return score_dict(
        prepost_gap_frame(as_of, universe, loader, lookback_days=lookback_days),
        "prepost_gap_score",
    )


def prepost_gap_frame(
    as_of: date,
    universe: Iterable[str],
    loader: PrePostLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the pre/post-market pressure cross-section known at `as_of`."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        raw = loader.prepost_bars(tickers, as_of, lookback_days)
    except Exception:
        return _empty_frame()
    if raw.is_empty():
        return _empty_frame()
    frame = raw.to_pandas()
    price_column = _first_column(frame, ("prepost_close", "extended_close", "close"))
    reference_column = _first_column(frame, ("reference_close", "regular_close", "previous_close"))
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    rows = [
        row
        for ticker, group in frame.groupby("ticker", sort=True)
        if (row := _factor_row(str(ticker), group, price_column, reference_column)) is not None
    ]
    output = pd.DataFrame(rows)
    if output.empty:
        return _empty_frame()
    output["prepost_gap_score"] = zscore(output["prepost_pressure"])
    return output.sort_values(["prepost_gap_score", "ticker"], ascending=[False, True]).reset_index(
        drop=True
    )


def _factor_row(
    ticker: str,
    group: pd.DataFrame,
    price_column: str,
    reference_column: str,
) -> dict[str, object] | None:
    ordered = _ordered(group)
    latest = ordered.iloc[-1]
    latest_close = positive_float(latest.get(price_column))
    reference_close = positive_float(latest.get(reference_column))
    latest_volume = positive_float(latest.get("volume"))
    if latest_close is None or reference_close is None or latest_volume is None:
        return None
    baseline_volume = _baseline_volume(ordered.iloc[:-1], latest_volume)
    relative_volume = latest_volume / baseline_volume
    gap_return = latest_close / reference_close - 1.0
    pressure = gap_return * math.log1p(relative_volume)
    return {
        "ticker": ticker,
        "session": latest.get("session"),
        "gap_return": gap_return,
        "prepost_volume": latest_volume,
        "baseline_prepost_volume": baseline_volume,
        "relative_volume": relative_volume,
        "prepost_pressure": pressure,
    }


def _ordered(group: pd.DataFrame) -> pd.DataFrame:
    ordered = group.copy()
    if "session" in ordered.columns:
        ordered["__session_order"] = ordered["session"].map({"pre": 0, "post": 1}).fillna(0)
    else:
        ordered["__session_order"] = 0
    sort_columns = [column for column in ("date", "__session_order") if column in ordered.columns]
    return ordered.sort_values(sort_columns) if sort_columns else ordered


def _baseline_volume(history: pd.DataFrame, fallback: float) -> float:
    if history.empty or "volume" not in history.columns:
        return fallback
    values = pd.to_numeric(history["volume"], errors="coerce")
    values = values[values > 0.0]
    if values.empty:
        return fallback
    return float(values.median())


def _first_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    for column in candidates:
        if column in frame.columns:
            return column
    joined = ", ".join(candidates)
    raise ValueError(f"pre/post frame must include one of: {joined}")


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "session",
            "gap_return",
            "prepost_volume",
            "baseline_prepost_volume",
            "relative_volume",
            "prepost_pressure",
            "prepost_gap_score",
        ]
    )
