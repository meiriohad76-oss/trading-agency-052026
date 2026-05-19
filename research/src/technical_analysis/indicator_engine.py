from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
import math
from typing import Any, cast

import pandas as pd

IndicatorSnapshotFactory = Callable[
    [pd.Series, pd.Series, pd.Series, pd.Series],
    "ExternalIndicatorSnapshot",
]

MIN_INDICATOR_ROWS = 40
OBV_SLOPE_DAYS = 20
REASON_DIRECTION_THRESHOLD = 0.10
REASON_COMPONENT_THRESHOLD = 0.15
NEUTRAL_VALUES: dict[str, float | None] = {
    "adx14": None,
    "aroon25": None,
    "cci20": None,
    "bollinger_percent_b": None,
    "bollinger_width": None,
    "keltner_percent_b": None,
    "donchian_percent_b": None,
    "cmf20": None,
    "mfi14": None,
    "obv_slope_20": None,
    "vwap_distance": None,
    "stochrsi14": None,
    "williams_r14": None,
}


@dataclass(frozen=True)
class ExternalIndicatorSnapshot:
    provider: str
    status: str
    score: float
    trend_score: float
    momentum_score: float
    channel_score: float
    volume_score: float
    reason_codes: list[str]
    values: dict[str, float | None]

    @property
    def summary_fragment(self) -> str:
        if self.status != "ta_available":
            return "Optional indicator pack is unavailable; score contribution is neutral."
        return (
            f"Optional indicator pack {self.provider} score {self.score:+.2f} "
            f"(trend {self.trend_score:+.2f}, momentum {self.momentum_score:+.2f}, "
            f"channels {self.channel_score:+.2f}, volume {self.volume_score:+.2f})."
        )


def external_indicator_snapshot(
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    factory: IndicatorSnapshotFactory | None = None,
) -> ExternalIndicatorSnapshot:
    """Return optional third-party TA indicators without making them required."""
    normalized_close = _numeric(close)
    normalized_high = _numeric(high).fillna(normalized_close)
    normalized_low = _numeric(low).fillna(normalized_close)
    normalized_volume = _numeric(volume).fillna(0.0)
    if len(normalized_close.dropna()) < MIN_INDICATOR_ROWS:
        return _neutral("insufficient_data")
    if factory is not None:
        return factory(normalized_close, normalized_high, normalized_low, normalized_volume)
    try:
        return _ta_snapshot(normalized_close, normalized_high, normalized_low, normalized_volume)
    except ModuleNotFoundError:
        return _neutral("ta_not_installed")
    except Exception:
        return _neutral("ta_error")


def _ta_snapshot(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> ExternalIndicatorSnapshot:
    adx = _last(
        _indicator("ta.trend", "ADXIndicator")(
            high=high,
            low=low,
            close=close,
            window=14,
        ).adx()
    )
    adx_pos = _last(
        _indicator("ta.trend", "ADXIndicator")(
            high=high,
            low=low,
            close=close,
            window=14,
        ).adx_pos()
    )
    adx_neg = _last(
        _indicator("ta.trend", "ADXIndicator")(
            high=high,
            low=low,
            close=close,
            window=14,
        ).adx_neg()
    )
    aroon = _last(_indicator("ta.trend", "AroonIndicator")(high=high, low=low).aroon_indicator())
    cci = _last(_indicator("ta.trend", "CCIIndicator")(high=high, low=low, close=close).cci())
    bollinger = _indicator("ta.volatility", "BollingerBands")(close=close)
    bollinger_pband = _last(bollinger.bollinger_pband())
    bollinger_width = _last(bollinger.bollinger_wband())
    keltner = _indicator("ta.volatility", "KeltnerChannel")(high=high, low=low, close=close)
    keltner_pband = _last(keltner.keltner_channel_pband())
    donchian = _indicator("ta.volatility", "DonchianChannel")(high=high, low=low, close=close)
    donchian_pband = _last(donchian.donchian_channel_pband())
    cmf = _last(
        _indicator("ta.volume", "ChaikinMoneyFlowIndicator")(
            high=high,
            low=low,
            close=close,
            volume=volume,
        ).chaikin_money_flow()
    )
    mfi = _last(
        _indicator("ta.volume", "MFIIndicator")(
            high=high,
            low=low,
            close=close,
            volume=volume,
        ).money_flow_index()
    )
    obv = _indicator("ta.volume", "OnBalanceVolumeIndicator")(
        close=close,
        volume=volume,
    ).on_balance_volume()
    vwap = _last(
        _indicator("ta.volume", "VolumeWeightedAveragePrice")(
            high=high,
            low=low,
            close=close,
            volume=volume,
        ).volume_weighted_average_price()
    )
    stochrsi = _last(_indicator("ta.momentum", "StochRSIIndicator")(close=close).stochrsi())
    williams = _last(
        _indicator("ta.momentum", "WilliamsRIndicator")(
            high=high,
            low=low,
            close=close,
        ).williams_r()
    )
    values = {
        "adx14": adx,
        "aroon25": aroon,
        "cci20": cci,
        "bollinger_percent_b": bollinger_pband,
        "bollinger_width": bollinger_width,
        "keltner_percent_b": keltner_pband,
        "donchian_percent_b": donchian_pband,
        "cmf20": cmf,
        "mfi14": mfi,
        "obv_slope_20": _obv_slope(obv),
        "vwap_distance": _vwap_distance(close, vwap),
        "stochrsi14": stochrsi,
        "williams_r14": williams,
    }
    trend_score = _trend_score(adx=adx, adx_pos=adx_pos, adx_neg=adx_neg, aroon=aroon)
    momentum_score = _momentum_score(stochrsi=stochrsi, williams=williams, cci=cci)
    channel_score = _channel_score(
        bollinger=bollinger_pband,
        keltner=keltner_pband,
        donchian=donchian_pband,
    )
    volume_score = _volume_score(cmf=cmf, mfi=mfi, obv_slope=values["obv_slope_20"])
    vwap_score = _bounded((values["vwap_distance"] or 0.0) * 15.0)
    score = _bounded(
        0.30 * trend_score
        + 0.25 * momentum_score
        + 0.20 * volume_score
        + 0.15 * channel_score
        + 0.10 * vwap_score
    )
    return ExternalIndicatorSnapshot(
        provider="ta",
        status="ta_available",
        score=score,
        trend_score=trend_score,
        momentum_score=momentum_score,
        channel_score=channel_score,
        volume_score=volume_score,
        reason_codes=_reason_codes(score, trend_score, momentum_score, volume_score),
        values=values,
    )


def _indicator(module_name: str, class_name: str) -> type[Any]:
    value = getattr(import_module(module_name), class_name)
    if not isinstance(value, type):
        raise TypeError(f"{module_name}.{class_name} must be a class")
    return value


def _trend_score(
    *,
    adx: float | None,
    adx_pos: float | None,
    adx_neg: float | None,
    aroon: float | None,
) -> float:
    direction = _sign((adx_pos or 0.0) - (adx_neg or 0.0))
    adx_component = direction * _scale((adx or 0.0), lower=15.0, upper=35.0)
    aroon_component = _bounded((aroon or 0.0) / 100.0)
    return _bounded(0.60 * adx_component + 0.40 * aroon_component)


def _momentum_score(
    *,
    stochrsi: float | None,
    williams: float | None,
    cci: float | None,
) -> float:
    stoch_component = _bounded(((stochrsi or 0.5) - 0.5) * 2.0)
    williams_component = _bounded(((williams or -50.0) + 50.0) / 50.0)
    cci_component = _bounded((cci or 0.0) / 200.0)
    return _bounded(0.45 * stoch_component + 0.30 * williams_component + 0.25 * cci_component)


def _channel_score(
    *,
    bollinger: float | None,
    keltner: float | None,
    donchian: float | None,
) -> float:
    values = [value for value in (bollinger, keltner, donchian) if value is not None]
    if not values:
        return 0.0
    return _bounded(sum(_bounded((value - 0.5) * 2.0) for value in values) / len(values))


def _volume_score(
    *,
    cmf: float | None,
    mfi: float | None,
    obv_slope: float | None,
) -> float:
    cmf_component = _bounded(cmf or 0.0)
    mfi_component = _bounded(((mfi or 50.0) - 50.0) / 50.0)
    obv_component = _bounded(obv_slope or 0.0)
    return _bounded(0.45 * cmf_component + 0.35 * mfi_component + 0.20 * obv_component)


def _reason_codes(score: float, trend: float, momentum: float, volume: float) -> list[str]:
    direction = (
        "bullish"
        if score > REASON_DIRECTION_THRESHOLD
        else "bearish"
        if score < -REASON_DIRECTION_THRESHOLD
        else "neutral"
    )
    codes = [f"technical_indicator_pack_{direction}"]
    if trend > REASON_COMPONENT_THRESHOLD:
        codes.append("technical_indicator_trend_confirmed")
    if momentum > REASON_COMPONENT_THRESHOLD:
        codes.append("technical_indicator_momentum_confirmed")
    if volume > REASON_COMPONENT_THRESHOLD:
        codes.append("technical_indicator_volume_confirmed")
    return codes


def _neutral(status: str) -> ExternalIndicatorSnapshot:
    return ExternalIndicatorSnapshot(
        provider="ta",
        status=status,
        score=0.0,
        trend_score=0.0,
        momentum_score=0.0,
        channel_score=0.0,
        volume_score=0.0,
        reason_codes=[],
        values=dict(NEUTRAL_VALUES),
    )


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").reset_index(drop=True)


def _last(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return None if values.empty else float(values.iloc[-1])


def _obv_slope(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().tail(OBV_SLOPE_DAYS + 1)
    if len(values) <= 1:
        return 0.0
    start = abs(float(values.iloc[0]))
    end = float(values.iloc[-1])
    return 0.0 if start <= 0.0 else _bounded((end - float(values.iloc[0])) / start)


def _vwap_distance(close: pd.Series, vwap: float | None) -> float:
    latest_close = _float_or_none(close.iloc[-1])
    if latest_close is None or vwap is None or vwap <= 0.0:
        return 0.0
    return latest_close / vwap - 1.0


def _float_or_none(value: object) -> float | None:
    try:
        parsed = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _scale(value: float, *, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return _bounded((value - lower) / (upper - lower))


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def _bounded(value: float) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        return 0.0
    return max(-1.0, min(1.0, parsed))
