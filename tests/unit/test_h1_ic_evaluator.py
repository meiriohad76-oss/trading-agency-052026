from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest
from evaluation.h1_ic import H1ICConfig, evaluate_signal_ic
from pit.exceptions import LookaheadRequested

EXPECTED_OBSERVATIONS = 4


def test_evaluate_signal_ic_scores_positive_synthetic_edge() -> None:
    report = evaluate_signal_ic(
        signal_name="toy",
        signal_fn=_long_a_short_b,
        loader=_ToyLoader(),
        config=H1ICConfig(
            start=date(2023, 1, 1),
            end=date(2023, 1, 5),
            horizons=(1,),
            static_universe={"A", "B"},
        ),
    )

    row = report.results.iloc[0]
    assert row["signal"] == "toy"
    assert row["horizon"] == 1
    assert row["mean_ic"] == pytest.approx(1.0)
    assert row["n_observations"] == EXPECTED_OBSERVATIONS


def test_evaluate_signal_ic_scopes_signal_loader() -> None:
    with pytest.raises(LookaheadRequested):
        evaluate_signal_ic(
            signal_name="peek",
            signal_fn=_peeking_signal,
            loader=_ToyLoader(),
            config=H1ICConfig(
                start=date(2023, 1, 1),
                end=date(2023, 1, 5),
                horizons=(1,),
                static_universe={"A", "B"},
            ),
        )


def test_evaluate_signal_ic_handles_empty_scores() -> None:
    report = evaluate_signal_ic(
        signal_name="empty",
        signal_fn=_empty_signal,
        loader=_ToyLoader(),
        config=H1ICConfig(
            start=date(2023, 1, 1),
            end=date(2023, 1, 5),
            horizons=(1,),
            static_universe={"A", "B"},
        ),
    )

    assert report.scores.empty
    assert report.results.empty


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


def _peeking_signal(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del universe
    loader.prices(["A"], as_of + timedelta(days=1), 1)
    return {"A": 1.0}


def _empty_signal(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del as_of, universe, loader
    return {}


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {"ticker": ticker, "date": value_date, "adj_close": adj_close}
