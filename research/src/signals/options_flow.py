from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from signals._common import score_dict, zscore

DEFAULT_LOOKBACK_DAYS = 10


class OptionsLoader(Protocol):
    def option_chains(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def options_flow_score(
    as_of: date,
    universe: set[str],
    loader: OptionsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a forward options-chain call/put pressure score per ticker."""
    return score_dict(
        options_flow_frame(as_of, universe, loader, lookback_days),
        "options_flow_score",
    )


def options_flow_frame(
    as_of: date,
    universe: Iterable[str],
    loader: OptionsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the latest options snapshot cross-section known at `as_of`."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        raw = loader.option_chains(tickers, as_of, lookback_days)
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
    output["options_flow_score"] = zscore(output["options_pressure"])
    return output.sort_values(
        ["options_flow_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _factor_row(ticker: str, group: pd.DataFrame) -> dict[str, object] | None:
    latest = _latest_snapshot(group)
    if latest.empty:
        return None
    volumes = pd.to_numeric(_column(latest, "volume", 0), errors="coerce").fillna(0.0)
    latest = latest.assign(__volume=volumes)
    call_volume = float(latest.loc[latest["option_type"] == "call", "__volume"].sum())
    put_volume = float(latest.loc[latest["option_type"] == "put", "__volume"].sum())
    total_volume = call_volume + put_volume
    if total_volume <= 0.0:
        return None
    call_share = call_volume / total_volume
    pressure = (call_share - 0.5) * math.log1p(total_volume)
    open_interest = pd.to_numeric(_column(latest, "open_interest", 0), errors="coerce").fillna(0.0)
    implied_vol = pd.to_numeric(_column(latest, "implied_volatility", 0.0), errors="coerce")
    return {
        "ticker": ticker,
        "snapshot_date": latest["snapshot_date"].iloc[0],
        "call_volume": call_volume,
        "put_volume": put_volume,
        "total_volume": total_volume,
        "call_share": call_share,
        "put_call_volume_ratio": put_volume / call_volume if call_volume > 0.0 else float("inf"),
        "open_interest": float(open_interest.sum()),
        "mean_implied_volatility": float(implied_vol.dropna().mean()),
        "options_pressure": pressure,
    }


def _latest_snapshot(group: pd.DataFrame) -> pd.DataFrame:
    if "snapshot_date" not in group.columns:
        return group
    dates = pd.to_datetime(group["snapshot_date"], errors="coerce")
    if dates.dropna().empty:
        return pd.DataFrame()
    return group.loc[dates == dates.max()]


def _column(frame: pd.DataFrame, column: str, default: float | int) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([default for _ in range(len(frame))], index=frame.index)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "snapshot_date",
            "call_volume",
            "put_volume",
            "total_volume",
            "call_share",
            "put_call_volume_ratio",
            "open_interest",
            "mean_implied_volatility",
            "options_pressure",
            "options_flow_score",
        ]
    )
