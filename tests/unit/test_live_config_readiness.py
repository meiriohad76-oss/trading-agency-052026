from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agency.app import create_app
from agency.runtime.live_config_readiness import load_live_config_readiness

HTTP_OK = 200


def test_live_config_readiness_blocks_missing_alpaca_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["prices_daily"],
            "tickers": ["AAPL"],
            "market_data_provider": "alpaca",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert readiness["state"] == "blocked"
    assert readiness["blocker_count"] == 1
    assert _check(readiness, "Market data")["status"] == "BLOCK"


def test_live_config_readiness_passes_configured_live_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    cusip_map = tmp_path / "cusips.json"
    cusip_map.write_text('{"037833100": "AAPL"}', encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["prices_daily", "sec_13f", "news_rss"],
            "tickers": ["AAPL"],
            "rss_feeds": ["SEC,https://example.test/rss"],
            "filer_ciks": ["0001067983"],
            "cusip_map": str(cusip_map),
            "sec_user_agent": "Trading Agency test@example.com",
            "market_data_provider": "alpaca",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert readiness["state"] == "ready"
    assert readiness["ready"] is True
    assert readiness["blocker_count"] == 0


def test_live_config_readiness_warns_for_yfinance_current_date_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["prices_daily"],
            "tickers": ["AAPL"],
            "market_data_provider": "yfinance",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert readiness["state"] == "warning"
    assert readiness["warning_count"] == 1
    assert _check(readiness, "Market data")["status"] == "WARN"


def test_live_config_readiness_warns_for_inferred_options_chains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["options_chains"],
            "tickers": ["AAPL"],
            "market_data_provider": "alpaca",
        },
    )
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    readiness = load_live_config_readiness(config_path)

    assert readiness["runtime_signal_count"] == 0
    assert _check(readiness, "Options chains")["status"] == "WARN"


def test_live_config_readiness_blocks_stock_trades_without_massive_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["stock_trades"],
            "tickers": ["AAPL"],
            "market_data_provider": "yfinance",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert readiness["state"] == "blocked"
    assert _check(readiness, "Massive market-flow")["status"] == "BLOCK"


def test_live_config_readiness_accepts_stock_trades_with_polygon_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["stock_trades"],
            "tickers": ["AAPL"],
            "market_data_provider": "yfinance",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert _check(readiness, "Massive market-flow")["status"] == "PASS"


def test_live_config_readiness_warns_for_missing_subscription_email_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["subscription_emails"],
            "tickers": ["AAPL"],
            "market_data_provider": "yfinance",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert readiness["state"] == "warning"
    assert _check(readiness, "Subscription emails")["status"] == "WARN"


def test_live_config_readiness_passes_local_subscription_email_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    subscription_config = tmp_path / "subscription-email.json"
    subscription_config.write_text(
        json.dumps(
            {
                "mode": "local_eml",
                "input_path": str(mailbox),
                "enabled_services": ["seeking_alpha"],
            }
        ),
        encoding="utf-8",
    )
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["subscription_emails"],
            "tickers": ["AAPL"],
            "subscription_email_config": str(subscription_config),
            "market_data_provider": "yfinance",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert _check(readiness, "Subscription emails")["status"] == "PASS"


def test_live_config_readiness_passes_gmail_app_password_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_USERNAME", "user@example.test")
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_PASSWORD", "app-password")
    subscription_config = tmp_path / "subscription-email.json"
    subscription_config.write_text(
        json.dumps(
            {
                "mode": "gmail",
                "input_path": str(tmp_path / "mail"),
                "enabled_services": ["seeking_alpha"],
                "mailbox_username_env": "SUBSCRIPTION_EMAIL_USERNAME",
                "mailbox_password_env": "SUBSCRIPTION_EMAIL_PASSWORD",
            }
        ),
        encoding="utf-8",
    )
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["subscription_emails"],
            "tickers": ["AAPL"],
            "subscription_email_config": str(subscription_config),
            "market_data_provider": "yfinance",
        },
    )

    readiness = load_live_config_readiness(config_path)

    assert _check(readiness, "Subscription emails")["status"] == "PASS"


def test_live_config_status_endpoint_reads_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_env(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "datasets": ["prices_daily"],
            "tickers": ["AAPL"],
            "market_data_provider": "yfinance",
        },
    )
    monkeypatch.setenv("LIVE_REFRESH_CONFIG_PATH", str(config_path))
    client = TestClient(create_app())

    response = client.get("/status/live-config")

    assert response.status_code == HTTP_OK
    assert response.json()["state"] == "warning"


def _write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "live-refresh.local.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _blank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "MARKET_DATA_PROVIDER",
        "SEC_USER_AGENT",
        "LIVE_REFRESH_CONFIG_PATH",
        "MASSIVE_API_KEY",
        "POLYGON_API_KEY",
    ):
        monkeypatch.setenv(key, "")


def _check(readiness: dict[str, object], label: str) -> dict[str, str]:
    checks = readiness["checks"]
    if not isinstance(checks, list):
        raise TypeError("checks must be a list")
    for item in checks:
        if isinstance(item, dict) and item.get("label") == label:
            return {str(key): str(value) for key, value in item.items()}
    raise AssertionError(f"missing check: {label}")
