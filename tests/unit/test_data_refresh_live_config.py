from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_refresh.live_config import load_refresh_config

EXPECTED_WORKERS = 2
EXPECTED_RUNTIME_MAX_TICKERS = 250
EXPECTED_COMPANY_FACTS_MAX_AGE_DAYS = 14
EXPECTED_FORM4_MAX_AGE_DAYS = 2
EXPECTED_13F_MAX_AGE_DAYS = 60
EXPECTED_NEWS_MAX_AGE_MINUTES = 20
EXPECTED_EMAIL_MAX_AGE_MINUTES = 5


def test_load_refresh_config_parses_live_inputs(tmp_path: Path) -> None:
    cusip_map = tmp_path / "cusips.json"
    cusip_map.write_text("{}", encoding="utf-8")
    config_path = tmp_path / "refresh.json"
    config_path.write_text(
        json.dumps(
            {
                "start": "2021-01-01",
                "end": "2025-12-31",
                "datasets": ["prices_daily", "news_rss"],
                "tickers": ["AAPL", "MSFT"],
                "rss_feeds": ["Example,AAPL,https://example.com/rss.xml"],
                "filer_ciks": ["0001067983"],
                "cusip_map": "cusips.json",
                "activity_alerts_csv": "alerts.csv",
                "subscription_email_config": "subscription-email.json",
                "sec_user_agent": "Trading Agency admin@example.com",
                "workers": EXPECTED_WORKERS,
                "include_etfs": False,
                "refresh": True,
                "dry_run": True,
                "market_data_provider": "alpaca",
                "market_data_feed": "iex",
                "market_data_adjustment": "all",
                "market_data_base_url": "https://data.alpaca.markets",
                "massive_base_url": "https://api.polygon.io",
                "stock_trades_start": "2025-12-30",
                "stock_trades_end": "2025-12-31",
                "extraction_mode": "incremental",
                "sec_company_facts_max_age_days": EXPECTED_COMPANY_FACTS_MAX_AGE_DAYS,
                "sec_form4_max_age_days": EXPECTED_FORM4_MAX_AGE_DAYS,
                "sec_13f_max_age_days": EXPECTED_13F_MAX_AGE_DAYS,
                "news_rss_max_age_minutes": EXPECTED_NEWS_MAX_AGE_MINUTES,
                "subscription_email_max_age_minutes": EXPECTED_EMAIL_MAX_AGE_MINUTES,
                "runtime_signals": ["options_anomaly", "activity_alerts"],
                "runtime_universe": "active",
                "runtime_max_tickers": 250,
            }
        ),
        encoding="utf-8",
    )

    config = load_refresh_config(config_path, repo_root=tmp_path)

    assert config.start is not None
    assert config.start.isoformat() == "2021-01-01"
    assert config.datasets == ("prices_daily", "news_rss")
    assert config.tickers == ("AAPL", "MSFT")
    assert config.cusip_map == cusip_map
    assert config.activity_alerts_csv == tmp_path / "alerts.csv"
    assert config.subscription_email_config == tmp_path / "subscription-email.json"
    assert config.workers == EXPECTED_WORKERS
    assert config.include_etfs is False
    assert config.refresh is True
    assert config.dry_run is True
    assert config.market_data_provider == "alpaca"
    assert config.market_data_feed == "iex"
    assert config.massive_base_url == "https://api.polygon.io"
    assert config.stock_trades_start is not None
    assert config.stock_trades_start.isoformat() == "2025-12-30"
    assert config.stock_trades_end is not None
    assert config.stock_trades_end.isoformat() == "2025-12-31"
    assert config.extraction_mode == "incremental"
    assert config.sec_company_facts_max_age_days == EXPECTED_COMPANY_FACTS_MAX_AGE_DAYS
    assert config.sec_form4_max_age_days == EXPECTED_FORM4_MAX_AGE_DAYS
    assert config.sec_13f_max_age_days == EXPECTED_13F_MAX_AGE_DAYS
    assert config.news_rss_max_age_minutes == EXPECTED_NEWS_MAX_AGE_MINUTES
    assert config.subscription_email_max_age_minutes == EXPECTED_EMAIL_MAX_AGE_MINUTES
    assert config.runtime_signals == ("options_anomaly", "activity_alerts")
    assert config.runtime_universe == "active"
    assert config.runtime_max_tickers == EXPECTED_RUNTIME_MAX_TICKERS


def test_load_refresh_config_rejects_unknown_dataset(tmp_path: Path) -> None:
    config_path = tmp_path / "refresh.json"
    config_path.write_text('{"datasets": ["bad"]}', encoding="utf-8")

    with pytest.raises(ValueError, match="unknown dataset"):
        load_refresh_config(config_path, repo_root=tmp_path)


def test_load_refresh_config_rejects_wrong_feed_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "refresh.json"
    config_path.write_text('{"rss_feeds": "bad"}', encoding="utf-8")

    with pytest.raises(TypeError, match="rss_feeds"):
        load_refresh_config(config_path, repo_root=tmp_path)


def test_load_refresh_config_rejects_unknown_extraction_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "refresh.json"
    config_path.write_text('{"extraction_mode": "forever"}', encoding="utf-8")

    with pytest.raises(ValueError, match="extraction_mode"):
        load_refresh_config(config_path, repo_root=tmp_path)
