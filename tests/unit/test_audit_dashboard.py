from __future__ import annotations

from fastapi.testclient import TestClient

from agency.app import create_app
from agency.audit_dashboard import (
    agent_run_rows,
    audit_summary,
    execution_state_rows,
    portfolio_snapshot_rows,
    risk_snapshot_rows,
)

HTTP_OK = 200


def test_audit_dashboard_renders_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/audit")

    assert response.status_code == HTTP_OK
    assert "Runtime Audit" in response.text
    assert "No agent runs yet" in response.text
    assert "No risk snapshots yet" in response.text
    assert "No portfolio snapshots yet" in response.text
    assert "No execution states yet" in response.text


def test_audit_summary_counts_runtime_rows() -> None:
    summary = audit_summary([_agent_run()], [], [_risk_snapshot()], [_execution_state()])

    assert summary["run_count"] == 1
    assert summary["risk_snapshot_count"] == 1
    assert summary["execution_state_count"] == 1
    assert summary["portfolio_snapshot_count"] == 0
    assert summary["headline"] == "1 runtime runs are recorded."


def test_audit_rows_map_status_classes() -> None:
    run = agent_run_rows([_agent_run()])[0]
    snapshot = risk_snapshot_rows([_risk_snapshot()])[0]
    portfolio = portfolio_snapshot_rows([_portfolio_snapshot()])[0]
    state = execution_state_rows([_execution_state()])[0]

    assert run["status_class"] == "pass"
    assert run["selection_count"] == 1
    assert snapshot["risk_class"] == "pass"
    assert portfolio["position_count"] == 1
    assert state["state_class"] == "pass"


def _agent_run() -> dict[str, object]:
    return {
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
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "risk_level": "LOW",
        "gross_exposure_pct": 10.0,
        "generated_at": "2026-05-08T09:31:00Z",
    }


def _execution_state() -> dict[str, object]:
    return {
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "state": "READY",
        "event_time": "2026-05-08T09:31:00Z",
        "reason": "paper preview ready",
    }


def _portfolio_snapshot() -> dict[str, object]:
    return {
        "captured_at": "2026-05-08T09:34:00Z",
        "mode": "paper",
        "account_status": "ACTIVE",
        "equity": 100000.0,
        "cash": 99000.0,
        "position_count": 1,
        "open_order_count": 0,
        "gross_exposure_pct": 1.0,
    }
