from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest
from backtests.portfolio import CostModel
from backtests.walk_forward import WalkForwardConfig
from evaluation.profile import WEEKLY_TARGET_RETURN, profile_strategy, profile_to_frame
from evaluation.sweep import SweepPoint, best_by_sharpe, run_parameter_sweep, threshold_signal

SWEEP_POINTS = 2


def test_profile_strategy_reports_performance_and_weekly_target_gap() -> None:
    profile = profile_strategy(
        name="toy",
        config=WalkForwardConfig(
            step_size_days=2,
            max_positions=1,
            static_universe={"A", "B"},
            cost_model=CostModel(bps_per_side=0.0),
        ),
        loader=_ToyLoader(),
        signal_fn=_long_a_short_b,
        start=date(2023, 1, 1),
        end=date(2023, 1, 5),
    )

    frame = profile_to_frame(profile)

    assert profile.weekly_target == WEEKLY_TARGET_RETURN
    assert profile.weekly_target_gap == pytest.approx(profile.weekly_return - WEEKLY_TARGET_RETURN)
    assert frame.iloc[0]["name"] == "toy"
    assert frame.iloc[0]["total_return"] > 0.0


def test_threshold_signal_removes_low_absolute_scores() -> None:
    wrapped = threshold_signal(_mixed_scores, 0.5)

    assert wrapped(date(2023, 1, 1), {"A", "B", "C"}, _ToyLoader()) == {"A": 0.6}


def test_run_parameter_sweep_returns_one_row_per_point_and_selects_best() -> None:
    sweep = run_parameter_sweep(
        name="toy",
        base_config=WalkForwardConfig(
            static_universe={"A", "B"},
            cost_model=CostModel(bps_per_side=0.0),
        ),
        points=[
            SweepPoint(step_size_days=1, max_positions=1, score_threshold=0.0),
            SweepPoint(step_size_days=2, max_positions=1, score_threshold=0.0),
        ],
        loader=_ToyLoader(),
        signal_fn=_long_a_short_b,
        start=date(2023, 1, 1),
        end=date(2023, 1, 5),
    )

    best = best_by_sharpe(sweep, max_drawdown_floor=-1.0)

    assert len(sweep) == SWEEP_POINTS
    assert {"step_size_days", "max_positions", "score_threshold"}.issubset(sweep.columns)
    assert best["sharpe"] == sweep["sharpe"].max()


class _ToyLoader:
    def universe_members(self, as_of: date) -> set[str]:
        del as_of
        return {"A", "B"}

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        start = date(2023, 1, 1)
        for offset in range((as_of - start).days + 1):
            value_date = start + timedelta(days=offset)
            if "A" in tickers:
                rows.append(_price("A", value_date, 100.0 + offset))
            if "B" in tickers:
                rows.append(_price("B", value_date, 100.0 - offset))
        return pl.DataFrame(rows)


def _long_a_short_b(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del as_of, loader
    return {ticker: 1.0 if ticker == "A" else -1.0 for ticker in universe}


def _mixed_scores(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del as_of, universe, loader
    return {"A": 0.6, "B": 0.4, "C": -0.2}


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {"ticker": ticker, "date": value_date, "adj_close": adj_close}
