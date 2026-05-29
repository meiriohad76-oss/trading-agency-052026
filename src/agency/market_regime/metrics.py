from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def metrics_by_ticker(bars: Mapping[str, object]) -> dict[str, dict[str, object]]:
    return {
        ticker.upper(): _metric(rows(raw_rows))
        for ticker, raw_rows in bars.items()
        if rows(raw_rows)
    }


def latest_date(metrics: Mapping[str, Mapping[str, object]]) -> str | None:
    dates = [str(metric.get("latest_date", "")) for metric in metrics.values()]
    return max([value for value in dates if value], default=None)


def sector_spread(sector_map: Mapping[str, Mapping[str, object]]) -> float | None:
    scores = [number(row.get("score")) for row in sector_map.values()]
    usable = [score for score in scores if score is not None]
    return max(usable) - min(usable) if len(usable) >= 2 else None


def rows(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in value] if isinstance(value, list) else []


def mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


def percent_label(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}%"


def _metric(input_rows: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(input_rows, key=lambda row: str(row.get("date", "")))
    closes = [number(row.get("close")) for row in ordered]
    usable_closes = [close for close in closes if close is not None and close > 0.0]
    latest = ordered[-1]
    latest_close = number(latest.get("close"))
    fallback_return = _pct(latest_close, number(latest.get("open")))
    daily_returns = [
        (usable_closes[index] / usable_closes[index - 1] - 1.0) * 100.0
        for index in range(1, len(usable_closes))
        if usable_closes[index - 1] > 0.0
    ]
    return {
        "latest_date": str(latest.get("date", "")),
        "latest_price": latest_close,
        "return_5d_pct": _window_return(usable_closes, 5, fallback_return),
        "return_20d_pct": _window_return(usable_closes, 20, fallback_return),
        "return_60d_pct": _window_return(usable_closes, 60, fallback_return),
        "realized_vol_10d": _realized_vol(daily_returns[-10:]),
        "cmf_14": _cmf(ordered[-14:]),
        "obv_trend": _obv_trend(ordered),
    }


def _window_return(closes: Sequence[float], sessions: int, fallback: float | None) -> float | None:
    if len(closes) < 2:
        return fallback
    return _pct(closes[-1], closes[max(0, len(closes) - sessions - 1)])


def _realized_vol(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252), 2)


def _cmf(input_rows: Sequence[Mapping[str, object]]) -> float | None:
    volume_sum = 0.0
    flow_sum = 0.0
    for row in input_rows:
        high = number(row.get("high"))
        low = number(row.get("low"))
        close = number(row.get("close"))
        volume = number(row.get("volume")) or 0.0
        if high is None or low is None or close is None or high == low:
            continue
        flow_sum += (((close - low) - (high - close)) / (high - low)) * volume
        volume_sum += volume
    return round(flow_sum / volume_sum, 4) if volume_sum else None


def _obv_trend(input_rows: Sequence[Mapping[str, object]]) -> str:
    if len(input_rows) < 2:
        latest = input_rows[-1] if input_rows else {}
        return "UP" if (number(latest.get("close")) or 0.0) >= (
            number(latest.get("open")) or 0.0
        ) else "DOWN"
    first = number(input_rows[0].get("close")) or 0.0
    last = number(input_rows[-1].get("close")) or 0.0
    return "UP" if last >= first else "DOWN"


def _pct(end: float | None, start: float | None) -> float | None:
    if end is None or start is None or start <= 0.0:
        return None
    return round((end / start - 1.0) * 100.0, 2)
