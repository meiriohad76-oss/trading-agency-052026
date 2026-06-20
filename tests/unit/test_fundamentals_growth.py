from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest
from pit.exceptions import DataNotAvailableAt
from signals.fundamentals import fundamental_factor_frame

AS_OF = date(2024, 12, 31)


def test_returns_shared_detail_contract_keys_without_optional_loaders() -> None:
    loader = _FakeFundamentalsLoader({"AAPL": _payload()})

    frame = fundamental_factor_frame(AS_OF, {"AAPL"}, loader)
    row = frame.iloc[0]

    for key in (
        "filing_period",
        "filing_year",
        "filing_form",
        "filing_period_end",
        "period_alignment_status",
        "quality_score",
        "growth_score",
        "valuation_score",
        "forward_score",
        "composite_score",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "fcf_margin",
        "roe",
        "roa",
        "leverage",
        "revenue_growth_qoq",
        "revenue_growth_yoy",
        "net_income_growth_qoq",
        "net_income_growth_yoy",
        "fcf_growth_qoq",
        "fcf_growth_yoy",
        "trailing_pe",
        "inverse_trailing_pe",
        "forward_pe",
        "forward_eps",
        "eps_beat_rate",
        "analyst_count",
        "forward_data_status",
        "forward_data_as_of",
    ):
        assert key in frame.columns

    assert row["period_alignment_status"] == "aligned"
    assert row["net_margin"] == pytest.approx(0.24)
    assert pd.isna(row["growth_score"])
    assert pd.isna(row["forward_score"])


def test_revenue_growth_yoy_matches_same_quarter_last_year() -> None:
    loader = _FakeFundamentalsLoader({"GROW": _payload()})
    history_loader = _FakeHistoryLoader({"GROW": _history([100.0, 105.0, 108.0, 112.0, 125.0])})

    frame = fundamental_factor_frame(AS_OF, {"GROW"}, loader, history_loader=history_loader)
    row = frame.iloc[0]

    assert row["revenue_growth_yoy"] == pytest.approx(0.25)
    assert row["revenue_growth_qoq"] == pytest.approx((125.0 / 112.0) - 1.0)


def test_growth_uses_period_end_not_row_order() -> None:
    ordered = _history([100.0, 105.0, 108.0, 112.0, 125.0])
    shuffled = ordered.iloc[list(reversed(range(len(ordered))))].reset_index(drop=True)
    loader = _FakeFundamentalsLoader({"GROW": _payload()})
    history_loader = _FakeHistoryLoader({"GROW": shuffled})

    frame = fundamental_factor_frame(AS_OF, {"GROW"}, loader, history_loader=history_loader)

    assert frame.iloc[0]["revenue_growth_yoy"] == pytest.approx(0.25)


def test_single_period_history_returns_none_growth_without_crashing() -> None:
    loader = _FakeFundamentalsLoader({"AAPL": _payload()})
    history_loader = _FakeHistoryLoader({"AAPL": _history([100.0])})

    frame = fundamental_factor_frame(AS_OF, {"AAPL"}, loader, history_loader=history_loader)

    assert len(frame) == 1
    assert pd.isna(frame.iloc[0]["revenue_growth_yoy"])
    assert pd.isna(frame.iloc[0]["growth_score"])


def test_loader_programming_error_is_not_silently_swallowed() -> None:
    loader = _FakeFundamentalsLoader({"AAPL": _payload()})

    class BrokenHistoryLoader:
        def fundamentals_history(
            self,
            ticker: str,
            as_of: date,
            n_periods: int = 8,
        ) -> pd.DataFrame:
            raise KeyError("schema drift")

    with pytest.raises(KeyError, match="schema drift"):
        fundamental_factor_frame(AS_OF, {"AAPL"}, loader, history_loader=BrokenHistoryLoader())


def test_composite_score_uses_quality_and_growth_when_available() -> None:
    loader = _FakeFundamentalsLoader(
        {
            "GROW": _payload(),
            "FLAT": _payload(),
        }
    )
    history_loader = _FakeHistoryLoader(
        {
            "GROW": _history([100.0, 105.0, 108.0, 112.0, 125.0]),
            "FLAT": _history([100.0, 100.0, 100.0, 100.0, 100.0]),
        }
    )

    frame = fundamental_factor_frame(AS_OF, {"GROW", "FLAT"}, loader, history_loader=history_loader)

    grow = frame[frame["ticker"] == "GROW"].iloc[0]
    flat = frame[frame["ticker"] == "FLAT"].iloc[0]
    assert grow["growth_score"] > flat["growth_score"]
    assert grow["composite_score"] > flat["composite_score"]


def test_price_loader_adds_trailing_valuation_fields() -> None:
    loader = _FakeFundamentalsLoader(
        {"AAPL": _payload() | {"shares_outstanding": 10.0}}
    )
    price_loader = _FakePriceLoader(
        pd.DataFrame([{"ticker": "AAPL", "date": AS_OF, "close": 10.0}])
    )

    frame = fundamental_factor_frame(AS_OF, {"AAPL"}, loader, price_loader=price_loader)
    row = frame.iloc[0]

    assert row["trailing_pe"] == pytest.approx((10.0 * 10.0) / 24.0)
    assert row["inverse_trailing_pe"] == pytest.approx(-((10.0 * 10.0) / 24.0))
    assert row["fcf_yield"] == pytest.approx(27.0 / 100.0)
    assert row["valuation_score"] == pytest.approx(0.0)


@dataclass
class _ProvenancedValue:
    value: dict[str, object]


class _FakeFundamentalsLoader:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self._values = values

    def fundamentals(self, ticker: str, as_of: date) -> _ProvenancedValue:
        normalized = ticker.upper()
        if normalized not in self._values:
            raise DataNotAvailableAt("sec_company_facts", as_of, f"missing {normalized}")
        return _ProvenancedValue(self._values[normalized])


class _FakeHistoryLoader:
    def __init__(self, values: dict[str, pd.DataFrame]) -> None:
        self._values = values

    def fundamentals_history(
        self,
        ticker: str,
        as_of: date,
        n_periods: int = 8,
    ) -> pd.DataFrame:
        return self._values.get(ticker.upper(), pd.DataFrame())


class _FakePriceLoader:
    def __init__(self, prices: pd.DataFrame) -> None:
        self._prices = prices

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pd.DataFrame:
        return self._prices[self._prices["ticker"].isin(tickers)]


def _payload() -> dict[str, object]:
    return {
        "revenue": 100.0,
        "gross_profit": 44.0,
        "operating_income": 30.0,
        "net_income": 24.0,
        "free_cash_flow": 27.0,
        "total_assets": 200.0,
        "total_liabilities": 90.0,
        "total_equity": 110.0,
        "filing_period": "Q3",
        "filing_year": 2024,
        "filing_form": "10-Q",
        "filing_period_end": "2024-09-30",
    }


def _history(revenues: list[float]) -> pd.DataFrame:
    period_ends = [
        date(2023, 9, 30),
        date(2023, 12, 31),
        date(2024, 3, 31),
        date(2024, 6, 30),
        date(2024, 9, 30),
    ][: len(revenues)]
    rows: list[dict[str, object]] = []
    for revenue, period_end in zip(revenues, period_ends, strict=True):
        rows.extend(
            [
                {"metric": "revenue", "value": revenue, "period_end": period_end},
                {"metric": "net_income", "value": revenue * 0.24, "period_end": period_end},
                {"metric": "free_cash_flow", "value": revenue * 0.27, "period_end": period_end},
            ]
        )
    return pd.DataFrame(rows)
