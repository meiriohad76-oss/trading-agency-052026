from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl

FEATURE_COLUMNS = ("buy_sell_pressure", "block_trade_pressure")
DEFAULT_LOOKBACK_DAYS = 3


@dataclass(frozen=True)
class MarketFlowFeatureConfig:
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    pre_market_weight: float = 0.35
    net_notional_weight: float = 0.45
    net_volume_weight: float = 0.20


class StockTradesLoader(Protocol):
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def market_flow_feature_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    config: MarketFlowFeatureConfig | None = None,
) -> pd.DataFrame:
    normalized_config = config or MarketFlowFeatureConfig()
    if normalized_config.lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        raw = loader.stock_trades(tickers, as_of, normalized_config.lookback_days)
    except Exception:
        return _empty_frame()
    if raw.is_empty():
        return _empty_frame()
    frame = raw.to_pandas()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    rows = [
        row
        for ticker, group in frame.groupby("ticker", sort=True)
        if (row := _feature_row(str(ticker), group, normalized_config)) is not None
    ]
    output = pd.DataFrame(rows)
    return _empty_frame() if output.empty else output.sort_values("ticker").reset_index(drop=True)


def _feature_row(
    ticker: str,
    group: pd.DataFrame,
    config: MarketFlowFeatureConfig,
) -> dict[str, object] | None:
    prepared = group.assign(
        __size=_numeric(group, "size", 0.0),
        __notional=_notional(group),
        __signed_volume=_numeric(group, "signed_volume", 0.0),
        __signed_notional=_numeric(group, "signed_notional", 0.0),
    )
    total_volume = float(prepared["__size"].sum())
    total_notional = float(prepared["__notional"].sum())
    if total_volume <= 0.0 or total_notional <= 0.0:
        return None
    pre_market = prepared[_session_mask(prepared, "PRE_MARKET")]
    focus = prepared[_bool(prepared, "is_block_trade") | _bool(prepared, "is_off_exchange")]
    buy_sell_pressure = _buy_sell_pressure(prepared, pre_market, config, total_volume)
    block_trade_pressure = _block_trade_pressure(focus, total_notional)
    return {
        "ticker": ticker,
        "trade_count": len(prepared),
        "total_volume": total_volume,
        "total_notional": total_notional,
        "net_volume_pressure": _ratio(float(prepared["__signed_volume"].sum()), total_volume),
        "net_notional_pressure": _ratio(
            float(prepared["__signed_notional"].sum()),
            total_notional,
        ),
        "pre_market_volume": float(pre_market["__size"].sum()),
        "block_count": int(_bool(focus, "is_block_trade").sum()) if not focus.empty else 0,
        "off_exchange_count": int(_bool(focus, "is_off_exchange").sum()) if not focus.empty else 0,
        "focus_notional": float(focus["__notional"].sum()) if not focus.empty else 0.0,
        "buy_sell_pressure": buy_sell_pressure,
        "block_trade_pressure": block_trade_pressure,
    }


def _buy_sell_pressure(
    prepared: pd.DataFrame,
    pre_market: pd.DataFrame,
    config: MarketFlowFeatureConfig,
    total_volume: float,
) -> float:
    total_notional = float(prepared["__notional"].sum())
    pre_market_volume = float(pre_market["__size"].sum())
    pre_market_share = _ratio(pre_market_volume, total_volume)
    return (
        config.net_notional_weight
        * _ratio(float(prepared["__signed_notional"].sum()), total_notional)
        + config.net_volume_weight
        * _ratio(float(prepared["__signed_volume"].sum()), total_volume)
        + config.pre_market_weight
        * _ratio(float(pre_market["__signed_volume"].sum()), pre_market_volume)
        * min(1.0, pre_market_share * 4.0)
    )


def _block_trade_pressure(focus: pd.DataFrame, total_notional: float) -> float:
    if focus.empty:
        return 0.0
    focus_notional = float(focus["__notional"].sum())
    directional_pressure = _ratio(float(focus["__signed_notional"].sum()), focus_notional)
    activity_share = _ratio(focus_notional, total_notional)
    return directional_pressure * activity_share * math.log1p(len(focus))


def _numeric(frame: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default for _ in range(len(frame))], index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _notional(frame: pd.DataFrame) -> pd.Series:
    if "notional" in frame.columns:
        return _numeric(frame, "notional", 0.0)
    return _numeric(frame, "price", 0.0) * _numeric(frame, "size", 0.0)


def _session_mask(frame: pd.DataFrame, session: str) -> pd.Series:
    if "session" not in frame.columns:
        return pd.Series([False for _ in range(len(frame))], index=frame.index)
    return frame["session"].astype(str).str.upper() == session


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([False for _ in range(len(frame))], index=frame.index)
    return frame[column].fillna(False).astype(bool)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "trade_count",
            "total_volume",
            "total_notional",
            "net_volume_pressure",
            "net_notional_pressure",
            "pre_market_volume",
            "block_count",
            "off_exchange_count",
            "focus_notional",
            *FEATURE_COLUMNS,
        ]
    )
