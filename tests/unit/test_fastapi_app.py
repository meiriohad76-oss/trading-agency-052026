from __future__ import annotations

from fastapi.testclient import TestClient

from agency.app import create_app

HTTP_OK = 200
HTTP_NOT_FOUND = 404


def test_health_endpoint_reports_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok", "service": "trading-agency-v2"}


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
