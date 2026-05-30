from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from signals.calibration import DEFAULT_THRESHOLDS

EASTERN = ZoneInfo("America/New_York")
PRE_MARKET_START = time(4, 0)
REGULAR_START = time(9, 30)
REGULAR_END = time(16, 0)
AFTER_HOURS_END = time(20, 0)
DEFAULT_BLOCK_NOTIONAL = DEFAULT_THRESHOLDS.block_absolute_notional_floor
DEFAULT_BLOCK_SIZE = DEFAULT_THRESHOLDS.block_absolute_shares_floor
TRF_EXCHANGE_CODE = "4"
TRF_VENUES = {
    "201": "FINRA/NYSE TRF",
    "202": "FINRA/NASDAQ TRF Carteret",
    "203": "FINRA/NASDAQ TRF Chicago",
}


@dataclass(frozen=True)
class MarketFlowSummary:
    ticker: str
    trade_count: int
    total_volume: float
    total_notional: float
    buy_volume: float
    sell_volume: float
    net_volume_pressure: float
    net_notional_pressure: float
    block_count: int
    off_exchange_count: int
    pre_market_volume: float
    pre_market_net_pressure: float


def classify_trades(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    output = frame.copy()
    output["trade_ts"] = pd.to_datetime(output["trade_ts"], utc=True)
    output["price"] = pd.to_numeric(output["price"], errors="coerce")
    output["size"] = pd.to_numeric(output["size"], errors="coerce").fillna(0.0)
    if "sequence_number" not in output.columns:
        output["sequence_number"] = 0
    output["sequence_number"] = (
        pd.to_numeric(output["sequence_number"], errors="coerce").fillna(0).astype("int64")
    )
    if "trade_id" not in output.columns:
        output["trade_id"] = ""
    output["trade_id"] = output["trade_id"].fillna("").astype(str)
    output = output.dropna(subset=["ticker", "trade_ts", "price"])
    output = output[output["size"] > 0.0]
    if output.empty:
        return output
    output["ticker"] = output["ticker"].astype(str).str.upper()
    output = output.sort_values(["ticker", "trade_ts", "sequence_number", "trade_id"])
    output["eligible"] = output.apply(_eligible_row, axis=1)
    output = output[output["eligible"]].copy()
    if output.empty:
        return output
    output["trade_date"] = output["trade_ts"].map(_local_date)
    output["session"] = output["trade_ts"].map(_session)
    output["notional"] = output["price"] * output["size"]
    output["direction"], output["direction_method"], output["direction_confidence"] = (
        _trade_direction(output)
    )
    output["signed_volume"] = output["direction"] * output["size"]
    output["signed_notional"] = output["direction"] * output["notional"]
    output["is_trf_off_exchange"] = output.apply(_trf_off_exchange_row, axis=1)
    output["trf_venue"] = output.apply(_trf_venue, axis=1)
    output["is_off_exchange"] = output.apply(_off_exchange_row, axis=1)
    output["is_block_trade"] = (output["notional"] >= DEFAULT_BLOCK_NOTIONAL) | (
        output["size"] >= DEFAULT_BLOCK_SIZE
    )
    return output.reset_index(drop=True)


def summarize_market_flow(classified: pd.DataFrame) -> list[MarketFlowSummary]:
    if classified.empty:
        return []
    rows: list[MarketFlowSummary] = []
    for ticker, group in classified.groupby("ticker"):
        total_volume = float(group["size"].sum())
        total_notional = float(group["notional"].sum())
        buy_volume = float(group.loc[group["direction"] > 0, "size"].sum())
        sell_volume = float(group.loc[group["direction"] < 0, "size"].sum())
        pre_market = group[group["session"] == "PRE_MARKET"]
        pre_market_volume = float(pre_market["size"].sum())
        rows.append(
            MarketFlowSummary(
                ticker=str(ticker),
                trade_count=len(group),
                total_volume=total_volume,
                total_notional=total_notional,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
                net_volume_pressure=_ratio(float(group["signed_volume"].sum()), total_volume),
                net_notional_pressure=_ratio(
                    float(group["signed_notional"].sum()),
                    total_notional,
                ),
                block_count=int(group["is_block_trade"].sum()),
                off_exchange_count=int(group["is_off_exchange"].sum()),
                pre_market_volume=pre_market_volume,
                pre_market_net_pressure=_ratio(
                    float(pre_market["signed_volume"].sum()),
                    pre_market_volume,
                ),
            )
        )
    return rows


def _eligible_row(row: pd.Series) -> bool:
    correction = row.get("correction")
    if not _is_blank(correction) and correction not in (0, "0"):
        return False
    return float(row["price"]) > 0.0 and float(row["size"]) > 0.0


def _tick_test_direction(frame: pd.DataFrame) -> pd.Series:
    price_diff = frame.groupby("ticker")["price"].diff()
    raw = price_diff.map(lambda value: 1 if value > 0 else (-1 if value < 0 else 0))
    carried = raw.replace(0, pd.NA).groupby(frame["ticker"]).ffill().fillna(0)
    return carried.astype("int64")


def _trade_direction(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    tick_direction = _tick_test_direction(frame)
    quote_direction = _quote_rule_direction(frame)
    has_quote = quote_direction != 0
    direction = quote_direction.where(has_quote, tick_direction).astype("int64")
    method = pd.Series("tick_test", index=frame.index, dtype="object")
    method.loc[has_quote] = "quote_rule"
    confidence = pd.Series(0.55, index=frame.index, dtype="float64")
    confidence.loc[has_quote] = 0.90
    confidence.loc[direction == 0] = 0.0
    return direction, method, confidence


def _quote_rule_direction(frame: pd.DataFrame) -> pd.Series:
    if "bid" not in frame.columns or "ask" not in frame.columns:
        return pd.Series(0, index=frame.index, dtype="int64")
    bid = pd.to_numeric(frame["bid"], errors="coerce")
    ask = pd.to_numeric(frame["ask"], errors="coerce")
    price = pd.to_numeric(frame["price"], errors="coerce")
    midpoint = (bid + ask) / 2.0
    valid = bid.gt(0.0) & ask.gt(bid) & price.gt(0.0)
    direction = pd.Series(0, index=frame.index, dtype="int64")
    direction.loc[valid & price.gt(midpoint)] = 1
    direction.loc[valid & price.lt(midpoint)] = -1
    return direction


def _local_date(value: pd.Timestamp) -> object:
    return value.tz_convert(EASTERN).date()


def _session(value: pd.Timestamp) -> str:
    local_time = value.tz_convert(EASTERN).time()
    if PRE_MARKET_START <= local_time < REGULAR_START:
        return "PRE_MARKET"
    if REGULAR_START <= local_time < REGULAR_END:
        return "REGULAR"
    if REGULAR_END <= local_time < AFTER_HOURS_END:
        return "AFTER_HOURS"
    return "OUT_OF_SESSION"


def _off_exchange_row(row: pd.Series) -> bool:
    if _trf_off_exchange_row(row):
        return True
    for column in ("trf_id", "trf_timestamp"):
        value = row.get(column)
        if not _is_blank(value):
            return True
    text = f"{row.get('exchange', '')} {row.get('conditions', '')}".upper()
    return any(marker in text for marker in ("TRF", "FINRA", "DARK", "OFF_EXCHANGE"))


def _trf_off_exchange_row(row: pd.Series) -> bool:
    return _normalized_text(row.get("exchange")) == TRF_EXCHANGE_CODE and not _is_blank(
        row.get("trf_id")
    )


def _trf_venue(row: pd.Series) -> str:
    if not _trf_off_exchange_row(row):
        return ""
    trf_id = _normalized_text(row.get("trf_id"))
    return TRF_VENUES.get(trf_id, f"FINRA TRF {trf_id}" if trf_id else "FINRA TRF")


def _normalized_text(value: Any) -> str:
    if _is_blank(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError, ValueError:
        return False
    return isinstance(value, str) and value.strip() == ""


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator
