from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from agency.api.health import runtime_data_source_status
from agency.app import create_app

HTTP_OK = 200
HTTP_NOT_FOUND = 404


def test_health_endpoint_reports_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok", "service": "trading-agency-v2"}


def test_dashboard_renders_status_overview() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == HTTP_OK
    assert "Agency Status" in response.text
    assert "SelectionReport" in response.text


def test_static_styles_are_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/styles.css")

    assert response.status_code == HTTP_OK
    assert "summary-band" in response.text


def test_contracts_endpoint_lists_contracts() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts")

    assert response.status_code == HTTP_OK
    names = {item["name"] for item in response.json()}
    assert {"selection-report", "evidence-pack", "data-source-health"}.issubset(names)


def test_contract_schema_endpoint_returns_json_schema() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/selection-report")

    assert response.status_code == HTTP_OK
    assert response.json()["title"] == "SelectionReport"


def test_contract_schema_endpoint_rejects_unknown_contract() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/unknown")

    assert response.status_code == HTTP_NOT_FOUND


def test_data_source_status_endpoint_returns_valid_status_payload() -> None:
    client = TestClient(create_app())

    response = client.get("/status/data-sources")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload[0]["source"] == "bootstrap"
    assert payload[0]["status"] == "DEGRADED"


async def test_runtime_data_source_status_uses_repository_payloads() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        assert session == "fake-session"
        return [_source_health("sec-edgar")]

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "sec-edgar"
    assert payloads[0]["status"] == "HEALTHY"


async def test_runtime_data_source_status_falls_back_for_empty_repository() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        del session
        return []

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "bootstrap"


async def test_runtime_data_source_status_falls_back_for_missing_db() -> None:
    payloads = await runtime_data_source_status(session_provider=_raising_session_provider)

    assert payloads[0]["source"] == "bootstrap"


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _source_health(source: str) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": source,
        "source_tier": "OFFICIAL_FILING",
        "status": "HEALTHY",
        "checked_at": "2026-05-07T09:30:00Z",
        "freshness": "FRESH",
        "last_success_at": "2026-05-07T09:29:00Z",
        "observed_lag_seconds": 60,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": [],
    }
