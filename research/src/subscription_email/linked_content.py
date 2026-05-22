from __future__ import annotations

import math
import os
import re
from base64 import urlsafe_b64decode
from binascii import Error as BinasciiError
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import httpx
from news.scrapling_adapter import fetch_page
from subscription_email.article_analysis import summary_from_analysis
from subscription_email.article_cache import (
    cacheable_analysis,
    load_article_analysis_cache,
    write_article_analysis_cache,
)
from subscription_email.article_llm_analysis import analyze_article_with_optional_llm
from subscription_email.article_session import (
    BrowserArticleSession,
    BrowserSessionUnavailableError,
    article_login_preflight_providers,
    fetch_with_browser_session,
    provider_for_url,
)
from subscription_email.article_types import FetchedArticle, html_to_text
from subscription_email.config import SubscriptionEmailConfig
from subscription_email.types import EmailRecord

URL_RE = re.compile(r"https?://[^\s<>)\"]+")
SUBJECT_FOCUS_RE = re.compile(r"^\s*\$?([A-Z]{1,5})(?:\s*:|\s+-)")
LOGIN_EMAIL_RE = re.compile(r"(security code|verification code|sign.?in|log.?in)", re.I)
TICKER_TEMPLATE = r"(?<![A-Z0-9])\$?{ticker}(?![A-Z0-9])"
MIN_USABLE_ARTICLE_CHARS = 200
MIN_TRACKING_SEGMENT_CHARS = 16
FUTURE_CACHE_SKEW_MINUTES = 5
LOGIN_GATED_LINK_STATUS = "article_login_required"
LOGIN_PREFLIGHT_REQUIRED_STATUS = "article_login_preflight_required"
ARTICLE_UNAVAILABLE_STATUS = "article_unavailable"
HTTP_SCHEMES = ("http://", "https://")
ASSET_EXTENSIONS = {
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".png",
    ".svg",
    ".webp",
}
ASSET_DOMAIN_PREFIXES = ("assets.", "images.", "img.", "static.", "staticx.")
SENSITIVE_QUERY_KEYS = {
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
}
TRACKING_QUERY_KEYS = {
    "campaign",
    "cid",
    "cmpid",
    "email",
    "feed",
    "feed_item_type",
    "icid",
    "mailing_id",
    "message_id",
    "ref",
    "source",
    "source_id",
}
SENSITIVE_PATH_TOKENS = (
    "unsubscribe",
    "login",
    "signin",
    "sign-in",
    "account",
    "auth",
    "preferences",
    "manage-email",
)
TRACKING_DOMAIN_PREFIXES = ("click.", "links.", "link.", "email-st.")
REDIRECT_QUERY_KEYS = (
    "url",
    "u",
    "target",
    "redirect",
    "redirect_url",
    "destination",
    "dest",
    "link",
)
ARTICLE_PATH_TOKENS = (
    "/article/",
    "/news/",
    "/stock/news/",
    "/research/",
    "/analysis/",
)

ArticleFetcher = Callable[[str, int], "FetchedArticle"]
ArticleAnalyzer = Callable[
    ["FetchedArticle", SubscriptionEmailConfig, EmailRecord],
    dict[str, object],
]
ArticleLoginHandler = Callable[
    [SubscriptionEmailConfig, str, EmailRecord],
    SubscriptionEmailConfig,
]


class ArticleLoginRequiredError(RuntimeError):
    """Raised when a fetched link is a login or human-verification page."""


@dataclass(frozen=True)
class LinkedContentStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    cached: int = 0
    login_required: int = 0
    unavailable: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LinkedContentResult:
    records: list[EmailRecord]
    stats: LinkedContentStats


def enrich_records_with_linked_content(
    records: list[EmailRecord],
    *,
    config: SubscriptionEmailConfig,
    fetcher: ArticleFetcher | None = None,
    analyzer: ArticleAnalyzer | None = None,
    article_login_handler: ArticleLoginHandler | None = None,
) -> LinkedContentResult:
    if (
        not config.follow_article_links
        or config.article_max_links_per_email == 0
        or config.article_max_total_per_run == 0
    ):
        return LinkedContentResult(records=records, stats=LinkedContentStats(skipped=len(records)))
    analyze = analyzer or (
        lambda page, active_config, record: analyze_article_with_optional_llm(
            page,
            config=active_config,
            record=record,
        )
    )
    cache = load_article_analysis_cache(config.article_analysis_cache_path)
    cache_changed = False
    output: list[EmailRecord] = []
    attempted = succeeded = failed = skipped = cached = 0
    force_supplied_fetcher = fetcher is not None
    with _article_fetcher_for_run(config, fetcher) as fetch_article:
        for record in records:
            skip_status = _pre_link_skip_status(record, config)
            if skip_status is not None:
                output.append(_with_status(record, skip_status))
                skipped += 1
                continue
            links = _allowed_article_link_pairs(record, config)
            if not links:
                output.append(_with_status(record, "no_allowed_article_link"))
                skipped += 1
                continue
            enriched = record
            for link in links[: config.article_max_links_per_email]:
                fetch_url = link["fetch_url"]
                cache_url = link["safe_url"]
                cached_analysis = _usable_cached_analysis(cache.get(cache_url), config)
                if cached_analysis is not None:
                    enriched = _with_analysis(record, cached_analysis)
                    cached += 1
                    succeeded += 1
                    break
                if _link_needs_confirmed_login_preflight(cache_url, config):
                    if article_login_handler is not None:
                        try:
                            config = article_login_handler(config, fetch_url, record)
                        except (BrowserSessionUnavailableError, EOFError):
                            raise
                        except Exception:
                            enriched = _with_status(
                                record,
                                LOGIN_PREFLIGHT_REQUIRED_STATUS,
                                url=cache_url,
                            )
                            skipped += 1
                            break
                    if _link_needs_confirmed_login_preflight(cache_url, config):
                        enriched = _with_status(
                            record,
                            LOGIN_PREFLIGHT_REQUIRED_STATUS,
                            url=cache_url,
                        )
                        skipped += 1
                        break
                if attempted >= config.article_max_total_per_run:
                    enriched = _with_status(record, "article_fetch_limited", url=cache_url)
                    skipped += 1
                    break
                attempted += 1
                try:
                    page = _fetch_article_with_current_login_state(
                        fetch_article,
                        fetch_url,
                        config,
                        force_supplied_fetcher=force_supplied_fetcher,
                    )
                    if _login_gated_article(page):
                        raise ArticleLoginRequiredError(
                            "article page requires login or human verification"
                        )
                except ArticleLoginRequiredError:
                    if article_login_handler is not None:
                        try:
                            config = article_login_handler(config, fetch_url, record)
                            page = _fetch_article_after_confirmed_login(
                                fetch_article,
                                fetch_url,
                                config,
                                force_supplied_fetcher=force_supplied_fetcher,
                            )
                            if _login_gated_article(page):
                                raise ArticleLoginRequiredError(
                                    "article page still requires login or human verification"
                                )
                        except (BrowserSessionUnavailableError, EOFError):
                            raise
                        except ArticleLoginRequiredError:
                            failed += 1
                            enriched = _with_status(
                                record,
                                LOGIN_GATED_LINK_STATUS,
                                url=cache_url,
                            )
                            continue
                        except Exception:
                            failed += 1
                            enriched = _with_status(
                                record,
                                LOGIN_GATED_LINK_STATUS,
                                url=cache_url,
                            )
                            continue
                    else:
                        failed += 1
                        enriched = _with_status(record, LOGIN_GATED_LINK_STATUS, url=cache_url)
                        continue
                except Exception:
                    failed += 1
                    enriched = _with_status(record, ARTICLE_UNAVAILABLE_STATUS, url=cache_url)
                    continue
                analysis = analyze(page, config, record)
                safe = cacheable_analysis(analysis, fetched_at=datetime.now(UTC).isoformat())
                if safe is not None:
                    cache[cache_url] = safe
                    cache[_normalize_url(str(safe["url"]))] = safe
                    cache_changed = True
                enriched = _with_analysis(record, analysis)
                succeeded += 1
                break
            output.append(enriched)
    if cache_changed:
        write_article_analysis_cache(config.article_analysis_cache_path, cache)
    return LinkedContentResult(
        records=output,
        stats=LinkedContentStats(
            attempted=attempted,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            cached=cached,
            login_required=_status_count(output, LOGIN_GATED_LINK_STATUS)
            + _status_count(output, LOGIN_PREFLIGHT_REQUIRED_STATUS),
            unavailable=_status_count(output, ARTICLE_UNAVAILABLE_STATUS),
            status_counts=_linked_content_status_counts(output),
        ),
    )


def allowed_article_links(record: EmailRecord, config: SubscriptionEmailConfig) -> list[str]:
    return [link["safe_url"] for link in _allowed_article_link_pairs(record, config)]


def allowed_article_fetch_links(
    record: EmailRecord,
    config: SubscriptionEmailConfig,
) -> list[str]:
    return [link["fetch_url"] for link in _allowed_article_link_pairs(record, config)]


def _allowed_article_link_pairs(
    record: EmailRecord,
    config: SubscriptionEmailConfig,
) -> list[dict[str, str]]:
    domains = config.article_link_domains or config.allowed_sender_domains
    candidates = [
        _expand_tracking_url(_clean_url(match))
        for match in URL_RE.findall(_record_text(record))
    ]
    output: list[tuple[int, int, dict[str, str]]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        url = _normalize_url(candidate)
        if (
            not _allowed_url(url, domains)
            or _asset_url(url)
            or _sensitive_or_tracking_url(url)
            or url in seen
        ):
            continue
        seen.add(url)
        output.append(
            (
                _article_priority(url),
                index,
                {
                    "fetch_url": candidate,
                    "safe_url": url,
                },
            )
        )
    return [link for _priority, _index, link in sorted(output, key=lambda item: (-item[0], item[1]))]


def _focused_on_unconfigured_ticker(
    record: EmailRecord,
    config: SubscriptionEmailConfig,
) -> bool:
    focus = _subject_focus_ticker(record.subject)
    if focus is None:
        return False
    configured = {ticker.upper() for ticker in config.tickers}
    return bool(configured) and focus not in configured


def _login_or_security_email(record: EmailRecord) -> bool:
    return bool(LOGIN_EMAIL_RE.search(record.subject))


def _mentions_configured_ticker(record: EmailRecord, config: SubscriptionEmailConfig) -> bool:
    configured = {ticker.upper() for ticker in config.tickers}
    if not configured:
        return True
    text = _record_text(record).upper()
    return any(
        re.search(TICKER_TEMPLATE.format(ticker=re.escape(ticker)), text)
        for ticker in configured
    )


def _pre_link_skip_status(
    record: EmailRecord,
    config: SubscriptionEmailConfig,
) -> str | None:
    if _login_or_security_email(record):
        return "login_or_security_email"
    if not _mentions_configured_ticker(record, config):
        if _focused_on_unconfigured_ticker(record, config):
            return "non_universe_ticker_email"
        if _allowed_article_link_pairs(record, config):
            return None
        return "no_configured_ticker_in_email"
    return None


def _link_needs_confirmed_login_preflight(
    url: str,
    config: SubscriptionEmailConfig,
) -> bool:
    if not config.article_login_preflight_required:
        return False
    if config.article_login_preflight_confirmed:
        return False
    provider = provider_for_url(url)
    if provider is None:
        return False
    return provider in article_login_preflight_providers(config)


def _usable_cached_analysis(
    analysis: dict[str, object] | None,
    config: SubscriptionEmailConfig,
) -> dict[str, object] | None:
    if analysis is None:
        return None
    if not _cache_entry_is_fresh(analysis, config):
        return None
    cached_tickers = {value.upper() for value in _string_items(analysis.get("tickers"))}
    configured_tickers = {ticker.upper() for ticker in config.tickers}
    if configured_tickers and not cached_tickers:
        return None
    if configured_tickers and cached_tickers and not cached_tickers.intersection(configured_tickers):
        return None
    context_source = str(analysis.get("context_source", ""))
    llm_enabled = _article_llm_enabled(config)
    if llm_enabled and not context_source.startswith(
        "openai_llm_article_analysis:"
    ):
        return None
    if llm_enabled:
        active_model = os.environ.get("OPENAI_ARTICLE_ANALYSIS_MODEL") or config.article_llm_model
        expected_suffix = (
            f":{active_model}:subscription-email-article-analysis-v1"
        )
        if not context_source.endswith(expected_suffix):
            return None
    return analysis


def _cache_entry_is_fresh(
    analysis: Mapping[str, object],
    config: SubscriptionEmailConfig,
) -> bool:
    fetched_at = analysis.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        return False
    try:
        parsed = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = datetime.now(UTC) - parsed.astimezone(UTC)
    if age.total_seconds() < 0:
        return abs(age) <= timedelta(minutes=FUTURE_CACHE_SKEW_MINUTES)
    return age <= timedelta(hours=config.article_cache_ttl_hours)


def fetch_linked_article(
    url: str,
    timeout_seconds: int,
    *,
    config: SubscriptionEmailConfig | None = None,
    browser_fetcher: ArticleFetcher | None = None,
) -> FetchedArticle:
    errors: list[str] = []
    login_required = False
    for fetch_name, fetcher in _fetchers(config, browser_fetcher=browser_fetcher):
        try:
            page = fetcher(url, timeout_seconds)
        except BrowserSessionUnavailableError as exc:
            errors.append(f"{fetch_name}: {exc}")
            if _protected_login_provider_url(url, config):
                raise ArticleLoginRequiredError(
                    f"linked article requires browser login ({'; '.join(errors)})"
                ) from exc
            continue
        except Exception as exc:
            errors.append(f"{fetch_name}: {exc}")
            continue
        if _login_gated_article(page):
            login_required = True
            errors.append(f"{fetch_name}: article page requires login or human verification")
            if fetch_name == "browser_session":
                raise ArticleLoginRequiredError(
                    f"linked article requires browser login ({'; '.join(errors)})"
                )
            continue
        if _usable_article(page):
            return page
        errors.append(f"{fetch_name}: fetched page did not look like article content")
    if login_required:
        raise ArticleLoginRequiredError(f"linked article requires login ({'; '.join(errors)})")
    raise RuntimeError(f"linked article fetch failed ({'; '.join(errors)})")


def _fetchers(
    config: SubscriptionEmailConfig | None,
    *,
    browser_fetcher: ArticleFetcher | None = None,
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
                browser_fetcher or _browser_fetcher(config),
            )
        ]
    if config is not None and _browser_fetch_configured(config):
        return [
            (
                "browser_session",
                browser_fetcher or _browser_fetcher(config),
            ),
            ("httpx", _fetch_with_httpx),
            ("scrapling", _fetch_with_scrapling),
        ]
    return [
        ("httpx", _fetch_with_httpx),
        ("scrapling", _fetch_with_scrapling),
    ]


@contextmanager
def _article_fetcher_for_run(
    config: SubscriptionEmailConfig,
    fetcher: ArticleFetcher | None,
) -> Iterator[ArticleFetcher]:
    if fetcher is not None:
        yield fetcher
        return
    if _use_reusable_browser_session(config):
        with BrowserArticleSession(config=config) as browser_session:
            yield lambda url, timeout: fetch_linked_article(
                url,
                timeout,
                config=config,
                browser_fetcher=browser_session.fetch,
            )
        return
    yield lambda url, timeout: fetch_linked_article(url, timeout, config=config)


def _use_reusable_browser_session(config: SubscriptionEmailConfig) -> bool:
    return config.article_fetch_mode == "browser" or (
        config.article_fetch_mode == "auto" and _browser_fetch_configured(config)
    )


def _browser_fetch_configured(config: SubscriptionEmailConfig) -> bool:
    return config.article_browser_state_dir is not None or bool(config.article_browser_cdp_url)


def _browser_fetcher(config: SubscriptionEmailConfig) -> ArticleFetcher:
    return lambda url, timeout: fetch_with_browser_session(
        url,
        config=config,
        timeout_seconds=timeout,
    )


def _fetch_article_with_current_login_state(
    fetch_article: ArticleFetcher,
    url: str,
    config: SubscriptionEmailConfig,
    *,
    force_supplied_fetcher: bool,
) -> FetchedArticle:
    if _has_confirmed_article_login(url, config):
        return _fetch_article_after_confirmed_login(
            fetch_article,
            url,
            config,
            force_supplied_fetcher=force_supplied_fetcher,
        )
    return fetch_article(url, config.article_fetch_timeout_seconds)


def _fetch_article_after_confirmed_login(
    fetch_article: ArticleFetcher,
    url: str,
    config: SubscriptionEmailConfig,
    *,
    force_supplied_fetcher: bool,
) -> FetchedArticle:
    if force_supplied_fetcher:
        return fetch_article(url, config.article_fetch_timeout_seconds)
    if not _has_confirmed_article_login(url, config):
        return fetch_linked_article(url, config.article_fetch_timeout_seconds, config=config)
    browser_config = replace(config, article_fetch_mode="browser")
    return fetch_linked_article(
        url,
        config.article_fetch_timeout_seconds,
        config=browser_config,
    )


def _has_confirmed_article_login(url: str, config: SubscriptionEmailConfig) -> bool:
    return config.article_login_preflight_confirmed and provider_for_url(url) is not None


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
    return not _login_gated_article(page)


def _login_gated_article(page: FetchedArticle) -> bool:
    if int(page.status_code) in {401, 403}:
        return True
    text = " ".join(f"{page.title} {page.text}".split()).lower()
    login_markers = (
        "access to this page has been denied",
        "before we continue",
        "confirm you are a human",
        "press & hold",
        "press and hold",
        "not a bot",
        "sign in to continue",
        "sign in",
        "log in",
        "subscribe to continue",
        "create an account",
        "security code",
    )
    return any(marker in text for marker in login_markers)


def _with_analysis(record: EmailRecord, analysis: dict[str, object]) -> EmailRecord:
    return EmailRecord(
        **{
            **record.__dict__,
            "linked_content_summary": summary_from_analysis(analysis),
            "linked_content_status": str(analysis["status"]),
            "linked_content_url": _normalize_url(str(analysis["url"])),
            "linked_content_title_hash": str(analysis["title_hash"]),
            "linked_content_direction": _string(analysis.get("direction")),
            "linked_content_thesis": _string(analysis.get("thesis")),
            "linked_content_catalysts": tuple(_string_items(analysis.get("catalysts"))),
            "linked_content_risk_flags": tuple(_string_items(analysis.get("risk_flags"))),
            "linked_content_key_points": tuple(_string_items(analysis.get("key_points"))),
            "linked_content_tickers": tuple(_string_items(analysis.get("tickers"))),
            "linked_content_decision_use": _sentence_case(_string(analysis.get("decision_use"))),
            "linked_content_signal_strength": _string(analysis.get("signal_strength")),
            "linked_content_context_chars": _integer(analysis.get("context_chars")),
            "linked_content_confidence": _confidence_value(analysis.get("confidence")),
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


def _linked_content_status_counts(records: list[EmailRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = record.linked_content_status or "not_requested"
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _status_count(records: list[EmailRecord], status: str) -> int:
    return sum(1 for record in records if record.linked_content_status == status)


def _protected_login_provider_url(
    url: str,
    config: SubscriptionEmailConfig | None,
) -> bool:
    if config is None:
        return False
    provider = provider_for_url(url)
    if provider is None:
        return False
    configured = set(config.article_login_preflight_services or config.enabled_services)
    return provider in configured


def _record_text(record: EmailRecord) -> str:
    return f"{record.subject}\n{record.body_text}"


def _allowed_url(url: str, domains: tuple[str, ...]) -> bool:
    domain = urlsplit(url).netloc.lower()
    if not domains:
        return bool(domain)
    return bool(domain) and any(domain == item or domain.endswith(f".{item}") for item in domains)


def _article_llm_enabled(config: SubscriptionEmailConfig) -> bool:
    if config.article_llm_analysis_enabled:
        return True
    value = os.environ.get("SUBSCRIPTION_EMAIL_LLM_ANALYSIS_ENABLED", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _asset_url(url: str) -> bool:
    parsed = urlsplit(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(domain.startswith(prefix) for prefix in ASSET_DOMAIN_PREFIXES):
        return True
    return any(path.endswith(extension) for extension in ASSET_EXTENSIONS)


def _sensitive_or_tracking_url(url: str) -> bool:
    parsed = urlsplit(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(domain.startswith(prefix) for prefix in TRACKING_DOMAIN_PREFIXES):
        return True
    return any(token in path for token in SENSITIVE_PATH_TOKENS)


def _article_priority(url: str) -> int:
    path = urlsplit(url).path.lower()
    if any(token in path for token in ARTICLE_PATH_TOKENS):
        return 2
    return 1


def _clean_url(value: str) -> str:
    return value.strip().rstrip(".,;:!?]}'\"")


def _expand_tracking_url(value: str) -> str:
    parsed = urlsplit(value)
    domain = parsed.netloc.lower()
    direct_ref = _email_auth_ref(value)
    if direct_ref is not None:
        return direct_ref
    query_target = _redirect_query_target(parsed.query)
    if query_target is not None:
        return query_target
    if not domain.endswith("seekingalpha.com") or "/click/" not in parsed.path:
        return value
    for segment in parsed.path.split("/"):
        decoded = _decode_url_segment(segment)
        if decoded is None:
            continue
        target = _email_auth_ref(decoded) or decoded
        if target.startswith(HTTP_SCHEMES):
            return target
    return value


def _redirect_query_target(query: str) -> str | None:
    for key, values in parse_qs(query).items():
        if key.lower() not in REDIRECT_QUERY_KEYS:
            continue
        for value in values:
            decoded = unquote(value)
            if decoded.startswith(HTTP_SCHEMES):
                return decoded
    return None


def _decode_url_segment(segment: str) -> str | None:
    if len(segment) < MIN_TRACKING_SEGMENT_CHARS:
        return None
    padded = segment + ("=" * (-len(segment) % 4))
    try:
        decoded = urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (BinasciiError, UnicodeDecodeError, ValueError):
        return None
    if decoded.startswith(HTTP_SCHEMES):
        return decoded
    return None


def _email_auth_ref(value: str) -> str | None:
    parsed = urlsplit(value)
    if not parsed.netloc.lower().endswith("seekingalpha.com"):
        return None
    refs = parse_qs(parsed.query).get("ref", [])
    if not refs:
        return None
    return unquote(refs[0])


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
    return (
        normalized in SENSITIVE_QUERY_KEYS
        or normalized in TRACKING_QUERY_KEYS
        or normalized.startswith(("utm_", "mc_", "mkt_"))
    )


def _subject_focus_ticker(value: str) -> str | None:
    match = SUBJECT_FOCUS_RE.search(value.upper())
    return match.group(1) if match is not None else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _sentence_case(value: str | None) -> str | None:
    if value is None:
        return None
    return value[0].upper() + value[1:] if value else value


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _confidence_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        return None
    return max(0.0, min(1.0, parsed))
