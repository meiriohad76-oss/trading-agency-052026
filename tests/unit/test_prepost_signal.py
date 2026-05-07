from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import polars as pl
import pytest
from backtests.portfolio import CostModel
from backtests.walk_forward import WalkForward, WalkForwardConfig
from signals.prepost import prepost_gap_frame, prepost_gap_score

AS_OF = date(2023, 1, 31)
LOOKBACK_DAYS = 5


def test_prepost_gap_score_rewards_positive_gap_and_penalizes_negative_gap() -> None:
    loader = _FakePrePostLoader(
        [
            _bar("AAPL", date(2023, 1, 30), "post", 101.0, 100.0, 100),
            _bar("AAPL", AS_OF, "pre", 110.0, 100.0, 1_000),
            _bar("MSFT", date(2023, 1, 30), "post", 100.0, 100.0, 100),
            _bar("MSFT", AS_OF, "pre", 100.0, 100.0, 100),
            _bar("TSLA", date(2023, 1, 30), "post", 99.0, 100.0, 100),
            _bar("TSLA", AS_OF, "pre", 90.0, 100.0, 1_000),
        ]
    )

    scores = prepost_gap_score(AS_OF, {"tsla", "AAPL", "MSFT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "TSLA"]
    assert scores["AAPL"] > scores["MSFT"] > scores["TSLA"]


def test_prepost_gap_frame_skips_missing_or_incomplete_rows() -> None:
    loader = _FakePrePostLoader(
        [
            _bar("AAPL", AS_OF, "pre", 110.0, 100.0, 1_000),
            {"ticker": "BAD", "date": AS_OF, "session": "pre", "close": 10.0, "volume": 100},
            _bar("ZERO", AS_OF, "pre", 0.0, 100.0, 1_000),
        ]
    )

    frame = prepost_gap_frame(AS_OF, {"AAPL", "BAD", "ZERO"}, loader)

    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["prepost_gap_score"] == pytest.approx(0.0)


def test_prepost_gap_score_is_deterministic_uppercases_and_forwards_lookback() -> None:
    loader = _FakePrePostLoader(
        [
            _bar("AAPL", AS_OF, "pre", 110.0, 100.0, 1_000),
            _bar("MSFT", AS_OF, "pre", 100.0, 100.0, 100),
        ]
    )

    first = prepost_gap_score(AS_OF, {"msft", "aapl"}, loader, LOOKBACK_DAYS)
    second = prepost_gap_score(AS_OF, {"aapl", "msft"}, loader, LOOKBACK_DAYS)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}
    assert loader.calls == [
        (["AAPL", "MSFT"], AS_OF, LOOKBACK_DAYS),
        (["AAPL", "MSFT"], AS_OF, LOOKBACK_DAYS),
    ]


def test_prepost_gap_score_runs_inside_walk_forward_scoped_loader() -> None:
    loader = _FakeWalkForwardPrePostLoader(
        [
            _bar("AAPL", AS_OF, "pre", 110.0, 100.0, 1_000),
            _bar("MSFT", AS_OF, "pre", 100.0, 100.0, 100),
        ]
    )
    config = WalkForwardConfig(
        step_size_days=2,
        max_positions=1,
        static_universe={"AAPL", "MSFT"},
        cost_model=CostModel(bps_per_side=0.0),
    )

    portfolio = WalkForward(config, loader, prepost_gap_score).run(AS_OF, date(2023, 2, 2))

    assert portfolio.positions.iloc[0]["AAPL"] == pytest.approx(1.0)


class _FakePrePostLoader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[list[str], date, int]] = []

    def prepost_bars(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        self.calls.append((tickers, as_of, lookback_days))
        requested = set(tickers)
        return pl.DataFrame([row for row in self._rows if row["ticker"] in requested])


class _FakeWalkForwardPrePostLoader(_FakePrePostLoader):
    def universe_members(self, as_of: date) -> set[str]:
        del as_of
        return {"AAPL", "MSFT"}

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        for offset in range((as_of - AS_OF).days + 1):
            value_date = AS_OF + timedelta(days=offset)
            for ticker in tickers:
                rows.append(_price(ticker, value_date, 100.0 + offset))
        return pl.DataFrame(rows)


def _bar(
    ticker: str,
    value_date: date,
    session: str,
    close: float,
    reference_close: float,
    volume: int,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": value_date,
        "session": session,
        "close": close,
        "reference_close": reference_close,
        "volume": volume,
    }


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": pd.Timestamp(value_date),
        "adj_close": adj_close,
        "timestamp_as_of": value_date,
    }
