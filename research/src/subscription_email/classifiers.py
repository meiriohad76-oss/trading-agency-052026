from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from subscription_email.config import SubscriptionEmailConfig
from subscription_email.types import ClassifiedEmailRows, EmailRecord

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, compute_freshness

URL_RE = re.compile(r"https?://[^\s<>)\"]+")
MONEY_RE = re.compile(r"\$?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[KMB])?", re.IGNORECASE)
TICKER_TEMPLATE = r"(?<![A-Z0-9])\$?{ticker}(?![A-Z0-9])"

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
    news_rows = [
        _news_row(record, service, ticker, event_type=kind, fetched_at=fetched_at)
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
                direction=_direction(_text(record)),
                source_url=str(row["source_url"]),
                source_id=str(row["source_id"]),
                confidence=_float(row["confidence"]),
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
        direction = _direction(text)
        news_rows = [
            _news_row(
                record,
                "tradevision",
                ticker,
                event_type=f"tradevision_{direction.lower()}_news",
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
    fetched_at: datetime,
) -> dict[str, object]:
    url = _first_url(record)
    source_url = url or f"email://{_hash(record.message_id)}"
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
        "summary": _summary(service, event_type, _direction(_text(record))),
        "published_at": record.received_at,
        "source": f"{service}-email",
        "source_tier": SourceTier.PAID_SUB_EMAIL.value,
        "source_id": _source_id(service, record, ticker, event_type, url),
        "source_url": source_url,
        "timestamp_observed": record.received_at,
        "timestamp_as_of": record.received_at,
        "freshness": freshness,
        "confidence": _confidence(service, event_type),
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
    source_url = url or f"email://{_hash(record.message_id)}"
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
        "summary": _summary("tradevision", alert_type, direction),
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
) -> dict[str, object]:
    message_id_hash = _hash(record.message_id)
    return {
        "ticker": ticker,
        "service": service,
        "services": [service],
        "event_type": event_type,
        "event_types": [event_type],
        "direction": direction,
        "title": _title(record, service, event_type),
        "source_refs": [
            {
                "service": service,
                "source_id": source_id,
                "source_url": source_url,
                "message_id_hash": message_id_hash,
            }
        ],
        "source_id": f"subscription_email:{service}:{ticker}:{event_type}:{message_id_hash}",
        "source_url": source_url,
        "message_id_hash": message_id_hash,
        "sender_domain": record.sender_domain,
        "received_at": record.received_at.isoformat(),
        "timestamp_observed": record.received_at.isoformat(),
        "timestamp_as_of": record.received_at.isoformat(),
        "confidence": confidence,
        "verification_level": VerificationLevel.CONFIRMED.value,
    }


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
    if "block trade" in lowered or "block" in lowered:
        return "block_trade"
    if "sweep" in lowered:
        return "options_sweep"
    if "option" in lowered and ("flow" in lowered or "unusual" in lowered):
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


def _title(record: EmailRecord, service: str, event_type: str) -> str:
    subject = " ".join(record.subject.split())
    prefix = SERVICE_LABELS[service]
    return f"{prefix}: {event_type.replace('_', ' ')} - {subject}"


def _summary(service: str, event_type: str, direction: str) -> str:
    return (
        f"Email-derived {SERVICE_LABELS[service]} evidence classified as "
        f"{event_type} with {direction.lower()} direction."
    )


def _first_url(record: EmailRecord) -> str | None:
    for match in URL_RE.findall(_text(record)):
        return _normalize_url(match.rstrip(".,;"))
    return None


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


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


def _confidence(service: str, event_type: str) -> float:
    if service == "tradevision":
        return 0.85
    if "rating" in event_type or "rank" in event_type:
        return 0.8
    return 0.7


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
    seen: set[tuple[str, str, str, str]] = set()
    output: list[dict[str, object]] = []
    for row in rows:
        key = (
            str(row["ticker"]),
            str(row["alert_type"]),
            str(row["event_time"]),
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
        }
    )


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
    return f"{record.subject}\n{record.body_text}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
