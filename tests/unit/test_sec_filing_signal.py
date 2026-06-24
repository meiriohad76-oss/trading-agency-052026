from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from signals.sec_filing import SecFilingLoader, sec_filing_score


@dataclass
class _FakeFilingLoader:
    _analyses: dict[str, list[dict]]

    def latest_filing_analyses(
        self, ticker: str, as_of: date, n: int = 3
    ) -> list[dict]:
        return self._analyses.get(ticker.upper(), [])


def test_bullish_filing_produces_positive_score() -> None:
    loader = _FakeFilingLoader({
        "AAPL": [
            {"sentiment": "BULLISH", "confidence": 0.85, "filing_date": "2024-11-01",
             "eps_vs_estimate": "BEAT", "guidance_change": "RAISED"},
        ]
    })

    scores = sec_filing_score(date(2024, 11, 15), {"AAPL"}, loader)

    assert "AAPL" in scores
    assert scores["AAPL"] > 0


def test_bearish_filing_produces_negative_score() -> None:
    loader = _FakeFilingLoader({
        "MSFT": [
            {"sentiment": "BEARISH", "confidence": 0.7, "filing_date": "2024-11-01",
             "eps_vs_estimate": "MISS", "guidance_change": "LOWERED"},
        ]
    })

    scores = sec_filing_score(date(2024, 11, 15), {"MSFT"}, loader)

    assert scores["MSFT"] < 0


def test_missing_ticker_excluded_from_scores() -> None:
    loader = _FakeFilingLoader({})  # no data for AMZN

    scores = sec_filing_score(date(2024, 11, 15), {"AMZN"}, loader)

    assert "AMZN" not in scores
