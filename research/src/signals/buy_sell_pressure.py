from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from signals._common import score_dict, zscore

DEFAULT_LOOKBACK_DAYS = 3
PRE_MARKET_WEIGHT = 0.35
NET_NOTIONAL_WEIGHT = 0.45
NET_VOLUME_WEIGHT = 0.20


class StockTradesLoader(Protocol):
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def buy_sell_pressure_score(
    as_of: date,
    universe: set[str],
    loader: StockTradesLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return inferred buy/sell pressure from delayed confirmed stock prints."""
    return score_dict(
        buy_sell_pressure_frame(as_of, universe, loader, lookback_days),
        "buy_sell_pressure_score",
    )


def buy_sell_pressure_frame(
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
    try:
        raw = loader.stock_trades(tickers, as_of, lookback_days)
    except Exception:
        return _empty_frame()
    if raw.is_empty():
        return _empty_frame()
    frame = raw.to_pandas()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    rows = [
        row
        for ticker, group in frame.groupby("ticker", sort=True)
        if (row := _factor_row(str(ticker), group)) is not None
    ]
    output = pd.DataFrame(rows)
    if output.empty:
        return _empty_frame()
    output["buy_sell_pressure_score"] = zscore(output["buy_sell_pressure"])
    return output.sort_values(
        ["buy_sell_pressure_score", "ticker"],
        ascending=[False, True],
    ).reset_index(drop=True)


def _factor_row(ticker: str, group: pd.DataFrame) -> dict[str, object] | None:
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
    pre_market_volume = float(pre_market["__size"].sum())
    net_volume_pressure = _ratio(float(prepared["__signed_volume"].sum()), total_volume)
    net_notional_pressure = _ratio(float(prepared["__signed_notional"].sum()), total_notional)
    pre_market_net_pressure = _ratio(
        float(pre_market["__signed_volume"].sum()),
        pre_market_volume,
    )
    pre_market_volume_share = _ratio(pre_market_volume, total_volume)
    buy_sell_pressure = (
        NET_NOTIONAL_WEIGHT * net_notional_pressure
        + NET_VOLUME_WEIGHT * net_volume_pressure
        + PRE_MARKET_WEIGHT * pre_market_net_pressure * min(1.0, pre_market_volume_share * 4.0)
    )
    return {
        "ticker": ticker,
        "trade_count": len(prepared),
        "total_volume": total_volume,
        "total_notional": total_notional,
        "net_volume_pressure": net_volume_pressure,
        "net_notional_pressure": net_notional_pressure,
        "pre_market_volume": pre_market_volume,
        "pre_market_volume_share": pre_market_volume_share,
        "pre_market_net_pressure": pre_market_net_pressure,
        "buy_sell_pressure": buy_sell_pressure,
    }


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
            "pre_market_volume_share",
            "pre_market_net_pressure",
            "buy_sell_pressure",
            "buy_sell_pressure_score",
        ]
    )
