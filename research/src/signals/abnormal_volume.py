from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from pit.exceptions import DataNotAvailableAt
from signals._common import directional_rank_score, positive_float, score_dict

DEFAULT_LOOKBACK_DAYS = 60
MIN_OBSERVATIONS = 2


class PriceLoader(Protocol):
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...


def abnormal_volume_score(
    as_of: date,
    universe: set[str],
    loader: PriceLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a PIT-safe directional abnormal-volume score per ticker."""
    return score_dict(
        abnormal_volume_frame(as_of, universe, loader, lookback_days=lookback_days),
        "abnormal_volume_score",
    )


def abnormal_volume_frame(
    as_of: date,
    universe: Iterable[str],
    loader: PriceLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the daily-bar abnormal-volume cross-section known at `as_of`."""
    if lookback_days < MIN_OBSERVATIONS:
        raise ValueError("lookback_days must be >= 2")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        raw = loader.prices(tickers, as_of, lookback_days)
    except DataNotAvailableAt:
        return _empty_frame()
    if raw.is_empty():
        return _empty_frame()
    frame = raw.to_pandas()
    price_column = _price_column(frame)
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    rows = [
        row
        for ticker, group in frame.groupby("ticker", sort=True)
        if (row := _factor_row(str(ticker), group, price_column)) is not None
    ]
    output = pd.DataFrame(rows)
    if output.empty:
        return _empty_frame()
    output["abnormal_volume_score"] = (
        directional_rank_score(output["signed_volume_pressure"])
        if len(output) >= MIN_OBSERVATIONS
        else 0.0
    )
    return output.sort_values(
        ["abnormal_volume_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _factor_row(ticker: str, group: pd.DataFrame, price_column: str) -> dict[str, object] | None:
    ordered = group.sort_values("date") if "date" in group.columns else group
    if len(ordered) < MIN_OBSERVATIONS:
        return None
    latest = ordered.iloc[-1]
    history = ordered.iloc[:-1]
    latest_volume = positive_float(latest.get("volume"))
    baseline_volume = _positive_median(history["volume"])
    latest_price = positive_float(latest.get(price_column))
    previous_price = _latest_positive(history[price_column])
    if (
        latest_volume is None
        or baseline_volume is None
        or latest_price is None
        or previous_price is None
    ):
        return None
    latest_return = latest_price / previous_price - 1.0
    volume_ratio = latest_volume / baseline_volume
    signed_pressure = _sign(latest_return) * max(math.log(volume_ratio), 0.0)
    return {
        "ticker": ticker,
        "latest_volume": latest_volume,
        "baseline_volume": baseline_volume,
        "volume_ratio": volume_ratio,
        "latest_return": latest_return,
        "signed_volume_pressure": signed_pressure,
    }


def _positive_median(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce")
    values = values[values > 0.0]
    if values.empty:
        return None
    return float(values.median())


def _latest_positive(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce")
    values = values[values > 0.0]
    if values.empty:
        return None
    return float(values.iloc[-1])


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def _price_column(frame: pd.DataFrame) -> str:
    for column in ("adj_close", "close"):
        if column in frame.columns:
            return column
    raise ValueError("price frame must include adj_close or close")


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "latest_volume",
            "baseline_volume",
            "volume_ratio",
            "latest_return",
            "signed_volume_pressure",
            "abnormal_volume_score",
        ]
    )
