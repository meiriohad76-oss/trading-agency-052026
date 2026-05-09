from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from subscription_email.article_types import FetchedArticle
from subscription_email.config import SubscriptionEmailConfig

TICKER_TEMPLATE = r"(?<![A-Z0-9])\$?{ticker}(?![A-Z0-9])"

POSITIVE_TERMS = frozenset(
    {"upgrade", "upgraded", "bullish", "buy", "outperform", "beats", "raises", "positive"}
)
NEGATIVE_TERMS = frozenset(
    {"downgrade", "downgraded", "bearish", "sell", "underperform", "misses", "cuts", "negative"}
)

CATALYST_TERMS = {
    "quant_rating": ("quant rating", "quant rank"),
    "analyst_rating": ("upgrade", "downgrade", "price target", "analyst"),
    "earnings": ("earnings", "eps", "revenue", "guidance"),
    "rank_change": ("zacks rank", "rank #"),
    "unusual_activity": ("dark pool", "block trade", "unusual options", "sweep"),
}
CATALYST_LABELS = {
    "quant_rating": "quant-rating signal",
    "analyst_rating": "analyst/rating cue",
    "earnings": "earnings/guidance cue",
    "rank_change": "rank-change cue",
    "unusual_activity": "unusual-activity cue",
}
RISK_TERMS = {
    "negative_revision": ("downgrade", "cut", "miss", "lowered", "weak"),
    "valuation": ("valuation", "multiple", "overvalued", "expensive"),
    "macro": ("inflation", "rates", "oil", "recession", "tariff"),
    "legal_or_regulatory": ("lawsuit", "regulatory", "investigation", "antitrust"),
    "execution": ("margin pressure", "competition", "slowdown", "inventory"),
}
RISK_LABELS = {
    "negative_revision": "negative-revision language",
    "valuation": "valuation sensitivity",
    "macro": "macro sensitivity",
    "legal_or_regulatory": "legal/regulatory risk",
    "execution": "execution risk",
}


def analyze_article(page: FetchedArticle, *, config: SubscriptionEmailConfig) -> dict[str, object]:
    clipped = " ".join(page.text[: config.article_max_chars].split())
    tickers = _tickers(f"{page.title or ''}\n{clipped}", config.tickers)
    direction = _direction(clipped)
    catalysts = _catalysts(clipped)
    risk_flags = _risk_flags(clipped)
    key_points = _key_points(catalysts, risk_flags)
    thesis = _thesis(tickers=tickers, direction=direction, catalysts=catalysts, risks=risk_flags)
    return {
        "status": "article_analyzed",
        "url": _normalize_url(page.url),
        "title_hash": _hash(page.title or ""),
        "tickers": tickers,
        "direction": direction,
        "catalysts": catalysts,
        "risk_flags": risk_flags,
        "key_points": key_points,
        "thesis": thesis,
        "context_source": "title_plus_browser_rendered_text",
        "context_chars": len(clipped),
        "status_code": int(page.status_code),
        "text_hash": _hash(clipped),
    }


def summary_from_analysis(analysis: Mapping[str, object]) -> str:
    catalyst_items = _string_items(analysis.get("catalysts"))
    risk_items = _string_items(analysis.get("risk_flags"))
    point_items = _string_items(analysis.get("key_points")) or _key_points(
        catalyst_items,
        risk_items,
    )
    tickers = ",".join(_string_items(analysis.get("tickers"))) or "none"
    catalysts = ",".join(catalyst_items) or "none"
    risks = ",".join(risk_items) or "none"
    key_points = "; ".join(point_items) or "none"
    thesis = _string(analysis.get("thesis")) or _fallback_thesis(analysis)
    context = _string(analysis.get("context_source")) or "cached_legacy_article_analysis"
    chars = _integer(analysis.get("context_chars"))
    chars_detail = f"; chars={chars}" if chars else ""
    return (
        f"Linked content thesis: {thesis} "
        f"Context: {context}{chars_detail}; "
        f"tickers={tickers}; direction={analysis['direction']}; "
        f"catalysts={catalysts}; risks={risks}; key_points={key_points}; "
        f"text_hash={analysis['text_hash']}."
    )


def _tickers(text: str, configured: tuple[str, ...]) -> list[str]:
    upper = text.upper()
    return sorted(
        {
            ticker
            for ticker in configured
            if re.search(TICKER_TEMPLATE.format(ticker=re.escape(ticker.upper())), upper)
        }
    )


def _direction(text: str) -> str:
    lowered = text.lower()
    positive = sum(1 for term in POSITIVE_TERMS if term in lowered)
    negative = sum(1 for term in NEGATIVE_TERMS if term in lowered)
    if positive > negative:
        return "BULLISH"
    if negative > positive:
        return "BEARISH"
    return "NEUTRAL"


def _catalysts(text: str) -> list[str]:
    lowered = text.lower()
    return [
        label
        for label, terms in CATALYST_TERMS.items()
        if any(term in lowered for term in terms)
    ]


def _risk_flags(text: str) -> list[str]:
    lowered = text.lower()
    return [
        label
        for label, terms in RISK_TERMS.items()
        if any(term in lowered for term in terms)
    ]


def _key_points(catalysts: list[str], risks: list[str]) -> list[str]:
    points = [CATALYST_LABELS[item] for item in catalysts if item in CATALYST_LABELS]
    points.extend(RISK_LABELS[item] for item in risks if item in RISK_LABELS)
    return points[:5]


def _thesis(
    *,
    tickers: list[str],
    direction: str,
    catalysts: list[str],
    risks: list[str],
) -> str:
    subject = ", ".join(tickers) if tickers else "the covered ticker universe"
    stance = {
        "BULLISH": "constructive",
        "BEARISH": "cautious",
        "NEUTRAL": "mixed or informational",
    }[direction]
    catalyst_text = _label_join([CATALYST_LABELS.get(item, item) for item in catalysts])
    risk_text = _label_join([RISK_LABELS.get(item, item) for item in risks])
    if catalyst_text and risk_text:
        return (
            f"{stance} context for {subject}, driven by {catalyst_text}, "
            f"with {risk_text} to monitor"
        )
    if catalyst_text:
        return f"{stance} context for {subject}, driven by {catalyst_text}"
    if risk_text:
        return f"{stance} context for {subject}, with {risk_text} to monitor"
    return f"{stance} context for {subject}; no specific catalyst bucket was detected"


def _label_join(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def _fallback_thesis(analysis: Mapping[str, object]) -> str:
    tickers = _string_items(analysis.get("tickers"))
    direction = _string(analysis.get("direction")) or "NEUTRAL"
    return _thesis(
        tickers=tickers,
        direction=direction,
        catalysts=_string_items(analysis.get("catalysts")),
        risks=_string_items(analysis.get("risk_flags")),
    )


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0
