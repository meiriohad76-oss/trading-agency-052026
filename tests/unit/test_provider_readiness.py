from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agency.app import create_app
from agency.runtime.provider_readiness import load_provider_readiness

HTTP_OK = 200


def test_provider_readiness_blocks_only_active_missing_required_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)

    readiness = load_provider_readiness(
        {
            "provider": "alpaca",
            "checks": [{"label": "SEC User-Agent", "status": "PASS"}],
        }
    )

    assert readiness["ready"] is False
    assert readiness["blocker_count"] == 1
    assert readiness["warning_count"] == 0
    assert _provider(readiness, "Alpaca")["status"] == "BLOCK"
    assert _provider(readiness, "SEC EDGAR")["status"] == "PASS"
    assert _provider(readiness, "Subscription Email Agents")["status"] == "PASS"
    assert _provider(readiness, "Unusual Whales")["status"] == "PLANNED"


def test_provider_readiness_reports_future_provider_keys_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "uw")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")

    readiness = load_provider_readiness(
        {
            "provider": "alpaca",
            "checks": [{"label": "SEC User-Agent", "status": "PASS"}],
        }
    )

    assert readiness["ready"] is True
    assert readiness["blocker_count"] == 0
    assert _provider(readiness, "Alpaca")["status"] == "PASS"
    assert _provider(readiness, "Unusual Whales")["status"] == "PASS"
    assert _provider(readiness, "Polygon or Massive")["status"] == "PASS"
    assert _provider(readiness, "Benzinga")["status"] == "PLANNED"


def test_provider_readiness_warns_for_partial_key_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)
    monkeypatch.setenv("THETADATA_USERNAME", "user")

    readiness = load_provider_readiness({"provider": "yfinance", "checks": []})

    assert readiness["ready"] is True
    assert readiness["state"] == "attention"
    assert readiness["warning_count"] == 1
    assert _provider(readiness, "ThetaData")["status"] == "WARN"


def test_provider_readiness_blocks_massive_when_market_flow_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)

    readiness = load_provider_readiness(
        {
            "provider": "yfinance",
            "checks": [{"label": "Massive market-flow", "status": "BLOCK"}],
        }
    )

    assert readiness["ready"] is False
    assert _provider(readiness, "Polygon or Massive")["required_now"] is True
    assert _provider(readiness, "Polygon or Massive")["status"] == "BLOCK"


def test_provider_readiness_blocks_openai_when_llm_review_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)
    monkeypatch.setenv("AGENCY_ENABLE_LLM_REVIEW", "true")

    readiness = load_provider_readiness({"provider": "yfinance", "checks": []})

    assert readiness["ready"] is False
    assert _provider(readiness, "OpenAI")["required_now"] is True
    assert _provider(readiness, "OpenAI")["status"] == "BLOCK"


def test_provider_readiness_reports_local_llm_shadow_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)
    monkeypatch.setenv("AGENCY_LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_BASE_URL", "http://10.0.0.5:3000")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_API_KEY", "owui-key")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_MODEL", "qwen2.5:7b")

    readiness = load_provider_readiness({"provider": "yfinance", "checks": []})

    row = _provider(readiness, "Raspberry Pi Local LLM")
    assert row["required_now"] is True
    assert row["configured"] is True
    assert row["status"] == "PASS"
    assert "shadow" in str(row["detail"]).lower()


def test_provider_readiness_supports_direct_ollama_local_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)
    monkeypatch.setenv("AGENCY_LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_BASE_URL", "http://10.100.102.18:11434")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_MODEL", "qwen2.5:3b-instruct")

    readiness = load_provider_readiness({"provider": "yfinance", "checks": []})

    row = _provider(readiness, "Raspberry Pi Local LLM")
    assert row["required_now"] is True
    assert row["configured"] is True
    assert row["status"] == "PASS"
    assert row["key_label"] == "AGENCY_LOCAL_LLM_BASE_URL, AGENCY_LOCAL_LLM_MODEL"


def test_provider_readiness_endpoint_returns_provider_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blank_provider_env(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/status/provider-readiness")

    assert response.status_code == HTTP_OK
    assert response.json()["schema_version"] == "0.1.0"
    assert response.json()["provider_count"] >= 1


def _provider(summary: dict[str, object], label: str) -> dict[str, object]:
    providers = summary["providers"]
    if not isinstance(providers, list):
        raise TypeError("providers must be a list")
    for provider in providers:
        if isinstance(provider, dict) and provider.get("label") == label:
            return provider
    raise AssertionError(f"missing provider: {label}")


def _blank_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "SEC_USER_AGENT",
        "OPENAI_API_KEY",
        "OPENFIGI_API_KEY",
        "BENZINGA_API_KEY",
        "UNUSUAL_WHALES_API_KEY",
        "FRED_API_KEY",
        "POLYGON_API_KEY",
        "MASSIVE_API_KEY",
        "THETADATA_USERNAME",
        "THETADATA_PASSWORD",
        "AGENCY_ENABLE_LLM_REVIEW",
        "AGENCY_ALPACA_BROKER_ENABLED",
        "AGENCY_BROKER_SUBMIT_ENABLED",
        "AGENCY_LOCAL_LLM_ENABLED",
        "AGENCY_LOCAL_LLM_PROVIDER",
        "AGENCY_LOCAL_LLM_BASE_URL",
        "AGENCY_LOCAL_LLM_API_KEY",
        "AGENCY_LOCAL_LLM_MODEL",
    ):
        monkeypatch.setenv(key, "")
