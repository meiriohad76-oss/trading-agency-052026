from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pandas as pd
import pytest
from subscription_email import linked_content
from subscription_email.article_analysis import analyze_article
from subscription_email.article_session import browser_state_path, provider_for_url
from subscription_email.calibration import write_subscription_email_calibration
from subscription_email.classifiers import classify_subscription_emails
from subscription_email.config import SubscriptionEmailConfig, load_subscription_email_config
from subscription_email.ingest import ingest_subscription_emails
from subscription_email.linked_content import FetchedArticle, html_to_text
from subscription_email.mailbox import sync_mailbox_emails
from subscription_email.monitor import monitor_subscription_emails_once
from subscription_email.parser import parse_email_file, read_local_emails
from subscription_email.types import EmailRecord

FETCHED_AT = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
EXPECTED_NEWS_ROWS = 2
EXPECTED_EVENT_ROWS = 3
EXPECTED_SOURCE_REFS = 2
EXPECTED_ARTICLE_TIMEOUT_SECONDS = 15
EXPECTED_MAILBOX_ATTEMPTED = 2
EXPECTED_MAILBOX_SAVED = 1
EXPECTED_MONITOR_CHANGED = 1


def test_subscription_email_config_parses_local_mode(tmp_path: Path) -> None:
    input_path = tmp_path / "mail"
    input_path.mkdir()
    config_path = _config_path(tmp_path, input_path=input_path)

    config = load_subscription_email_config(config_path, repo_root=tmp_path)

    assert config.mode == "local_eml"
    assert config.input_path == input_path
    assert config.enabled_services == ("seeking_alpha", "tradevision", "zacks")
    assert config.allowed_sender_domains[0] == "seekingalpha.com"
    assert config.follow_article_links is False


def test_subscription_email_config_rejects_unknown_service(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path, services=["seeking_alpha", "bad"])

    with pytest.raises(ValueError, match="unknown subscription email service"):
        load_subscription_email_config(config_path, repo_root=tmp_path)


def test_parse_local_eml_extracts_safe_metadata_and_text(tmp_path: Path) -> None:
    message_path = tmp_path / "sa.eml"
    _write_message(
        message_path,
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha Quant Rating for AAPL",
        body="<p>AAPL Quant Rating upgraded. https://seekingalpha.com/article/aapl</p>",
        subtype="html",
    )

    record = parse_email_file(message_path)
    records = read_local_emails(tmp_path)

    assert record.sender_domain == "email.seekingalpha.com"
    assert record.message_id == "sa.eml@example.test"
    assert "AAPL Quant Rating upgraded" in record.body_text
    assert records == [record]


def test_parse_html_email_preserves_href_urls(tmp_path: Path) -> None:
    message_path = tmp_path / "link.eml"
    _write_message(
        message_path,
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha link",
        body="<a href='https://seekingalpha.com/article/123?source=email'>Open article</a>",
        subtype="html",
    )

    record = parse_email_file(message_path)

    assert "https://seekingalpha.com/article/123?source=email" in record.body_text


def test_classifiers_route_service_emails_to_existing_lanes() -> None:
    config = _config()
    records = [
        _record("seeking_alpha", "Seeking Alpha Quant Rating", "AAPL quant rating upgraded"),
        _record("tradevision", "TradeVision Dark Pool", "MSFT dark pool bullish notional $2M"),
        _record("zacks", "Zacks Rank", "NVDA Zacks Rank #1 upgrade"),
        _record("bad", "Unknown", "AAPL", sender_domain="unknown.example"),
        _record("seeking_alpha", "No ticker", "Quant rating changed"),
    ]

    rows = classify_subscription_emails(records, config=config, fetched_at=FETCHED_AT)

    assert len(rows.news_rows) == EXPECTED_NEWS_ROWS
    assert len(rows.activity_rows) == 1
    assert len(rows.event_rows) == EXPECTED_EVENT_ROWS
    assert rows.manual_review[0]["reason"] == "no_ticker_match"
    assert rows.ignored[0]["reason"] == "sender_not_allowlisted"
    assert rows.activity_rows[0]["alert_type"] == "dark_pool"
    assert rows.news_rows[0]["source_tier"] == "PAID_SUB_EMAIL"


def test_classifiers_dedupe_cross_provider_events_by_ticker_and_url() -> None:
    config = _config()
    url = "https://example.test/research/aapl?utm_source=email"
    records = [
        _record("seeking_alpha", "Article", f"AAPL analyst article {url}"),
        _record("zacks", "Recommendation", f"AAPL analyst recommendation {url}"),
    ]

    rows = classify_subscription_emails(records, config=config, fetched_at=FETCHED_AT)

    assert len(rows.news_rows) == EXPECTED_NEWS_ROWS
    assert len(rows.event_rows) == 1
    assert rows.event_rows[0]["services"] == ["seeking_alpha", "zacks"]
    assert len(rows.event_rows[0]["source_refs"]) == EXPECTED_SOURCE_REFS


def test_ingest_writes_pit_clean_outputs_without_private_bodies(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "sa.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article on AAPL",
        body="AAPL analyst article. PRIVATE_BODY_SENTENCE https://example.test/aapl",
    )
    _write_message(
        mailbox / "future.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article on MSFT",
        body="MSFT analyst article. Future item.",
        received_at=FETCHED_AT + timedelta(days=1),
    )
    config_path = _config_path(tmp_path, input_path=mailbox)

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
    )

    news = pd.read_parquet(tmp_path / "research" / "data" / "parquet" / "news_rss.parquet")
    events = pd.read_parquet(
        tmp_path / "research" / "data" / "parquet" / "subscription_emails.parquet"
    )
    summary = json.loads((tmp_path / "summary" / "subscription-email-ingest.json").read_text())

    assert result.processed_emails == 1
    assert result.news_rows == 1
    assert result.ignored_count == 1
    assert news.iloc[0]["timestamp_as_of"] == pd.Timestamp(FETCHED_AT)
    assert events.iloc[0]["message_id_hash"] != "sa.eml@example.test"
    assert "PRIVATE_BODY_SENTENCE" not in json.dumps(summary)
    assert summary["ignored"][0]["reason"] == "future_email"


def test_ingest_uses_linked_article_content_for_ticker_and_summary(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "linked.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article alert",
        body="Read the latest analysis: https://seekingalpha.com/article/123",
    )
    config_path = _config_path(tmp_path, input_path=mailbox, follow_article_links=True)

    def fetcher(url: str, timeout_seconds: int) -> FetchedArticle:
        assert url == "https://seekingalpha.com/article/123"
        assert timeout_seconds == EXPECTED_ARTICLE_TIMEOUT_SECONDS
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Paid article title should be hashed",
            text="AAPL receives an analyst upgrade with positive revenue guidance.",
        )

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
    )

    news = pd.read_parquet(tmp_path / "research" / "data" / "parquet" / "news_rss.parquet")
    events = pd.read_parquet(
        tmp_path / "research" / "data" / "parquet" / "subscription_emails.parquet"
    )
    summary = json.loads((tmp_path / "summary" / "subscription-email-ingest.json").read_text())

    assert result.news_rows == 1
    assert result.linked_content_attempted == 1
    assert result.linked_content_succeeded == 1
    assert news.iloc[0]["ticker"] == "AAPL"
    assert "Linked content thesis" in news.iloc[0]["summary"]
    assert "analyst/rating cue" in news.iloc[0]["summary"]
    assert events.iloc[0]["linked_content_status"] == "article_analyzed"
    assert "Linked content thesis" in events.iloc[0]["linked_content_summary"]
    assert events.iloc[0]["source_tier"] == "PAID_SUB_EMAIL"
    assert summary["linked_content"]["succeeded"] == 1
    assert "analyst upgrade" not in json.dumps(summary)
    assert "Paid article title" not in json.dumps(summary)


def test_linked_article_cache_hit_avoids_fetcher(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "articles": {
                    "https://seekingalpha.com/article/123": {
                        "status": "article_analyzed",
                        "url": "https://seekingalpha.com/article/123",
                        "title_hash": "title123",
                        "tickers": ["MSFT"],
                        "direction": "BULLISH",
                        "catalysts": ["analyst_rating"],
                        "text_hash": "text123",
                        "fetched_at": FETCHED_AT.isoformat(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this https://seekingalpha.com/article/123",
        )
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("cache hit should not fetch article")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.cached == 1
    assert result.stats.attempted == 0
    assert result.records[0].linked_content_status == "article_analyzed"
    assert result.records[0].linked_content_title_hash == "title123"
    assert "MSFT" in str(result.records[0].linked_content_summary)
    assert "Linked content thesis" in str(result.records[0].linked_content_summary)


def test_article_analysis_builds_thesis_without_raw_text() -> None:
    analysis = analyze_article(
        FetchedArticle(
            url="https://seekingalpha.com/article/789",
            status_code=200,
            title="Paid article title must be hashed",
            text=(
                "MSFT is bullish after an analyst upgrade and higher revenue guidance. "
                "The article also notes valuation and regulatory risk."
            ),
        ),
        config=_config(),
    )

    assert analysis["tickers"] == ["MSFT"]
    assert analysis["direction"] == "BULLISH"
    assert analysis["catalysts"] == ["analyst_rating", "earnings"]
    assert analysis["risk_flags"] == ["valuation", "legal_or_regulatory"]
    assert "constructive context for MSFT" in str(analysis["thesis"])
    assert "Paid article title" not in json.dumps(analysis)
    assert "higher revenue guidance" not in json.dumps(analysis)


def test_linked_article_cache_miss_writes_only_safe_analysis(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this https://seekingalpha.com/article/456",
        )
    ]

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Paid title must not be cached",
            text="NVDA receives a bullish analyst upgrade with strong earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert result.stats.attempted == 1
    assert result.stats.succeeded == 1
    assert "https://seekingalpha.com/article/456" in cache["articles"]
    assert "Paid title must not be cached" not in json.dumps(cache)
    assert "bullish analyst upgrade" not in json.dumps(cache)
    assert "strong earnings guidance" not in json.dumps(cache)
    assert cache["articles"]["https://seekingalpha.com/article/456"]["tickers"] == ["NVDA"]
    assert "thesis" in cache["articles"]["https://seekingalpha.com/article/456"]
    assert "key_points" in cache["articles"]["https://seekingalpha.com/article/456"]


def test_linked_article_cache_reuses_original_redirect_url(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this https://email.seekingalpha.com/redirect/456",
        )
    ]
    calls = 0

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        nonlocal calls
        calls += 1
        return FetchedArticle(
            url="https://seekingalpha.com/article/456",
            status_code=200,
            title="Paid title must not be cached",
            text="NVDA receives a bullish analyst upgrade with strong earnings guidance.",
        )

    first = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )
    second = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert calls == 1
    assert first.stats.attempted == 1
    assert second.stats.cached == 1
    assert "https://email.seekingalpha.com/redirect/456" in cache["articles"]
    assert "https://seekingalpha.com/article/456" in cache["articles"]


def test_fetch_linked_article_can_fall_back_to_browser_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    (state_dir / "seeking_alpha.json").write_text("{}", encoding="utf-8")
    config = _config(article_fetch_mode="auto", article_browser_state_dir=state_dir)
    article_text = (
        "AAPL receives an analyst upgrade with positive revenue guidance. "
        "Management raised full-year expectations after strong demand signals. "
    ) * 3

    monkeypatch.setattr(
        linked_content,
        "_fetch_with_httpx",
        lambda _url, _timeout: FetchedArticle(
            url="https://seekingalpha.com/article/123",
            status_code=200,
            title="Login",
            text="Sign in to continue",
        ),
    )
    monkeypatch.setattr(
        linked_content,
        "_fetch_with_scrapling",
        lambda _url, _timeout: FetchedArticle(
            url="https://seekingalpha.com/article/123",
            status_code=200,
            title="Subscribe",
            text="Subscribe to continue",
        ),
    )
    monkeypatch.setattr(
        linked_content,
        "fetch_with_browser_session",
        lambda _url, **_kwargs: FetchedArticle(
            url="https://seekingalpha.com/article/123",
            status_code=200,
            title="AAPL upgrade",
            text=article_text,
        ),
    )

    page = linked_content.fetch_linked_article(
        "https://seekingalpha.com/article/123",
        EXPECTED_ARTICLE_TIMEOUT_SECONDS,
        config=config,
    )

    assert page.title == "AAPL upgrade"
    assert "positive revenue guidance" in page.text


def test_browser_session_provider_paths_are_local_and_gitignored(tmp_path: Path) -> None:
    assert provider_for_url("https://seekingalpha.com/article/123") == "seeking_alpha"
    assert provider_for_url("https://www.zacks.com/stock/news/abc") == "zacks"
    assert provider_for_url("https://example.test/article") is None
    assert browser_state_path(provider="tradevision", repo_root=tmp_path) == (
        tmp_path / "research" / "config" / "browser-sessions" / "tradevision.json"
    )


def test_subscription_email_config_supports_real_browser_channel(tmp_path: Path) -> None:
    config_path = _config_path(
        tmp_path,
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_channel="msedge",
        article_browser_headless=False,
    )

    config = load_subscription_email_config(config_path, repo_root=tmp_path)

    assert config.article_fetch_mode == "browser"
    assert config.article_browser_channel == "msedge"
    assert config.article_browser_headless is False


def test_mailbox_sync_saves_only_allowlisted_messages(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail")
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    client = FakeImapClient(
        {
            "1": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha AAPL",
                body="AAPL analyst article",
            ),
            "2": _message_bytes(
                sender="spam@example.test",
                subject="Spam",
                body="AAPL",
            ),
        }
    )

    result = sync_mailbox_emails(
        config,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
        imap_factory=lambda _config: client,
    )

    assert result.attempted == EXPECTED_MAILBOX_ATTEMPTED
    assert result.saved == EXPECTED_MAILBOX_SAVED
    assert result.skipped == EXPECTED_MAILBOX_SAVED
    assert len(list(mailbox.glob("*.eml"))) == EXPECTED_MAILBOX_SAVED
    assert client.selected_mailbox == "INBOX"


def test_mailbox_sync_requires_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config_path(tmp_path, input_path=tmp_path / "mail", mode="gmail")
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_USERNAME", "real-user@example.test")
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_PASSWORD", "real-password")

    with pytest.raises(RuntimeError, match="missing SUBSCRIPTION_EMAIL_USERNAME"):
        sync_mailbox_emails(config, env={})


def test_monitor_analyzes_new_local_emails_once(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "sa.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article on AAPL",
        body="AAPL analyst article.",
    )
    config_path = _config_path(tmp_path, input_path=mailbox)
    state_path = tmp_path / "monitor-state.json"

    first = monitor_subscription_emails_once(
        config_path=config_path,
        repo_root=tmp_path,
        state_path=state_path,
        summary_root=tmp_path / "summary",
        clock=lambda: FETCHED_AT,
    )
    second = monitor_subscription_emails_once(
        config_path=config_path,
        repo_root=tmp_path,
        state_path=state_path,
        summary_root=tmp_path / "summary",
        clock=lambda: FETCHED_AT,
    )

    assert first.status == "analyzed"
    assert first.changed_files == EXPECTED_MONITOR_CHANGED
    assert first.ingest is not None
    assert first.ingest["news_rows"] == EXPECTED_MAILBOX_SAVED
    assert second.status == "skipped"
    assert second.ingest is None


def test_monitor_opens_article_links_only_for_changed_emails(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    old_path = mailbox / "old.eml"
    _write_message(
        old_path,
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article on AAPL",
        body="AAPL old article. https://seekingalpha.com/article/old",
    )
    state_path = tmp_path / "monitor-state.json"
    old_stat = old_path.stat()
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "files": [
                    {
                        "path": old_path.relative_to(mailbox).as_posix(),
                        "size": old_stat.st_size,
                        "mtime_ns": old_stat.st_mtime_ns,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_message(
        mailbox / "new.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article on MSFT",
        body="MSFT new article. https://seekingalpha.com/article/new",
    )
    config_path = _config_path(tmp_path, input_path=mailbox, follow_article_links=True)
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Safe title hash only",
            text="MSFT receives a bullish analyst upgrade with strong earnings guidance.",
        )

    result = monitor_subscription_emails_once(
        config_path=config_path,
        repo_root=tmp_path,
        state_path=state_path,
        summary_root=tmp_path / "summary",
        clock=lambda: FETCHED_AT,
        article_fetcher=fetcher,
    )

    assert result.status == "analyzed"
    assert result.changed_files == 1
    assert result.ingest is not None
    assert result.ingest["processed_emails"] == 1
    assert result.ingest["linked_content_attempted"] == 1
    assert fetched_urls == ["https://seekingalpha.com/article/new"]


def test_monitor_syncs_mailbox_then_runs_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail")
    client = FakeImapClient(
        {
            "101": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha article on MSFT",
                body="MSFT analyst article.",
            )
        }
    )
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_USERNAME", "user@example.test")
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_PASSWORD", "app-password")

    result = monitor_subscription_emails_once(
        config_path=config_path,
        repo_root=tmp_path,
        state_path=tmp_path / "monitor-state.json",
        summary_root=tmp_path / "summary",
        clock=lambda: FETCHED_AT,
        imap_factory=lambda _config: client,
    )

    assert result.status == "analyzed"
    assert result.mailbox_sync.saved == EXPECTED_MAILBOX_SAVED
    assert result.ingest is not None
    assert result.ingest["event_rows"] == EXPECTED_MAILBOX_SAVED


def test_html_to_text_removes_scripts_and_extracts_title() -> None:
    title, text = html_to_text(
        "<html><title>Example</title><script>secret()</script><p>AAPL upgraded</p></html>"
    )

    assert title == "Example"
    assert text == "AAPL upgraded"


def test_subscription_email_calibration_keeps_lanes_context_only(tmp_path: Path) -> None:
    summary_path = tmp_path / "subscription-email-ingest.json"
    summary_path.write_text(
        json.dumps(
            {
                "event_rows": 3,
                "news_rows": 2,
                "activity_rows": 1,
                "manual_review_count": 0,
                "service_counts": {"seeking_alpha": 1, "tradevision": 1, "zacks": 1},
            }
        ),
        encoding="utf-8",
    )

    report = write_subscription_email_calibration(
        ingest_summary_path=summary_path,
        output_root=tmp_path / "calibration",
    )

    assert report["verdict"] == "context_only_until_forward_validation"
    assert report["runtime_guidance"]["activity_alerts"] == (
        "context_only_until_forward_validation"
    )
    assert (tmp_path / "calibration" / "subscription-email-calibration.md").is_file()


def _config_path(
    tmp_path: Path,
    *,
    input_path: Path | None = None,
    services: list[str] | None = None,
    follow_article_links: bool = False,
    mode: str = "local_eml",
    article_fetch_mode: str = "auto",
    article_browser_state_dir: Path | None = None,
    article_analysis_cache_path: Path | None = None,
    article_browser_channel: str = "chrome",
    article_browser_headless: bool = True,
) -> Path:
    path = tmp_path / "subscription-email.json"
    payload: dict[str, object] = {
        "mode": mode,
        "input_path": str(input_path or tmp_path / "mail"),
        "enabled_services": services or ["seeking_alpha", "tradevision", "zacks"],
        "allowed_sender_domains": [
            "seekingalpha.com",
            "email.seekingalpha.com",
            "tradevision.io",
            "zacks.com",
        ],
        "tickers": ["AAPL", "MSFT", "NVDA"],
        "lookback_days": 30,
        "unmatched_ticker_policy": "manual_review",
        "mailbox_label": "INBOX",
        "mailbox_search": "UNSEEN",
        "mailbox_mark_seen": False,
        "follow_article_links": follow_article_links,
        "article_link_domains": ["seekingalpha.com"],
        "article_fetch_mode": article_fetch_mode,
        "article_browser_channel": article_browser_channel,
        "article_browser_headless": article_browser_headless,
    }
    if article_browser_state_dir is not None:
        payload["article_browser_state_dir"] = str(article_browser_state_dir)
    if article_analysis_cache_path is not None:
        payload["article_analysis_cache_path"] = str(article_analysis_cache_path)
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


def _config(
    *,
    follow_article_links: bool = False,
    article_fetch_mode: str = "auto",
    article_browser_state_dir: Path | None = None,
    article_analysis_cache_path: Path | None = None,
    article_browser_channel: str = "chrome",
    article_browser_headless: bool = True,
) -> SubscriptionEmailConfig:
    return SubscriptionEmailConfig(
        mode="local_eml",
        input_path=Path("mail"),
        enabled_services=("seeking_alpha", "tradevision", "zacks"),
        allowed_sender_domains=(
            "seekingalpha.com",
            "email.seekingalpha.com",
            "tradevision.io",
            "zacks.com",
        ),
        tickers=("AAPL", "MSFT", "NVDA"),
        follow_article_links=follow_article_links,
        article_fetch_mode=article_fetch_mode,
        article_browser_state_dir=article_browser_state_dir,
        article_analysis_cache_path=article_analysis_cache_path,
        article_browser_channel=article_browser_channel,
        article_browser_headless=article_browser_headless,
    )


def _record(
    service: str,
    subject: str,
    body: str,
    *,
    sender_domain: str | None = None,
) -> EmailRecord:
    domains = {
        "seeking_alpha": "email.seekingalpha.com",
        "tradevision": "tradevision.io",
        "zacks": "zacks.com",
        "bad": "bad.example",
    }
    domain = sender_domain or domains[service]
    return EmailRecord(
        message_id=f"{service}-{subject}@example.test",
        sender=f"alerts@{domain}",
        sender_domain=domain,
        subject=subject,
        received_at=FETCHED_AT,
        body_text=body,
    )


def _write_message(
    path: Path,
    *,
    sender: str,
    subject: str,
    body: str,
    subtype: str = "plain",
    received_at: datetime = FETCHED_AT,
) -> None:
    path.write_bytes(
        _message_bytes(
            sender=sender,
            subject=subject,
            body=body,
            subtype=subtype,
            received_at=received_at,
            message_id=f"<{path.name}@example.test>",
        )
    )


def _message_bytes(
    *,
    sender: str,
    subject: str,
    body: str,
    subtype: str = "plain",
    received_at: datetime = FETCHED_AT,
    message_id: str = "<message@example.test>",
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "agency@example.test"
    message["Subject"] = subject
    message["Date"] = format_datetime(received_at)
    message["Message-ID"] = message_id
    message.set_content(body, subtype=subtype)
    return message.as_bytes()


class FakeImapClient:
    def __init__(self, messages: dict[str, bytes]) -> None:
        self.messages = messages
        self.selected_mailbox = ""
        self.stored: list[tuple[str | None, ...]] = []

    def login(self, user: str, password: str) -> object:
        return (user, password)

    def select(self, mailbox: str) -> object:
        self.selected_mailbox = mailbox
        return "OK"

    def uid(
        self,
        command: str,
        *args: str,
    ) -> tuple[str, list[bytes | tuple[bytes, bytes]]]:
        if command == "SEARCH":
            payload = b" ".join(uid.encode("ascii") for uid in self.messages)
            return "OK", [payload]
        if command == "FETCH":
            uid = str(args[0])
            return "OK", [(b"BODY[]", self.messages[uid])]
        if command == "STORE":
            self.stored.append(args)
            return "OK", []
        raise AssertionError(f"unexpected IMAP command: {command}")

    def logout(self) -> object:
        return "OK"
