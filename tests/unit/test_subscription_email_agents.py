from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from subscription_email import article_session, linked_content
from subscription_email.article_analysis import analyze_article
from subscription_email.article_llm_analysis import (
    ArticleLlmAnalyzer,
    normalize_article_llm_analysis,
)
from subscription_email.article_session import browser_state_path, provider_for_url
from subscription_email.calibration import write_subscription_email_calibration
from subscription_email.classifiers import classify_subscription_emails
from subscription_email.config import SubscriptionEmailConfig, load_subscription_email_config
from subscription_email.ingest import ingest_subscription_emails
from subscription_email.linked_content import FetchedArticle, html_to_text
from subscription_email.mailbox import preview_mailbox_emails, sync_mailbox_emails
from subscription_email.monitor import monitor_subscription_emails_once
from subscription_email.parser import parse_email_file, parse_email_message, read_local_emails
from subscription_email.storage import write_event_frame
from subscription_email.types import EmailRecord

from research.scripts import import_subscription_emails as import_subscription_script

FETCHED_AT = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
EXPECTED_NEWS_ROWS = 2
EXPECTED_EVENT_ROWS = 3
EXPECTED_SOURCE_REFS = 2
EXPECTED_ARTICLE_TIMEOUT_SECONDS = 15
EXPECTED_MAILBOX_ATTEMPTED = 2
EXPECTED_MAILBOX_SAVED = 1
EXPECTED_MONITOR_CHANGED = 1
EXPECTED_MAILBOX_LIMIT_MATCHED = 3
EXPECTED_MAILBOX_LIMIT_SAVED = 2
EXPECTED_LLM_ANALYZED_LINKS = 2
EXPECTED_NON_EVIDENCE_EMAILS = 2
EXPECTED_BROWSER_SESSION_COUNT = 1
EXPECTED_BROWSER_SESSION_LINKS = 2
DEFAULT_ARTICLE_MAX_TOTAL_PER_RUN = 5
DEFAULT_ARTICLE_CACHE_TTL_HOURS = 168
DEFAULT_MAILBOX_MAX_MESSAGES = 10


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
    assert config.article_max_total_per_run == DEFAULT_ARTICLE_MAX_TOTAL_PER_RUN
    assert config.article_cache_ttl_hours == DEFAULT_ARTICLE_CACHE_TTL_HOURS
    assert config.article_llm_analysis_enabled is False
    assert config.article_llm_model == "gpt-5-nano"
    assert config.mailbox_unseen_only is True
    assert config.mailbox_max_messages == DEFAULT_MAILBOX_MAX_MESSAGES


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


def test_parse_multipart_plain_email_preserves_html_only_hrefs() -> None:
    message = EmailMessage()
    message["From"] = "alerts@email.seekingalpha.com"
    message["To"] = "agency@example.test"
    message["Subject"] = "Seeking Alpha link"
    message["Date"] = format_datetime(FETCHED_AT)
    message["Message-ID"] = "<multipart@example.test>"
    message.set_content("Read the AAPL article in the browser.")
    message.add_alternative(
        "<a href='https://seekingalpha.com/article/123?source=email'>Open</a>",
        subtype="html",
    )

    record = parse_email_message(message)

    assert "Read the AAPL article" in record.body_text
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


def test_tradevision_blockchain_news_is_not_misclassified_as_block_trade() -> None:
    rows = classify_subscription_emails(
        [
            _record(
                "tradevision",
                "TradeVision bullish MSFT blockchain news",
                "MSFT positive blockchain adoption update, no unusual activity alert.",
            )
        ],
        config=_config(),
        fetched_at=FETCHED_AT,
    )

    assert rows.activity_rows == []
    assert len(rows.news_rows) == 1
    assert rows.event_rows[0]["event_type"] == "tradevision_bullish_news"


def test_classifiers_make_article_analysis_ticker_specific() -> None:
    record = EmailRecord(
        message_id="sa-msft-quant@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="MSFT: SA Asks: What are the most attractive quantum computing stocks?",
        received_at=FETCHED_AT,
        body_text="MSFT and NVDA quant rating article https://seekingalpha.com/article/quant",
        linked_content_status="article_analyzed",
        linked_content_summary="Linked content thesis: constructive context for MSFT and NVDA.",
        linked_content_direction="BULLISH",
        linked_content_thesis="constructive context for MSFT and NVDA",
        linked_content_catalysts=("quant_rating",),
        linked_content_risk_flags=("valuation",),
        linked_content_key_points=("quant/ranking data is supportive",),
        linked_content_tickers=("MSFT", "NVDA"),
        linked_content_decision_use="Treat as context-only bullish thesis.",
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)
    by_ticker = {str(row["ticker"]): row for row in rows.event_rows}

    assert "Direct relevance" in str(by_ticker["MSFT"]["linked_content_thesis"])
    assert "constructive context for MSFT and NVDA" in str(
        by_ticker["MSFT"]["linked_content_thesis"]
    )
    assert "Secondary relevance" in str(by_ticker["NVDA"]["linked_content_thesis"])
    assert "headline focus is MSFT" in str(by_ticker["NVDA"]["linked_content_thesis"])
    assert "constructive context for MSFT and NVDA" in str(
        by_ticker["NVDA"]["linked_content_thesis"]
    )
    assert "secondary basket/theme context" in str(
        by_ticker["NVDA"]["linked_content_decision_use"]
    )
    assert by_ticker["MSFT"]["linked_content_tickers"] == ["MSFT", "NVDA"]


def test_classifiers_do_not_promote_articles_without_ticker_match() -> None:
    record = EmailRecord(
        message_id="sa-aapl-generic@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="AAPL: Market commentary",
        received_at=FETCHED_AT,
        body_text="AAPL article link https://seekingalpha.com/article/generic",
        linked_content_status="article_analyzed",
        linked_content_summary="Linked content thesis: mixed context for the covered ticker universe.",
        linked_content_direction="NEUTRAL",
        linked_content_thesis="mixed context for the covered ticker universe",
        linked_content_key_points=("macro context",),
        linked_content_tickers=(),
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)

    assert rows.event_rows[0]["linked_content_status"] == "article_analyzed_no_ticker_match"
    assert rows.event_rows[0]["linked_content_thesis"] is None


def test_classifiers_keep_article_without_ticker_specific_thesis_as_portfolio_context() -> None:
    record = EmailRecord(
        message_id="sa-cbrs-portfolio-context@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="Portfolio news for MSFT and NVDA",
        received_at=FETCHED_AT,
        body_text=(
            "Portfolio digest mentions MSFT and NVDA. "
            "https://seekingalpha.com/article/cerebras-lockup"
        ),
        linked_content_status="article_analyzed",
        linked_content_summary=(
            "Linked content thesis: Cerebras Systems (CBRS) is overvalued after "
            "its IPO lockup."
        ),
        linked_content_direction="BEARISH",
        linked_content_thesis=(
            "Cerebras Systems (CBRS) is overvalued after its IPO lockup and "
            "share unlock pressure."
        ),
        linked_content_catalysts=("analyst_rating", "earnings"),
        linked_content_risk_flags=("valuation", "execution"),
        linked_content_key_points=(
            "Cerebras lockup expiration is the central risk.",
            "CBRS valuation is the article thesis.",
        ),
        linked_content_tickers=("MSFT", "NVDA"),
        linked_content_decision_use=(
            "Use this analysis to monitor CBRS until valuation normalizes."
        ),
        linked_content_signal_strength="high",
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)
    by_ticker = {str(row["ticker"]): row for row in rows.event_rows}

    assert by_ticker["MSFT"]["linked_content_status"] == "article_analyzed_portfolio_context_only"
    assert by_ticker["MSFT"]["linked_content_thesis"] is None
    assert by_ticker["MSFT"]["linked_content_key_points"] == []
    assert "Do not use" in str(by_ticker["MSFT"]["linked_content_decision_use"])
    assert "monitor CBRS" not in str(by_ticker["MSFT"]["linked_content_summary"])
    assert by_ticker["NVDA"]["linked_content_status"] == "article_analyzed_portfolio_context_only"
    assert all(
        "Cerebras Systems" not in str(row["summary"])
        for row in rows.news_rows
        if row["ticker"] in {"MSFT", "NVDA"}
    )


def test_classifiers_do_not_treat_detected_ticker_boilerplate_as_specific_thesis() -> None:
    record = EmailRecord(
        message_id="sa-detected-ticker-boilerplate@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="Portfolio news for MSFT",
        received_at=FETCHED_AT,
        body_text="Portfolio digest mentions MSFT. https://seekingalpha.com/article/cbrs",
        linked_content_status="article_analyzed",
        linked_content_summary="Linked content thesis: MSFT was detected in article context.",
        linked_content_direction="BEARISH",
        linked_content_thesis=(
            "Ticker relevance: MSFT was detected in analyzed article/email context. "
            "Article thesis: Cerebras Systems (CBRS) is overvalued."
        ),
        linked_content_key_points=("MSFT was detected in the article context.",),
        linked_content_tickers=("MSFT",),
        linked_content_decision_use="Use this analysis to monitor CBRS.",
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)

    assert rows.event_rows[0]["linked_content_status"] == (
        "article_analyzed_portfolio_context_only"
    )
    assert rows.event_rows[0]["linked_content_thesis"] is None


def test_classifiers_do_not_match_common_word_ticker_mentions_in_lowercase() -> None:
    record = EmailRecord(
        message_id="sa-fast-common-word@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="Portfolio news for NVDA",
        received_at=FETCHED_AT,
        body_text="Portfolio digest mentions NVDA. https://seekingalpha.com/article/cbrs",
        linked_content_status="article_analyzed",
        linked_content_summary="Linked content thesis: Cerebras lockup comes fast.",
        linked_content_direction="BEARISH",
        linked_content_thesis="Cerebras lockup comes fast and pressures CBRS valuation.",
        linked_content_key_points=("The lockup comes fast.",),
        linked_content_tickers=("NVDA",),
        linked_content_decision_use="Use this analysis to monitor CBRS.",
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)

    assert rows.event_rows[0]["linked_content_status"] == (
        "article_analyzed_portfolio_context_only"
    )


def test_classifiers_do_not_match_ambiguous_email_words_as_tickers() -> None:
    config = replace(_config(), tickers=("APP", "NOW", "T"))
    record = _record(
        "seeking_alpha",
        "Daily market notes",
        "Open the app now to read the full article and latest portfolio notes.",
    )

    rows = classify_subscription_emails([record], config=config, fetched_at=FETCHED_AT)

    assert rows.news_rows == []
    assert rows.event_rows == []
    assert rows.manual_review[0]["reason"] == "no_ticker_match"


def test_classifiers_allow_explicit_ambiguous_ticker_syntax() -> None:
    config = replace(_config(), tickers=("APP", "NOW", "T"))
    records = [
        _record("seeking_alpha", "APP: analyst article", "APP: AppLovin coverage update."),
        _record("seeking_alpha", "Dividend watch", "$T dividend coverage update."),
    ]

    rows = classify_subscription_emails(records, config=config, fetched_at=FETCHED_AT)

    assert sorted(row["ticker"] for row in rows.news_rows) == ["APP", "T"]


def test_classifiers_do_not_promote_peer_comparison_as_ticker_thesis() -> None:
    record = EmailRecord(
        message_id="sa-cbrs-peer-comparison@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="Portfolio context for MSFT",
        received_at=FETCHED_AT,
        body_text="Portfolio digest mentions MSFT. https://seekingalpha.com/article/cbrs",
        linked_content_status="article_analyzed",
        linked_content_summary="Linked content thesis: Cerebras Systems (CBRS) is overvalued.",
        linked_content_direction="BEARISH",
        linked_content_thesis="Cerebras Systems (CBRS) is overvalued after its IPO lockup.",
        linked_content_key_points=(
            "Peers like Nvidia and MSFT trade at much lower multiples, highlighting "
            "Cerebras' valuation premium.",
        ),
        linked_content_tickers=("MSFT",),
        linked_content_decision_use="Use this analysis to monitor CBRS.",
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)

    assert rows.event_rows[0]["linked_content_status"] == (
        "article_analyzed_portfolio_context_only"
    )
    assert rows.event_rows[0]["linked_content_thesis"] is None


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


def test_event_storage_dedupes_same_article_url_across_runs(tmp_path: Path) -> None:
    config = _config()
    path = tmp_path / "subscription_emails.parquet"
    url = "https://example.test/research/aapl?utm_source=email"
    first = classify_subscription_emails(
        [_record("seeking_alpha", "Article", f"AAPL analyst article {url}")],
        config=config,
        fetched_at=FETCHED_AT,
    )
    second = classify_subscription_emails(
        [_record("zacks", "Recommendation", f"AAPL analyst recommendation {url}")],
        config=config,
        fetched_at=FETCHED_AT + timedelta(minutes=1),
    )

    write_event_frame(path, pd.DataFrame(first.event_rows))
    write_event_frame(path, pd.DataFrame(second.event_rows))
    stored = pd.read_parquet(path)

    assert len(stored) == 1
    assert stored.iloc[0]["service"] == "zacks"


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


def test_ingest_source_paths_skip_mailbox_sync_for_remote_config(tmp_path: Path) -> None:
    source_path = tmp_path / "saved.eml"
    _write_message(
        source_path,
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article on AAPL",
        body="AAPL analyst article.",
    )
    config_path = _config_path(tmp_path, input_path=tmp_path / "mailbox", mode="gmail")

    def imap_factory(_config: SubscriptionEmailConfig) -> object:
        raise AssertionError("source-path ingest must not open the mailbox")

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        source_paths=(source_path,),
        imap_factory=imap_factory,
    )

    assert result.processed_emails == 1
    assert result.mailbox_sync["mode"] == "local_eml"
    assert result.mailbox_sync["reason"] == "source paths supplied; mailbox sync skipped"
    assert result.mailbox_sync["attempted"] == 1


def test_ingest_uses_linked_article_content_for_ticker_and_summary(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "linked.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha article alert",
        body="Read the latest AAPL analysis: https://seekingalpha.com/article/123",
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
        article_login_preflight=lambda config, _records: replace(
            config,
            article_login_preflight_confirmed=True,
        ),
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
    assert events.iloc[0]["linked_content_direction"] == "BULLISH"
    assert "Ticker relevance" in events.iloc[0]["linked_content_thesis"]
    assert "analyst/rating" in events.iloc[0]["linked_content_thesis"]
    assert "analyst or rating" in " ".join(events.iloc[0]["linked_content_key_points"])
    assert events.iloc[0]["source_tier"] == "PAID_SUB_EMAIL"
    assert summary["recent_evidence"][0]["ticker"] == "AAPL"
    assert summary["recent_evidence"][0]["linked_content_status"] == "article_analyzed"
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
                        "fetched_at": datetime.now(UTC).isoformat(),
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
            "Read this MSFT article https://seekingalpha.com/article/123",
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


def test_linked_article_cache_ttl_expires_stale_analysis(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "articles": {
                    "https://seekingalpha.com/article/expired": {
                        "status": "article_analyzed",
                        "url": "https://seekingalpha.com/article/expired",
                        "title_hash": "oldtitle",
                        "tickers": ["MSFT"],
                        "direction": "BULLISH",
                        "catalysts": ["analyst_rating"],
                        "text_hash": "oldtext",
                        "fetched_at": "2000-01-01T00:00:00+00:00",
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
            "Read this MSFT article https://seekingalpha.com/article/expired",
        )
    ]
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Fresh title",
            text="MSFT receives a bullish analyst upgrade with positive earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert fetched_urls == ["https://seekingalpha.com/article/expired"]
    assert result.stats.cached == 0
    assert result.stats.attempted == 1
    assert result.records[0].linked_content_title_hash != "oldtitle"


def test_linked_article_cache_rejects_future_timestamp_beyond_clock_skew(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    future = datetime.now(UTC) + timedelta(hours=2)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "articles": {
                    "https://seekingalpha.com/article/future": {
                        "status": "article_analyzed",
                        "url": "https://seekingalpha.com/article/future",
                        "title_hash": "futuretitle",
                        "tickers": ["MSFT"],
                        "direction": "BULLISH",
                        "catalysts": ["analyst_rating"],
                        "text_hash": "futuretext",
                        "fetched_at": future.isoformat(),
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
            "Read this MSFT article https://seekingalpha.com/article/future",
        )
    ]
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Fresh title",
            text="MSFT receives a bullish analyst upgrade with positive earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert fetched_urls == ["https://seekingalpha.com/article/future"]
    assert result.stats.cached == 0
    assert result.stats.attempted == 1


def test_linked_article_login_gate_is_not_analyzed_or_cached(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this AAPL article https://seekingalpha.com/article/human-check",
        )
    ]

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        return FetchedArticle(
            url=url,
            status_code=403,
            title="Access to this page has been denied",
            text="Before we continue, press and hold to confirm you are a human.",
        )

    def analyzer(
        page: FetchedArticle,
        active_config: SubscriptionEmailConfig,
        record: EmailRecord,
    ) -> dict[str, object]:
        del page, active_config, record
        raise AssertionError("login-gated page should not be analyzed")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        analyzer=analyzer,
    )

    assert result.stats.failed == 1
    assert result.stats.login_required == 1
    assert result.stats.status_counts == {"article_login_required": 1}
    assert result.records[0].linked_content_status == "article_login_required"
    assert not cache_path.exists()


def test_linked_article_login_gate_prompts_and_retries_same_link(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    article_url = "https://seekingalpha.com/article/reactive-aapl"
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            f"AAPL analyst article {article_url}",
        )
    ]
    fetched_urls: list[str] = []
    login_challenges: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        if len(fetched_urls) == 1:
            return FetchedArticle(
                url=url,
                status_code=403,
                title="Access to this page has been denied",
                text="Before we continue, press and hold to confirm you are a human.",
            )
        return FetchedArticle(
            url=url,
            status_code=200,
            title="AAPL article",
            text="AAPL receives bullish analyst coverage with positive earnings guidance.",
        )

    def article_login_handler(
        active_config: SubscriptionEmailConfig,
        url: str,
        record: EmailRecord,
    ) -> SubscriptionEmailConfig:
        del record
        login_challenges.append(url)
        return replace(active_config, article_login_preflight_confirmed=True)

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        article_login_handler=article_login_handler,
    )

    assert fetched_urls == [article_url, article_url]
    assert login_challenges == [article_url]
    assert result.stats.attempted == 1
    assert result.stats.failed == 0
    assert result.stats.succeeded == 1
    assert result.records[0].linked_content_status == "article_analyzed"


def test_sa_article_links_are_not_opened_until_login_preflight_is_confirmed(
    tmp_path: Path,
) -> None:
    config = _config(
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            "AAPL analyst article https://seekingalpha.com/article/aapl",
        )
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("SA article links must not open before login is verified")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.attempted == 0
    assert result.stats.skipped == 1
    assert result.stats.failed == 0
    assert result.records[0].linked_content_status == "article_login_preflight_required"
    assert result.records[0].linked_content_url == "https://seekingalpha.com/article/aapl"


def test_sa_article_links_require_login_preflight_by_default_when_following_links(
    tmp_path: Path,
) -> None:
    config_path = _config_path(
        tmp_path,
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
    )
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            "AAPL analyst article https://seekingalpha.com/article/aapl",
        )
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("SA article links must not open before login is verified")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.attempted == 0
    assert result.stats.skipped == 1
    assert result.records[0].linked_content_status == "article_login_preflight_required"


def test_ingest_source_health_marks_article_login_needed(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "sa-login-needed.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha AAPL article",
        body="AAPL analyst article https://seekingalpha.com/article/aapl",
    )
    config_path = _config_path(
        tmp_path,
        input_path=mailbox,
        follow_article_links=True,
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("preflight-required articles must not open before login")

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
    )
    summary = json.loads((tmp_path / "summary" / "subscription-email-ingest.json").read_text())
    source_health = {
        str(row["source"]): row
        for row in summary["source_health"]
    }

    assert result.linked_content_login_required == 1
    assert result.linked_content_status_counts == {"article_login_preflight_required": 1}
    assert result.event_rows == 1
    assert result.news_rows == 0
    assert summary["verdict"] == "needs_article_login"
    assert summary["recent_evidence"][0]["ticker"] == "AAPL"
    assert summary["recent_evidence"][0]["linked_content_status"] == "article_login_preflight_required"
    assert "login" in str(summary["recent_evidence"][0]["thesis"]).lower()
    assert "do not count" in str(summary["recent_evidence"][0]["decision_use"]).lower()
    assert summary["ignored"] == []
    assert source_health["subscription-email-seeking_alpha"]["status"] == "DEGRADED"
    assert source_health["subscription-email-seeking_alpha"]["freshness"] == "UNAVAILABLE"
    assert source_health["subscription-email-seeking_alpha"]["event_count"] == 1
    assert source_health["subscription-email-seeking_alpha"]["needs_login"] is True
    assert source_health["subscription-email-seeking_alpha"]["linked_content_status_counts"] == {
        "article_login_preflight_required": 1
    }
    assert "login confirmation" in " ".join(
        source_health["subscription-email-seeking_alpha"]["notes"]
    )
    assert source_health["subscription-email-seeking_alpha"]["checked_at"] == FETCHED_AT.isoformat()


def test_sa_article_preflight_required_prompts_before_first_open(
    tmp_path: Path,
) -> None:
    config = _config(
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    article_url = "https://seekingalpha.com/article/preflight-aapl"
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            f"AAPL analyst article {article_url}",
        )
    ]
    fetched_urls: list[str] = []
    login_challenges: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="AAPL article",
            text="AAPL receives bullish analyst coverage with positive earnings guidance.",
        )

    def article_login_handler(
        active_config: SubscriptionEmailConfig,
        url: str,
        record: EmailRecord,
    ) -> SubscriptionEmailConfig:
        del record
        login_challenges.append(url)
        return replace(active_config, article_login_preflight_confirmed=True)

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        article_login_handler=article_login_handler,
    )

    assert login_challenges == [article_url]
    assert fetched_urls == [article_url]
    assert result.stats.attempted == 1
    assert result.stats.succeeded == 1
    assert result.records[0].linked_content_status == "article_analyzed"


def test_sa_article_preflight_handler_failure_aborts_before_open(
    tmp_path: Path,
) -> None:
    config = _config(
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    article_url = "https://seekingalpha.com/article/preflight-aapl"
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            f"AAPL analyst article {article_url}",
        )
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("SA article links must not open after failed login preflight")

    def article_login_handler(
        active_config: SubscriptionEmailConfig,
        url: str,
        record: EmailRecord,
    ) -> SubscriptionEmailConfig:
        del active_config, url, record
        raise article_session.BrowserSessionUnavailableError("Chrome login was not verified")

    with pytest.raises(article_session.BrowserSessionUnavailableError, match="not verified"):
        linked_content.enrich_records_with_linked_content(
            records,
            config=config,
            fetcher=fetcher,
            article_login_handler=article_login_handler,
        )


def test_import_preflight_aborts_when_login_cannot_be_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    article_url = "https://seekingalpha.com/article/preflight-aapl"
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            f"AAPL analyst article {article_url}",
        )
    ]

    def fail_login(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        raise article_session.BrowserSessionUnavailableError("Chrome login was not verified")

    monkeypatch.setattr(
        import_subscription_script,
        "ensure_interactive_article_login",
        fail_login,
    )

    with pytest.raises(article_session.BrowserSessionUnavailableError, match="not verified"):
        import_subscription_script._run_article_login_preflight(
            config,
            SimpleNamespace(article_login_service=[]),
            records,
        )


def test_import_subscription_preflight_records_login_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    article_url = "https://seekingalpha.com/article/aapl?mailing_id=1"
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            f"AAPL analyst article {article_url}",
        )
    ]
    progress_path = tmp_path / "subscription-email-progress.json"
    snapshots: list[dict[str, object]] = []

    def fake_login(
        _config: SubscriptionEmailConfig,
        *,
        providers: tuple[str, ...],
        verification_urls: dict[str, str],
    ) -> tuple[article_session.ArticleLoginPreflightResult, ...]:
        snapshots.append(json.loads(progress_path.read_text(encoding="utf-8")))
        return (
            article_session.ArticleLoginPreflightResult(
                provider=providers[0],
                login_url="https://seekingalpha.com/account/login",
                mode="attached_chrome_cdp",
                confirmed=True,
                verification_url=verification_urls[providers[0]],
            ),
        )

    monkeypatch.setattr(
        import_subscription_script,
        "ensure_interactive_article_login",
        fake_login,
    )

    updated = import_subscription_script._run_article_login_preflight(
        config,
        SimpleNamespace(article_login_service=[], progress_output=progress_path),
        records,
    )

    assert updated.article_login_preflight_confirmed is True
    assert snapshots[0]["state"] == "waiting_for_login_confirmation"
    assert snapshots[0]["selected_email_count"] == 1
    assert snapshots[0]["article_links_found"] == 1
    complete = json.loads(progress_path.read_text(encoding="utf-8"))
    assert complete["state"] == "login_confirmed"
    assert complete["article_links_found"] == 1
    assert "Opening and analyzing article links" in str(complete["detail"])


def test_linked_article_unavailable_is_durable_status(tmp_path: Path) -> None:
    config = _config(
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
    )
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            "AAPL analyst article https://seekingalpha.com/article/unavailable",
        )
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise RuntimeError("article removed")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.failed == 1
    assert result.stats.unavailable == 1
    assert result.stats.status_counts == {"article_unavailable": 1}
    assert result.records[0].linked_content_status == "article_unavailable"


def test_ingest_verdict_is_not_ready_when_all_paid_article_fetches_fail(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "first.eml",
        sender="alerts@email.seekingalpha.com",
        subject="AAPL paid article one",
        body="AAPL analyst article https://seekingalpha.com/article/aapl-one",
    )
    _write_message(
        mailbox / "second.eml",
        sender="alerts@email.seekingalpha.com",
        subject="AAPL paid article two",
        body="AAPL analyst article https://seekingalpha.com/article/aapl-two",
    )
    config_path = _config_path(
        tmp_path,
        input_path=mailbox,
        follow_article_links=True,
        max_article_links=1,
    )

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise RuntimeError("login or paid article access required")

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
        article_login_preflight=_confirmed_article_login_preflight,
    )
    summary = json.loads((tmp_path / "summary" / "subscription-email-ingest.json").read_text())

    assert result.linked_content_attempted == 1
    assert result.linked_content_succeeded == 0
    assert result.linked_content_unavailable == 1
    assert result.event_rows >= 1
    assert summary["verdict"] == "linked_content_unavailable"


def test_sa_article_links_open_after_login_preflight_is_confirmed(tmp_path: Path) -> None:
    config = _config(
        follow_article_links=True,
        article_analysis_cache_path=tmp_path / "article-cache.local.json",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
        article_login_preflight_confirmed=True,
    )
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha AAPL article",
            "AAPL analyst article https://seekingalpha.com/article/aapl",
        )
    ]
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="AAPL article",
            text="AAPL receives bullish analyst coverage with positive earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert fetched_urls == ["https://seekingalpha.com/article/aapl"]
    assert result.stats.attempted == 1
    assert result.stats.succeeded == 1
    assert result.records[0].linked_content_status == "article_analyzed"


def test_linked_article_analysis_respects_total_run_limit() -> None:
    config = _config(follow_article_links=True, article_max_total_per_run=1)
    records = [
        _record(
            "seeking_alpha",
            "AAPL article",
            "AAPL analyst article https://seekingalpha.com/article/aapl",
        ),
        _record(
            "seeking_alpha",
            "MSFT article",
            "MSFT analyst article https://seekingalpha.com/article/msft",
        ),
    ]
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Article",
            text="AAPL receives a bullish analyst upgrade with positive guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert fetched_urls == ["https://seekingalpha.com/article/aapl"]
    assert result.stats.attempted == 1
    assert result.stats.skipped == 1
    assert result.records[0].linked_content_status == "article_analyzed"
    assert result.records[1].linked_content_status == "article_fetch_limited"


def test_allowed_article_links_strip_email_punctuation_and_dedupe() -> None:
    config = _config(follow_article_links=True)
    record = _record(
        "seeking_alpha",
        "AAPL article",
        (
            "AAPL analyst article "
            "https://seekingalpha.com/article/aapl?mail=1]. "
            "Duplicate https://SEEKINGALPHA.com/article/aapl?mail=1}"
        ),
    )

    assert linked_content.allowed_article_links(record, config) == [
        "https://seekingalpha.com/article/aapl?mail=1"
    ]


def test_allowed_article_links_allows_public_urls_when_domains_are_unset() -> None:
    config = SubscriptionEmailConfig(
        mode="local_eml",
        input_path=Path("mail"),
        enabled_services=("seeking_alpha",),
        allowed_sender_domains=(),
        tickers=("AAPL",),
        follow_article_links=True,
    )
    record = _record(
        "seeking_alpha",
        "AAPL article",
        "AAPL analyst article https://seekingalpha.com/article/aapl",
    )

    assert linked_content.allowed_article_links(record, config) == [
        "https://seekingalpha.com/article/aapl"
    ]


def test_allowed_article_links_ignore_zacks_logo_assets() -> None:
    config = _config(follow_article_links=True)
    record = _record(
        "zacks",
        "Zacks rank change",
        (
            "Daily update "
            "https://staticx.zacks.com/images/zacks/logos/zacks_portfolio_email_logo_180x52.png "
            "https://www.zacks.com/stock/news/1234/aapl-rank-upgrade"
        ),
    )

    assert linked_content.allowed_article_links(record, config) == [
        "https://www.zacks.com/stock/news/1234/aapl-rank-upgrade"
    ]


def test_allowed_article_links_expand_seeking_alpha_tracking_redirect() -> None:
    config = _config(follow_article_links=True)
    target = (
        "https://seekingalpha.com/account/email-auth?"
        "ref=https%3A%2F%2Fseekingalpha.com%2Fnews%2F123-aapl-update%3Fsource%3Demail"
    )
    encoded = urlsafe_b64encode(target.encode("utf-8")).decode("ascii").rstrip("=")
    record = _record(
        "seeking_alpha",
        "AAPL update",
        f"Open https://email-st.seekingalpha.com/click/1/{encoded}/abc",
    )

    assert linked_content.allowed_article_links(record, config) == [
        "https://seekingalpha.com/news/123-aapl-update"
    ]


def test_allowed_article_links_expand_zacks_tracking_redirect() -> None:
    config = _config(follow_article_links=True)
    record = _record(
        "zacks",
        "AAPL rank change",
        (
            "Open "
            "https://click.zacks.com/track?u=https%3A%2F%2Fwww.zacks.com%2Fstock%2Fnews%2F1234%2Faapl-rank-upgrade"
        ),
    )

    assert linked_content.allowed_article_links(record, config) == [
        "https://www.zacks.com/stock/news/1234/aapl-rank-upgrade"
    ]


def test_allowed_article_links_skip_sensitive_links_and_strip_sensitive_query() -> None:
    config = _config(follow_article_links=True)
    record = _record(
        "seeking_alpha",
        "AAPL update",
        (
            "AAPL update "
            "https://seekingalpha.com/account/email-auth?token=secret "
            "https://seekingalpha.com/article/aapl?token=secret&utm_source=email&source=email"
        ),
    )

    assert linked_content.allowed_article_links(record, config) == [
        "https://seekingalpha.com/article/aapl"
    ]


def test_linked_article_fetches_signed_url_but_stores_safe_url() -> None:
    config = _config(follow_article_links=True)
    records = [
        _record(
            "seeking_alpha",
            "AAPL update",
            (
                "AAPL update "
                "https://seekingalpha.com/article/aapl?token=secret&source=email"
            ),
        )
    ]
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="AAPL update",
            text="AAPL receives a bullish analyst upgrade with earnings upside. " * 4,
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert fetched_urls == [
        "https://seekingalpha.com/article/aapl?token=secret&source=email"
    ]
    assert result.records[0].linked_content_url == "https://seekingalpha.com/article/aapl"


def test_linked_article_analysis_skips_subject_focused_non_universe_ticker() -> None:
    config = _config(follow_article_links=True, article_max_total_per_run=1)
    records = [
        _record(
            "seeking_alpha",
            "HIMS: Here are the major earnings after the close Monday",
            "Read https://seekingalpha.com/news/hims-earnings",
        )
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("non-universe focused emails should not spend article budget")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.attempted == 0
    assert result.stats.skipped == 1
    assert result.records[0].linked_content_status == "non_universe_ticker_email"


def test_linked_article_analysis_keeps_non_universe_subject_with_universe_body() -> None:
    config = _config(follow_article_links=True, article_max_total_per_run=1)
    records = [
        _record(
            "seeking_alpha",
            "CRWD: AI skeptics ahead of Nvidia report",
            "Nvidia (NVDA) earnings are the article focus. https://seekingalpha.com/news/nvda",
        )
    ]
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="NVDA article",
            text="NVDA receives bullish analyst coverage with positive earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert fetched_urls == ["https://seekingalpha.com/news/nvda"]
    assert result.stats.attempted == 1
    assert result.stats.succeeded == 1
    assert result.records[0].linked_content_status == "article_analyzed"


def test_linked_article_analysis_skips_login_and_no_ticker_emails() -> None:
    config = _config(follow_article_links=True, article_max_total_per_run=2)
    records = [
        _record(
            "seeking_alpha",
            "Security Code for logging in to Seeking Alpha",
            "Use code 123456. https://help.seekingalpha.com/",
        ),
        _record(
            "seeking_alpha",
            "Market story without configured ticker",
            "No configured ticker or article URL is present in this market story.",
        ),
    ]

    def fetcher(_url: str, _timeout_seconds: int) -> FetchedArticle:
        raise AssertionError("non-evidence emails should not spend article budget")

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.attempted == 0
    assert result.stats.skipped == EXPECTED_NON_EVIDENCE_EMAILS
    assert result.records[0].linked_content_status == "login_or_security_email"
    assert result.records[1].linked_content_status == "no_configured_ticker_in_email"


def test_generic_provider_email_can_fetch_article_before_ticker_classification() -> None:
    config = _config(follow_article_links=True, article_max_total_per_run=1)
    records = [
        _record(
            "seeking_alpha",
            "Market story without configured ticker",
            "Read https://seekingalpha.com/article/market-story",
        ),
    ]

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        return FetchedArticle(
            url=url,
            status_code=200,
            title="AAPL demand turns higher",
            text="AAPL receives a bullish analyst upgrade as demand and earnings guidance improve.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
    )

    assert result.stats.attempted == 1
    assert result.records[0].linked_content_status == "article_analyzed"
    assert "AAPL" in result.records[0].linked_content_tickers


def test_classifiers_ignore_terminal_non_evidence_link_statuses() -> None:
    record = EmailRecord(
        message_id="security@example.test",
        sender="alerts@email.seekingalpha.com",
        sender_domain="email.seekingalpha.com",
        subject="Security Code for logging in",
        received_at=FETCHED_AT,
        body_text="Use code 123456",
        linked_content_status="login_or_security_email",
    )

    rows = classify_subscription_emails([record], config=_config(), fetched_at=FETCHED_AT)

    assert rows.manual_review == []
    assert rows.ignored[0]["reason"] == "login_or_security_email"


def test_article_analysis_builds_thesis_without_raw_text() -> None:
    analysis = analyze_article(
        FetchedArticle(
            url="https://seekingalpha.com/article/789?token=secret&utm_source=email&source=email",
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
    assert analysis["url"] == "https://seekingalpha.com/article/789"
    assert "constructive context for MSFT" in str(analysis["thesis"])
    assert "Paid article title" not in json.dumps(analysis)
    assert "higher revenue guidance" not in json.dumps(analysis)


def test_article_analysis_uses_word_boundaries_for_direction_terms() -> None:
    analysis = analyze_article(
        FetchedArticle(
            url="https://seekingalpha.com/article/790",
            status_code=200,
            title="AAPL campus update",
            text="AAPL opened a Mississippi engineering campus for long-term operations.",
        ),
        config=_config(),
    )

    assert analysis["direction"] == "NEUTRAL"


def test_llm_article_analysis_normalizes_ticker_focused_payload() -> None:
    config = _config()
    page = FetchedArticle(
        url="https://seekingalpha.com/article/991",
        status_code=200,
        title="AAPL earnings setup",
        text=(
            "AAPL article body says services growth and guidance are improving, "
            "but valuation remains a concern."
        ),
    )
    fallback = analyze_article(page, config=config)

    analysis = normalize_article_llm_analysis(
        {
            "direction": "BULLISH",
            "confidence": 0.82,
            "tickers": ["AAPL", "BAD"],
            "thesis": "AAPL has a specific services-growth setup with valuation risk.",
            "key_points": [
                "Services growth is the core support for the thesis.",
                "Guidance language improves the near-term setup.",
            ],
            "catalysts": ["earnings", "analyst_rating", "unsupported"],
            "risk_flags": ["valuation"],
            "decision_use": "Use as ticker-specific bullish context, not a trade trigger.",
            "signal_strength": "high",
        },
        page=page,
        config=config,
        fallback=fallback,
        model="gpt-test",
    )

    assert analysis["context_source"] == (
        "openai_llm_article_analysis:gpt-test:subscription-email-article-analysis-v1"
    )
    assert analysis["tickers"] == ["AAPL"]
    assert analysis["direction"] == "BULLISH"
    assert analysis["catalysts"] == ["earnings", "analyst_rating"]
    assert analysis["risk_flags"] == ["valuation"]
    assert "services-growth setup" in str(analysis["thesis"])
    assert "AAPL article body says" not in json.dumps(analysis)


def test_article_llm_analyzer_calls_provider_with_article_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FetchedArticle(
        url="https://seekingalpha.com/article/992",
        status_code=200,
        title="MSFT thesis",
        text="MSFT article text discusses cloud growth and valuation risk.",
    )
    record = _record(
        "seeking_alpha",
        "MSFT: analyst article",
        "Open this link: https://seekingalpha.com/article/992",
    )
    captured_messages: list[dict[str, str]] = []

    def fake_request(
        self: ArticleLlmAnalyzer,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        assert self.model == "gpt-test"
        captured_messages.extend(messages)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "direction": "BULLISH",
                                "confidence": 0.77,
                                "tickers": ["MSFT"],
                                "thesis": "MSFT cloud growth supports the setup.",
                                "key_points": ["Cloud growth is the article's main support."],
                                "catalysts": ["earnings"],
                                "risk_flags": ["valuation"],
                                "decision_use": "Use as MSFT-specific context only.",
                                "signal_strength": "medium",
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(ArticleLlmAnalyzer, "_request", fake_request)

    analysis = ArticleLlmAnalyzer(
        api_key="sk-" + ("a" * 32),
        model="gpt-test",
        enabled=True,
    ).analyze(page, config=_config(), record=record)

    assert captured_messages
    assert "MSFT article text discusses cloud growth" in captured_messages[1]["content"]
    assert "https://seekingalpha.com/article/992" not in captured_messages[1]["content"]
    assert "[url redacted]" in captured_messages[1]["content"]
    assert analysis["context_source"] == (
        "openai_llm_article_analysis:gpt-test:subscription-email-article-analysis-v1"
    )
    assert analysis["tickers"] == ["MSFT"]
    assert analysis["direction"] == "BULLISH"


def test_article_llm_analyzer_attaches_local_ollama_shadow_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FetchedArticle(
        url="https://seekingalpha.com/article/local-msft",
        status_code=200,
        title="MSFT downgrade thesis",
        text="MSFT was downgraded after weak guidance and margin pressure.",
    )
    record = _record(
        "seeking_alpha",
        "MSFT: analyst article",
        "Open this link: https://seekingalpha.com/article/local-msft",
    )
    captured_messages: list[dict[str, str]] = []

    def fake_request(
        self: ArticleLlmAnalyzer,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        assert self.provider == "local_ollama"
        captured_messages.extend(messages)
        return {
            "direction": "BULLISH",
            "confidence": "0.69",
            "tickers": ["MSFT"],
            "thesis": "MSFT cloud demand may offset the headline downgrade.",
            "key_points": ["Cloud demand is the local model's constructive evidence."],
            "catalysts": ["analyst_rating"],
            "risk_flags": ["negative_revision"],
            "decision_use": "Use as a shadow read and verify against deterministic evidence.",
            "signal_strength": "medium",
        }

    monkeypatch.setattr(ArticleLlmAnalyzer, "_request_local_ollama", fake_request)

    analysis = ArticleLlmAnalyzer(
        api_key=None,
        model="qwen2.5:3b-instruct",
        enabled=True,
        provider="local_ollama",
        base_url="http://pi.local:11434",
    ).analyze(page, config=_config(), record=record)

    assert captured_messages
    assert "shadow-only" in captured_messages[0]["content"].lower()
    assert "MSFT was downgraded" in captured_messages[1]["content"]
    assert analysis["direction"] == "BEARISH"
    assert analysis["context_source"] == "title_plus_browser_rendered_text"
    assert analysis["local_llm_article_status"] == "completed"
    assert analysis["local_llm_article_provider"] == "local_ollama"
    assert analysis["local_llm_article_model"] == "qwen2.5:3b-instruct"
    assert analysis["local_llm_article_context_source"] == (
        "local_ollama_article_analysis:"
        "qwen2.5:3b-instruct:subscription-email-article-analysis-v1"
    )
    assert analysis["local_llm_article_direction"] == "BULLISH"
    assert analysis["local_llm_article_confidence"] == 0.69
    assert analysis["local_llm_article_can_affect_trade_gates"] is False
    assert "disagrees" in str(analysis["local_llm_article_comparison"]).lower()


def test_article_llm_analyzer_local_ollama_not_configured_keeps_deterministic() -> None:
    page = FetchedArticle(
        url="https://seekingalpha.com/article/local-aapl",
        status_code=200,
        title="AAPL upgrade thesis",
        text="AAPL was upgraded after positive guidance and strong earnings.",
    )
    record = _record(
        "seeking_alpha",
        "AAPL: analyst article",
        "Open this link: https://seekingalpha.com/article/local-aapl",
    )

    analysis = ArticleLlmAnalyzer(
        api_key=None,
        model="",
        enabled=True,
        provider="local_ollama",
        base_url="",
    ).analyze(page, config=_config(), record=record)

    assert analysis["direction"] == "BULLISH"
    assert analysis["local_llm_article_status"] == "not_configured"
    assert analysis["local_llm_article_can_affect_trade_gates"] is False
    assert "AGENCY_LOCAL_LLM_BASE_URL" in str(analysis["local_llm_article_error"])


def test_article_llm_analyzer_local_ollama_uses_article_timeout_when_env_timeout_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    config = SubscriptionEmailConfig(
        **{
            **config.__dict__,
            "article_llm_provider": "local_ollama",
            "article_llm_model": "qwen2.5:3b-instruct",
            "article_llm_timeout_seconds": 123,
        }
    )
    monkeypatch.setenv("AGENCY_LOCAL_LLM_BASE_URL", "http://pi.local:11434")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_MODEL", "qwen2.5:3b-instruct")
    monkeypatch.delenv("AGENCY_LOCAL_LLM_TIMEOUT_SECONDS", raising=False)

    analyzer = ArticleLlmAnalyzer.from_config(config)

    assert analyzer.provider == "local_ollama"
    assert analyzer.timeout_seconds == 123


def test_article_llm_analyzer_local_ollama_failure_keeps_readable_error_without_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FetchedArticle(
        url="https://seekingalpha.com/article/local-msft-failure",
        status_code=200,
        title="MSFT upgrade thesis",
        text="MSFT was upgraded after positive guidance and stronger cloud demand.",
    )
    record = _record(
        "seeking_alpha",
        "MSFT: analyst article",
        "Open this link: https://seekingalpha.com/article/local-msft-failure",
    )

    def fake_request(
        _self: ArticleLlmAnalyzer,
        _messages: list[dict[str, str]],
    ) -> dict[str, object]:
        raise ValueError("local ollama unavailable")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ArticleLlmAnalyzer, "_request_local_ollama", fake_request)

    analysis = ArticleLlmAnalyzer(
        api_key=None,
        model="qwen2.5:3b-instruct",
        enabled=True,
        provider="local_ollama",
        base_url="http://pi.local:11434",
    ).analyze(page, config=_config(), record=record)

    assert analysis["local_llm_article_status"] == "failed"
    assert analysis["local_llm_article_error"] == "local ollama unavailable"
    assert "[REDACTED]l[REDACTED]" not in str(analysis["local_llm_article_error"])
    assert analysis["local_llm_article_can_affect_trade_gates"] is False


def test_article_llm_analysis_derives_confidence_from_strength_when_local_model_uses_label() -> None:
    config = _config()
    page = FetchedArticle(
        url="https://seekingalpha.com/article/local-confidence",
        status_code=200,
        title="MSFT local confidence",
        text="MSFT was upgraded after positive guidance.",
    )
    fallback = analyze_article(page, config=config)

    analysis = normalize_article_llm_analysis(
        {
            "direction": "BULLISH",
            "confidence": "high",
            "tickers": ["MSFT"],
            "thesis": "MSFT guidance is constructive.",
            "key_points": ["Guidance is constructive."],
            "catalysts": ["earnings"],
            "risk_flags": [],
            "decision_use": "Use as local shadow evidence.",
            "signal_strength": "high",
        },
        page=page,
        config=config,
        fallback=fallback,
        model="qwen2.5:3b-instruct",
        provider="local_ollama",
    )

    assert analysis["confidence"] == 0.8
    assert analysis["signal_strength"] == "high"


def test_article_llm_analyzer_caps_article_context_to_portfolio_agent_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_text = "AAPL cloud services demand and bullish upgrade. " * 300
    page = FetchedArticle(
        url="https://seekingalpha.com/article/long-aapl",
        status_code=200,
        title="AAPL thesis",
        text=long_text,
    )
    record = _record(
        "seeking_alpha",
        "AAPL: analyst article",
        "Open this link: https://seekingalpha.com/article/long-aapl",
    )
    captured_payloads: list[dict[str, object]] = []

    def fake_request(
        _self: ArticleLlmAnalyzer,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        captured_payloads.append(json.loads(messages[1]["content"]))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "direction": "BULLISH",
                                "confidence": 0.78,
                                "tickers": ["AAPL"],
                                "thesis": "AAPL article supports the thesis.",
                                "key_points": ["Services demand is constructive."],
                                "catalysts": ["analyst_rating"],
                                "risk_flags": [],
                                "decision_use": "Use as AAPL-specific context only.",
                                "signal_strength": "medium",
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(ArticleLlmAnalyzer, "_request", fake_request)

    ArticleLlmAnalyzer(
        api_key="sk-" + ("a" * 32),
        model="gpt-test",
        enabled=True,
    ).analyze(page, config=_config(), record=record)

    assert captured_payloads
    article_payload = captured_payloads[0]["article"]
    assert isinstance(article_payload, dict)
    assert 4_900 <= len(str(article_payload["text"])) <= 5_000
    assert article_payload["body_characters_original"] == len(long_text)
    assert article_payload["body_truncated"] is True


def test_local_ollama_article_prompt_uses_compact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_text = "MSFT cloud demand, analyst upgrade, valuation risk. " * 250
    page = FetchedArticle(
        url="https://seekingalpha.com/article/local-long-msft",
        status_code=200,
        title="MSFT local thesis",
        text=long_text,
    )
    record = _record(
        "seeking_alpha",
        "MSFT: local article",
        "Open this link: https://seekingalpha.com/article/local-long-msft",
    )
    captured_payloads: list[dict[str, object]] = []

    def fake_request(
        _self: ArticleLlmAnalyzer,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        captured_payloads.append(json.loads(messages[1]["content"]))
        return {
            "direction": "BULLISH",
            "confidence": 0.61,
            "tickers": ["MSFT"],
            "thesis": "MSFT cloud demand is constructive.",
            "key_points": ["Cloud demand is constructive."],
            "catalysts": ["analyst_rating"],
            "risk_flags": ["valuation"],
            "decision_use": "Use as a compact shadow-only read.",
            "signal_strength": "medium",
        }

    monkeypatch.setattr(ArticleLlmAnalyzer, "_request_local_ollama", fake_request)

    ArticleLlmAnalyzer(
        api_key=None,
        model="qwen2.5:3b-instruct",
        enabled=True,
        provider="local_ollama",
        base_url="http://pi.local:11434",
    ).analyze(page, config=_config(), record=record)

    assert captured_payloads
    payload = captured_payloads[0]
    assert len(str(payload["article_text"])) <= 1_000
    assert payload["body_characters_original"] == len(long_text)
    assert payload["body_truncated"] is True
    assert payload["shadow_only"] is True
    assert payload["allowed"]["direction"] == ["BEARISH", "BULLISH", "NEUTRAL"]


def test_article_llm_analyzer_marks_missing_key_as_deterministic_fallback() -> None:
    page = FetchedArticle(
        url="https://seekingalpha.com/article/993",
        status_code=200,
        title="MSFT thesis",
        text="MSFT article text discusses cloud growth and valuation risk.",
    )
    record = _record(
        "seeking_alpha",
        "MSFT: analyst article",
        "Open this link: https://seekingalpha.com/article/993",
    )

    analysis = ArticleLlmAnalyzer(
        api_key=None,
        model="gpt-test",
        enabled=True,
    ).analyze(page, config=_config(), record=record)

    assert analysis["status"] == "article_analyzed_deterministic_fallback"
    assert str(analysis["context_source"]).startswith("deterministic_keyword_fallback")


def test_linked_article_cache_miss_writes_only_safe_analysis(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this NVDA article https://seekingalpha.com/article/456",
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


def test_linked_article_cache_persists_local_ollama_shadow_without_raw_text(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "MSFT article",
            "MSFT analyst article https://seekingalpha.com/article/msft-local",
        )
    ]

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Paid title must not be cached",
            text="MSFT receives a bullish upgrade with article-only private body details.",
        )

    def analyzer(
        page: FetchedArticle,
        active_config: SubscriptionEmailConfig,
        _record: EmailRecord,
    ) -> dict[str, object]:
        fallback = analyze_article(page, config=active_config)
        return {
            **fallback,
            "local_llm_article_status": "completed",
            "local_llm_article_provider": "local_ollama",
            "local_llm_article_model": "qwen2.5:3b-instruct",
            "local_llm_article_context_source": (
                "local_ollama_article_analysis:"
                "qwen2.5:3b-instruct:subscription-email-article-analysis-v1"
            ),
            "local_llm_article_direction": "BULLISH",
            "local_llm_article_confidence": 0.72,
            "local_llm_article_tickers": ["MSFT"],
            "local_llm_article_thesis": "MSFT upgrade context is constructive.",
            "local_llm_article_key_points": ["Upgrade language is constructive."],
            "local_llm_article_catalysts": ["analyst_rating"],
            "local_llm_article_risk_flags": ["valuation"],
            "local_llm_article_decision_use": "Use as shadow-only confirmation.",
            "local_llm_article_signal_strength": "medium",
            "local_llm_article_comparison": (
                "Local LLM agrees with deterministic direction BULLISH."
            ),
            "local_llm_article_can_affect_trade_gates": False,
        }

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        analyzer=analyzer,
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert result.records[0].local_llm_article_status == "completed"
    assert result.records[0].local_llm_article_direction == "BULLISH"
    cached = cache["articles"]["https://seekingalpha.com/article/msft-local"]
    assert cached["local_llm_article_status"] == "completed"
    assert cached["local_llm_article_can_affect_trade_gates"] is False
    assert "Paid title must not be cached" not in json.dumps(cache)
    assert "article-only private body details" not in json.dumps(cache)


def test_linked_article_llm_analyzer_runs_for_each_opened_link(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(
        follow_article_links=True,
        article_max_total_per_run=2,
        article_analysis_cache_path=cache_path,
    )
    config = SubscriptionEmailConfig(
        **{**config.__dict__, "article_llm_analysis_enabled": True}
    )
    records = [
        _record(
            "seeking_alpha",
            "AAPL article",
            "AAPL analyst article https://seekingalpha.com/article/aapl",
        ),
        _record(
            "seeking_alpha",
            "MSFT article",
            "MSFT analyst article https://seekingalpha.com/article/msft",
        ),
    ]
    analyzed_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Article",
            text="AAPL and MSFT receive specific bullish article analysis.",
        )

    def analyzer(
        page: FetchedArticle,
        active_config: SubscriptionEmailConfig,
        _record: EmailRecord,
    ) -> dict[str, object]:
        analyzed_urls.append(page.url)
        return normalize_article_llm_analysis(
            {
                "direction": "BULLISH",
                "confidence": 0.8,
                "tickers": ["AAPL", "MSFT"],
                "thesis": f"Specific LLM thesis for {page.url}.",
                "key_points": ["The article identifies a concrete catalyst."],
                "catalysts": ["analyst_rating"],
                "risk_flags": ["valuation"],
                "decision_use": "Use as article-specific context only.",
                "signal_strength": "medium",
            },
            page=page,
            config=active_config,
            fallback=analyze_article(page, config=active_config),
            model="gpt-test",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        analyzer=analyzer,
    )

    assert analyzed_urls == [
        "https://seekingalpha.com/article/aapl",
        "https://seekingalpha.com/article/msft",
    ]
    assert result.stats.succeeded == EXPECTED_LLM_ANALYZED_LINKS
    assert all(record.linked_content_status == "article_analyzed" for record in result.records)
    assert all(
        "Context: openai_llm_article_analysis:gpt-test"
        in str(record.linked_content_summary)
        for record in result.records
    )


def test_llm_enabled_ignores_deterministic_article_cache(tmp_path: Path) -> None:
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
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    config = SubscriptionEmailConfig(
        **{**config.__dict__, "article_llm_analysis_enabled": True}
    )
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this MSFT article https://seekingalpha.com/article/123",
        )
    ]
    fetched = False

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        nonlocal fetched
        fetched = True
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Article",
            text="MSFT receives a bullish analyst upgrade with strong earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        analyzer=lambda page, active_config, _record: analyze_article(
            page,
            config=active_config,
        ),
    )

    assert fetched is True
    assert result.stats.cached == 0
    assert result.stats.attempted == 1


def test_local_ollama_provider_ignores_failed_shadow_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "articles": {
                    "https://seekingalpha.com/article/failed-local": {
                        "status": "article_analyzed",
                        "url": "https://seekingalpha.com/article/failed-local",
                        "title_hash": "title123",
                        "tickers": ["MSFT"],
                        "direction": "BULLISH",
                        "catalysts": ["analyst_rating"],
                        "text_hash": "text123",
                        "local_llm_article_status": "failed",
                        "local_llm_article_context_source": (
                            "local_ollama_article_analysis:"
                            "qwen2.5:3b-instruct:subscription-email-article-analysis-v1"
                        ),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    config = SubscriptionEmailConfig(
        **{
            **config.__dict__,
            "article_llm_analysis_enabled": True,
            "article_llm_provider": "local_ollama",
            "article_llm_model": "qwen2.5:3b-instruct",
        }
    )
    records = [
        _record(
            "seeking_alpha",
            "MSFT article",
            "Read this MSFT article https://seekingalpha.com/article/failed-local",
        )
    ]
    fetched = False

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        nonlocal fetched
        fetched = True
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Article",
            text="MSFT receives a bullish analyst upgrade with strong earnings guidance.",
        )

    result = linked_content.enrich_records_with_linked_content(
        records,
        config=config,
        fetcher=fetcher,
        analyzer=lambda page, active_config, _record: analyze_article(
            page,
            config=active_config,
        ),
    )

    assert fetched is True
    assert result.stats.cached == 0
    assert result.stats.attempted == 1


def test_linked_article_cache_reuses_original_redirect_url(tmp_path: Path) -> None:
    cache_path = tmp_path / "article-cache.local.json"
    config = _config(follow_article_links=True, article_analysis_cache_path=cache_path)
    records = [
        _record(
            "seeking_alpha",
            "Seeking Alpha article alert",
            "Read this NVDA article https://email.seekingalpha.com/redirect/456",
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


def test_fetch_linked_article_stops_when_attached_browser_hits_login_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    (state_dir / "seeking_alpha.json").write_text("{}", encoding="utf-8")
    config = _config(article_fetch_mode="auto", article_browser_state_dir=state_dir)

    monkeypatch.setattr(
        linked_content,
        "fetch_with_browser_session",
        lambda _url, **_kwargs: FetchedArticle(
            url="https://seekingalpha.com/article/123",
            status_code=403,
            title="Access to this page has been denied",
            text="Before we continue, press and hold to confirm you are a human.",
        ),
    )
    monkeypatch.setattr(
        linked_content,
        "_fetch_with_httpx",
        lambda _url, _timeout: FetchedArticle(
            url="https://seekingalpha.com/article/123",
            status_code=200,
            title="HTTP teaser",
            text=("AAPL bullish analyst upgrade. " * 30),
        ),
    )

    with pytest.raises(linked_content.ArticleLoginRequiredError):
        linked_content.fetch_linked_article(
            "https://seekingalpha.com/article/123",
            EXPECTED_ARTICLE_TIMEOUT_SECONDS,
            config=config,
        )


def test_fetch_linked_article_does_not_fallback_when_browser_login_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_fetch_mode="auto",
        article_browser_state_dir=tmp_path / "sessions",
        article_login_preflight_services=("seeking_alpha",),
    )

    def httpx_fetch(_url: str, _timeout: int) -> FetchedArticle:
        raise AssertionError("protected article should not fall back to httpx")

    monkeypatch.setattr(linked_content, "_fetch_with_httpx", httpx_fetch)

    with pytest.raises(linked_content.ArticleLoginRequiredError):
        linked_content.fetch_linked_article(
            "https://seekingalpha.com/article/needs-login",
            EXPECTED_ARTICLE_TIMEOUT_SECONDS,
            config=config,
        )


def test_browser_article_session_detects_human_verification_gate() -> None:
    article = FetchedArticle(
        url="https://seekingalpha.com/article/4902449",
        status_code=200,
        title="Access to this page has been denied",
        text=(
            "Before we continue... Press & Hold to confirm you are a human "
            "and not a bot."
        ),
    )

    assert article_session._looks_like_login(article) is True


def test_readable_seeking_alpha_article_wins_over_footer_login_markers() -> None:
    article_text = (
        "AAPL receives a bullish analyst upgrade after management raised revenue "
        "guidance and described stronger services demand. "
    ) * 6
    article = FetchedArticle(
        url="https://seekingalpha.com/article/readable-aapl",
        status_code=200,
        title="AAPL upgrade thesis",
        text=(
            f"{article_text} Footer: sign in to continue, enable javascript and "
            "cookies, ad-blocker enabled."
        ),
    )

    assert article_session._looks_like_login(article) is False
    assert linked_content._login_gated_article(article) is False


def test_browser_article_fetch_tolerates_navigation_timeout_when_content_is_readable() -> None:
    class FakeNavigationTimeout(RuntimeError):
        pass

    class TimeoutPage:
        url = "https://seekingalpha.com/article/timeout-aapl"

        def goto(self, *_args: object, **_kwargs: object) -> object:
            raise FakeNavigationTimeout("Page.goto: Timeout 15000ms exceeded")

        def wait_for_timeout(self, _timeout: int) -> None:
            return None

        def content(self) -> str:
            return (
                "<html><title>AAPL upgrade thesis</title><article>"
                + (
                    "AAPL receives a bullish analyst upgrade after stronger demand "
                    "and positive earnings guidance. "
                )
                * 6
                + "</article><footer>sign in to continue</footer></html>"
            )

    article = article_session._fetch_page_article(
        TimeoutPage(),
        "https://seekingalpha.com/article/timeout-aapl",
        timeout_seconds=EXPECTED_ARTICLE_TIMEOUT_SECONDS,
        wait_seconds=1,
    )

    assert article.status_code == 0
    assert article.title == "AAPL upgrade thesis"
    assert "positive earnings guidance" in article.text
    assert article_session._looks_like_login(article) is False


def test_enrich_reuses_browser_session_across_paid_article_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_max_total_per_run=EXPECTED_BROWSER_SESSION_LINKS,
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
    )
    records = [
        _record(
            "seeking_alpha",
            "AAPL article",
            "AAPL paid article https://seekingalpha.com/article/aapl",
        ),
        _record(
            "seeking_alpha",
            "MSFT article",
            "MSFT paid article https://seekingalpha.com/article/msft",
        ),
    ]
    sessions: list[object] = []

    class FakeBrowserSession:
        def __init__(self, *, config: SubscriptionEmailConfig) -> None:
            del config
            self.closed = False
            self.fetches: list[str] = []
            sessions.append(self)

        def __enter__(self) -> FakeBrowserSession:
            return self

        def __exit__(self, *_args: object) -> None:
            self.closed = True

        def fetch(self, url: str, _timeout_seconds: int) -> FetchedArticle:
            self.fetches.append(url)
            return FetchedArticle(
                url=url,
                status_code=200,
                title="Paid article",
                text=(
                    "AAPL and MSFT receive bullish analyst coverage with positive "
                    "earnings guidance. "
                )
                * 4,
            )

    monkeypatch.setattr(linked_content, "BrowserArticleSession", FakeBrowserSession)

    result = linked_content.enrich_records_with_linked_content(records, config=config)

    assert len(sessions) == EXPECTED_BROWSER_SESSION_COUNT
    session = sessions[0]
    assert isinstance(session, FakeBrowserSession)
    assert session.closed is True
    assert session.fetches == [
        "https://seekingalpha.com/article/aapl",
        "https://seekingalpha.com/article/msft",
    ]
    assert result.stats.succeeded == EXPECTED_BROWSER_SESSION_LINKS


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
        article_browser_cdp_url="http://127.0.0.1:9222",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )

    config = load_subscription_email_config(config_path, repo_root=tmp_path)

    assert config.article_fetch_mode == "browser"
    assert config.article_browser_channel == "msedge"
    assert config.article_browser_headless is False
    assert config.article_browser_cdp_url == "http://127.0.0.1:9222"
    assert config.article_login_preflight_required is True
    assert config.article_login_preflight_services == ("seeking_alpha",)


def test_cdp_browser_config_does_not_require_state_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _config(
        article_fetch_mode="browser",
        article_browser_cdp_url="http://127.0.0.1:9222",
    )

    fetch_config = article_session.browser_fetch_config(config)

    assert fetch_config is not None
    assert fetch_config.cdp_url == "http://127.0.0.1:9222"
    assert fetch_config.state_dir == (
        article_session.DEFAULT_REPO_ROOT / article_session.DEFAULT_STATE_DIR
    )


def test_browser_fetch_config_uses_explicit_repo_root_for_default_state_dir(
    tmp_path: Path,
) -> None:
    config = _config(article_fetch_mode="browser")

    fetch_config = article_session.browser_fetch_config(config, repo_root=tmp_path)

    assert fetch_config is not None
    assert fetch_config.state_dir == tmp_path / article_session.DEFAULT_STATE_DIR


def test_interactive_login_preflight_opens_provider_in_attached_chrome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    context = FakeChromeContext()
    browser = FakeCdpBrowser(context)
    runtime = FakePlaywrightRuntime(browser)
    prompts: list[str] = []
    messages: list[str] = []
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )

    results = article_session.ensure_interactive_article_login(
        config,
        input_func=lambda prompt: prompts.append(prompt) or "",
        output=messages.append,
    )

    assert len(results) == 1
    assert results[0].provider == "seeking_alpha"
    assert results[0].mode == "attached_chrome_cdp"
    assert runtime.connected_urls == ["http://127.0.0.1:9222"]
    assert context.pages[0].url == "https://seekingalpha.com/account/login"
    assert prompts == [
        "Press Enter only after you are fully logged in and ready for the email agent..."
    ]
    assert "activating" not in " ".join(messages).lower()


def test_attached_chrome_preflight_starts_dedicated_cdp_browser_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )

    class RecoveringCdpRuntime:
        def __init__(self, browser: FakeCdpBrowser) -> None:
            self.chromium = self
            self.browser = browser
            self.connected_urls: list[str] = []
            self.stopped = False
            self.attempts = 0

        def connect_over_cdp(self, url: str) -> FakeCdpBrowser:
            self.connected_urls.append(url)
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("connection refused")
            return self.browser

        def stop(self) -> None:
            self.stopped = True

    runtime = RecoveringCdpRuntime(FakeCdpBrowser(FakeChromeContext()))
    started_urls: list[str] = []
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )
    monkeypatch.setattr(
        article_session,
        "_start_cdp_browser",
        lambda _config, first_login_url: started_urls.append(first_login_url),
    )

    results = article_session.ensure_interactive_article_login(
        config,
        verification_urls={
            "seeking_alpha": "https://seekingalpha.com/article/aapl",
        },
        input_func=lambda _prompt: "",
        output=lambda _message: None,
    )

    assert runtime.connected_urls == [
        "http://127.0.0.1:9222",
        "http://127.0.0.1:9222",
    ]
    assert started_urls == ["https://seekingalpha.com/account/login"]
    assert runtime.stopped is True
    assert len(results) == 1
    assert results[0].confirmed is True


def test_cdp_browser_fallback_opens_regular_chrome_profile_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = article_session.BrowserSessionFetchConfig(
        state_dir=tmp_path / "sessions",
        wait_seconds=5,
        browser_channel="chrome",
        headless=False,
        cdp_url="http://127.0.0.1:9222",
    )
    launched: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        pid = 1234

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        launched.append((command, dict(kwargs)))
        return FakeProcess()

    monkeypatch.setattr(
        article_session,
        "_browser_executable",
        lambda _channel: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    )
    monkeypatch.setattr(article_session.subprocess, "Popen", fake_popen)

    article_session._start_cdp_browser(
        config,
        "https://seekingalpha.com/account/login",
    )

    assert len(launched) == 1
    command = launched[0][0]
    assert command[0].endswith("chrome.exe")
    assert "--remote-debugging-port=9222" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--new-window" in command
    assert "https://seekingalpha.com/account/login" in command
    assert not any(arg.startswith("--user-data-dir=") for arg in command)
    assert "--no-first-run" not in command
    assert "--no-default-browser-check" not in command


def test_interactive_login_preflight_requires_verified_provider_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
        article_browser_wait_seconds=1,
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    context = FakeChromeContext()
    browser = FakeCdpBrowser(context)
    runtime = FakePlaywrightRuntime(browser)
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )
    monkeypatch.setattr(
        article_session,
        "_article_from_page",
        lambda page, response: FetchedArticle(
            url=page.url,
            status_code=200,
            title="Sign in",
            text="Sign in to continue. Press and hold to confirm you are a human.",
        ),
    )
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(article_session.time, "monotonic", lambda: next(ticks, 2.0))

    with pytest.raises(article_session.BrowserSessionUnavailableError, match="not verified"):
        article_session.ensure_interactive_article_login(
            config,
            input_func=lambda _prompt: "",
            output=lambda _message: None,
        )

    assert runtime.stopped is True
    assert context.pages[0].closed is True


def test_interactive_login_preflight_verifies_email_article_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        follow_article_links=True,
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    article_url = "https://seekingalpha.com/article/email-msft?token=secret"
    context = FakeChromeContext()
    browser = FakeCdpBrowser(context)
    runtime = FakePlaywrightRuntime(browser)
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )

    results = article_session.ensure_interactive_article_login(
        config,
        verification_urls={"seeking_alpha": article_url},
        input_func=lambda _prompt: "",
        output=lambda _message: None,
    )

    assert len(results) == 1
    assert results[0].verification_url == article_url
    assert results[0].as_dict()["verification_url"] == (
        "https://seekingalpha.com/article/email-msft"
    )
    assert context.pages[0].visited_urls == [
        "https://seekingalpha.com/account/login",
        article_url,
    ]


def test_browser_article_session_can_attach_to_user_chrome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
    )
    context = FakeChromeContext()
    browser = FakeCdpBrowser(context)
    runtime = FakePlaywrightRuntime(browser)
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )

    with article_session.BrowserArticleSession(config=config) as session:
        page = session.fetch(
            "https://seekingalpha.com/article/attached-aapl",
            EXPECTED_ARTICLE_TIMEOUT_SECONDS,
        )

    assert runtime.connected_urls == ["http://127.0.0.1:9222"]
    assert page.url == "https://seekingalpha.com/article/attached-aapl"
    assert "positive earnings guidance" in page.text
    assert context.closed is False
    assert context.pages[0].closed is True


def test_browser_article_session_starts_cdp_chrome_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
    )

    class RecoveringCdpRuntime:
        def __init__(self, browser: FakeCdpBrowser) -> None:
            self.chromium = self
            self.browser = browser
            self.connected_urls: list[str] = []
            self.stopped = False
            self.attempts = 0

        def connect_over_cdp(self, url: str) -> FakeCdpBrowser:
            self.connected_urls.append(url)
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("connection refused")
            return self.browser

        def stop(self) -> None:
            self.stopped = True

    context = FakeChromeContext()
    runtime = RecoveringCdpRuntime(FakeCdpBrowser(context))
    started_urls: list[str] = []
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )
    monkeypatch.setattr(
        article_session,
        "_start_cdp_browser",
        lambda _config, first_login_url: started_urls.append(first_login_url),
    )

    with article_session.BrowserArticleSession(config=config) as session:
        page = session.fetch(
            "https://seekingalpha.com/article/attached-aapl",
            EXPECTED_ARTICLE_TIMEOUT_SECONDS,
        )

    assert runtime.connected_urls == [
        "http://127.0.0.1:9222",
        "http://127.0.0.1:9222",
    ]
    assert started_urls == ["https://seekingalpha.com/account/login"]
    assert page.url == "https://seekingalpha.com/article/attached-aapl"
    assert runtime.stopped is True


def test_fetch_with_browser_session_uses_cdp_without_saved_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _config(
        article_fetch_mode="browser",
        article_browser_cdp_url="http://127.0.0.1:9222",
    )
    context = FakeChromeContext()
    browser = FakeCdpBrowser(context)
    runtime = FakePlaywrightRuntime(browser)
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )

    page = article_session.fetch_with_browser_session(
        "https://seekingalpha.com/article/attached-aapl",
        config=config,
        timeout_seconds=EXPECTED_ARTICLE_TIMEOUT_SECONDS,
    )

    assert runtime.connected_urls == ["http://127.0.0.1:9222"]
    assert page.url == "https://seekingalpha.com/article/attached-aapl"
    assert "positive earnings guidance" in page.text
    assert context.closed is False
    assert context.pages[0].closed is True


def test_visible_browser_session_verifies_first_email_article_before_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        article_fetch_mode="browser",
        article_browser_state_dir=tmp_path / "sessions",
        article_browser_cdp_url="http://127.0.0.1:9222",
        article_browser_headless=False,
    )
    context = FakeChromeContext()
    browser = FakeCdpBrowser(context)
    runtime = FakePlaywrightRuntime(browser)
    monkeypatch.setattr(
        article_session,
        "_playwright_sync_api",
        lambda: FakePlaywrightApi(runtime),
    )
    monkeypatch.setattr("builtins.input", lambda: "")

    with article_session.BrowserArticleSession(config=config) as session:
        page = session.fetch(
            "https://seekingalpha.com/article/first-link",
            EXPECTED_ARTICLE_TIMEOUT_SECONDS,
        )

    assert page.url == "https://seekingalpha.com/article/first-link"
    assert context.pages[0].visited_urls == [
        "https://seekingalpha.com/account/login",
        "https://seekingalpha.com/article/first-link",
        "https://seekingalpha.com/article/first-link",
    ]


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


def test_mailbox_sync_defers_mark_seen_until_ingest_persists(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mailbox_mark_seen"] = True
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    client = FakeImapClient(
        {
            "1": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha AAPL",
                body="AAPL analyst article",
            )
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

    assert result.selected_uids == ("1",)
    assert client.stored == []


def test_ingest_marks_mailbox_seen_only_after_outputs_are_written(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mailbox_mark_seen"] = True
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    client = FakeImapClient(
        {
            "1": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha AAPL",
                body="AAPL analyst article",
            )
        }
    )

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        imap_factory=lambda _config: client,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
    )

    assert result.mailbox_sync["selected_uids"] == ["1"]
    assert client.stored == [("1", "+FLAGS", r"(\Seen)")]
    assert (tmp_path / "research" / "data" / "parquet" / "subscription_emails.parquet").exists()


def test_mailbox_sync_limits_to_latest_configured_messages(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail", max_emails=2)
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    client = FakeImapClient(
        {
            "1": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Old Seeking Alpha AAPL",
                body="AAPL analyst article",
            ),
            "2": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Newer Seeking Alpha MSFT",
                body="MSFT analyst article",
            ),
            "3": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Newest Seeking Alpha NVDA",
                body="NVDA analyst article",
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

    fetched_uids = [args[0] for args in client.fetched]
    assert result.matched == EXPECTED_MAILBOX_LIMIT_MATCHED
    assert result.attempted == EXPECTED_MAILBOX_ATTEMPTED
    assert result.saved == EXPECTED_MAILBOX_LIMIT_SAVED
    assert len(result.saved_paths) == EXPECTED_MAILBOX_LIMIT_SAVED
    assert len(result.selected_paths) == EXPECTED_MAILBOX_LIMIT_SAVED
    assert result.limited is True
    assert fetched_uids == ["2", "3"]


def test_mailbox_include_seen_removes_unseen_search_filter(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    config = SubscriptionEmailConfig(
        **{
            **_config().__dict__,
            "mode": "gmail",
            "input_path": mailbox,
            "mailbox_search": "UNSEEN",
            "mailbox_unseen_only": False,
        }
    )
    client = FakeImapClient(
        {
            "1": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha AAPL",
                body="AAPL analyst article",
            )
        }
    )

    sync_mailbox_emails(
        config,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
        imap_factory=lambda _config: client,
    )

    assert client.search_queries == ["ALL"]


def test_mailbox_include_seen_removes_parenthesized_unseen_search_filter(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    config = SubscriptionEmailConfig(
        **{
            **_config().__dict__,
            "mode": "gmail",
            "input_path": mailbox,
            "mailbox_search": '(UNSEEN FROM "alerts@email.seekingalpha.com") is:unread',
            "mailbox_unseen_only": False,
        }
    )
    client = FakeImapClient(
        {
            "1": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha AAPL",
                body="AAPL analyst article",
            )
        }
    )

    sync_mailbox_emails(
        config,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
        imap_factory=lambda _config: client,
    )

    assert client.search_queries == ['(FROM "alerts@email.seekingalpha.com")']


def test_mailbox_sync_selects_existing_duplicate_for_scoped_processing(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    raw = _message_bytes(
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha duplicate MSFT",
        body="MSFT analyst article",
    )
    existing_path = mailbox / f"{hashlib.sha256(raw).hexdigest()[:24]}.eml"
    existing_path.write_bytes(raw)
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail", max_emails=1)
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    client = FakeImapClient({"9": raw})

    result = sync_mailbox_emails(
        config,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
        imap_factory=lambda _config: client,
    )

    assert result.saved == 0
    assert result.skipped == EXPECTED_MAILBOX_SAVED
    assert result.saved_paths == ()
    assert result.selected_paths == (existing_path,)


def test_mailbox_preview_does_not_save_messages(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail", max_emails=1)
    config = load_subscription_email_config(config_path, repo_root=tmp_path)
    client = FakeImapClient(
        {
            "7": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha MSFT preview",
                body="MSFT analyst article. https://seekingalpha.com/article/preview",
            )
        }
    )

    result = preview_mailbox_emails(
        config,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
        imap_factory=lambda _config: client,
    )

    assert result.matched == EXPECTED_MAILBOX_SAVED
    assert result.sampled == EXPECTED_MAILBOX_SAVED
    assert result.messages[0]["allowed_sender"] is True
    assert result.messages[0]["subject"] == "Seeking Alpha MSFT preview"
    assert list(mailbox.glob("*.eml")) == []
    assert client.fetched[0][1] == "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"


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
        article_login_preflight=_confirmed_article_login_preflight,
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


def test_monitor_marks_remote_mail_seen_after_successful_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mailbox_mark_seen"] = True
    config_path.write_text(json.dumps(payload), encoding="utf-8")
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
    assert result.ingest is not None
    assert result.ingest["mailbox_marked_seen"] == EXPECTED_MAILBOX_SAVED
    assert client.stored == [("101", "+FLAGS", r"(\Seen)")]


def test_monitor_processes_saved_mail_after_partial_mailbox_fetch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(tmp_path, input_path=mailbox, mode="gmail")
    client = PartialFailureImapClient(
        {
            "101": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha article on MSFT",
                body="MSFT analyst article.",
            ),
            "102": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha article on AAPL",
                body="AAPL analyst article.",
            ),
        },
        fail_uids={"102"},
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
    assert result.mailbox_sync.saved == 1
    assert result.mailbox_sync.failed == 1
    assert result.ingest is not None
    assert result.ingest["event_rows"] == 1


def test_import_syncs_gmail_emails_then_analyzes_real_article_links(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(
        tmp_path,
        input_path=mailbox,
        mode="gmail",
        follow_article_links=True,
    )
    article_url = "https://seekingalpha.com/article/real-msft"
    client = FakeImapClient(
        {
            "201": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha MSFT analyst article",
                body=f"MSFT analyst article is available here: {article_url}",
            )
        }
    )
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Authenticated Seeking Alpha article",
            text=(
                "MSFT receives a bullish analyst upgrade with positive revenue "
                "guidance and earnings momentum."
            ),
        )

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
        article_login_preflight=_confirmed_article_login_preflight,
        imap_factory=lambda _config: client,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
    )

    events = pd.read_parquet(
        tmp_path / "research" / "data" / "parquet" / "subscription_emails.parquet"
    )
    news = pd.read_parquet(tmp_path / "research" / "data" / "parquet" / "news_rss.parquet")
    summary = json.loads((tmp_path / "summary" / "subscription-email-ingest.json").read_text())

    assert result.mailbox_sync is not None
    assert result.mailbox_sync["mode"] == "gmail"
    assert result.mailbox_sync["saved"] == EXPECTED_MAILBOX_SAVED
    assert len(result.mailbox_sync["selected_paths"]) == EXPECTED_MAILBOX_SAVED
    assert len(list(mailbox.glob("*.eml"))) == EXPECTED_MAILBOX_SAVED
    assert fetched_urls == [article_url]
    assert events.iloc[0]["linked_content_status"] == "article_analyzed"
    assert "Linked content thesis" in events.iloc[0]["linked_content_summary"]
    assert "Context: title_plus_browser_rendered_text" in events.iloc[0][
        "linked_content_summary"
    ]
    assert "Linked content thesis" in news.iloc[0]["summary"]
    assert summary["mode"] == "gmail"
    assert summary["mailbox_sync"]["saved"] == EXPECTED_MAILBOX_SAVED
    assert summary["linked_content"]["succeeded"] == EXPECTED_MAILBOX_SAVED


def test_gmail_import_processes_only_newly_saved_mailbox_files(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "old.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha old AAPL article",
        body="AAPL old analyst article. https://seekingalpha.com/article/old",
    )
    config_path = _config_path(
        tmp_path,
        input_path=mailbox,
        mode="gmail",
        follow_article_links=True,
        max_emails=1,
        max_article_links=1,
    )
    new_url = "https://seekingalpha.com/article/new-msft"
    client = FakeImapClient(
        {
            "301": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha new MSFT article",
                body=f"MSFT new analyst article. {new_url}",
            )
        }
    )
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Authenticated article",
            text="MSFT receives a bullish analyst upgrade with positive earnings guidance.",
        )

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
        article_login_preflight=_confirmed_article_login_preflight,
        imap_factory=lambda _config: client,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
    )
    events = pd.read_parquet(
        tmp_path / "research" / "data" / "parquet" / "subscription_emails.parquet"
    )

    assert result.processed_emails == EXPECTED_MAILBOX_SAVED
    assert result.event_rows == EXPECTED_MAILBOX_SAVED
    assert fetched_urls == [new_url]
    assert events["ticker"].to_list() == ["MSFT"]
    assert "AAPL" not in events["ticker"].to_list()


def test_gmail_import_processes_selected_duplicate_without_whole_folder(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    _write_message(
        mailbox / "old-aapl.eml",
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha old AAPL article",
        body="AAPL old analyst article. https://seekingalpha.com/article/old",
    )
    new_url = "https://seekingalpha.com/article/current-msft"
    raw = _message_bytes(
        sender="alerts@email.seekingalpha.com",
        subject="Seeking Alpha current MSFT article",
        body=f"MSFT current analyst article. {new_url}",
    )
    duplicate_path = mailbox / f"{hashlib.sha256(raw).hexdigest()[:24]}.eml"
    duplicate_path.write_bytes(raw)
    config_path = _config_path(
        tmp_path,
        input_path=mailbox,
        mode="gmail",
        follow_article_links=True,
        max_emails=1,
        max_article_links=1,
    )
    client = FakeImapClient({"401": raw})
    fetched_urls: list[str] = []

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Authenticated article",
            text="MSFT receives a bullish analyst upgrade with positive earnings guidance.",
        )

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
        article_login_preflight=_confirmed_article_login_preflight,
        imap_factory=lambda _config: client,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
    )
    events = pd.read_parquet(
        tmp_path / "research" / "data" / "parquet" / "subscription_emails.parquet"
    )

    assert result.mailbox_sync is not None
    assert result.mailbox_sync["saved"] == 0
    assert result.mailbox_sync["skipped"] == EXPECTED_MAILBOX_SAVED
    assert len(result.mailbox_sync["selected_paths"]) == EXPECTED_MAILBOX_SAVED
    assert result.processed_emails == EXPECTED_MAILBOX_SAVED
    assert fetched_urls == [new_url]
    assert events["ticker"].to_list() == ["MSFT"]


def test_gmail_ingest_preflight_uses_selected_email_article_link(
    tmp_path: Path,
) -> None:
    mailbox = tmp_path / "mail"
    config_path = _config_path(
        tmp_path,
        input_path=mailbox,
        mode="gmail",
        follow_article_links=True,
        article_login_preflight_required=True,
        article_login_preflight_services=("seeking_alpha",),
    )
    article_url = "https://seekingalpha.com/article/verified-msft?token=email-token"
    client = FakeImapClient(
        {
            "501": _message_bytes(
                sender="alerts@email.seekingalpha.com",
                subject="Seeking Alpha MSFT analyst article",
                body=f"MSFT analyst article is available here: {article_url}",
            )
        }
    )
    preflight_links: list[str] = []
    fetched_urls: list[str] = []

    def preflight(
        active_config: SubscriptionEmailConfig,
        records: list[EmailRecord],
    ) -> SubscriptionEmailConfig:
        assert len(records) == EXPECTED_MAILBOX_SAVED
        preflight_links.extend(
            linked_content.allowed_article_fetch_links(records[0], active_config)
        )
        return replace(active_config, article_login_preflight_confirmed=True)

    def fetcher(url: str, _timeout_seconds: int) -> FetchedArticle:
        fetched_urls.append(url)
        return FetchedArticle(
            url=url,
            status_code=200,
            title="Authenticated article",
            text="MSFT receives a bullish analyst upgrade with positive earnings guidance.",
        )

    result = ingest_subscription_emails(
        config_path=config_path,
        repo_root=tmp_path,
        clock=lambda: FETCHED_AT,
        summary_root=tmp_path / "summary",
        article_fetcher=fetcher,
        article_login_preflight=preflight,
        imap_factory=lambda _config: client,
        env={
            "SUBSCRIPTION_EMAIL_USERNAME": "user@example.test",
            "SUBSCRIPTION_EMAIL_PASSWORD": "app-password",
        },
    )

    assert preflight_links == [article_url]
    assert fetched_urls == [article_url]
    assert result.linked_content_attempted == 1
    assert result.linked_content_succeeded == 1


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
    max_emails: int = 10,
    max_article_links: int = 5,
    article_fetch_mode: str = "auto",
    article_browser_state_dir: Path | None = None,
    article_analysis_cache_path: Path | None = None,
    article_browser_channel: str = "chrome",
    article_browser_headless: bool = True,
    article_browser_cdp_url: str | None = None,
    article_login_preflight_required: bool = False,
    article_login_preflight_services: tuple[str, ...] = (),
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
        "mailbox_unseen_only": True,
        "mailbox_max_messages": max_emails,
        "mailbox_mark_seen": False,
        "follow_article_links": follow_article_links,
        "article_link_domains": ["seekingalpha.com"],
        "article_max_total_per_run": max_article_links,
        "article_fetch_mode": article_fetch_mode,
        "article_browser_channel": article_browser_channel,
        "article_browser_headless": article_browser_headless,
        "article_login_preflight_required": article_login_preflight_required,
        "article_login_preflight_services": list(article_login_preflight_services),
    }
    if article_browser_state_dir is not None:
        payload["article_browser_state_dir"] = str(article_browser_state_dir)
    if article_analysis_cache_path is not None:
        payload["article_analysis_cache_path"] = str(article_analysis_cache_path)
    if article_browser_cdp_url is not None:
        payload["article_browser_cdp_url"] = article_browser_cdp_url
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


def _confirmed_article_login_preflight(
    config: SubscriptionEmailConfig,
    _records: list[EmailRecord],
) -> SubscriptionEmailConfig:
    return replace(config, article_login_preflight_confirmed=True)


def _config(
    *,
    follow_article_links: bool = False,
    article_max_total_per_run: int = 5,
    article_fetch_mode: str = "auto",
    article_browser_state_dir: Path | None = None,
    article_analysis_cache_path: Path | None = None,
    article_browser_channel: str = "chrome",
    article_browser_headless: bool = True,
    article_browser_cdp_url: str | None = None,
    article_browser_wait_seconds: int = 5,
    article_login_preflight_required: bool = False,
    article_login_preflight_services: tuple[str, ...] = (),
    article_login_preflight_confirmed: bool = False,
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
        article_max_total_per_run=article_max_total_per_run,
        article_fetch_mode=article_fetch_mode,
        article_browser_state_dir=article_browser_state_dir,
        article_analysis_cache_path=article_analysis_cache_path,
        article_browser_channel=article_browser_channel,
        article_browser_headless=article_browser_headless,
        article_browser_cdp_url=article_browser_cdp_url,
        article_browser_wait_seconds=article_browser_wait_seconds,
        article_login_preflight_required=article_login_preflight_required,
        article_login_preflight_services=article_login_preflight_services,
        article_login_preflight_confirmed=article_login_preflight_confirmed,
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
        self.fetched: list[tuple[str, ...]] = []
        self.search_queries: list[str] = []

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
            self.search_queries.append(" ".join(args))
            payload = b" ".join(uid.encode("ascii") for uid in self.messages)
            return "OK", [payload]
        if command == "FETCH":
            uid = str(args[0])
            self.fetched.append(args)
            return "OK", [(b"BODY[]", self.messages[uid])]
        if command == "STORE":
            self.stored.append(args)
            return "OK", []
        raise AssertionError(f"unexpected IMAP command: {command}")

    def logout(self) -> object:
        return "OK"


class PartialFailureImapClient(FakeImapClient):
    def __init__(self, messages: dict[str, bytes], *, fail_uids: set[str]) -> None:
        super().__init__(messages)
        self.fail_uids = fail_uids

    def uid(
        self,
        command: str,
        *args: str,
    ) -> tuple[str, list[bytes | tuple[bytes, bytes]]]:
        if command == "FETCH" and str(args[0]) in self.fail_uids:
            raise RuntimeError(f"simulated fetch failure for uid {args[0]}")
        return super().uid(command, *args)


class FakePlaywrightApi:
    def __init__(self, runtime: FakePlaywrightRuntime) -> None:
        self.runtime = runtime

    def sync_playwright(self) -> FakePlaywrightManager:
        return FakePlaywrightManager(self.runtime)


class FakePlaywrightManager:
    def __init__(self, runtime: FakePlaywrightRuntime) -> None:
        self.runtime = runtime

    def start(self) -> FakePlaywrightRuntime:
        return self.runtime


class FakePlaywrightRuntime:
    def __init__(self, browser: FakeCdpBrowser) -> None:
        self.chromium = self
        self.browser = browser
        self.connected_urls: list[str] = []
        self.stopped = False

    def connect_over_cdp(self, url: str) -> FakeCdpBrowser:
        self.connected_urls.append(url)
        return self.browser

    def stop(self) -> None:
        self.stopped = True


class FakeCdpBrowser:
    def __init__(self, context: FakeChromeContext) -> None:
        self.contexts = [context]


class FakeChromeContext:
    def __init__(self) -> None:
        self.pages: list[FakeChromePage] = []
        self.closed = False

    def new_page(self) -> FakeChromePage:
        page = FakeChromePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True


class FakeChromePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.visited_urls: list[str] = []
        self.closed = False

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> FakeChromeResponse:
        del wait_until, timeout
        self.url = url
        self.visited_urls.append(url)
        return FakeChromeResponse()

    def wait_for_timeout(self, timeout: int) -> None:
        del timeout

    def content(self) -> str:
        return (
            "<html><title>AAPL article</title><p>AAPL receives bullish analyst "
            "coverage with positive earnings guidance.</p></html>"
        )

    def close(self) -> None:
        self.closed = True


class FakeChromeResponse:
    status = 200
