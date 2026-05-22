from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.dashboard as dashboard_module
from agency.app import create_app


def _context() -> dict[str, object]:
    return {
        "cycle": {"id": "cycle-route-test", "mode": "PAPER"},
        "market": {"regime": "balanced"},
        "engines": [{"name": "Runtime", "state": "live", "age": "just checked"}],
        "funnel": {"final": 1, "actionable": 1},
        "candidates": [
            {
                "ticker": "ROUT",
                "final_conviction": 0.74,
                "status": "approved",
                "actionable": True,
                "evidence": [{"tier": "confirmed", "text": "Real route fixture evidence."}],
            }
        ],
        "positions": [],
        "account": {"buying_power": 1000.0},
        "sectors": [],
        "sources": [],
        "universe_blocked": [],
        "signals": [],
        "audit_lifecycle": {"traces": {}},
        "policy": {},
        "monitor_events": [],
        "scenario": {"state": "normal", "headline": "1 trade ready."},
    }


def _client(monkeypatch: MonkeyPatch) -> TestClient:
    async def fake_cockpit_context() -> dict[str, object]:
        return _context()

    monkeypatch.setattr(dashboard_module, "cockpit_context", fake_cockpit_context)
    return TestClient(create_app())


def test_cockpit_route_renders(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/cockpit")

    assert response.status_code == 200
    assert "Pre-Flight Cockpit" in response.text
    assert "1 trade ready" in response.text
    assert "ROUT" in response.text


def test_api_cockpit_returns_contract(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/cockpit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cycle"]["id"] == "cycle-route-test"
    assert payload["candidates"][0]["ticker"] == "ROUT"


def test_api_cycle_returns_lightweight_sections(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/cycle")

    assert response.status_code == 200
    assert set(response.json()) == {"cycle", "market", "engines", "scenario"}


def test_api_payloads_are_bounded_and_secret_free(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/cockpit")
    payload = response.text

    assert response.status_code == 200
    assert len(response.json()["candidates"]) <= 25
    assert "ALPACA_SECRET_KEY" not in payload
    assert "DATABASE_URL" not in payload
    assert "api_key" not in payload.lower()


def test_api_routes_do_not_collide_with_existing_namespaces(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    assert client.get("/status/full-live-readiness").status_code in {200, 500}
    assert client.get("/api/cockpit").status_code == 200


def test_api_audit_rejects_invalid_ticker(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/audit/../BAD")

    assert response.status_code == 404


def test_api_audit_normalizes_ticker(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/audit/rout")

    assert response.status_code == 200
    assert response.json()["ticker"] == "ROUT"


def test_api_audit_returns_trace_for_known_ticker(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/audit/ROUT")

    assert response.status_code == 200
    assert response.json()["events"][0]["message"] == "Approved by current cockpit context."
