from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from market_flow.features import MarketFlowFeatureConfig, market_flow_feature_frame
from signals._common import directional_rank_score, score_dict

DEFAULT_LOOKBACK_DAYS = 1


class StockTradesLoader(Protocol):
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def block_trade_pressure_score(
    as_of: date,
    universe: set[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return inferred pressure from large and off-exchange stock prints."""
    return score_dict(
        block_trade_pressure_frame(as_of, universe, loader, lookback_days),
        "block_trade_pressure_score",
    )


def block_trade_pressure_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    features = market_flow_feature_frame(
        as_of,
        tickers,
        loader,
        MarketFlowFeatureConfig(lookback_days=lookback_days),
    )
    if features.empty:
        return _empty_frame()
    columns = [
        "ticker",
        "trade_count",
        "focus_trade_count",
        "block_count",
        "off_exchange_count",
        "total_notional",
        "focus_notional",
        "focus_notional_share",
        "signed_focus_notional",
        "directional_pressure",
        "block_trade_pressure",
    ]
    output = features.loc[:, columns].copy()
    if output.empty:
        return _empty_frame()
    output["block_trade_pressure_score"] = directional_rank_score(output["block_trade_pressure"])
    return output.sort_values(
        ["block_trade_pressure_score", "ticker"],
        ascending=[False, True],
    ).reset_index(drop=True)


def _factor_row(ticker: str, group: pd.DataFrame) -> dict[str, object] | None:
    prepared = group.assign(
        __size=_numeric(group, "size", 0.0),
        __notional=_notional(group),
        __signed_notional=_numeric(group, "signed_notional", 0.0),
    )
    total_notional = float(prepared["__notional"].sum())
    if total_notional <= 0.0:
        return None
    focus = prepared[_bool(prepared, "is_block_trade") | _bool(prepared, "is_off_exchange")]
    if focus.empty:
        return None
    focus_notional = float(focus["__notional"].sum())
    signed_focus_notional = float(focus["__signed_notional"].sum())
    focus_count = len(focus)
    off_exchange_count = int(_bool(focus, "is_off_exchange").sum())
    block_count = int(_bool(focus, "is_block_trade").sum())
    activity_share = _ratio(focus_notional, total_notional)
    directional_pressure = _ratio(signed_focus_notional, focus_notional)
    block_trade_pressure = directional_pressure * activity_share * math.log1p(focus_count)
    return {
        "ticker": ticker,
        "trade_count": len(prepared),
        "focus_trade_count": focus_count,
        "block_count": block_count,
        "off_exchange_count": off_exchange_count,
        "total_notional": total_notional,
        "focus_notional": focus_notional,
        "focus_notional_share": activity_share,
        "signed_focus_notional": signed_focus_notional,
        "directional_pressure": directional_pressure,
        "block_trade_pressure": block_trade_pressure,
    }


def _numeric(frame: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default for _ in range(len(frame))], index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _notional(frame: pd.DataFrame) -> pd.Series:
    if "notional" in frame.columns:
        return _numeric(frame, "notional", 0.0)
    return _numeric(frame, "price", 0.0) * _numeric(frame, "size", 0.0)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([False for _ in range(len(frame))], index=frame.index)
    return frame[column].map(_bool_value).fillna(False).astype(bool)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value is pd.NA or value is pd.NaT:
        return False
    if isinstance(value, int | float):
        if isinstance(value, float) and pd.isna(value):
            return False
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "trade_count",
            "focus_trade_count",
            "block_count",
            "off_exchange_count",
            "total_notional",
            "focus_notional",
            "focus_notional_share",
            "signed_focus_notional",
            "directional_pressure",
            "block_trade_pressure",
            "block_trade_pressure_score",
        ]
    )
