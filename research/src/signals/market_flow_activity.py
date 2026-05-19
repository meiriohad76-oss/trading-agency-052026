from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from market_flow.features import (
    DEFAULT_LOOKBACK_DAYS,
    MarketFlowFeatureConfig,
    market_flow_feature_frame,
)
from signals._common import directional_rank_score, score_dict


class StockTradesLoader(Protocol):
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def unusual_trade_activity_score(
    as_of: date,
    universe: set[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return signed unusual-trade activity from confirmed delayed prints."""
    return score_dict(
        unusual_trade_activity_frame(as_of, universe, loader, lookback_days),
        "unusual_trade_activity_score",
    )


def pre_market_unusual_activity_score(
    as_of: date,
    universe: set[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return signed pre-market unusual activity from confirmed delayed prints."""
    return score_dict(
        pre_market_unusual_activity_frame(as_of, universe, loader, lookback_days),
        "pre_market_unusual_activity_score",
    )


def market_flow_trend_score(
    as_of: date,
    universe: set[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return short trend in signed market-flow pressure."""
    return score_dict(
        market_flow_trend_frame(as_of, universe, loader, lookback_days),
        "market_flow_trend_score",
    )


def unusual_trade_activity_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    return _score_frame(
        as_of,
        universe,
        loader,
        lookback_days,
        feature="unusual_trade_activity",
        score_column="unusual_trade_activity_score",
    )


def pre_market_unusual_activity_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    return _score_frame(
        as_of,
        universe,
        loader,
        lookback_days,
        feature="pre_market_unusual_activity",
        score_column="pre_market_unusual_activity_score",
    )


def market_flow_trend_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    return _score_frame(
        as_of,
        universe,
        loader,
        lookback_days,
        feature="market_flow_trend",
        score_column="market_flow_trend_score",
    )


def _score_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    lookback_days: int,
    *,
    feature: str,
    score_column: str,
) -> pd.DataFrame:
    frame = market_flow_feature_frame(
        as_of,
        universe,
        loader,
        MarketFlowFeatureConfig(lookback_days=lookback_days),
    )
    if frame.empty:
        return _empty_frame(feature, score_column)
    output = frame.copy()
    output[score_column] = directional_rank_score(output[feature])
    return output.sort_values([score_column, "ticker"], ascending=[False, True]).reset_index(
        drop=True
    )


def _empty_frame(feature: str, score_column: str) -> pd.DataFrame:
    return pd.DataFrame(columns=["ticker", feature, score_column])
