from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import polars as pl
import pytest
from backtests.portfolio import CostModel
from backtests.walk_forward import WalkForwardConfig
from evaluation.combination import combine_signal_scores, weights_from_ic
from evaluation.llm_ab import ReviewDecision, reviewed_signal_fn, run_llm_ab


def test_combine_signal_scores_zscores_and_weights_components() -> None:
    combined = combine_signal_scores(
        {
            "quality": {"A": 2.0, "B": 1.0},
            "flow": {"A": 0.0, "B": 1.0},
        },
        {"quality": 0.75, "flow": 0.25},
    )

    assert combined["A"] == pytest.approx(0.5)
    assert combined["B"] == pytest.approx(-0.5)


def test_combine_signal_scores_keeps_tickers_missing_from_one_lane() -> None:
    combined = combine_signal_scores(
        {
            "quality": {"A": 2.0, "B": 1.0},
            "flow": {"A": 1.0, "B": 0.0, "C": 2.0},
        },
        {"quality": 1.0, "flow": 1.0},
    )

    assert "C" in combined


def test_weights_from_ic_uses_positive_information_ratio_only() -> None:
    weights = weights_from_ic(
        pd.DataFrame(
            [
                {"signal": "quality", "information_ratio": 2.0},
                {"signal": "flow", "information_ratio": 1.0},
                {"signal": "noise", "information_ratio": -1.0},
            ]
        )
    )

    assert weights == pytest.approx({"quality": 2.0 / 3.0, "flow": 1.0 / 3.0})


def test_reviewed_signal_rejects_and_scales_scores() -> None:
    def reviewer(
        as_of: date,
        ticker: str,
        score: float,
        evidence: dict[str, object],
    ) -> ReviewDecision:
        del as_of, score, evidence
        if ticker == "B":
            return ReviewDecision(approved=False, reason="blocked")
        return ReviewDecision(score_multiplier=0.5)

    reviewed = reviewed_signal_fn(_long_a_short_b, reviewer)

    assert reviewed(date(2023, 1, 1), {"A", "B"}, _ToyLoader()) == {"A": 0.5}


def test_run_llm_ab_returns_deterministic_and_reviewed_rows() -> None:
    def reviewer(
        as_of: date,
        ticker: str,
        score: float,
        evidence: dict[str, object],
    ) -> ReviewDecision:
        del as_of, ticker, score, evidence
        return ReviewDecision(score_multiplier=0.5)

    result = run_llm_ab(
        name="toy",
        config=WalkForwardConfig(
            step_size_days=2,
            max_positions=1,
            static_universe={"A", "B"},
            cost_model=CostModel(bps_per_side=0.0),
        ),
        loader=_ToyLoader(),
        signal_fn=_long_a_short_b,
        reviewer=reviewer,
        start=date(2023, 1, 1),
        end=date(2023, 1, 5),
        repeats=2,
    )

    assert result["variant"].to_list() == ["deterministic", "reviewed", "reviewed"]
    assert result["repeat"].to_list() == [0, 0, 1]


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


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {"ticker": ticker, "date": value_date, "adj_close": adj_close}
