from __future__ import annotations

import pandas as pd
import pytest
from backtests.regimes import subset_by_regime


def test_subset_by_regime_splits_returns_by_named_windows() -> None:
    returns = pd.Series(
        [0.01, -0.02, 0.03],
        index=pd.to_datetime(["2020-03-01", "2020-03-02", "2022-06-01"]),
    )
    regimes = pd.DataFrame(
        [
            {"regime": "covid", "start": "2020-03-01", "end": "2020-03-31"},
            {"regime": "bear", "start": "2022-01-01", "end": "2022-12-31"},
        ]
    )

    subsets = subset_by_regime(returns, regimes)

    assert subsets["covid"].to_list() == [0.01, -0.02]
    assert subsets["bear"].to_list() == [0.03]


def test_subset_by_regime_requires_expected_columns() -> None:
    with pytest.raises(ValueError, match="missing"):
        subset_by_regime(pd.Series(dtype="float64"), pd.DataFrame({"regime": []}))
