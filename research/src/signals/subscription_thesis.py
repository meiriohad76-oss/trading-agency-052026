from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from signals._common import float_or_none, payload_dict

DEFAULT_LOOKBACK_DAYS = 10
MAX_SUMMARY_CHARS = 420
MAX_SUMMARY_ITEMS = 3
DIRECTION_SCORES = {
    "BULLISH": 0.65,
    "BEARISH": -0.65,
    "NEUTRAL": 0.0,
    "MIXED": 0.0,
}


@dataclass(frozen=True)
class SubscriptionThesisContext:
    ticker: str
    score: float
    summary: str


class SubscriptionEmailLoader(Protocol):
    def subscription_emails(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> Sequence[object]: ...


def subscription_thesis_score(
    as_of: date,
    universe: set[str],
    loader: SubscriptionEmailLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return signed context scores from analyzed subscription article theses."""
    return {
        context.ticker: context.score
        for context in subscription_thesis_contexts(as_of, universe, loader, lookback_days)
    }


def subscription_thesis_contexts(
    as_of: date,
    universe: Iterable[str],
    loader: SubscriptionEmailLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[SubscriptionThesisContext]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return []
    try:
        events = loader.subscription_emails(tickers, as_of, lookback_days)
    except Exception:
        return []
    grouped = _group_analyzed_events(tickers, events)
    return [
        _context(ticker, grouped[ticker])
        for ticker in sorted(grouped)
        if grouped[ticker]
    ]


def _group_analyzed_events(
    tickers: list[str],
    events: Sequence[object],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {ticker: [] for ticker in tickers}
    for event in events:
        payload = payload_dict(event, "subscription email")
        ticker = str(payload.get("ticker", "")).upper()
        if ticker not in grouped:
            continue
        if str(payload.get("linked_content_status")) != "article_analyzed":
            continue
        if not _text(payload.get("linked_content_summary")):
            continue
        grouped[ticker].append(payload)
    return grouped


def _context(ticker: str, events: list[dict[str, object]]) -> SubscriptionThesisContext:
    scores = [_direction_score(event) * _confidence(event) for event in events]
    score = sum(scores) / len(scores) if scores else 0.0
    return SubscriptionThesisContext(
        ticker=ticker,
        score=round(max(-1.0, min(1.0, score)), 6),
        summary=_summary(events),
    )


def _summary(events: list[dict[str, object]]) -> str:
    snippets: list[str] = []
    for event in events[:MAX_SUMMARY_ITEMS]:
        service = _label(str(event.get("service", "subscription")))
        event_type = _label(str(event.get("event_type", "article thesis")))
        direction = str(event.get("direction", "NEUTRAL")).upper()
        thesis = _clip(_text(event.get("linked_content_summary")) or "analysis available")
        snippets.append(f"{direction} {service} {event_type}: {thesis}")
    suffix = "" if len(events) <= MAX_SUMMARY_ITEMS else f" +{len(events) - MAX_SUMMARY_ITEMS} more"
    return f"Subscription article thesis{suffix}: " + " | ".join(snippets)


def _direction_score(event: dict[str, object]) -> float:
    return DIRECTION_SCORES.get(str(event.get("direction", "")).upper(), 0.0)


def _confidence(event: dict[str, object]) -> float:
    value = float_or_none(event.get("confidence"))
    if value is None:
        return 1.0
    return max(0.0, min(1.0, value))


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _clip(value: str) -> str:
    if len(value) <= MAX_SUMMARY_CHARS:
        return value
    return value[: MAX_SUMMARY_CHARS - 3].rstrip() + "..."


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip() or "subscription"
