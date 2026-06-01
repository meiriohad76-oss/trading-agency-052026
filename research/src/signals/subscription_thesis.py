from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from pit.exceptions import DataNotAvailableAt
from signals._common import float_or_none, payload_dict

DEFAULT_LOOKBACK_DAYS = 10
MAX_SUMMARY_CHARS = 420
MAX_SUMMARY_ITEMS = 3
RECENCY_DECAY = 0.65
HEADLINE_FOCUS_RE = re.compile(r"(?: - |Email:\s+)\$?([A-Z]{1,5})(?=\s*:|\s+)")
DIRECTION_SCORES = {
    "BULLISH": 0.65,
    "BEARISH": -0.65,
    "NEUTRAL": 0.0,
    "MIXED": 0.0,
}
SOURCE_QUALITY_WEIGHTS = {
    "premium_article": 1.0,
    "full_article": 1.0,
    "article": 0.9,
    "email_summary": 0.65,
    "deterministic_fallback": 0.5,
    "headline_only": 0.35,
}
RELEVANCE_WEIGHTS = {
    "direct": 1.0,
    "primary": 1.0,
    "secondary": 0.55,
    "sector": 0.35,
    "macro": 0.25,
}
ANALYZED_LINK_STATUSES = {
    "article_analyzed",
    "article_analyzed_deterministic_fallback",
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
    except DataNotAvailableAt:
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
        if str(payload.get("linked_content_status")) not in ANALYZED_LINK_STATUSES:
            continue
        if not _text(payload.get("linked_content_summary")):
            continue
        grouped[ticker].append(payload)
    return grouped


def _context(ticker: str, events: list[dict[str, object]]) -> SubscriptionThesisContext:
    ordered = sorted(events, key=_timestamp_key, reverse=True)
    scores = [_direction_score(event) * _confidence(event) for event in ordered]
    weights = [
        (RECENCY_DECAY**index) * _source_quality_weight(event) * _relevance_weight(event)
        for index, event in enumerate(ordered)
    ]
    total_weight = sum(weights)
    score = (
        sum(score * weight for score, weight in zip(scores, weights, strict=True))
        / total_weight
        if total_weight
        else 0.0
    )
    return SubscriptionThesisContext(
        ticker=ticker,
        score=round(max(-1.0, min(1.0, score)), 6),
        summary=_summary(ticker, ordered),
    )


def _summary(ticker: str, events: list[dict[str, object]]) -> str:
    snippets: list[str] = []
    for event in events[:MAX_SUMMARY_ITEMS]:
        service = _label(str(event.get("service", "subscription")))
        event_type = _label(str(event.get("event_type", "article thesis")))
        direction = _event_direction(event)
        thesis = _clip(
            _text(event.get("linked_content_thesis"))
            or _extract_legacy_thesis(_text(event.get("linked_content_summary")))
            or "article thesis analyzed"
        )
        relevance = _ticker_relevance_prefix(ticker, event)
        points = _point_text(_string_items(event.get("linked_content_key_points")))
        suffix = f" ({points})" if points else ""
        snippets.append(f"{direction} {service} {event_type}: {relevance}{thesis}{suffix}")
    suffix = "" if len(events) <= MAX_SUMMARY_ITEMS else f" +{len(events) - MAX_SUMMARY_ITEMS} more"
    return f"Subscription article thesis{suffix}: " + " | ".join(snippets)


def _ticker_relevance_prefix(ticker: str, event: dict[str, object]) -> str:
    title = _text(event.get("title")) or ""
    focus = _headline_focus_ticker(title)
    if focus == ticker.upper():
        return f"direct headline focus on {ticker}; "
    if focus is not None:
        return f"secondary theme context; headline focus is {focus}; "
    return ""


def _headline_focus_ticker(title: str) -> str | None:
    match = HEADLINE_FOCUS_RE.search(title)
    return match.group(1).upper() if match is not None else None


def _direction_score(event: dict[str, object]) -> float:
    return DIRECTION_SCORES.get(_event_direction(event), 0.0)


def _event_direction(event: dict[str, object]) -> str:
    linked_direction = str(event.get("linked_content_direction") or "").upper()
    if linked_direction in DIRECTION_SCORES:
        return linked_direction
    return str(event.get("direction", "")).upper()


def _confidence(event: dict[str, object]) -> float:
    value = float_or_none(event.get("confidence"))
    if value is None:
        return 1.0
    return max(0.0, min(1.0, value))


def _source_quality_weight(event: dict[str, object]) -> float:
    key = _weight_key(event.get("source_quality") or event.get("linked_content_depth"))
    if key is None and str(event.get("linked_content_status") or "").endswith(
        "deterministic_fallback"
    ):
        key = "deterministic_fallback"
    return SOURCE_QUALITY_WEIGHTS.get(key or "", 0.75)


def _relevance_weight(event: dict[str, object]) -> float:
    key = _relevance_key(event.get("linked_content_relevance") or event.get("ticker_relevance"))
    return RELEVANCE_WEIGHTS.get(key or "", 0.75)


def _relevance_key(value: object) -> str | None:
    key = _weight_key(value)
    if key is None:
        return None
    if key.startswith(("direct_relevance", "direct")):
        return "direct"
    if key.startswith("primary"):
        return "primary"
    if key.startswith("secondary"):
        return "secondary"
    if key.startswith("sector"):
        return "sector"
    if key.startswith("macro"):
        return "macro"
    return key


def _weight_key(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or None


def _timestamp_key(event: dict[str, object]) -> str:
    return str(event.get("timestamp_as_of") or event.get("received_at") or "")


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _string_items(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _point_text(points: list[str]) -> str:
    if not points:
        return ""
    return "; ".join(points[:2])


def _extract_legacy_thesis(summary: str | None) -> str | None:
    if summary is None or not summary.startswith("Linked content thesis:"):
        return summary
    cleaned = summary.removeprefix("Linked content thesis:").strip()
    for marker in (". Why it matters:", " Context:", "; tickers=", "; direction="):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0]
            break
    return cleaned.strip(" .") or None


def _clip(value: str) -> str:
    if len(value) <= MAX_SUMMARY_CHARS:
        return value
    return value[: MAX_SUMMARY_CHARS - 3].rstrip() + "..."


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip() or "subscription"
