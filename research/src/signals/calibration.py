from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

MAD_NORMALIZER = 1.4826


@dataclass(frozen=True)
class SignalCalibrationThresholds:
    rvol_attention: float = 1.5
    rvol_strong: float = 2.0
    rvol_extreme: float = 3.0
    anomaly_z_attention: float = 2.0
    anomaly_z_extreme: float = 3.0
    block_absolute_shares_floor: float = 10_000.0
    block_absolute_notional_floor: float = 200_000.0
    block_relative_median_multiple: float = 5.0
    order_imbalance_strong: float = 0.30
    order_imbalance_extreme: float = 0.50


DEFAULT_THRESHOLDS = SignalCalibrationThresholds()


def robust_z_score(latest: float, baseline: pd.Series) -> float:
    values = _finite_positive_or_zero(baseline)
    if values.empty:
        return 0.0
    std = float(values.std(ddof=0))
    if std <= 0.0 or not math.isfinite(std):
        mean = float(values.mean())
        delta = float(latest) - mean
        if delta == 0.0:
            return 0.0
        fallback_scale = max(abs(mean) * 0.01, 1.0)
        return delta / fallback_scale
    return (float(latest) - float(values.mean())) / std


def robust_mad_score(latest: float, baseline: pd.Series) -> float:
    values = _finite_positive_or_zero(baseline)
    if values.empty:
        return 0.0
    median = float(values.median())
    mad = float((values - median).abs().median())
    scaled = mad * MAD_NORMALIZER
    if scaled <= 0.0 or not math.isfinite(scaled):
        delta = float(latest) - median
        if delta == 0.0:
            return 0.0
        fallback_scale = max(abs(median) * 0.01, 1.0)
        return delta / fallback_scale
    return (float(latest) - median) / scaled


def volume_signal_band(
    ratio: float,
    thresholds: SignalCalibrationThresholds = DEFAULT_THRESHOLDS,
) -> str:
    if ratio >= thresholds.rvol_extreme:
        return "extreme"
    if ratio >= thresholds.rvol_strong:
        return "strong"
    if ratio >= thresholds.rvol_attention:
        return "attention"
    return "normal"


def anomaly_band(
    ratio: float,
    z_score: float = 0.0,
    mad_score: float = 0.0,
    thresholds: SignalCalibrationThresholds = DEFAULT_THRESHOLDS,
) -> str:
    magnitude = max(abs(z_score), abs(mad_score))
    if ratio >= thresholds.rvol_extreme or magnitude >= thresholds.anomaly_z_extreme:
        return "extreme"
    if ratio >= thresholds.rvol_strong or magnitude >= thresholds.anomaly_z_attention:
        return "strong"
    if ratio >= thresholds.rvol_attention:
        return "attention"
    return "normal"


def confluence_confidence(
    *,
    base: float,
    agreements: int = 0,
    conflicts: int = 0,
) -> float:
    return _clamp(base + 0.08 * agreements - 0.10 * conflicts, lower=0.0, upper=1.0)


def _finite_positive_or_zero(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    values = values[values.map(lambda value: math.isfinite(float(value)))]
    return values.astype(float)


def _clamp(value: float, *, lower: float, upper: float) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        return lower
    return min(upper, max(lower, parsed))
