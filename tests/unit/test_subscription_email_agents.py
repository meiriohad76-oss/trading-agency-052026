from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pandas as pd
import pytest
from subscription_email.calibration import write_subscription_email_calibration
from subscription_email.classifiers import classify_subscription_emails
from subscription_email.config import SubscriptionEmailConfig, load_subscription_email_config
from subscription_email.ingest import ingest_subscription_emails
from subscription_email.linked_content import FetchedArticle, html_to_text
from subscription_email.parser import parse_email_file, read_local_emails
from subscription_email.types import EmailRecord

FETCHED_AT = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
EXPECTED_NEWS_ROWS = 2
EXPECTED_EVENT_ROWS = 3
EXPECTED_SOURCE_REFS = 2
EXPECTED_ARTICLE_TIMEOUT_SECONDS = 15


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
    assert "Linked content analysis" in news.iloc[0]["summary"]
    assert events.iloc[0]["linked_content_status"] == "article_analyzed"
    assert summary["linked_content"]["succeeded"] == 1
    assert "analyst upgrade" not in json.dumps(summary)
    assert "Paid article title" not in json.dumps(summary)


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
) -> Path:
    path = tmp_path / "subscription-email.json"
    path.write_text(
        json.dumps(
            {
                "mode": "local_eml",
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
                "follow_article_links": follow_article_links,
                "article_link_domains": ["seekingalpha.com"],
            }
        ),
        encoding="utf-8",
    )
    return path


def _config() -> SubscriptionEmailConfig:
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
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "agency@example.test"
    message["Subject"] = subject
    message["Date"] = format_datetime(received_at)
    message["Message-ID"] = f"<{path.name}@example.test>"
    message.set_content(body, subtype=subtype)
    path.write_bytes(message.as_bytes())
