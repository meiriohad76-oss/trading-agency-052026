from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

import agency.dashboard as dashboard_module
from agency.app import create_app
from agency.services import (
    PortfolioPolicy,
    build_execution_preview,
    build_order_approval_event,
    build_risk_decision,
)
from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.service_fixtures import selection_report
from tests.unit.test_cockpit_contract import _sample_sources


def test_operator_can_advance_candidate_to_execution_preview() -> None:
    report = selection_report(action="BUY", score=0.74)
    policy = PortfolioPolicy(broker_submit_enabled=True)
    source_health = {
        "source_count": 3,
        "degraded_source_count": 0,
        "missing_source_count": 0,
        "missing_sources": [],
    }

    risk_result = build_risk_decision(report, source_health, policy=policy)
    risk_decision = risk_result.risk_decision
    unapproved_preview = build_execution_preview(
        risk_decision,
        policy=policy,
        account={"buying_power": 100000.0, "equity": 100000.0},
        research_approval_required=True,
        research_approval_recorded=False,
    ).preview
    approved_preview = build_execution_preview(
        risk_decision,
        policy=policy,
        account={"buying_power": 100000.0, "equity": 100000.0},
        research_approval_required=True,
        research_approval_recorded=True,
    ).preview

    assert report["ticker"] == "AAPL"
    assert risk_decision["decision"] in {"ALLOW", "WARN"}
    assert approved_preview["preview_state"] == "READY"
    assert unapproved_preview["submit_enabled"] is False
    assert "current human approval required" in unapproved_preview["reasons"]
    assert approved_preview["submit_enabled"] is True

    approval_event = build_order_approval_event(approved_preview)

    assert approval_event["event_type"] == "ORDER_APPROVAL"
    assert approval_event["payload"]["paper_only"] is True  # type: ignore[index]
    assert (
        approval_event["payload"]["order_intent_hash"]  # type: ignore[index]
        == approved_preview["order_intent_hash"]
    )


def test_cockpit_context_for_operator_flow_is_json_serializable() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert isinstance(json.dumps(context), str)


def test_operator_review_route_records_approval_and_moves_to_execution(
    monkeypatch,
) -> None:
    session = _FakeSession()
    writes: list[dict[str, object]] = []

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_report_hash(**kwargs: object) -> str:
        assert kwargs["ticker"] == "aapl"
        return "a" * 64

    async def fake_caution_required(**_kwargs: object) -> bool:
        return False

    async def fake_persist(_session: object, **kwargs: object) -> dict[str, object]:
        writes.append(dict(kwargs))
        return {"event_type": "HUMAN_REVIEW"}

    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    monkeypatch.setattr(
        dashboard_module,
        "_caution_acknowledgement_required_for_review",
        fake_caution_required,
    )
    monkeypatch.setattr(
        dashboard_module,
        "build_and_persist_human_review_event",
        fake_persist,
    )

    response = TestClient(create_app()).post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/execution-preview?ticker=AAPL#focused-preview-AAPL"
    assert session.committed is True
    assert writes == [
        {
            "cycle_id": "cycle-1",
            "ticker": "aapl",
            "as_of": "2026-05-07T09:30:00Z",
            "decision": "APPROVE",
            "review_reason": None,
            "notes": None,
            "selection_report_hash": "a" * 64,
        }
    ]


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True
