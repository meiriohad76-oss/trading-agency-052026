from __future__ import annotations

from agency.services import (
    PortfolioPolicy,
    build_execution_preview,
    build_order_approval_event,
    build_risk_decision,
)
from tests.unit.service_fixtures import selection_report


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
