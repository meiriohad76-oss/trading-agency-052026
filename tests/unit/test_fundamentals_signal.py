from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from signals.fundamentals import fundamental_factor_frame, fundamental_score

AS_OF = date(2022, 12, 31)


def test_fundamental_score_rewards_margins_and_penalizes_leverage() -> None:
    loader = _FakeFundamentalsLoader(
        {
            "AAPL": _fundamentals(
                revenue=100.0,
                net_income=30.0,
                free_cash_flow=25.0,
                leverage=0.20,
            ),
            "MSFT": _fundamentals(
                revenue=100.0,
                net_income=20.0,
                free_cash_flow=20.0,
                leverage=0.30,
            ),
            "DEBT": _fundamentals(
                revenue=100.0,
                net_income=15.0,
                free_cash_flow=12.0,
                leverage=0.80,
            ),
        }
    )

    scores = fundamental_score(AS_OF, {"msft", "AAPL", "DEBT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "DEBT"]
    assert scores["AAPL"] > scores["MSFT"] > scores["DEBT"]


def test_fundamental_factor_frame_skips_missing_or_incomplete_tickers() -> None:
    loader = _FakeFundamentalsLoader(
        {
            "AAPL": _fundamentals(
                revenue=100.0,
                net_income=30.0,
                free_cash_flow=25.0,
                leverage=0.20,
            ),
            "BAD": {"revenue": 100.0, "net_income": 10.0},
        }
    )

    frame = fundamental_factor_frame(AS_OF, {"AAPL", "BAD", "MISSING"}, loader)

    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["composite_score"] == pytest.approx(0.0)


def test_fundamental_score_is_deterministic_and_uppercases_tickers() -> None:
    loader = _FakeFundamentalsLoader(
        {
            "AAPL": _fundamentals(
                revenue=100.0,
                net_income=30.0,
                free_cash_flow=25.0,
                leverage=0.20,
            ),
            "MSFT": _fundamentals(
                revenue=100.0,
                net_income=20.0,
                free_cash_flow=20.0,
                leverage=0.30,
            ),
        }
    )

    first = fundamental_score(AS_OF, {"msft", "aapl"}, loader)
    second = fundamental_score(AS_OF, {"aapl", "msft"}, loader)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}


@dataclass(frozen=True)
class _ProvenancedValue:
    value: dict[str, object]


class _FakeFundamentalsLoader:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self._values = values

    def fundamentals(self, ticker: str, as_of: date) -> _ProvenancedValue:
        del as_of
        return _ProvenancedValue(self._values[ticker.upper()])


def _fundamentals(
    *,
    revenue: float,
    net_income: float,
    free_cash_flow: float,
    leverage: float,
) -> dict[str, object]:
    assets = 100.0
    return {
        "revenue": revenue,
        "net_income": net_income,
        "free_cash_flow": free_cash_flow,
        "total_assets": assets,
        "total_liabilities": assets * leverage,
    }
