from __future__ import annotations

from service_fixtures import selection_report

from agency.contracts import validate_contract
from agency.services import PortfolioPolicy, build_execution_preview, build_risk_decision

GENERATED_AT = "2026-05-07T09:33:00Z"


def test_execution_preview_builds_ready_paper_preview_for_allowed_trade() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")

    result = build_execution_preview(risk_decision, generated_at=GENERATED_AT)

    validate_contract("execution-preview", result.preview)
    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    assert result.preview["preview_state"] == "READY"
    assert result.preview["side"] == "BUY"
    assert result.preview["submit_enabled"] is False
    assert result.lifecycle_event["status"] == "RECORDED"


def test_execution_preview_stays_closed_even_when_policy_allows_submit() -> None:
    risk_decision = _risk_decision(action="WATCH", decision_source="WARN")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
    )

    assert result.preview["preview_state"] == "DISABLED"
    assert result.preview["side"] == "NONE"
    assert result.preview["submit_enabled"] is False


def test_execution_preview_blocks_when_risk_blocks() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="BLOCK")

    result = build_execution_preview(risk_decision, generated_at=GENERATED_AT)

    assert result.preview["preview_state"] == "BLOCKED"
    assert result.lifecycle_event["status"] == "BLOCKED"


def _risk_decision(*, action: str, decision_source: str) -> dict[str, object]:
    if decision_source == "BLOCK":
        report = selection_report(action=action, policy_status="BLOCK")
    elif decision_source == "WARN":
        report = selection_report(action=action, risk_flags=["source_warning"])
    else:
        report = selection_report(action=action)
    return build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision
