from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import polars as pl
import pytest
from backtests.portfolio import CostModel
from backtests.walk_forward import WalkForward, WalkForwardConfig
from signals.insider import insider_factor_frame, insider_score

AS_OF = date(2023, 1, 15)
LOOKBACK_DAYS = 45


def test_insider_score_rewards_purchases_and_penalizes_sales() -> None:
    loader = _FakeInsiderLoader(
        {
            "AAPL": [_transaction("P", shares=100.0, price=20.0, filer_cik="1")],
            "MSFT": [],
            "TSLA": [_transaction("S", shares=80.0, price=25.0, filer_cik="2")],
        }
    )

    scores = insider_score(AS_OF, {"tsla", "AAPL", "MSFT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "TSLA"]
    assert scores["AAPL"] > scores["MSFT"] > scores["TSLA"]


def test_insider_factor_frame_ignores_non_directional_and_incomplete_rows() -> None:
    loader = _FakeInsiderLoader(
        {
            "AAPL": [
                _transaction("A", shares=200.0, price=10.0, filer_cik="1"),
                {"transaction_type": "P", "price": 10.0},
                _transaction("P", shares=10.0, price=None, filer_name="Buyer"),
            ],
            "MISSING": KeyError("missing data"),
        }
    )

    frame = insider_factor_frame(AS_OF, {"AAPL", "MISSING"}, loader)

    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["net_transaction_value"] == pytest.approx(10.0)
    assert frame.iloc[0]["directional_transactions"] == 1
    assert frame.iloc[0]["unique_filers"] == 1
    assert frame.iloc[0]["insider_score"] == pytest.approx(0.0)


def test_insider_score_is_deterministic_uppercases_tickers_and_passes_lookback() -> None:
    loader = _FakeInsiderLoader(
        {
            "AAPL": [_transaction("P", shares=100.0, price=20.0, filer_cik="1")],
            "MSFT": [_transaction("S", shares=10.0, price=20.0, filer_cik="2")],
        }
    )

    first = insider_score(AS_OF, {"msft", "aapl"}, loader, lookback_days=LOOKBACK_DAYS)
    second = insider_score(AS_OF, {"aapl", "msft"}, loader, lookback_days=LOOKBACK_DAYS)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}
    assert loader.calls == [
        ("AAPL", AS_OF, LOOKBACK_DAYS),
        ("MSFT", AS_OF, LOOKBACK_DAYS),
        ("AAPL", AS_OF, LOOKBACK_DAYS),
        ("MSFT", AS_OF, LOOKBACK_DAYS),
    ]


def test_insider_score_runs_inside_walk_forward_scoped_loader() -> None:
    loader = _FakeWalkForwardLoader(
        {
            "AAPL": [_transaction("P", shares=100.0, price=20.0, filer_cik="1")],
            "MSFT": [],
        }
    )
    config = WalkForwardConfig(
        step_size_days=2,
        max_positions=1,
        static_universe={"AAPL", "MSFT"},
        cost_model=CostModel(bps_per_side=0.0),
    )

    portfolio = WalkForward(config, loader, insider_score).run(date(2023, 1, 15), date(2023, 1, 17))

    assert portfolio.positions.iloc[0]["AAPL"] == pytest.approx(1.0)


@dataclass(frozen=True)
class _ProvenancedValue:
    value: dict[str, object]


class _FakeInsiderLoader:
    def __init__(self, values: dict[str, list[dict[str, object]] | Exception]) -> None:
        self._values = values
        self.calls: list[tuple[str, date, int]] = []

    def insider_transactions(
        self,
        ticker: str,
        as_of: date,
        lookback_days: int,
    ) -> list[_ProvenancedValue]:
        normalized = ticker.upper()
        self.calls.append((normalized, as_of, lookback_days))
        values = self._values[normalized]
        if isinstance(values, Exception):
            raise values
        return [_ProvenancedValue(value) for value in values]


class _FakeWalkForwardLoader(_FakeInsiderLoader):
    def universe_members(self, as_of: date) -> set[str]:
        del as_of
        return {"AAPL", "MSFT"}

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        start = date(2023, 1, 15)
        for offset in range((as_of - start).days + 1):
            value_date = start + timedelta(days=offset)
            for ticker in tickers:
                rows.append(_price(ticker, value_date, 100.0 + offset))
        return pl.DataFrame(rows)


def _transaction(
    transaction_type: str,
    *,
    shares: float,
    price: float | None,
    filer_cik: str | None = None,
    filer_name: str | None = None,
) -> dict[str, object]:
    return {
        "transaction_type": transaction_type,
        "shares": shares,
        "price": price,
        "filer_cik": filer_cik,
        "filer_name": filer_name,
    }


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": pd.Timestamp(value_date),
        "adj_close": adj_close,
        "timestamp_as_of": value_date,
    }
