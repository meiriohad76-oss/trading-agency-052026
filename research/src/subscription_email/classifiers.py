from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from subscription_email.config import SubscriptionEmailConfig
from subscription_email.types import ClassifiedEmailRows, EmailRecord

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, compute_freshness

URL_RE = re.compile(r"https?://[^\s<>)\"]+")
MONEY_RE = re.compile(r"\$?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[KMB])?", re.IGNORECASE)
TICKER_TEMPLATE = r"(?<![A-Z0-9])\$?{ticker}(?![A-Z0-9])"
HEADLINE_FOCUS_RE = re.compile(r"(?: - |Email:\s+)\$?([A-Z]{1,5})(?=\s*:|\s+)")
BLOCK_TRADE_RE = re.compile(
    r"\bblock(?:s|\s+(?:trade|trades|print|prints|order|orders|activity))?\b"
)
OPTION_RE = re.compile(r"\boptions?\b")

SERVICE_DOMAINS = {
    "seeking_alpha": ("seekingalpha.com", "email.seekingalpha.com"),
    "tradevision": ("tradevision.io", "tradevision.com"),
    "zacks": ("zacks.com", "zacksalerts.com"),
}
SERVICE_LABELS = {
    "seeking_alpha": "Seeking Alpha Email",
    "tradevision": "TradeVision Email",
    "zacks": "Zacks Email",
}
TAXONOMY_PAIR_COUNT = 2
TERMINAL_NON_EVIDENCE_LINK_STATUSES = {
    "article_login_preflight_required",
    "article_login_required",
    "article_unavailable",
    "login_or_security_email",
    "no_configured_ticker_in_email",
    "non_universe_ticker_email",
}
VISIBLE_LOGIN_REQUIRED_LINK_STATUSES = {
    "article_login_preflight_required",
    "article_login_required",
}
ANALYZED_LINK_STATUSES = {
    "article_analyzed",
    "article_analyzed_deterministic_fallback",
}
NO_TICKER_MATCH_STATUS = "article_analyzed_no_ticker_match"
PORTFOLIO_CONTEXT_LINK_STATUS = "article_analyzed_portfolio_context_only"
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


def classify_subscription_emails(
    records: list[EmailRecord],
    *,
    config: SubscriptionEmailConfig,
    fetched_at: datetime,
) -> ClassifiedEmailRows:
    news_rows: list[dict[str, object]] = []
    activity_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    manual_review: list[dict[str, object]] = []
    ignored: list[dict[str, object]] = []
    for record in records:
        service = _service_for(record)
        if not _allowed(record, config):
            ignored.append(_audit_stub(record, service, "sender_not_allowlisted"))
            continue
        if service is None or service not in config.enabled_services:
            ignored.append(_audit_stub(record, service, "service_disabled_or_unknown"))
            continue
        if record.linked_content_status in TERMINAL_NON_EVIDENCE_LINK_STATUSES:
            tickers = _tickers(record, config.tickers)
            if record.linked_content_status in VISIBLE_LOGIN_REQUIRED_LINK_STATUSES and tickers:
                event_rows.extend(
                    _login_required_event_rows(record, service, tickers, fetched_at=fetched_at)
                )
                continue
            ignored.append(_audit_stub(record, service, record.linked_content_status))
            continue
        tickers = _tickers(record, config.tickers)
        if not tickers:
            target = manual_review if config.unmatched_ticker_policy == "manual_review" else ignored
            target.append(_audit_stub(record, service, "no_ticker_match"))
            continue
        classified = _classify_service(record, service, tickers, fetched_at=fetched_at)
        news_rows.extend(classified.news_rows)
        activity_rows.extend(classified.activity_rows)
        event_rows.extend(classified.event_rows)
    return ClassifiedEmailRows(
        news_rows=_dedupe_news(news_rows),
        activity_rows=_dedupe_activity(activity_rows),
        event_rows=_dedupe_events(event_rows),
        manual_review=manual_review,
        ignored=ignored,
    )


def _classify_service(
    record: EmailRecord,
    service: str,
    tickers: list[str],
    *,
    fetched_at: datetime,
) -> ClassifiedEmailRows:
    if service == "tradevision":
        return _tradevision_rows(record, tickers, fetched_at=fetched_at)
    kind = _seeking_alpha_kind(record) if service == "seeking_alpha" else _zacks_kind(record)
    direction = _record_direction(record)
    news_rows = [
        _news_row(
            record,
            service,
            ticker,
            event_type=kind,
            direction=direction,
            fetched_at=fetched_at,
        )
        for ticker in tickers
    ]
    return ClassifiedEmailRows(
        news_rows=news_rows,
        activity_rows=[],
        event_rows=[
            _event_row(
                record,
                service,
                ticker,
                event_type=kind,
                direction=direction,
                source_url=str(row["source_url"]),
                source_id=str(row["source_id"]),
                confidence=_float(row["confidence"]),
                fetched_at=fetched_at,
            )
            for ticker, row in zip(tickers, news_rows, strict=True)
        ],
        manual_review=[],
        ignored=[],
    )


def _tradevision_rows(
    record: EmailRecord,
    tickers: list[str],
    *,
    fetched_at: datetime,
) -> ClassifiedEmailRows:
    text = _text(record)
    alert_type = _tradevision_alert_type(text)
    if alert_type is None:
        direction = _record_direction(record)
        news_rows = [
            _news_row(
                record,
                "tradevision",
                ticker,
                event_type=f"tradevision_{direction.lower()}_news",
                direction=direction,
                fetched_at=fetched_at,
            )
            for ticker in tickers
        ]
        return ClassifiedEmailRows(
            news_rows=news_rows,
            activity_rows=[],
            event_rows=[
                _event_row(
                    record,
                    "tradevision",
                    ticker,
                    event_type=f"tradevision_{direction.lower()}_news",
                    direction=direction,
                    source_url=str(row["source_url"]),
                    source_id=str(row["source_id"]),
                    confidence=_float(row["confidence"]),
                    fetched_at=fetched_at,
                )
                for ticker, row in zip(tickers, news_rows, strict=True)
            ],
            manual_review=[],
            ignored=[],
        )
    activity_rows = [
        _activity_row(record, ticker, alert_type=alert_type, fetched_at=fetched_at)
        for ticker in tickers
    ]
    return ClassifiedEmailRows(
        news_rows=[],
        activity_rows=activity_rows,
        event_rows=[
            _event_row(
                record,
                "tradevision",
                ticker,
                event_type=alert_type,
                direction=str(row["direction"]),
                source_url=str(row["source_url"]),
                source_id=str(row["source_id"]),
                confidence=_float(row["confidence"]),
                fetched_at=fetched_at,
            )
            for ticker, row in zip(tickers, activity_rows, strict=True)
        ],
        manual_review=[],
        ignored=[],
    )


def _news_row(
    record: EmailRecord,
    service: str,
    ticker: str,
    *,
    event_type: str,
    direction: str,
    fetched_at: datetime,
) -> dict[str, object]:
    url = _first_url(record)
    source_url = _source_url(record)
    freshness = compute_freshness(
        record.received_at,
        FreshnessDomain.NEWS,
        now=fetched_at,
    ).value
    return {
        "ticker": ticker,
        "feed_url": f"email://{service}",
        "feed_name": SERVICE_LABELS[service],
        "title": _title(record, service, event_type),
        "url": source_url,
        "summary": _summary(service, event_type, direction, record, ticker=ticker),
        "published_at": record.received_at,
        "source": f"{service}-email",
        "source_tier": SourceTier.PAID_SUB_EMAIL.value,
        "source_id": _source_id(service, record, ticker, event_type, url),
        "source_url": source_url,
        "timestamp_observed": record.received_at,
        "timestamp_as_of": record.received_at,
        "freshness": freshness,
        "confidence": _confidence(service, event_type, record),
        "verification_level": VerificationLevel.CONFIRMED.value,
    }


def _activity_row(
    record: EmailRecord,
    ticker: str,
    *,
    alert_type: str,
    fetched_at: datetime,
) -> dict[str, object]:
    text = _text(record)
    direction = _direction(text)
    notional = _amount_after(text, "notional")
    premium = _amount_after(text, "premium")
    url = _first_url(record)
    source_url = _source_url(record)
    freshness = compute_freshness(
        record.received_at,
        FreshnessDomain.NEWS,
        now=fetched_at,
    ).value
    return {
        "ticker": ticker,
        "alert_type": alert_type,
        "direction": direction,
        "event_time": record.received_at.isoformat(),
        "summary": _summary("tradevision", alert_type, direction, record, ticker=ticker),
        "price": None,
        "volume": None,
        "notional": notional,
        "premium": premium,
        "source": "tradevision-email",
        "source_tier": SourceTier.PAID_SUB_EMAIL.value,
        "source_id": _source_id("tradevision", record, ticker, alert_type, url),
        "source_url": source_url,
        "timestamp_observed": record.received_at.isoformat(),
        "timestamp_as_of": record.received_at.isoformat(),
        "freshness": freshness,
        "confidence": 0.85,
        "verification_level": VerificationLevel.CONFIRMED.value,
    }


def _event_row(
    record: EmailRecord,
    service: str,
    ticker: str,
    *,
    event_type: str,
    direction: str,
    source_url: str,
    source_id: str,
    confidence: float,
    fetched_at: datetime,
) -> dict[str, object]:
    message_id_hash = _hash(record.message_id)
    event_title = _title(record, service, event_type)
    linked_status = _linked_content_status_for_ticker(record, ticker)
    linked = _ticker_linked_content(
        record,
        ticker=ticker,
        title=event_title,
        event_type=event_type,
        direction=direction,
        linked_status=linked_status,
    )
    freshness = compute_freshness(
        record.received_at,
        FreshnessDomain.NEWS,
        now=fetched_at,
    ).value
    return {
        "ticker": ticker,
        "service": service,
        "services": [service],
        "event_type": event_type,
        "event_types": [event_type],
        "direction": direction,
        "title": event_title,
        "source_refs": [
            {
                "service": service,
                "source_id": source_id,
                "source_url": source_url,
                "message_id_hash": message_id_hash,
            }
        ],
        "source": f"{service}-email",
        "source_tier": SourceTier.PAID_SUB_EMAIL.value,
        "source_id": f"subscription_email:{service}:{ticker}:{event_type}:{message_id_hash}",
        "source_url": source_url,
        "message_id_hash": message_id_hash,
        "sender_domain": record.sender_domain,
        "received_at": record.received_at.isoformat(),
        "linked_content_status": linked_status,
        "linked_content_url": record.linked_content_url,
        "linked_content_title_hash": record.linked_content_title_hash,
        "linked_content_summary": linked["summary"],
        "linked_content_direction": record.linked_content_direction,
        "linked_content_thesis": linked["thesis"],
        "linked_content_catalysts": list(record.linked_content_catalysts),
        "linked_content_risk_flags": list(record.linked_content_risk_flags),
        "linked_content_key_points": linked["key_points"],
        "linked_content_tickers": list(record.linked_content_tickers),
        "linked_content_decision_use": linked["decision_use"],
        "linked_content_signal_strength": record.linked_content_signal_strength,
        "linked_content_context_chars": record.linked_content_context_chars,
        "linked_content_confidence": record.linked_content_confidence,
        "timestamp_observed": record.received_at.isoformat(),
        "timestamp_as_of": record.received_at.isoformat(),
        "freshness": freshness,
        "confidence": confidence,
        "verification_level": VerificationLevel.CONFIRMED.value,
    }


def _login_required_event_rows(
    record: EmailRecord,
    service: str,
    tickers: list[str],
    *,
    fetched_at: datetime,
) -> list[dict[str, object]]:
    source_url = _source_url(record)
    return [
        _event_row(
            record,
            service,
            ticker,
            event_type=record.linked_content_status or "article_login_required",
            direction="NEUTRAL",
            source_url=source_url,
            source_id=_source_id(
                service,
                record,
                ticker,
                record.linked_content_status or "article_login_required",
                source_url,
            ),
            confidence=0.0,
            fetched_at=fetched_at,
        )
        for ticker in tickers
    ]


def _ticker_linked_content(
    record: EmailRecord,
    *,
    ticker: str,
    title: str,
    event_type: str,
    direction: str,
    linked_status: str,
) -> dict[str, object]:
    if linked_status in VISIBLE_LOGIN_REQUIRED_LINK_STATUSES:
        return {
            "summary": (
                "Linked article was not analyzed because provider login or human "
                "verification is required. Log in to the provider, acknowledge the "
                "login prompt, then rerun the email/article agent."
            ),
            "thesis": None,
            "key_points": [],
            "decision_use": (
                "Do not count this as bullish or bearish evidence until the article "
                "is opened and analyzed after login."
            ),
        }
    if linked_status == NO_TICKER_MATCH_STATUS:
        return {
            "summary": (
                f"Linked article was analyzed, but it did not materially mention {ticker}; "
                "use only the mailbox headline as context."
            ),
            "thesis": None,
            "key_points": [],
            "decision_use": "Do not use this linked article as ticker-specific evidence.",
        }
    if linked_status == PORTFOLIO_CONTEXT_LINK_STATUS:
        return {
            "summary": (
                f"Linked article was analyzed, but its thesis is not specific to {ticker}; "
                "keep it as portfolio/theme context only."
            ),
            "thesis": None,
            "key_points": [],
            "decision_use": (
                "Do not use this linked article as ticker-specific evidence unless a "
                "direct causal link is confirmed."
            ),
        }
    if not _is_analyzed_link_status(linked_status):
        return {
            "summary": record.linked_content_summary,
            "thesis": record.linked_content_thesis,
            "key_points": list(record.linked_content_key_points),
            "decision_use": record.linked_content_decision_use,
        }
    catalysts = list(record.linked_content_catalysts)
    risks = list(record.linked_content_risk_flags)
    relevance = _ticker_relevance(
        ticker=ticker,
        title=title,
        event_type=event_type,
        direction=direction,
        catalysts=catalysts,
        risks=risks,
    )
    raw_thesis = _clean_sentence(record.linked_content_thesis)
    signal = f"{direction.lower()} article signal"
    catalyst_text = _taxonomy_list(catalysts)
    risk_text = _taxonomy_list(risks)
    if catalyst_text:
        signal += f" from {catalyst_text}"
    thesis = _ticker_specific_thesis(
        relevance=relevance,
        raw_thesis=raw_thesis,
        signal=signal,
    )
    if risk_text:
        thesis += f" Watch: {risk_text}."
    decision_use = _ticker_decision_use(
        ticker=ticker,
        title=title,
        direction=direction,
        default=record.linked_content_decision_use,
    )
    key_points = [
        relevance,
        *([raw_thesis] if raw_thesis else []),
        *list(record.linked_content_key_points),
    ][:5]
    context_detail = _summary_context_detail(record.linked_content_summary)
    context_suffix = f" {context_detail}" if context_detail else ""
    return {
        "summary": (
            f"Linked content thesis for {ticker}: {thesis} "
            f"Agency use: {decision_use}{context_suffix}"
        ),
        "thesis": thesis,
        "key_points": key_points,
        "decision_use": decision_use,
    }


def _ticker_specific_thesis(
    *,
    relevance: str,
    raw_thesis: str | None,
    signal: str,
) -> str:
    if raw_thesis:
        if relevance.lower() in raw_thesis.lower():
            return raw_thesis.rstrip(".") + "."
        return f"{relevance} Article thesis: {raw_thesis.rstrip('.')}."
    return f"{relevance} Detected {signal}."


def _clean_sentence(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _linked_content_status_for_ticker(record: EmailRecord, ticker: str) -> str:
    status = record.linked_content_status
    if not _is_analyzed_link_status(status):
        return status
    article_tickers = {item.upper() for item in record.linked_content_tickers}
    if not article_tickers or ticker.upper() not in article_tickers:
        return NO_TICKER_MATCH_STATUS
    if not _article_has_ticker_specific_claim(record, ticker):
        return PORTFOLIO_CONTEXT_LINK_STATUS
    return status


def _is_analyzed_link_status(status: str) -> bool:
    return status in ANALYZED_LINK_STATUSES


def _ticker_relevance(
    *,
    ticker: str,
    title: str,
    event_type: str,
    direction: str,
    catalysts: list[str],
    risks: list[str],
) -> str:
    focus = _headline_focus_ticker(title)
    topic = _topic_from_title(title, event_type)
    if focus == ticker.upper():
        opener = f"Direct relevance: headline focus is {ticker} and the article discusses {topic}."
    elif focus is not None:
        opener = (
            f"Secondary relevance: headline focus is {focus}; {ticker} was detected in "
            "the article/email context, so this is basket or theme evidence."
        )
    else:
        opener = f"Ticker relevance: {ticker} was detected in analyzed article/email context."
    details = [opener, f"Direction is {direction.lower()}."]
    catalyst_text = _taxonomy_list(catalysts)
    risk_text = _taxonomy_list(risks)
    if catalyst_text:
        details.append(f"Detected drivers: {catalyst_text}.")
    if risk_text:
        details.append(f"Watch items: {risk_text}.")
    return " ".join(details)


def _summary_context_detail(summary: str | None) -> str:
    if not summary or "Context:" not in summary:
        return ""
    context = summary.split("Context:", 1)[1].strip()
    if not context:
        return ""
    return f"Context: {context}"


def _ticker_decision_use(
    *,
    ticker: str,
    title: str,
    direction: str,
    default: str | None,
) -> str:
    focus = _headline_focus_ticker(title)
    if focus is not None and focus != ticker.upper():
        return (
            "Use as secondary basket/theme context only; require direct ticker "
            "confirmation before it can support a decision."
        )
    if default:
        return default
    if direction == "BULLISH":
        return "Treat as context-only bullish thesis; require independent confirmation."
    if direction == "BEARISH":
        return "Treat as caution context and raise the review burden."
    return "Treat as informational context only."


def _article_has_ticker_specific_claim(record: EmailRecord, ticker: str) -> bool:
    return any(
        _specific_ticker_mention(ticker, value)
        for value in (
            record.linked_content_thesis,
            record.linked_content_decision_use,
            *record.linked_content_key_points,
        )
    )


def _specific_ticker_mention(ticker: str, value: object) -> bool:
    if not _mentions_ticker(ticker, value):
        return False
    return any(
        _mentions_ticker(ticker, sentence)
        and not _boilerplate_detection_sentence(ticker, sentence)
        for sentence in _sentences(str(value))
    )


def _boilerplate_detection_sentence(ticker: str, sentence: str) -> bool:
    if not _mentions_ticker(ticker, sentence):
        return False
    lowered = sentence.lower()
    return (
        (
            "detected" in lowered
            and (
                "ticker relevance" in lowered
                or "article/email context" in lowered
                or "article context" in lowered
                or "email context" in lowered
            )
        )
        or _peer_comparison_sentence(ticker, sentence)
    )


def _peer_comparison_sentence(ticker: str, sentence: str) -> bool:
    lowered = sentence.lower()
    normalized = re.escape(ticker.lower())
    patterns = (
        rf"\b(?:peers?|rivals?|competitors?|companies)\s+"
        rf"(?:like|including|such as)\b[^.!?;:]*\b{normalized}\b",
        rf"\b(?:compared|relative)\s+(?:with|to)\b[^.!?;:]*\b{normalized}\b",
        rf"\b(?:versus|vs\.?)\b[^.!?;:]*\b{normalized}\b",
    )
    return any(re.search(pattern, lowered) is not None for pattern in patterns)


def _sentences(value: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", value) if sentence.strip()]


def _mentions_ticker(ticker: str, value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = re.escape(ticker.upper())
    return (
        re.search(
            rf"(?<![A-Za-z0-9])(?:\${normalized}|{normalized})(?![A-Za-z0-9])",
            value,
        )
        is not None
    )


def _headline_focus_ticker(title: str) -> str | None:
    match = HEADLINE_FOCUS_RE.search(title)
    return match.group(1).upper() if match is not None else None


def _topic_from_title(title: str, event_type: str) -> str:
    lowered = title.lower()
    if "quantum" in lowered:
        return "the quantum-computing theme"
    if "insider" in lowered:
        return "insider-trading activity"
    if "adds" in lowered or "exits" in lowered or "q1 moves" in lowered:
        return "fund holdings changes"
    if "dark pool" in lowered or "block trade" in lowered:
        return "unusual trading activity"
    if "earnings" in lowered or "transcript" in lowered:
        return "earnings or transcript context"
    return event_type.replace("_", " ")


def _taxonomy_list(values: list[str]) -> str:
    labels = [_taxonomy_label(value) for value in values if value]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == TAXONOMY_PAIR_COUNT:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _taxonomy_label(value: str) -> str:
    labels = {
        "analyst_rating": "analyst/rating",
        "earnings": "earnings/guidance",
        "execution": "execution risk",
        "legal_or_regulatory": "legal/regulatory risk",
        "macro": "macro",
        "negative_revision": "negative revisions",
        "quant_rating": "quant rating",
        "rank_change": "rank change",
        "unusual_activity": "unusual activity",
        "valuation": "valuation",
    }
    return labels.get(value, value.replace("_", " "))


def _service_for(record: EmailRecord) -> str | None:
    domain = record.sender_domain.lower()
    subject = record.subject.lower()
    for service, domains in SERVICE_DOMAINS.items():
        if any(domain == item or domain.endswith(f".{item}") for item in domains):
            return service
    if "seeking alpha" in subject:
        return "seeking_alpha"
    if "tradevision" in subject:
        return "tradevision"
    if "zacks" in subject:
        return "zacks"
    return None


def _allowed(record: EmailRecord, config: SubscriptionEmailConfig) -> bool:
    if not config.allowed_sender_domains:
        return True
    domain = record.sender_domain.lower()
    return any(
        domain == item or domain.endswith(f".{item}")
        for item in config.allowed_sender_domains
    )


def _tickers(record: EmailRecord, configured: tuple[str, ...]) -> list[str]:
    text = _text(record).upper()
    matches = [
        ticker
        for ticker in configured
        if re.search(TICKER_TEMPLATE.format(ticker=re.escape(ticker.upper())), text)
    ]
    return sorted(set(matches))


def _seeking_alpha_kind(record: EmailRecord) -> str:
    text = _text(record).lower()
    if "quant" in text and ("rating" in text or "rank" in text):
        return "sa_quant_rating_change"
    if "earnings" in text or "transcript" in text:
        return "sa_earnings_or_transcript"
    if "article" in text or "author" in text or "analyst" in text:
        return "sa_analyst_article"
    return "sa_news"


def _zacks_kind(record: EmailRecord) -> str:
    text = _text(record).lower()
    if "zacks rank" in text or "rank #" in text:
        return "zacks_rank_change"
    if "upgrade" in text or "downgrade" in text or "rating" in text:
        return "zacks_rating_change"
    if "recommend" in text:
        return "zacks_analyst_recommendation"
    return "zacks_news"


def _tradevision_alert_type(text: str) -> str | None:
    lowered = text.lower()
    if "dark pool" in lowered or "darkpool" in lowered:
        return "dark_pool"
    if BLOCK_TRADE_RE.search(lowered):
        return "block_trade"
    if "sweep" in lowered:
        return "options_sweep"
    if OPTION_RE.search(lowered) and ("flow" in lowered or "unusual" in lowered):
        return "unusual_options_activity"
    if "unusual stock" in lowered:
        return "unusual_stock_activity"
    return None


def _direction(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("bearish", "downgrade", "sell", "put", "negative")):
        return "BEARISH"
    if any(term in lowered for term in ("bullish", "upgrade", "buy", "call", "positive")):
        return "BULLISH"
    return "NEUTRAL"


def _record_direction(record: EmailRecord) -> str:
    if record.linked_content_direction in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return record.linked_content_direction
    return _direction(_text(record))


def _title(record: EmailRecord, service: str, event_type: str) -> str:
    subject = " ".join(record.subject.split())
    prefix = SERVICE_LABELS[service]
    return f"{prefix}: {event_type.replace('_', ' ')} - {subject}"


def _summary(
    service: str,
    event_type: str,
    direction: str,
    record: EmailRecord,
    *,
    ticker: str | None = None,
) -> str:
    summary = (
        f"Email-derived {SERVICE_LABELS[service]} evidence classified as "
        f"{event_type} with {direction.lower()} direction."
    )
    linked_summary = (
        _linked_summary_for_news(record, ticker) if ticker is not None else record.linked_content_summary
    )
    if linked_summary is None:
        return summary
    return f"{summary} {linked_summary}"


def _linked_summary_for_news(record: EmailRecord, ticker: str) -> str | None:
    status = _linked_content_status_for_ticker(record, ticker)
    if status == NO_TICKER_MATCH_STATUS:
        return (
            f"Linked article was analyzed, but it did not materially mention {ticker}; "
            "do not use the article as ticker-specific news evidence."
        )
    if status == PORTFOLIO_CONTEXT_LINK_STATUS:
        return (
            f"Linked article was analyzed, but its thesis is not specific to {ticker}; "
            "treat it as portfolio/theme context only."
        )
    return record.linked_content_summary


def _first_url(record: EmailRecord) -> str | None:
    if record.linked_content_url:
        return _normalize_url(record.linked_content_url)
    for match in URL_RE.findall(_text(record)):
        candidate = _normalize_url(match.rstrip(".,;"))
        if not _sensitive_or_tracking_url(candidate):
            return candidate
    return None


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


def _source_url(record: EmailRecord) -> str:
    url = _first_url(record)
    if url is None:
        return f"email://{_hash(record.message_id)}"
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


def _sensitive_or_tracking_url(value: str) -> bool:
    parsed = urlsplit(value)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(domain.startswith(prefix) for prefix in ("click.", "links.", "link.", "email.")):
        return True
    return any(
        token in path
        for token in (
            "unsubscribe",
            "login",
            "signin",
            "sign-in",
            "account",
            "auth",
            "preferences",
            "manage-email",
        )
    )


def _sensitive_query_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {
        "token",
        "auth",
        "signature",
        "sig",
        "key",
        "apikey",
        "api_key",
        "email",
        "user",
        "uid",
    } or normalized in TRACKING_QUERY_KEYS or normalized.startswith(("utm_", "mc_", "mkt_"))


def _amount_after(text: str, label: str) -> float | None:
    lowered = text.lower()
    index = lowered.find(label)
    if index < 0:
        return None
    match = MONEY_RE.search(text[index : index + 80])
    if match is None:
        return None
    value = float(match.group("value"))
    unit = (match.group("unit") or "").upper()
    multiplier = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}.get(unit, 1.0)
    return value * multiplier


def _confidence(service: str, event_type: str, record: EmailRecord) -> float:
    if service == "tradevision":
        base = 0.85
    elif "rating" in event_type or "rank" in event_type:
        base = 0.8
    else:
        base = 0.7
    if record.linked_content_status == "article_analyzed":
        if record.linked_content_confidence is not None:
            return min(0.95, max(base, record.linked_content_confidence))
        return min(0.95, base + 0.1)
    return base


def _source_id(
    service: str,
    record: EmailRecord,
    ticker: str,
    event_type: str,
    url: str | None,
) -> str:
    return f"{service}:{ticker}:{event_type}:{_hash(record.message_id)}:{_hash(url or '')}"


def _audit_stub(record: EmailRecord, service: str | None, reason: str) -> dict[str, object]:
    return {
        "service": service,
        "reason": reason,
        "message_id_hash": _hash(record.message_id),
        "sender_domain": record.sender_domain,
        "received_at": record.received_at.isoformat(),
        "linked_content_status": record.linked_content_status,
    }


def _dedupe_news(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str, str]] = set()
    output: list[dict[str, object]] = []
    for row in rows:
        key = (str(row["ticker"]), str(row["url"]), str(row["title"]).lower())
        if key not in seen:
            seen.add(key)
            output.append(row)
    return output


def _dedupe_activity(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str, str]] = set()
    output: list[dict[str, object]] = []
    for row in rows:
        # Do not include event_time: the same alert re-processed near midnight UTC
        # would otherwise produce a duplicate with a shifted timestamp.
        key = (
            str(row["ticker"]),
            str(row["alert_type"]),
            str(row["source_id"]),
        )
        if key not in seen:
            seen.add(key)
            output.append(row)
    return output


def _dedupe_events(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = _event_key(row)
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(row)
            continue
        _merge_event(existing, row, key)
    return sorted(
        merged.values(),
        key=lambda row: (str(row["timestamp_as_of"]), str(row["ticker"]), str(row["source_id"])),
    )


def _event_key(row: dict[str, object]) -> tuple[str, str]:
    ticker = str(row["ticker"])
    url = str(row.get("source_url") or "")
    if url.startswith("http"):
        return ticker, _normalize_url(url)
    return ticker, str(row.get("title") or "").lower()


def _merge_event(
    existing: dict[str, object],
    row: dict[str, object],
    key: tuple[str, str],
) -> None:
    services = sorted(
        {*_string_items(existing.get("services")), *_string_items(row.get("services"))}
    )
    event_types = sorted(
        {*_string_items(existing.get("event_types")), *_string_items(row.get("event_types"))}
    )
    refs = _unique_refs(
        [*_ref_items(existing.get("source_refs")), *_ref_items(row.get("source_refs"))]
    )
    as_of = max(str(existing["timestamp_as_of"]), str(row["timestamp_as_of"]))
    existing.update(
        {
            "service": ",".join(services),
            "services": services,
            "event_type": ",".join(event_types),
            "event_types": event_types,
            "source_refs": refs,
            "timestamp_observed": as_of,
            "timestamp_as_of": as_of,
            "received_at": as_of,
            "confidence": max(_float(existing["confidence"]), _float(row["confidence"])),
            "source_id": f"subscription_email_event:{_hash('|'.join(key))}:{_hash(str(refs))}",
            "linked_content_summary": _merge_summary(existing, row),
        }
    )
    if _linked_content_rank(row) > _linked_content_rank(existing) or (
        _linked_content_rank(row) == _linked_content_rank(existing)
        and _linked_content_quality(row) >= _linked_content_quality(existing)
    ):
        for field in (
            "linked_content_status",
            "linked_content_url",
            "linked_content_title_hash",
            "linked_content_direction",
            "linked_content_thesis",
            "linked_content_catalysts",
            "linked_content_risk_flags",
            "linked_content_key_points",
            "linked_content_decision_use",
            "linked_content_signal_strength",
            "linked_content_context_chars",
            "linked_content_summary",
        ):
            if field in row:
                existing[field] = row[field]


def _linked_content_rank(row: dict[str, object]) -> int:
    status = str(row.get("linked_content_status", ""))
    if status == "article_analyzed":
        return 3
    if status and status not in {"None", "no_allowed_article_link"}:
        return 2
    return 1


def _linked_content_quality(row: dict[str, object]) -> int:
    summary = str(row.get("linked_content_summary") or "")
    score = len(summary)
    for field in (
        "linked_content_thesis",
        "linked_content_decision_use",
        "linked_content_key_points",
        "linked_content_catalysts",
        "linked_content_risk_flags",
    ):
        if row.get(field):
            score += 100
    if "openai_llm_article_analysis" in summary:
        score += 500
    return score


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _ref_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _unique_refs(refs: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    output: list[dict[str, object]] = []
    for ref in refs:
        key = str(ref.get("source_id", ""))
        if key not in seen:
            seen.add(key)
            output.append(ref)
    return output


def _merge_summary(existing: dict[str, object], row: dict[str, object]) -> str | None:
    summaries = [
        str(value)
        for value in (existing.get("linked_content_summary"), row.get("linked_content_summary"))
        if isinstance(value, str) and value
    ]
    if not summaries:
        return None
    return max(summaries, key=len)


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def _text(record: EmailRecord) -> str:
    linked = f"\n{record.linked_content_summary}" if record.linked_content_summary else ""
    return f"{record.subject}\n{record.body_text}{linked}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
