from __future__ import annotations

import math

import pandas as pd
import pytest
from backtests.metrics import compute_performance

TOTAL_RETURN = 0.20
MAX_DRAWDOWN = -0.10
TURNOVER = 1.25
TIME_IN_MARKET = 2.0 / 3.0


def test_compute_performance_matches_hand_computed_fixture() -> None:
    equity = pd.Series(
        [1.0, 1.1, 0.99, 1.2],
        index=pd.to_datetime(["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"]),
        name="equity",
    )
    trades = pd.DataFrame(
        {
            "turnover": [1.0, 0.25, 0.0],
            "gross_exposure": [1.0, 1.0, 0.0],
        }
    )

    report = compute_performance(equity, trades)

    assert report.total_return == pytest.approx(TOTAL_RETURN)
    assert report.max_drawdown == pytest.approx(MAX_DRAWDOWN)
    assert report.turnover == pytest.approx(TURNOVER)
    assert report.time_in_market == pytest.approx(TIME_IN_MARKET)
    assert report.hit_rate == pytest.approx(2.0 / 3.0)
    assert report.average_win > 0.0
    assert report.average_loss < 0.0
    assert not math.isnan(report.sharpe)


def test_compute_performance_rejects_short_equity_curve() -> None:
    with pytest.raises(ValueError, match="at least two"):
        compute_performance(pd.Series([1.0], index=pd.to_datetime(["2022-01-01"])), pd.DataFrame())
