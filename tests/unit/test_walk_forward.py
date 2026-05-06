from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import polars as pl
import pytest
from backtests.portfolio import CostModel, rebalance_cost_return, target_weights
from backtests.walk_forward import WalkForward, WalkForwardConfig
from hypothesis import given
from hypothesis import strategies as st
from pit.exceptions import LookaheadRequested

EXPECTED_EQUAL_WEIGHT = 0.5
EXPECTED_SCORE_WEIGHT_A = 2.0 / 3.0
EXPECTED_SCORE_WEIGHT_B = -1.0 / 3.0
EXPECTED_VOL_WEIGHT_A = 1.0 / 3.0
EXPECTED_VOL_WEIGHT_B = -2.0 / 3.0
TEN_BPS = 10.0
BASIS_POINTS = 10_000


def test_position_sizing_rules_produce_expected_weights() -> None:
    scores = {"A": 2.0, "B": -1.0, "C": 0.5}

    equal = target_weights(
        scores,
        max_positions=2,
        sizing_rule="equal_weight",
        max_gross_exposure=1.0,
    )
    score = target_weights(
        scores,
        max_positions=2,
        sizing_rule="score_weighted",
        max_gross_exposure=1.0,
    )
    vol = target_weights(
        scores,
        max_positions=2,
        sizing_rule="volatility_targeted",
        max_gross_exposure=1.0,
        volatilities={"A": 0.20, "B": 0.05},
    )

    assert equal == pytest.approx({"A": EXPECTED_EQUAL_WEIGHT, "B": -EXPECTED_EQUAL_WEIGHT})
    assert score == pytest.approx({"A": EXPECTED_SCORE_WEIGHT_A, "B": EXPECTED_SCORE_WEIGHT_B})
    assert vol == pytest.approx({"A": EXPECTED_VOL_WEIGHT_A, "B": EXPECTED_VOL_WEIGHT_B})


def test_walk_forward_is_deterministic_for_seeded_scores() -> None:
    loader = _ToyLoader()
    config = WalkForwardConfig(
        step_size_days=2,
        max_positions=1,
        static_universe={"A", "B"},
        cost_model=CostModel(bps_per_side=0.0),
    )

    first = WalkForward(config, loader, _seeded_signal).run(date(2022, 1, 1), date(2022, 1, 5))
    second = WalkForward(config, loader, _seeded_signal).run(date(2022, 1, 1), date(2022, 1, 5))

    pd.testing.assert_series_equal(first.equity_curve, second.equity_curve)
    pd.testing.assert_frame_equal(first.trades, second.trades)


def test_scoped_loader_rejects_signal_that_peeks_forward() -> None:
    loader = _ToyLoader()
    config = WalkForwardConfig(step_size_days=2, static_universe={"A"})

    def peeking_signal(as_of: date, universe: set[str], loader_arg: object) -> dict[str, float]:
        del universe
        loader_arg.prices(["A"], as_of + timedelta(days=1), 1)
        return {"A": 1.0}

    with pytest.raises(LookaheadRequested):
        WalkForward(config, loader, peeking_signal).run(date(2022, 1, 1), date(2022, 1, 5))


def test_walk_forward_applies_known_rebalance_cost_drag() -> None:
    loader = _FlatLoader()
    config = WalkForwardConfig(
        step_size_days=2,
        max_positions=1,
        static_universe={"A"},
        cost_model=CostModel(bps_per_side=TEN_BPS),
    )

    portfolio = WalkForward(config, loader, _long_a).run(date(2022, 1, 1), date(2022, 1, 3))

    assert portfolio.trades.iloc[0]["cost_return"] == pytest.approx(TEN_BPS / BASIS_POINTS)
    assert portfolio.equity_curve.iloc[0] == pytest.approx(1.0 - TEN_BPS / BASIS_POINTS)


@given(st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False))
def test_rebalance_cost_property_for_full_entry(cost_bps: float) -> None:
    cost = rebalance_cost_return({}, {"A": 1.0}, CostModel(bps_per_side=cost_bps))

    assert cost == pytest.approx(cost_bps / BASIS_POINTS)


class _ToyLoader:
    def universe_members(self, as_of: date) -> set[str]:
        del as_of
        return {"A", "B"}

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        start = date(2022, 1, 1)
        for offset in range((as_of - start).days + 1):
            value_date = start + timedelta(days=offset)
            if "A" in tickers:
                rows.append(_price("A", value_date, 100.0 + offset))
            if "B" in tickers:
                rows.append(_price("B", value_date, 100.0 - offset))
        return pl.DataFrame(rows)


class _FlatLoader(_ToyLoader):
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        return pl.DataFrame([_price(ticker, as_of, 100.0) for ticker in tickers])


def _seeded_signal(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del loader
    return {
        ticker: float(((sum(ord(char) for char in ticker) + as_of.toordinal()) % 100) / 100)
        for ticker in universe
    }


def _long_a(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del as_of, universe, loader
    return {"A": 1.0}


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": value_date,
        "adj_close": adj_close,
        "timestamp_as_of": value_date,
    }
