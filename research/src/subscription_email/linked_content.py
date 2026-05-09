from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx
from news.scrapling_adapter import fetch_page
from subscription_email.article_session import (
    BrowserSessionUnavailableError,
    fetch_with_browser_session,
)
from subscription_email.article_types import FetchedArticle, html_to_text
from subscription_email.config import SubscriptionEmailConfig
from subscription_email.types import EmailRecord

URL_RE = re.compile(r"https?://[^\s<>)\"]+")
TICKER_TEMPLATE = r"(?<![A-Z0-9])\$?{ticker}(?![A-Z0-9])"
MIN_USABLE_ARTICLE_CHARS = 200

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

ArticleFetcher = Callable[[str, int], "FetchedArticle"]


@dataclass(frozen=True)
class LinkedContentStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class LinkedContentResult:
    records: list[EmailRecord]
    stats: LinkedContentStats


def enrich_records_with_linked_content(
    records: list[EmailRecord],
    *,
    config: SubscriptionEmailConfig,
    fetcher: ArticleFetcher | None = None,
) -> LinkedContentResult:
    if not config.follow_article_links or config.article_max_links_per_email == 0:
        return LinkedContentResult(records=records, stats=LinkedContentStats(skipped=len(records)))
    fetch_article = fetcher or fetch_linked_article
    output: list[EmailRecord] = []
    attempted = succeeded = failed = skipped = 0
    for record in records:
        links = allowed_article_links(record, config)
        if not links:
            output.append(_with_status(record, "no_allowed_article_link"))
            skipped += 1
            continue
        enriched = record
        for url in links[: config.article_max_links_per_email]:
            attempted += 1
            try:
                page = fetch_article(url, config.article_fetch_timeout_seconds)
            except Exception:
                failed += 1
                enriched = _with_status(record, "article_fetch_failed", url=url)
                continue
            analysis = analyze_article(page, config=config)
            enriched = _with_analysis(record, analysis)
            succeeded += 1
            break
        output.append(enriched)
    return LinkedContentResult(
        records=output,
        stats=LinkedContentStats(
            attempted=attempted,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
        ),
    )


def allowed_article_links(record: EmailRecord, config: SubscriptionEmailConfig) -> list[str]:
    domains = config.article_link_domains or config.allowed_sender_domains
    candidates = [_clean_url(match) for match in URL_RE.findall(_record_text(record))]
    return [_normalize_url(url) for url in candidates if _allowed_url(url, domains)]


def fetch_linked_article(
    url: str,
    timeout_seconds: int,
    *,
    config: SubscriptionEmailConfig | None = None,
) -> FetchedArticle:
    errors: list[str] = []
    for fetch_name, fetcher in _fetchers(config):
        try:
            page = fetcher(url, timeout_seconds)
        except BrowserSessionUnavailableError as exc:
            errors.append(f"{fetch_name}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{fetch_name}: {exc}")
            continue
        if _usable_article(page):
            return page
        errors.append(f"{fetch_name}: fetched page did not look like article content")
    raise RuntimeError(f"linked article fetch failed ({'; '.join(errors)})")


def _fetchers(
    config: SubscriptionEmailConfig | None,
) -> list[tuple[str, ArticleFetcher]]:
    mode = "auto" if config is None else config.article_fetch_mode
    if mode == "http":
        return [("httpx", _fetch_with_httpx)]
    if mode == "browser":
        if config is None:
            return []
        return [
            (
                "browser_session",
                lambda url, timeout: fetch_with_browser_session(
                    url,
                    config=config,
                    timeout_seconds=timeout,
                ),
            )
        ]
    output: list[tuple[str, ArticleFetcher]] = [
        ("httpx", _fetch_with_httpx),
        ("scrapling", _fetch_with_scrapling),
    ]
    if config is not None:
        output.append(
            (
                "browser_session",
                lambda url, timeout: fetch_with_browser_session(
                    url,
                    config=config,
                    timeout_seconds=timeout,
                ),
            )
        )
    return output


def _fetch_with_httpx(url: str, timeout_seconds: int) -> FetchedArticle:
    headers = {"User-Agent": "TradingAgency/0.1 subscription-email-agent"}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    title, text = html_to_text(response.text)
    return FetchedArticle(
        url=str(response.url),
        status_code=response.status_code,
        title=title,
        text=text,
    )


def _fetch_with_scrapling(url: str, timeout_seconds: int) -> FetchedArticle:
    page = fetch_page(url, timeout=timeout_seconds)
    return FetchedArticle(
        url=page.url,
        status_code=page.status_code or 0,
        title=page.title,
        text=page.text,
    )


def _usable_article(page: FetchedArticle) -> bool:
    text = " ".join(page.text.split())
    if len(text) < MIN_USABLE_ARTICLE_CHARS:
        return False
    lowered = text.lower()
    login_markers = (
        "sign in to continue",
        "sign in",
        "log in",
        "subscribe to continue",
        "create an account",
    )
    return not any(marker in lowered for marker in login_markers)


def analyze_article(page: FetchedArticle, *, config: SubscriptionEmailConfig) -> dict[str, object]:
    clipped = page.text[: config.article_max_chars]
    tickers = _tickers(f"{page.title or ''}\n{clipped}", config.tickers)
    direction = _direction(clipped)
    catalysts = _catalysts(clipped)
    return {
        "status": "article_analyzed",
        "url": _normalize_url(page.url),
        "title_hash": _hash(page.title or ""),
        "tickers": tickers,
        "direction": direction,
        "catalysts": catalysts,
        "text_hash": _hash(clipped),
    }


def _with_analysis(record: EmailRecord, analysis: dict[str, object]) -> EmailRecord:
    tickers = ",".join(str(item) for item in _list(analysis.get("tickers")))
    catalysts = ",".join(str(item) for item in _list(analysis.get("catalysts")))
    summary = (
        "Linked content analysis: "
        f"tickers={tickers or 'none'}; "
        f"direction={analysis['direction']}; "
        f"catalysts={catalysts or 'none'}; "
        f"text_hash={analysis['text_hash']}."
    )
    return EmailRecord(
        **{
            **record.__dict__,
            "linked_content_summary": summary,
            "linked_content_status": str(analysis["status"]),
            "linked_content_url": str(analysis["url"]),
            "linked_content_title_hash": str(analysis["title_hash"]),
        }
    )


def _with_status(record: EmailRecord, status: str, *, url: str | None = None) -> EmailRecord:
    return EmailRecord(
        **{
            **record.__dict__,
            "linked_content_status": status,
            "linked_content_url": _normalize_url(url) if url is not None else None,
        }
    )


def _record_text(record: EmailRecord) -> str:
    return f"{record.subject}\n{record.body_text}"


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


def _allowed_url(url: str, domains: tuple[str, ...]) -> bool:
    domain = urlsplit(url).netloc.lower()
    return bool(domain) and any(domain == item or domain.endswith(f".{item}") for item in domains)


def _clean_url(value: str) -> str:
    return value.rstrip(".,;")


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
