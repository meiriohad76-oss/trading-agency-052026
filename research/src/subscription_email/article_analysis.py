from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from subscription_email.article_types import FetchedArticle
from subscription_email.config import SubscriptionEmailConfig

TICKER_TEMPLATE = r"(?<![A-Z0-9])\$?{ticker}(?![A-Z0-9])"

POSITIVE_TERMS = frozenset(
    {
        "accelerate",
        "beat",
        "beats",
        "bullish",
        "buy",
        "growth",
        "outperform",
        "positive",
        "raised",
        "raises",
        "upgrade",
        "upgraded",
    }
)
NEGATIVE_TERMS = frozenset(
    {
        "bearish",
        "cut",
        "cuts",
        "downgrade",
        "downgraded",
        "lowered",
        "miss",
        "misses",
        "negative",
        "sell",
        "slowdown",
        "underperform",
        "weak",
    }
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
TRACKING_QUERY_KEYS = {
    "campaign",
    "cid",
    "cmpid",
    "feed",
    "feed_item_type",
    "icid",
    "mailing_id",
    "message_id",
    "ref",
    "source",
    "source_id",
}
CATALYST_READOUTS = {
    "quant_rating": {
        "BULLISH": "quant/ranking data is supportive",
        "BEARISH": "quant/ranking data is pressuring the setup",
        "NEUTRAL": "quant/ranking context changed",
    },
    "analyst_rating": {
        "BULLISH": "analyst or rating language is constructive",
        "BEARISH": "analyst or rating language is cautious",
        "NEUTRAL": "analyst/rating coverage is relevant",
    },
    "earnings": {
        "BULLISH": "earnings or guidance language supports the thesis",
        "BEARISH": "earnings or guidance language is a pressure point",
        "NEUTRAL": "earnings or guidance context is relevant",
    },
    "rank_change": {
        "BULLISH": "rank-change context is supportive",
        "BEARISH": "rank-change context is cautious",
        "NEUTRAL": "rank-change context is relevant",
    },
    "unusual_activity": {
        "BULLISH": "unusual-activity context may support demand",
        "BEARISH": "unusual-activity context may show distribution",
        "NEUTRAL": "unusual-activity context is present",
    },
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
RISK_READOUTS = {
    "negative_revision": "estimate or revision language needs monitoring",
    "valuation": "valuation sensitivity could limit upside",
    "macro": "macro exposure could change the setup",
    "legal_or_regulatory": "legal or regulatory risk is part of the context",
    "execution": "execution risk could weaken the thesis",
}


def analyze_article(page: FetchedArticle, *, config: SubscriptionEmailConfig) -> dict[str, object]:
    clipped = " ".join(page.text[: config.article_max_chars].split())
    article_text = f"{page.title or ''}\n{clipped}"
    tickers = _tickers(article_text, config.tickers)
    direction = _direction(article_text)
    catalysts = _catalysts(article_text)
    risk_flags = _risk_flags(article_text)
    key_points = _key_points(catalysts, risk_flags, direction=direction)
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
        "signal_strength": _signal_strength(direction, catalysts, risk_flags),
        "decision_use": _decision_use(direction, catalysts, risk_flags),
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
        direction=_string(analysis.get("direction")) or "NEUTRAL",
    )
    tickers = ",".join(_string_items(analysis.get("tickers"))) or "none"
    key_points = "; ".join(point_items) or "no specific catalyst bucket was detected"
    thesis = _string(analysis.get("thesis")) or _fallback_thesis(analysis)
    decision_use = _string(analysis.get("decision_use")) or _fallback_decision_use(analysis)
    risk_text = _risk_text(risk_items)
    context = _string(analysis.get("context_source")) or "cached_legacy_article_analysis"
    chars = _integer(analysis.get("context_chars"))
    chars_detail = f"; chars={chars}" if chars else ""
    direction = _string(analysis.get("direction")) or "NEUTRAL"
    return (
        f"Linked content thesis: {thesis}. "
        f"Why it matters: {key_points}. "
        f"Watch: {risk_text}. "
        f"Agency use: {decision_use}. "
        f"Context: {context}{chars_detail}; tickers={tickers}; "
        f"direction={direction}."
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
    positive = _term_count(lowered, POSITIVE_TERMS)
    negative = _term_count(lowered, NEGATIVE_TERMS)
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


def _key_points(catalysts: list[str], risks: list[str], *, direction: str) -> list[str]:
    points = [
        CATALYST_READOUTS.get(item, {}).get(direction, CATALYST_LABELS[item])
        for item in catalysts
        if item in CATALYST_LABELS
    ]
    points.extend(RISK_READOUTS[item] for item in risks if item in RISK_READOUTS)
    return points[:5]


def _term_count(text: str, terms: frozenset[str]) -> int:
    return sum(len(re.findall(_term_pattern(term), text)) for term in terms)


def _term_pattern(term: str) -> str:
    return rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"


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


def _fallback_decision_use(analysis: Mapping[str, object]) -> str:
    return _decision_use(
        _string(analysis.get("direction")) or "NEUTRAL",
        _string_items(analysis.get("catalysts")),
        _string_items(analysis.get("risk_flags")),
    )


def _decision_use(direction: str, catalysts: list[str], risks: list[str]) -> str:
    if direction == "BULLISH" and catalysts:
        return "Treat as context-only bullish thesis; require independent confirmation"
    if direction == "BEARISH":
        return "Treat as caution context and raise the review burden"
    if risks:
        return "Treat as risk context until corroborated by another source"
    return "Treat as informational context only"


def _signal_strength(direction: str, catalysts: list[str], risks: list[str]) -> str:
    if direction == "NEUTRAL":
        return "low"
    if catalysts and len(catalysts) >= len(risks):
        return "medium"
    if catalysts:
        return "low"
    return "low"


def _risk_text(risks: list[str]) -> str:
    labels = [RISK_LABELS.get(item, item) for item in risks]
    return _label_join(labels) if labels else "no explicit risk bucket detected"


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _sensitive_query_key(key)
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, query, ""))


def _sensitive_query_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {
        "token",
        "auth",
        "authorization",
        "signature",
        "sig",
        "key",
        "apikey",
        "api_key",
        "email",
        "user",
        "uid",
    } or normalized in TRACKING_QUERY_KEYS or normalized.startswith(("utm_", "mc_", "mkt_"))


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
