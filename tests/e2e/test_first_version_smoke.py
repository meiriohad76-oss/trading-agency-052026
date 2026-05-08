from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agency.api.audit as audit_api
import agency.api.health as health_api
from agency import audit_dashboard, dashboard
from agency.app import create_app
from agency.services import DemoRuntimeSeed, build_demo_runtime_seed

HTTP_OK = 200


def test_first_version_happy_path_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = build_demo_runtime_seed()
    _patch_runtime_pages(monkeypatch, seed)
    client = TestClient(create_app())

    pages = {
        "/": ["Command", "NVDA", "Review data sources"],
        "/final-selection": ["Final Selection", "BUY", "WATCH"],
        "/risk": ["Risk Decisions", "ALLOW", "BLOCK"],
        "/execution-preview": ["Execution Preview", "Submission disabled", "Closed"],
        "/audit": ["Runtime Audit", "Agent Runs", "Risk Snapshots"],
        "/candidates/NVDA": ["Candidate Audit", "NVDA", "FINAL_ACTION"],
    }

    for path, expected_text in pages.items():
        response = client.get(path)
        assert response.status_code == HTTP_OK
        for text in expected_text:
            assert text in response.text


def test_first_version_machine_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = build_demo_runtime_seed()
    _patch_runtime_pages(monkeypatch, seed)
    client = TestClient(create_app())

    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/audit/agent-runs").status_code == HTTP_OK
    metrics = client.get("/metrics").text

    assert "agency_source_health_total" in metrics
    assert "agency_selection_reports_total" in metrics


def _patch_runtime_pages(
    monkeypatch: pytest.MonkeyPatch,
    seed: DemoRuntimeSeed,
) -> None:
    async def reports(*, ticker: str | None = None, limit: int = 50) -> list[dict[str, object]]:
        rows = list(seed.selection_reports)
        if ticker is not None:
            rows = [row for row in rows if row["ticker"] == ticker]
        return rows[:limit]

    async def sources() -> list[dict[str, object]]:
        return list(seed.source_health)

    async def timeline(
        *,
        ticker: str,
        cycle_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        del cycle_id
        rows = [event for event in seed.all_lifecycle_events if event["ticker"] == ticker]
        return rows[:limit]

    async def agent_runs(*, limit: int = 50) -> list[dict[str, object]]:
        del limit
        return [_agent_run()]

    async def prompt_audits(*, limit: int = 50) -> list[dict[str, object]]:
        del limit
        return []

    async def risk_snapshots(**_kwargs: object) -> list[dict[str, object]]:
        return [_risk_snapshot()]

    async def execution_states(**_kwargs: object) -> list[dict[str, object]]:
        return [_execution_state()]

    async def metrics_text() -> str:
        return "\n".join(
            [
                "agency_source_health_total 2",
                "agency_selection_reports_total 3",
                "",
            ]
        )

    monkeypatch.setattr(dashboard, "runtime_selection_reports", reports)
    monkeypatch.setattr(dashboard, "runtime_data_source_status", sources)
    monkeypatch.setattr(dashboard, "runtime_candidate_timeline", timeline)
    monkeypatch.setattr(audit_dashboard, "runtime_agent_runs", agent_runs)
    monkeypatch.setattr(audit_dashboard, "runtime_prompt_audits", prompt_audits)
    monkeypatch.setattr(audit_dashboard, "runtime_risk_snapshots", risk_snapshots)
    monkeypatch.setattr(audit_dashboard, "runtime_execution_states", execution_states)
    monkeypatch.setattr(audit_api, "runtime_agent_runs", agent_runs)
    monkeypatch.setattr(health_api, "runtime_metrics", metrics_text)


def _agent_run() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "cycle_id": "demo-cycle-1",
        "agent_name": "runtime-cycle",
        "status": "SUCCEEDED",
        "trigger": "MANUAL",
        "started_at": "2026-05-07T14:30:00Z",
        "finished_at": "2026-05-07T14:31:00Z",
        "payload": {"selection_report_count": 3, "risk_decision_count": 3},
    }


def _risk_snapshot() -> dict[str, object]:
    return {
        "cycle_id": "demo-cycle-1",
        "ticker": "NVDA",
        "risk_level": "LOW",
        "gross_exposure_pct": 10.0,
        "generated_at": "2026-05-07T14:31:00Z",
    }


def _execution_state() -> dict[str, object]:
    return {
        "cycle_id": "demo-cycle-1",
        "ticker": "NVDA",
        "state": "READY",
        "event_time": "2026-05-07T14:31:00Z",
        "reason": "paper preview ready",
    }
