from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from pit.exceptions import DataNotAvailableAt
from signals._common import directional_rank_score, score_dict

DEFAULT_LOOKBACK_DAYS = 10
CONTRACT_MULTIPLIER = 100.0
MIN_UNUSUAL_VOLUME = 100.0
MIN_VOLUME_TO_OI = 2.0


class OptionsAnomalyLoader(Protocol):
    def option_chains(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def options_anomaly_score(
    as_of: date,
    universe: set[str],
    loader: OptionsAnomalyLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return an inferred options anomaly score from forward chain snapshots."""
    return score_dict(
        options_anomaly_frame(as_of, universe, loader, lookback_days),
        "options_anomaly_score",
    )


def options_anomaly_frame(
    as_of: date,
    universe: Iterable[str],
    loader: OptionsAnomalyLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        raw = loader.option_chains(tickers, as_of, lookback_days)
    except DataNotAvailableAt:
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
    output["options_anomaly_score"] = directional_rank_score(
        output["options_anomaly_pressure"]
    ) if len(output) >= 2 else 0.0
    return output.sort_values(
        ["options_anomaly_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _factor_row(ticker: str, group: pd.DataFrame) -> dict[str, object] | None:
    latest = _latest_snapshot(group)
    if latest.empty:
        return None
    priced = latest.assign(
        __volume=pd.to_numeric(_column(latest, "volume", 0), errors="coerce").fillna(0.0),
        __open_interest=pd.to_numeric(
            _column(latest, "open_interest", 0),
            errors="coerce",
        ).fillna(0.0),
        __premium=_premium(latest),
    )
    if float(priced["__volume"].sum()) <= 0.0:
        return None
    calls = priced.loc[priced["option_type"] == "call"]
    puts = priced.loc[priced["option_type"] == "put"]
    call_premium = float(calls["__premium"].sum())
    put_premium = float(puts["__premium"].sum())
    gross_premium = call_premium + put_premium
    net_premium = call_premium - put_premium
    total_volume = float(priced["__volume"].sum())
    total_oi = float(priced["__open_interest"].sum())
    volume_to_oi = total_volume / total_oi if total_oi > 0.0 else float("inf")
    pressure = _signed_pressure(net_premium, gross_premium, volume_to_oi)
    return {
        "ticker": ticker,
        "snapshot_date": priced["snapshot_date"].iloc[0],
        "timestamp_as_of": _latest_timestamp_as_of(priced),
        "total_option_volume": total_volume,
        "total_open_interest": total_oi,
        "volume_to_open_interest": volume_to_oi,
        "unusual_contract_count": _unusual_contract_count(priced),
        "call_premium": call_premium,
        "put_premium": put_premium,
        "gross_premium": gross_premium,
        "net_premium": net_premium,
        "options_anomaly_pressure": pressure,
    }


def _premium(frame: pd.DataFrame) -> pd.Series:
    bid = pd.to_numeric(_column(frame, "bid", 0.0), errors="coerce").fillna(0.0)
    ask = pd.to_numeric(_column(frame, "ask", 0.0), errors="coerce").fillna(0.0)
    last = pd.to_numeric(_column(frame, "last_price", 0.0), errors="coerce").fillna(0.0)
    mid = (bid + ask) / 2.0
    price = mid.where(mid > 0.0, last)
    volume = pd.to_numeric(_column(frame, "volume", 0), errors="coerce").fillna(0.0)
    return price * volume * CONTRACT_MULTIPLIER


def _signed_pressure(net_premium: float, gross_premium: float, volume_to_oi: float) -> float:
    if gross_premium <= 0.0 or net_premium == 0.0:
        return 0.0
    ratio_boost = math.log1p(volume_to_oi if math.isfinite(volume_to_oi) else MIN_VOLUME_TO_OI)
    return math.copysign(math.log1p(gross_premium) * ratio_boost, net_premium)


def _unusual_contract_count(frame: pd.DataFrame) -> int:
    volume = frame["__volume"]
    oi = frame["__open_interest"]
    ratio = pd.Series(
        [
            float("inf") if open_interest <= 0.0 else option_volume / open_interest
            for option_volume, open_interest in zip(volume, oi, strict=True)
        ],
        index=frame.index,
    )
    return int(((volume >= MIN_UNUSUAL_VOLUME) & ((oi <= 0.0) | (ratio >= MIN_VOLUME_TO_OI))).sum())


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


def _latest_timestamp_as_of(frame: pd.DataFrame) -> object:
    if "timestamp_as_of" not in frame.columns:
        return None
    timestamps = pd.to_datetime(frame["timestamp_as_of"], errors="coerce", utc=True).dropna()
    return None if timestamps.empty else timestamps.max().to_pydatetime()


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "snapshot_date",
            "timestamp_as_of",
            "total_option_volume",
            "total_open_interest",
            "volume_to_open_interest",
            "unusual_contract_count",
            "call_premium",
            "put_premium",
            "gross_premium",
            "net_premium",
            "options_anomaly_pressure",
            "options_anomaly_score",
        ]
    )
