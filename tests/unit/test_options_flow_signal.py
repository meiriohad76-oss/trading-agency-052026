from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import polars as pl
import pytest
from backtests.portfolio import CostModel
from backtests.walk_forward import WalkForward, WalkForwardConfig
from signals.options_flow import options_flow_frame, options_flow_score

AS_OF = date(2026, 5, 7)
LOOKBACK_DAYS = 10


def test_options_flow_score_rewards_call_pressure_and_penalizes_put_pressure() -> None:
    loader = _FakeOptionsLoader(
        [
            _option("AAPL", "call", 100),
            _option("AAPL", "put", 20),
            _option("MSFT", "call", 50),
            _option("MSFT", "put", 50),
            _option("TSLA", "call", 20),
            _option("TSLA", "put", 100),
        ]
    )

    scores = options_flow_score(AS_OF, {"tsla", "AAPL", "MSFT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "TSLA"]
    assert scores["AAPL"] > scores["MSFT"] > scores["TSLA"]


def test_options_flow_frame_skips_zero_volume_tickers() -> None:
    loader = _FakeOptionsLoader(
        [
            _option("AAPL", "call", 100),
            _option("AAPL", "put", 20),
            _option("ZERO", "call", 0),
            _option("ZERO", "put", 0),
        ]
    )

    frame = options_flow_frame(AS_OF, {"AAPL", "ZERO"}, loader)

    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["options_flow_score"] == pytest.approx(1.0)


def test_options_flow_score_is_deterministic_uppercases_and_forwards_lookback() -> None:
    loader = _FakeOptionsLoader([_option("AAPL", "call", 100), _option("MSFT", "put", 100)])

    first = options_flow_score(AS_OF, {"msft", "aapl"}, loader, LOOKBACK_DAYS)
    second = options_flow_score(AS_OF, {"aapl", "msft"}, loader, LOOKBACK_DAYS)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}
    assert loader.calls == [
        (["AAPL", "MSFT"], AS_OF, LOOKBACK_DAYS),
        (["AAPL", "MSFT"], AS_OF, LOOKBACK_DAYS),
    ]


def test_options_flow_score_runs_inside_walk_forward_scoped_loader() -> None:
    loader = _FakeWalkForwardOptionsLoader(
        [_option("AAPL", "call", 100), _option("MSFT", "put", 100)]
    )
    config = WalkForwardConfig(
        step_size_days=2,
        max_positions=1,
        static_universe={"AAPL", "MSFT"},
        cost_model=CostModel(bps_per_side=0.0),
    )

    portfolio = WalkForward(config, loader, options_flow_score).run(AS_OF, date(2026, 5, 9))

    assert portfolio.positions.iloc[0]["AAPL"] == pytest.approx(1.0)


class _FakeOptionsLoader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[list[str], date, int]] = []

    def option_chains(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        self.calls.append((tickers, as_of, lookback_days))
        requested = set(tickers)
        return pl.DataFrame([row for row in self._rows if row["ticker"] in requested])


class _FakeWalkForwardOptionsLoader(_FakeOptionsLoader):
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


def _option(ticker: str, option_type: str, volume: int) -> dict[str, object]:
    return {
        "ticker": ticker,
        "snapshot_date": AS_OF,
        "expiration": date(2026, 6, 19),
        "option_type": option_type,
        "strike": 100.0,
        "volume": volume,
        "open_interest": volume * 2,
        "implied_volatility": 0.3,
    }


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": pd.Timestamp(value_date),
        "adj_close": adj_close,
        "timestamp_as_of": value_date,
    }
