from __future__ import annotations

import math
from statistics.ic import compute_ic, compute_ic_panel

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

PERFECT_IC = 1.0
ANTI_IC = -1.0
NEAR_ZERO_IC = 0.0
SCALE_MIN = 0.1
SCALE_MAX = 100.0


def test_compute_ic_perfect_cross_section() -> None:
    scores = pd.Series([1.0, 2.0, 3.0], index=["A", "B", "C"])
    returns = pd.Series([0.01, 0.02, 0.03], index=["A", "B", "C"])

    result = compute_ic(scores, returns)

    assert result.ic_series.iloc[0] == pytest.approx(PERFECT_IC)
    assert result.mean_ic == pytest.approx(PERFECT_IC)


def test_compute_ic_anti_correlated_cross_section() -> None:
    scores = pd.Series([1.0, 2.0, 3.0], index=["A", "B", "C"])
    returns = pd.Series([0.03, 0.02, 0.01], index=["A", "B", "C"])

    result = compute_ic(scores, returns)

    assert result.ic_series.iloc[0] == pytest.approx(ANTI_IC)


def test_compute_ic_no_correlation_fixture_is_near_zero() -> None:
    scores = pd.Series([1.0, 2.0, 3.0, 4.0], index=["A", "B", "C", "D"])
    returns = pd.Series([1.0, -1.0, -1.0, 1.0], index=["A", "B", "C", "D"])

    result = compute_ic(scores, returns)

    assert result.mean_ic == pytest.approx(NEAR_ZERO_IC)


def test_compute_ic_panel_matches_cross_section_average_and_t_stat() -> None:
    scores = pd.DataFrame(
        {
            "A": [1.0, 3.0, 1.0],
            "B": [2.0, 2.0, 3.0],
            "C": [3.0, 1.0, 2.0],
        },
        index=pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03"]),
    )
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.03, 0.02],
            "B": [0.02, 0.02, 0.01],
            "C": [0.03, 0.01, 0.03],
        },
        index=scores.index,
    )

    result = compute_ic_panel(scores, returns)
    manual_t = result.mean_ic / (result.ic_std / math.sqrt(result.n_observations))

    assert result.ic_series.to_list() == pytest.approx([1.0, 1.0, -0.5])
    assert result.mean_ic == pytest.approx(0.5)
    assert result.t_stat == pytest.approx(manual_t)


def test_compute_ic_drops_missing_pairs_within_cross_section() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2022-01-01"]), ["A", "B", "C"]],
        names=["date", "ticker"],
    )
    scores = pd.Series([1.0, None, 3.0], index=index)
    returns = pd.Series([0.01, 0.02, 0.03], index=index)

    result = compute_ic(scores, returns)

    assert result.ic_series.iloc[0] == pytest.approx(PERFECT_IC)


@given(st.floats(min_value=SCALE_MIN, max_value=SCALE_MAX, allow_nan=False, allow_infinity=False))
@settings(deadline=None)
def test_ic_t_stat_invariant_under_positive_linear_scaling(scale: float) -> None:
    scores = pd.DataFrame(
        {
            "A": [1.0, 3.0, 1.0],
            "B": [2.0, 2.0, 3.0],
            "C": [3.0, 1.0, 2.0],
        },
        index=pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03"]),
    )
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.03, 0.02],
            "B": [0.02, 0.02, 0.01],
            "C": [0.03, 0.01, 0.03],
        },
        index=scores.index,
    )

    base = compute_ic_panel(scores, returns)
    scaled = compute_ic_panel(scores * scale, returns * scale)

    assert scaled.t_stat == pytest.approx(base.t_stat)
