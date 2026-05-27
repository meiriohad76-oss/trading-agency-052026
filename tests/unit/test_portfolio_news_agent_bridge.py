from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from agency.runtime.portfolio_news_agent_bridge import (
    ensure_portfolio_news_agent_agency_config,
    export_portfolio_news_agent_events,
    load_portfolio_news_agent_status,
    portfolio_news_agent_run_config_path,
)


def test_portfolio_news_agent_status_uses_external_sqlite_db(tmp_path: Path) -> None:
    root = _agent_root(tmp_path)
    _write_agent_config(root)
    _write_agent_db(root / "data" / "portfolio_news.db")

    status = load_portfolio_news_agent_status(root=root, endpoint_checker=lambda _url: True)

    assert status["source_agent"] == "portfolio_news_agent"
    assert status["status_label"] == "SA email evidence analyzed"
    assert status["status_class"] == "pass"
    assert status["processed_email_count"] == 2
    assert status["article_links_found"] == 2
    assert status["linked_content_succeeded"] == 2
    assert status["summary_count"] == 1
    assert status["refresh_button_label"] == "Open SA browser and verify login"
    assert status["continue_button_label"] == "Analyze unread SA emails"
    assert status["browser_ready"] is True


def test_portfolio_news_agent_status_reports_active_article_processing(tmp_path: Path) -> None:
    root = _agent_root(tmp_path)
    _write_agent_config(root)
    db_path = root / "data" / "portfolio_news.db"
    _write_agent_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'running', finished_at = NULL
            WHERE id = 1
            """
        )
        connection.execute(
            """
            UPDATE gmail_article_links
            SET status = 'processing',
                status_detail = 'Opening article and running LLM analysis',
                last_attempt_at = '2026-05-27T12:04:20.100000+00:00'
            WHERE id = 2
            """
        )
        connection.commit()

    status = load_portfolio_news_agent_status(root=root, endpoint_checker=lambda _url: True)

    assert status["status_label"] == "Portfolio News Agent running"
    assert status["linked_content_processing"] == 1
    assert status["linked_content_attempted"] == 2
    assert status["current_article_url"] == "https://seekingalpha.com/article/market"
    assert status["current_article_status_detail"] == "Opening article and running LLM analysis"
    assert status["current_action_label"] == (
        "Opening/analyzing Seeking Alpha article: https://seekingalpha.com/article/market"
    )
    assert status["progress_label"] == "1/2 SA article links analyzed (1 opening/analyzing)"


def test_portfolio_news_agent_status_reports_browser_not_connected(tmp_path: Path) -> None:
    root = _agent_root(tmp_path)
    _write_agent_config(root)

    status = load_portfolio_news_agent_status(root=root, endpoint_checker=lambda _url: False)

    assert status["status_label"] == "SA browser login session not connected"
    assert status["status_class"] == "warn"
    assert "dedicated Chrome/Edge session is not reachable" in str(status["detail"])
    assert status["login_required"] == 0


def test_portfolio_news_agent_status_explains_article_access_failures(
    tmp_path: Path,
) -> None:
    root = _agent_root(tmp_path)
    _write_agent_config(root)
    db_path = root / "data" / "portfolio_news.db"
    _write_agent_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE gmail_article_links SET status = 'failed_access' WHERE id = 2"
        )
        connection.commit()

    status = load_portfolio_news_agent_status(root=root, endpoint_checker=lambda _url: False)

    assert status["status_label"] == "SA article access needs login or challenge"
    assert status["status_class"] == "warn"
    assert "failed at article access" in str(status["detail"])
    assert status["linked_content_failed"] == 1
    assert "Analyze unread SA emails" in str(status["next_action"])


def test_agency_config_overlay_disables_telegram_without_mutating_user_config(
    tmp_path: Path,
) -> None:
    root = _agent_root(tmp_path)
    _write_agent_config(root, telegram_enabled=True)

    run_config = ensure_portfolio_news_agent_agency_config(root=root)

    assert run_config == portfolio_news_agent_run_config_path(root)
    assert (root / "config.yaml").read_text(encoding="utf-8").count("telegram_enabled: true") == 1
    text = run_config.read_text(encoding="utf-8")
    assert "telegram_enabled: false" in text
    assert "database_path: \"data/portfolio_news.db\"" in text
    assert "commodity_exposure_overrides:" in text


def test_export_portfolio_news_agent_events_writes_subscription_email_dataset(
    tmp_path: Path,
) -> None:
    root = _agent_root(tmp_path)
    _write_agent_config(root)
    _write_agent_db(root / "data" / "portfolio_news.db")
    parquet_path = tmp_path / "subscription_emails.parquet"
    manifest_path = tmp_path / "subscription_emails.json"
    summary_root = tmp_path / "summary"

    result = export_portfolio_news_agent_events(
        root=root,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        summary_root=summary_root,
    )

    assert result["status"] == "exported"
    assert result["event_rows"] == 1
    frame = pd.read_parquet(parquet_path)
    row = frame.iloc[0].to_dict()
    assert row["ticker"] == "AAPL"
    assert row["service"] == "seeking_alpha"
    assert row["linked_content_status"] == "article_analyzed"
    assert row["linked_content_direction"] == "BULLISH"
    assert "Margins improved" in row["linked_content_thesis"]
    assert row["timestamp_as_of"] == "2026-05-27T12:02:10+00:00"
    assert row["source_refs"][0]["service"] == "seeking_alpha"
    assert row["source_refs"][0]["source_url"] == "https://seekingalpha.com/article/aapl"
    assert manifest_path.exists()
    assert (summary_root / "subscription-email-ingest.json").exists()


def _agent_root(tmp_path: Path) -> Path:
    root = tmp_path / "email news agent"
    (root / "data").mkdir(parents=True)
    return root


def _write_agent_config(root: Path, *, telegram_enabled: bool = False) -> None:
    (root / "config.yaml").write_text(
        "\n".join(
            [
                'portfolio_file: "portfolio.xlsx"',
                'gmail_sender: "account@seekingalpha.com"',
                'database_path: "data/portfolio_news.db"',
                'browser_profile_dir: "data/sa-browser-profile"',
                'browser_channel: "chrome"',
                'browser_cdp_url: "http://127.0.0.1:9222"',
                'openai_model: "gpt-5-nano"',
                'prompt_version: "v1"',
                f"telegram_enabled: {str(telegram_enabled).lower()}",
                "commodity_exposure_overrides:",
                "  gold: []",
            ]
        ),
        encoding="utf-8",
    )


def _write_agent_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT,
              finished_at TEXT,
              mode TEXT,
              emails_found INTEGER,
              articles_processed INTEGER,
              summaries_created INTEGER,
              status TEXT,
              error TEXT
            );
            CREATE TABLE gmail_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              gmail_message_id TEXT,
              sender TEXT,
              subject TEXT,
              received_at TEXT
            );
            CREATE TABLE articles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              canonical_url TEXT,
              source_url TEXT,
              headline TEXT,
              article_date TEXT,
              content_hash TEXT
            );
            CREATE TABLE gmail_article_links (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              gmail_message_id INTEGER,
              portfolio_import_id INTEGER,
              prompt_version TEXT,
              source_url TEXT,
              canonical_url TEXT,
              article_id INTEGER,
              status TEXT,
              status_detail TEXT,
              first_seen_at TEXT,
              last_attempt_at TEXT
            );
            CREATE TABLE article_asset_summaries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              article_id INTEGER,
              gmail_message_id INTEGER,
              gmail_article_link_id INTEGER,
              portfolio_import_id INTEGER,
              symbol TEXT,
              company_name TEXT,
              inferred_sentiment TEXT,
              theme TEXT,
              action_relevance TEXT,
              short_summary TEXT,
              confidence REAL,
              llm_model TEXT,
              prompt_version TEXT,
              created_at TEXT
            );
            INSERT INTO runs (
              started_at, finished_at, mode, emails_found, articles_processed,
              summaries_created, status
            )
            VALUES (
              '2026-05-27T12:00:00.100000+00:00', '2026-05-27T12:03:00.200000+00:00',
              'once', 2, 2, 1, 'success'
            );
            INSERT INTO gmail_messages (
              id, gmail_message_id, sender, subject, received_at
            )
            VALUES (
              1, 'gmail-1', 'account@seekingalpha.com',
              'Seeking Alpha AAPL article', '2026-05-27T11:58:00.300000+00:00'
            );
            INSERT INTO articles (
              id, canonical_url, source_url, headline, article_date, content_hash
            )
            VALUES (
              1, 'https://seekingalpha.com/article/aapl',
              'https://email.seekingalpha.com/aapl', 'AAPL margins improve',
              '2026-05-27T11:59:00.400000+00:00', 'hash-aapl'
            );
            INSERT INTO gmail_article_links (
              id, gmail_message_id, portfolio_import_id, prompt_version, source_url,
              canonical_url, article_id, status, last_attempt_at
            )
            VALUES
              (
                1, 1, 1, 'v1', 'https://seekingalpha.com/article/aapl',
                'https://seekingalpha.com/article/aapl', 1,
                'processed_relevant', '2026-05-27T12:02:00.500000+00:00'
              ),
              (
                2, 1, 1, 'v1', 'https://seekingalpha.com/article/market',
                'https://seekingalpha.com/article/market', NULL,
                'irrelevant_seen', '2026-05-27T12:02:30.600000+00:00'
              );
            INSERT INTO article_asset_summaries (
              article_id, gmail_message_id, gmail_article_link_id, portfolio_import_id,
              symbol, company_name, inferred_sentiment, theme, action_relevance,
              short_summary, confidence, llm_model, prompt_version, created_at
            )
            VALUES (
              1, 1, 1, 1, 'AAPL', 'Apple Inc.', 'bullish', 'bullish',
              'thesis_change', 'Margins improved after services growth.', 0.82,
              'gpt-5-nano', 'v1', '2026-05-27T12:02:10.700000+00:00'
            );
            """
        )
        connection.commit()
