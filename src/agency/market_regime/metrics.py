from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

MACRO_SERIES_IDS: tuple[str, ...] = (
    "VIXCLS",
    "T10Y2Y",
    "DGS10",
    "BAMLH0A0HYM2",
    "BAMLC0A0CM",
    "STLFSI4",
    "ICSA",
)

MACRO_PROXY_IDS: tuple[str, ...] = ("TLT", "GLD", "UUP")

_MACRO_LABELS: dict[str, str] = {
    "VIXCLS": "VIX",
    "T10Y2Y": "10Y-2Y",
    "DGS10": "10Y yield",
    "BAMLH0A0HYM2": "High yield spread",
    "BAMLC0A0CM": "IG spread",
    "STLFSI4": "Fed stress",
    "ICSA": "Jobless claims",
    "TLT": "Long bonds",
    "GLD": "Gold",
    "UUP": "US dollar",
}


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
    if not isinstance(value, int | float | str):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


def percent_label(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}%"


def build_macro_tiles(
    series: Mapping[str, object],
    proxies: Mapping[str, object],
) -> list[dict[str, object]]:
    """Return operator-ready macro tiles for FRED series and proxy ETFs."""
    tiles = [_macro_series_tile(series_id, series.get(series_id)) for series_id in MACRO_SERIES_IDS]
    tiles.extend(_macro_proxy_tile(proxy_id, proxies.get(proxy_id)) for proxy_id in MACRO_PROXY_IDS)
    return tiles


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
        "return_20d_pct_5d_ago": _window_return_offset(usable_closes, 20, 5),
        "realized_vol_10d": _realized_vol(daily_returns[-10:]),
        "cmf_14": _cmf(ordered[-14:]),
        "obv_trend": _obv_trend(ordered),
    }


def _window_return(closes: Sequence[float], sessions: int, fallback: float | None) -> float | None:
    if len(closes) < 2:
        return fallback
    return _pct(closes[-1], closes[max(0, len(closes) - sessions - 1)])


def _window_return_offset(closes: Sequence[float], sessions: int, offset: int) -> float | None:
    if len(closes) < sessions + offset + 1:
        return None
    tail = closes[: len(closes) - offset]
    return _window_return(tail, sessions, None)


def _macro_series_tile(series_id: str, raw_rows: object) -> dict[str, object]:
    series_rows = rows(raw_rows)
    latest = series_rows[-1] if series_rows else {}
    latest_value = number(latest.get("value"))
    prior_value = number(series_rows[-2].get("value")) if len(series_rows) >= 2 else None
    tile_class, trend, gauge = _classify_macro_series(series_id, latest_value, prior_value)
    return {
        "id": series_id,
        "label": _MACRO_LABELS.get(series_id, series_id),
        "value": _number_label(latest_value),
        "raw_value": latest_value,
        "class": tile_class,
        "trend": trend,
        "delta": _delta_label(latest_value, prior_value),
        "as_of": str(latest.get("date") or latest.get("timestamp") or "not recorded"),
        "gauge_style": _gauge_style(gauge),
    }


def _macro_proxy_tile(proxy_id: str, raw_value: object) -> dict[str, object]:
    value = number(raw_value)
    tile_class, trend, gauge = _classify_macro_proxy(proxy_id, value)
    return {
        "id": proxy_id,
        "label": _MACRO_LABELS.get(proxy_id, proxy_id),
        "value": "n/a" if value is None else f"{value:+.1f}%",
        "raw_value": value,
        "class": tile_class,
        "trend": trend,
        "delta": "5D proxy",
        "as_of": "latest ETF close",
        "gauge_style": _gauge_style(gauge),
    }


def _classify_macro_series(
    series_id: str,
    latest: float | None,
    prior: float | None,
) -> tuple[str, str, float]:
    if latest is None:
        return "neutral", "No reading", 0.0
    delta = latest - prior if prior is not None else 0.0
    if series_id == "VIXCLS":
        if latest > 35.0:
            return "block", "High fear", latest / 45.0
        if latest >= 20.0:
            return "warn", "Elevated fear", latest / 35.0
        return "pass", "Calm fear", latest / 20.0
    if series_id == "T10Y2Y":
        if latest < 0.0:
            return "warn", "Curve inverted", min(1.0, abs(latest) / 1.0)
        return "pass" if latest >= 0.75 else "neutral", "Curve normalizing", min(1.0, latest / 1.5)
    if series_id == "BAMLH0A0HYM2":
        # HY spread: warn if 5D delta > 50 bps; pass if tightening > 10 bps
        if delta > 0.50:
            return "warn", "Spreads widening", min(1.0, delta / 2.0)
        if delta < -0.10:
            return "pass", "Spreads tightening", min(1.0, abs(delta) / 1.0)
        return "neutral", "Spreads stable", min(1.0, latest / 800.0)
    if series_id == "BAMLC0A0CM":
        if delta > 0.25:
            return "warn", "IG spreads widening", min(1.0, delta / 1.0)
        if delta < -0.10:
            return "pass", "IG spreads tightening", min(1.0, abs(delta) / 1.0)
        return "neutral", "IG spreads stable", min(1.0, latest / 300.0)
    if series_id == "STLFSI4":
        # FSI: level-based (positive = above-average stress)
        if latest > 0.5:
            return "warn", "Stress elevated", min(1.0, latest / 5.0)
        if latest < 0.0:
            return "pass", "Stress below average", min(1.0, abs(latest) / 3.0)
        return "neutral", "Stress normal", min(1.0, latest / 0.5)
    if series_id == "ICSA":
        # Jobless claims: level-based threshold
        if latest > 300_000:
            return "warn", "Claims elevated", min(1.0, latest / 400_000)
        return "pass", "Claims normal", min(1.0, latest / 300_000)
    if series_id == "DGS10":
        if delta > 0.2:
            return "warn", "Yields rising", min(1.0, delta / 1.0)
        if delta < -0.2:
            return "pass", "Yields easing", min(1.0, abs(delta) / 1.0)
        return "neutral", "Yield stable", min(1.0, latest / 6.0)
    return "neutral", "Stable", 0.25


def _classify_macro_proxy(proxy_id: str, value: float | None) -> tuple[str, str, float]:
    if value is None:
        return "neutral", "No proxy", 0.0
    magnitude = min(1.0, abs(value) / 3.0)
    if proxy_id == "TLT" and value >= 1.0:
        return "warn", "Bond bid", magnitude
    if proxy_id == "GLD" and value >= 1.5:
        return "warn", "Safety bid", magnitude
    if proxy_id == "UUP" and value >= 1.0:
        return "warn", "Dollar bid", magnitude
    if value <= -1.0:
        return "pass", "Risk appetite", magnitude
    return "neutral", "Stable", magnitude


def _number_label(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _delta_label(latest: float | None, prior: float | None) -> str:
    if latest is None or prior is None:
        return "no prior"
    return f"{latest - prior:+.2f}"


def _gauge_style(value: float) -> str:
    return f"width: {round(max(0.0, min(1.0, value)) * 100)}%"


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
        return (
            "UP"
            if (number(latest.get("close")) or 0.0) >= (number(latest.get("open")) or 0.0)
            else "DOWN"
        )
    first = number(input_rows[0].get("close")) or 0.0
    last = number(input_rows[-1].get("close")) or 0.0
    return "UP" if last >= first else "DOWN"


def _pct(end: float | None, start: float | None) -> float | None:
    if end is None or start is None or start <= 0.0:
        return None
    return round((end / start - 1.0) * 100.0, 2)
