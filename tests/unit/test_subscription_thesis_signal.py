from __future__ import annotations

from datetime import date

import pytest
from pit.exceptions import DataNotAvailableAt
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


def test_subscription_thesis_accepts_deterministic_fallback_analysis() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "AAPL",
                "BULLISH",
                "Linked content thesis: deterministic fallback context for AAPL.",
                linked_content_status="article_analyzed_deterministic_fallback",
            )
        ]
    )

    scores = subscription_thesis_score(AS_OF, {"AAPL"}, loader)

    assert scores["AAPL"] == pytest.approx(0.65)


def test_subscription_thesis_ignores_no_ticker_match_analysis() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "AAPL",
                "BULLISH",
                "Linked content thesis: generic article context.",
                linked_content_status="article_analyzed_no_ticker_match",
            )
        ]
    )

    assert subscription_thesis_score(AS_OF, {"AAPL"}, loader) == {}


def test_subscription_thesis_ignores_portfolio_context_only_analysis() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "AAPL",
                "BEARISH",
                "Linked article is about another company, not AAPL.",
                linked_content_status="article_analyzed_portfolio_context_only",
            )
        ]
    )

    assert subscription_thesis_score(AS_OF, {"AAPL"}, loader) == {}


def test_subscription_thesis_score_propagates_loader_bugs() -> None:
    with pytest.raises(RuntimeError, match="loader bug"):
        subscription_thesis_score(AS_OF, {"AAPL"}, _BuggyLoader())


def test_subscription_thesis_score_weights_newer_reversal_more_heavily() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "AAPL",
                "BULLISH",
                "Linked content thesis: older constructive context.",
                timestamp_as_of="2026-05-01T12:00:00+00:00",
            ),
            _event(
                "AAPL",
                "BEARISH",
                "Linked content thesis: newer cautious context.",
                timestamp_as_of="2026-05-08T12:00:00+00:00",
            ),
        ]
    )

    scores = subscription_thesis_score(AS_OF, {"AAPL"}, loader)

    assert scores["AAPL"] < 0.0


def test_subscription_thesis_weights_source_depth_and_relevance_over_recency() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "ASML",
                "BULLISH",
                "Linked content thesis: direct bullish lithography thesis.",
                title="Seeking Alpha Email: ASML: direct thesis",
                timestamp_as_of="2026-05-07T12:00:00+00:00",
                linked_content_depth="full_article",
                linked_content_relevance="direct",
                confidence=0.8,
            ),
            _event(
                "ASML",
                "BEARISH",
                "Linked content thesis: weak secondary mention.",
                title="Seeking Alpha Email: NVDA: sector roundup",
                timestamp_as_of="2026-05-08T12:00:00+00:00",
                source_quality="headline_only",
                linked_content_relevance="secondary",
                confidence=0.8,
            ),
        ]
    )

    context = subscription_thesis_contexts(AS_OF, {"ASML"}, loader)[0]

    assert context.score > 0.20
    assert "direct headline focus on ASML" in context.summary


def test_subscription_thesis_summary_leads_with_newest_analyzed_article() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "AAPL",
                "BULLISH",
                "Linked content thesis: older constructive context.",
                timestamp_as_of="2026-05-06T12:00:00+00:00",
            ),
            _event(
                "AAPL",
                "BULLISH",
                "Linked content thesis: newest constructive context.",
                timestamp_as_of="2026-05-08T12:00:00+00:00",
            ),
        ]
    )

    context = subscription_thesis_contexts(AS_OF, {"AAPL"}, loader)[0]

    assert context.summary.index("newest constructive context") < context.summary.index(
        "older constructive context"
    )


def test_subscription_thesis_summary_marks_secondary_headline_focus() -> None:
    loader = _FakeSubscriptionEmailLoader(
        [
            _event(
                "NVDA",
                "BULLISH",
                "Linked content thesis: quantum-computing basket context.",
                title=(
                    "Seeking Alpha Email: sa quant rating change - "
                    "MSFT: SA Asks: What are the most attractive quantum computing stocks?"
                ),
            )
        ]
    )

    context = subscription_thesis_contexts(AS_OF, {"NVDA"}, loader)[0]

    assert "secondary theme context; headline focus is MSFT" in context.summary


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
        raise DataNotAvailableAt("subscription_emails", AS_OF, "no coverage")


class _BuggyLoader:
    def subscription_emails(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        del tickers, as_of, lookback_days
        raise RuntimeError("loader bug")


def _event(
    ticker: str,
    direction: str,
    summary: str | None,
    *,
    title: str = "Seeking Alpha Email: AAPL article",
    timestamp_as_of: str = "2026-05-08T12:00:00+00:00",
    linked_content_status: str = "article_analyzed",
    source_quality: str | None = None,
    linked_content_relevance: str | None = None,
    linked_content_depth: str | None = None,
    confidence: float = 1.0,
) -> dict[str, object]:
    event: dict[str, object] = {
        "ticker": ticker,
        "service": "seeking_alpha",
        "event_type": "sa_analyst_article",
        "direction": direction,
        "title": title,
        "linked_content_status": linked_content_status,
        "linked_content_summary": summary,
        "timestamp_as_of": timestamp_as_of,
        "confidence": confidence,
    }
    if source_quality is not None:
        event["source_quality"] = source_quality
    if linked_content_relevance is not None:
        event["linked_content_relevance"] = linked_content_relevance
    if linked_content_depth is not None:
        event["linked_content_depth"] = linked_content_depth
    return event
