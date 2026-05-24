from __future__ import annotations

import pandas as pd
import pytest
from signals.calibration import (
    SignalCalibrationThresholds,
    robust_mad_score,
    robust_z_score,
    volume_signal_band,
)


def test_volume_signal_band_uses_researched_rvol_thresholds() -> None:
    assert volume_signal_band(1.49) == "normal"
    assert volume_signal_band(1.50) == "attention"
    assert volume_signal_band(2.00) == "strong"
    assert volume_signal_band(3.00) == "extreme"


def test_robust_scores_use_baseline_distribution() -> None:
    baseline = pd.Series([100.0, 102.0, 98.0, 101.0, 99.0])

    assert robust_z_score(120.0, baseline) > 10.0
    assert robust_mad_score(120.0, baseline) == pytest.approx(13.49, abs=0.02)


def test_default_calibration_thresholds_are_conservative_floors() -> None:
    thresholds = SignalCalibrationThresholds()

    assert thresholds.rvol_attention == 1.5
    assert thresholds.rvol_strong == 2.0
    assert thresholds.rvol_extreme == 3.0
    assert thresholds.block_absolute_shares_floor == 10_000.0
    assert thresholds.block_absolute_notional_floor == 200_000.0
    assert thresholds.block_relative_median_multiple == 5.0
    assert thresholds.anomaly_z_attention == 2.0
