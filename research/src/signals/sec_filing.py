from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol


class SecFilingLoader(Protocol):
    def latest_filing_analyses(
        self, ticker: str, as_of: date, n: int = 3
    ) -> list[dict]: ...


def sec_filing_score(
    as_of: date,
    universe: Iterable[str],
    loader: SecFilingLoader,
) -> dict[str, float]:
    """Return a score per ticker from the most recent filing analysis.

    Score is in [−1, +1]: positive = bullish, negative = bearish.
    Returns only tickers with available analysis.
    """
    scores: dict[str, float] = {}
    for ticker in {t.upper() for t in universe}:
        analyses = loader.latest_filing_analyses(ticker, as_of, n=3)
        if not analyses:
            continue
        score = _aggregate_score(analyses)
        if score is not None:
            scores[ticker] = score
    return scores


def _aggregate_score(analyses: list[dict]) -> float | None:
    """Weighted average of signal_score across analyses, most recent weighted highest."""
    if not analyses:
        return None
    total = 0.0
    weight_sum = 0.0
    for i, analysis in enumerate(reversed(analyses)):  # most recent first
        weight = 1.0 / (2 ** i)                        # exponential decay: 1, 0.5, 0.25
        base = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}.get(
            str(analysis.get("sentiment", "NEUTRAL")), 0.0
        )
        confidence = float(analysis.get("confidence", 0.5))
        total += base * confidence * weight
        weight_sum += weight
    return total / weight_sum if weight_sum > 0 else None
