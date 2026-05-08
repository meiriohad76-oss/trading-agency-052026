from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol

import pandas as pd
from signals._common import float_or_none, payload_dict, score_dict, zscore

DEFAULT_LOOKBACK_DAYS = 10
BLOCK_TRADE_TYPES = frozenset(
    {
        "block_trade",
        "dark_pool",
        "large_print",
        "trade_print",
        "unusual_stock_activity",
        "sweep",
    }
)
BULLISH_DIRECTIONS = frozenset({"BULLISH", "BUY", "CALL", "LONG"})
BEARISH_DIRECTIONS = frozenset({"BEARISH", "SELL", "PUT", "SHORT"})


class ActivityAlertsLoader(Protocol):
    def activity_alerts(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> Sequence[object]: ...


def activity_alert_score(
    as_of: date,
    universe: set[str],
    loader: ActivityAlertsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a PIT-safe confirmed unusual-activity alert score per ticker."""
    return score_dict(
        activity_alert_frame(as_of, universe, loader, lookback_days),
        "activity_alert_score",
    )


def activity_alert_frame(
    as_of: date,
    universe: Iterable[str],
    loader: ActivityAlertsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the provider/email alert cross-section known at `as_of`."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        alerts = loader.activity_alerts(tickers, as_of, lookback_days)
    except Exception:
        return _empty_frame()
    rows = _rows(tickers, alerts)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_frame()
    frame["activity_alert_score"] = zscore(frame["activity_pressure"])
    return frame.sort_values(
        ["activity_alert_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _rows(tickers: list[str], alerts: Sequence[object]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {ticker: [] for ticker in tickers}
    for alert in alerts:
        payload = payload_dict(alert, "activity alert")
        ticker = str(payload.get("ticker", "")).upper()
        if ticker in grouped:
            grouped[ticker].append(payload)
    return [_factor_row(ticker, values) for ticker, values in grouped.items() if values]


def _factor_row(ticker: str, alerts: list[dict[str, object]]) -> dict[str, object]:
    pressures = [_alert_pressure(alert) for alert in alerts]
    sources = {str(alert.get("source")) for alert in alerts if alert.get("source")}
    alert_types = [_alert_type(alert) for alert in alerts]
    return {
        "ticker": ticker,
        "alert_count": len(alerts),
        "source_count": len(sources),
        "block_trade_count": sum(1 for item in alert_types if item in BLOCK_TRADE_TYPES),
        "bullish_count": sum(1 for alert in alerts if _direction(alert) > 0),
        "bearish_count": sum(1 for alert in alerts if _direction(alert) < 0),
        "gross_activity": float(sum(abs(item) for item in pressures)),
        "activity_pressure": float(sum(pressures)),
    }


def _alert_pressure(alert: dict[str, object]) -> float:
    direction = _direction(alert)
    if direction == 0:
        return 0.0
    confidence = _confidence(alert)
    type_weight = 1.25 if _alert_type(alert) in BLOCK_TRADE_TYPES else 1.0
    return direction * confidence * type_weight * math.log1p(_magnitude(alert))


def _magnitude(alert: dict[str, object]) -> float:
    for column in ("notional", "premium"):
        value = float_or_none(alert.get(column))
        if value is not None and value > 0.0:
            return value
    price = float_or_none(alert.get("price"))
    volume = float_or_none(alert.get("volume"))
    if price is not None and volume is not None and price > 0.0 and volume > 0.0:
        return price * volume
    if volume is not None and volume > 0.0:
        return volume
    return 1.0


def _direction(alert: dict[str, object]) -> int:
    value = str(alert.get("direction", "")).upper().strip()
    if value in BULLISH_DIRECTIONS:
        return 1
    if value in BEARISH_DIRECTIONS:
        return -1
    return 0


def _alert_type(alert: dict[str, object]) -> str:
    return str(alert.get("alert_type", "")).lower().strip().replace("-", "_").replace(" ", "_")


def _confidence(alert: dict[str, object]) -> float:
    value = float_or_none(alert.get("confidence"))
    if value is None:
        return 1.0
    return min(1.0, max(0.0, value))


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "alert_count",
            "source_count",
            "block_trade_count",
            "bullish_count",
            "bearish_count",
            "gross_activity",
            "activity_pressure",
            "activity_alert_score",
        ]
    )
