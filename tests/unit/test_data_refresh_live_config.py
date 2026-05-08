from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_refresh.live_config import load_refresh_config

EXPECTED_WORKERS = 2


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
                "sec_user_agent": "Trading Agency admin@example.com",
                "workers": EXPECTED_WORKERS,
                "include_etfs": False,
                "refresh": True,
                "dry_run": True,
                "market_data_provider": "alpaca",
                "market_data_feed": "iex",
                "market_data_adjustment": "all",
                "market_data_base_url": "https://data.alpaca.markets",
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
    assert config.workers == EXPECTED_WORKERS
    assert config.include_etfs is False
    assert config.refresh is True
    assert config.dry_run is True
    assert config.market_data_provider == "alpaca"
    assert config.market_data_feed == "iex"


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
