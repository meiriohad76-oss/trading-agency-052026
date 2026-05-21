from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

import agency.api.audit as audit_api
from agency.api.audit import (
    RuntimeAuditUnavailable,
    runtime_agent_runs,
    runtime_portfolio_snapshots,
    runtime_risk_snapshots,
)
from agency.app import create_app

HTTP_OK = 200
EXPECTED_LIMIT = 5


def test_audit_endpoints_report_storage_unavailable(monkeypatch) -> None:
    async def unavailable(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeAuditUnavailable("runtime audit storage is unavailable")

    monkeypatch.setattr(audit_api, "runtime_agent_runs", unavailable)
    monkeypatch.setattr(audit_api, "runtime_prompt_audits", unavailable)
    monkeypatch.setattr(audit_api, "runtime_risk_snapshots", unavailable)
    monkeypatch.setattr(audit_api, "runtime_execution_states", unavailable)
    monkeypatch.setattr(audit_api, "runtime_portfolio_snapshots", unavailable)
    client = TestClient(create_app())

    assert client.get("/audit/agent-runs").status_code == 503
    assert client.get("/audit/prompts").status_code == 503
    assert client.get("/audit/risk-snapshots").status_code == 503
    assert client.get("/audit/execution-states").status_code == 503
    assert client.get("/audit/portfolio-snapshots").status_code == 503


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


async def test_runtime_portfolio_snapshots_uses_repository_payloads() -> None:
    async def reader(session: object, limit: int) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert limit == EXPECTED_LIMIT
        return [_portfolio_snapshot()]

    payloads = await runtime_portfolio_snapshots(
        limit=EXPECTED_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["provider"] == "alpaca"
    assert payloads[0]["position_count"] == 1


async def test_runtime_agent_runs_can_raise_storage_unavailable() -> None:
    try:
        await runtime_agent_runs(
            session_provider=_raising_session_provider,
            raise_on_unavailable=True,
        )
    except RuntimeAuditUnavailable as exc:
        assert "runtime audit storage is unavailable" in str(exc)
    else:
        raise AssertionError("expected RuntimeAuditUnavailable")


def test_agent_runs_route_returns_storage_unavailable_without_config(monkeypatch) -> None:
    async def unavailable(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeAuditUnavailable("runtime audit storage is unavailable")

    monkeypatch.setattr(audit_api, "runtime_agent_runs", unavailable)
    client = TestClient(create_app())

    response = client.get("/audit/agent-runs")

    assert response.status_code == 503


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database offline")
    yield "unused"


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


def _portfolio_snapshot() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "snapshot_id": "portfolio-snap-1",
        "provider": "alpaca",
        "mode": "paper",
        "captured_at": "2026-05-08T09:34:00Z",
        "account_status": "ACTIVE",
        "equity": 100000.0,
        "cash": 99000.0,
        "buying_power": 198000.0,
        "portfolio_value": 100000.0,
        "position_count": 1,
        "open_order_count": 0,
        "gross_exposure_pct": 1.0,
        "payload": {"positions": []},
    }
