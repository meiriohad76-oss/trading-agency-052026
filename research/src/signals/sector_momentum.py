from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from pit.exceptions import DataNotAvailableAt
from prices.sector_etfs import SECTOR_ETF_SET, SECTOR_ETF_TICKERS
from signals._common import score_dict, zscore

DEFAULT_LOOKBACK_DAYS = 60
BROAD_MARKET_BENCHMARK = "SPY"
MIN_OBSERVATIONS = 2


class SectorETFLoader(Protocol):
    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame: ...


def sector_momentum_score(
    as_of: date,
    universe: set[str],
    loader: SectorETFLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a PIT-safe recent-momentum score for sector ETF tickers."""
    return score_dict(
        sector_momentum_frame(as_of, universe, loader, lookback_days=lookback_days),
        "sector_momentum_score",
    )


def sector_momentum_frame(
    as_of: date,
    universe: Iterable[str],
    loader: SectorETFLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the sector ETF relative-momentum cross-section known at `as_of`."""
    if lookback_days < MIN_OBSERVATIONS:
        raise ValueError("lookback_days must be >= 2")
    try:
        raw = loader.sector_etfs(as_of, lookback_days)
    except DataNotAvailableAt:
        return _empty_frame()
    if raw.is_empty():
        return _empty_frame()
    frame = raw.to_pandas()
    price_column = _price_column(frame)
    eligible = _eligible_etfs(universe)
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame = frame[frame["ticker"].isin(eligible)]
    rows = [
        row
        for ticker, group in frame.groupby("ticker", sort=True)
        if (row := _factor_row(str(ticker), group, price_column)) is not None
    ]
    output = pd.DataFrame(rows)
    if output.empty:
        return _empty_frame()
    spy_return = _spy_return(output)
    output["benchmark_return"] = spy_return
    output["excess_return"] = output["total_return"] - spy_return
    output["sector_momentum_score"] = zscore(output["excess_return"])
    return output.sort_values(
        ["sector_momentum_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _eligible_etfs(universe: Iterable[str]) -> set[str]:
    requested = {item.upper() for item in universe}
    requested_etfs = requested & SECTOR_ETF_SET
    return requested_etfs or set(SECTOR_ETF_TICKERS)


def _factor_row(ticker: str, group: pd.DataFrame, price_column: str) -> dict[str, object] | None:
    ordered = group.sort_values("date") if "date" in group.columns else group
    prices = pd.to_numeric(ordered[price_column], errors="coerce").dropna()
    if len(prices) < MIN_OBSERVATIONS:
        return None
    start_price = float(prices.iloc[0])
    end_price = float(prices.iloc[-1])
    if start_price <= 0.0 or end_price <= 0.0:
        return None
    return {
        "ticker": ticker,
        "observations": int(len(prices)),
        "start_price": start_price,
        "end_price": end_price,
        "total_return": end_price / start_price - 1.0,
    }


def _spy_return(frame: pd.DataFrame) -> float:
    spy = frame.loc[frame["ticker"] == BROAD_MARKET_BENCHMARK, "total_return"]
    if spy.empty:
        return 0.0
    return float(spy.iloc[0])


def _price_column(frame: pd.DataFrame) -> str:
    for column in ("adj_close", "close"):
        if column in frame.columns:
            return column
    raise ValueError("sector ETF frame must include adj_close or close")


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "observations",
            "start_price",
            "end_price",
            "total_return",
            "benchmark_return",
            "excess_return",
            "sector_momentum_score",
        ]
    )
