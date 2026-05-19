from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from pit.exceptions import DataNotAvailableAt
from signals.institutional import institutional_factor_frame, institutional_score

AS_OF = date(2023, 2, 28)


def test_institutional_score_rewards_accumulation_and_penalizes_distribution() -> None:
    loader = _FakeInstitutionalLoader(
        {
            "AAPL": _holdings(holder_count=5, shares_held=1_000.0, change=200.0),
            "MSFT": _holdings(holder_count=4, shares_held=1_000.0, change=0.0),
            "SELL": _holdings(holder_count=3, shares_held=1_000.0, change=-150.0),
        }
    )

    scores = institutional_score(AS_OF, {"sell", "AAPL", "MSFT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "SELL"]
    assert scores["AAPL"] > scores["MSFT"] > scores["SELL"]


def test_institutional_factor_frame_skips_missing_or_incomplete_tickers() -> None:
    loader = _FakeInstitutionalLoader(
        {
            "AAPL": _holdings(holder_count=5, shares_held=1_000.0, change=200.0),
            "BAD": {"holder_count": 1, "total_shares_held": 100.0},
            "MISSING": DataNotAvailableAt("sec_13f", AS_OF, "missing data"),
        }
    )

    frame = institutional_factor_frame(AS_OF, {"AAPL", "BAD", "MISSING"}, loader)

    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["institutional_score"] == pytest.approx(0.0)


def test_institutional_score_is_deterministic_and_uppercases_tickers() -> None:
    loader = _FakeInstitutionalLoader(
        {
            "AAPL": _holdings(holder_count=5, shares_held=1_000.0, change=200.0),
            "MSFT": _holdings(holder_count=4, shares_held=1_000.0, change=0.0),
        }
    )

    first = institutional_score(AS_OF, {"msft", "aapl"}, loader)
    second = institutional_score(AS_OF, {"aapl", "msft"}, loader)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}


@dataclass(frozen=True)
class _ProvenancedValue:
    value: dict[str, object]


class _FakeInstitutionalLoader:
    def __init__(self, values: dict[str, dict[str, object] | Exception]) -> None:
        self._values = values

    def institutional_holdings(self, ticker: str, as_of: date) -> _ProvenancedValue:
        del as_of
        value = self._values[ticker.upper()]
        if isinstance(value, Exception):
            raise value
        return _ProvenancedValue(value)


def _holdings(*, holder_count: int, shares_held: float, change: float) -> dict[str, object]:
    return {
        "quarter_end_date": date(2022, 12, 31),
        "holder_count": holder_count,
        "total_shares_held": shares_held,
        "total_change_from_prev_quarter": change,
    }
