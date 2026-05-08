from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from agency.api.audit import runtime_agent_runs, runtime_risk_snapshots
from agency.app import create_app

HTTP_OK = 200
EXPECTED_LIMIT = 5


def test_audit_endpoints_fall_back_to_empty_lists() -> None:
    client = TestClient(create_app())

    assert client.get("/audit/agent-runs").json() == []
    assert client.get("/audit/prompts").json() == []
    assert client.get("/audit/risk-snapshots").json() == []
    assert client.get("/audit/execution-states").json() == []


async def test_runtime_agent_runs_uses_repository_payloads() -> None:
    async def reader(session: object, limit: int) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert limit == EXPECTED_LIMIT
        return [_agent_run()]

    payloads = await runtime_agent_runs(
        limit=EXPECTED_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["run_id"] == "run-1"
    assert payloads[0]["status"] == "SUCCEEDED"


async def test_runtime_risk_snapshots_pass_filters_to_reader() -> None:
    async def reader(
        session: object,
        ticker: str | None,
        cycle_id: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert ticker == "AAPL"
        assert cycle_id == "cycle-1"
        assert limit == EXPECTED_LIMIT
        return [_risk_snapshot()]

    payloads = await runtime_risk_snapshots(
        ticker="AAPL",
        cycle_id="cycle-1",
        limit=EXPECTED_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["ticker"] == "AAPL"
    assert payloads[0]["risk_level"] == "LOW"


def test_agent_runs_route_returns_http_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/audit/agent-runs")

    assert response.status_code == HTTP_OK


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


def _agent_run() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "agent_name": "runtime-cycle",
        "status": "SUCCEEDED",
        "trigger": "MANUAL",
        "started_at": "2026-05-08T09:30:00Z",
        "finished_at": "2026-05-08T09:31:00Z",
        "payload": {"selection_report_count": 1, "risk_decision_count": 1},
    }


def _risk_snapshot() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "snapshot_id": "snap-1",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-08T09:30:00Z",
        "generated_at": "2026-05-08T09:31:00Z",
        "gross_exposure_pct": 10.0,
        "risk_level": "LOW",
        "payload": {"risk_decision": "ALLOW"},
    }
