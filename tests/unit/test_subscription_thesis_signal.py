from __future__ import annotations

from datetime import date

import pytest
from signals.subscription_thesis import (
    subscription_thesis_contexts,
    subscription_thesis_score,
)

AS_OF = date(2026, 5, 8)


def test_subscription_thesis_score_uses_analyzed_article_context_only() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event("AAPL", "BULLISH", "Linked content thesis: constructive context for AAPL."),
            _event("MSFT", "BEARISH", "Linked content thesis: cautious context for MSFT."),
            _event("NVDA", "BULLISH", None),
        ]
    )

    scores = subscription_thesis_score(AS_OF, {"aapl", "msft", "nvda"}, loader)
    contexts = subscription_thesis_contexts(AS_OF, {"AAPL", "MSFT", "NVDA"}, loader)

    assert scores["AAPL"] == pytest.approx(0.65)
    assert scores["MSFT"] == pytest.approx(-0.65)
    assert "NVDA" not in scores
    assert contexts[0].summary.startswith("Subscription article thesis")


def test_subscription_thesis_score_is_empty_when_loader_has_no_coverage() -> None:
    assert subscription_thesis_score(AS_OF, {"AAPL"}, _FailingLoader()) == {}


class _FakeSubscriptionEmailLoader:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = events

    def subscription_emails(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        del as_of, lookback_days
        return [event for event in self.events if event["ticker"] in tickers]


class _FailingLoader:
    def subscription_emails(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        del tickers, as_of, lookback_days
        raise RuntimeError("no coverage")


def _event(ticker: str, direction: str, summary: str | None) -> dict[str, object]:
    return {
        "ticker": ticker,
        "service": "seeking_alpha",
        "event_type": "sa_analyst_article",
        "direction": direction,
        "linked_content_status": "article_analyzed",
        "linked_content_summary": summary,
        "confidence": 1.0,
    }
