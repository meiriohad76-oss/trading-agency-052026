from __future__ import annotations

import warnings

import pandas as pd
import pytest

from signals._common import zscore


def test_zscore_warns_insufficient_cross_section() -> None:
    """Single observation should warn with 'insufficient_cross_section' and return all zeros."""
    with pytest.warns(UserWarning, match="insufficient_cross_section"):
        result = zscore(pd.Series([1.0]))
    assert list(result) == [0.0]


def test_zscore_warns_empty_series() -> None:
    """Empty series should warn with 'insufficient_cross_section' and return an empty Series of 0.0."""
    with pytest.warns(UserWarning, match="insufficient_cross_section"):
        result = zscore(pd.Series([], dtype=float))
    assert list(result) == []


def test_zscore_no_warning_when_sufficient() -> None:
    """Three observations: no warning should be emitted and result should be a proper zscore."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = zscore(pd.Series([1.0, 2.0, 3.0]))

    # Population zscore for [1, 2, 3]: mean=2, std=0.8165...
    # z = [-1.2247, 0.0, 1.2247]
    assert abs(result.iloc[0] - (-1.2247448713915892)) < 1e-6
    assert abs(result.iloc[1] - 0.0) < 1e-6
    assert abs(result.iloc[2] - 1.2247448713915892) < 1e-6
