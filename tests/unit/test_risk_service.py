from __future__ import annotations

from service_fixtures import selection_report, source_health

from agency.contracts import validate_contract
from agency.services import PortfolioPolicy, build_risk_decision, build_risk_decisions
from agency.services.risk import RiskDecisionResult

GENERATED_AT = "2026-05-07T09:32:00Z"


def test_risk_decision_allows_trade_candidate() -> None:
    result = _risk_result(selection_report(action="BUY"))

    validate_contract("risk-decision", result.risk_decision)
    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    assert result.risk_decision["decision"] == "ALLOW"
    assert result.lifecycle_event["event_type"] == "RISK_DECISION"
    assert result.lifecycle_event["status"] == "PASSED"


def test_risk_decision_warns_for_degraded_runtime_source() -> None:
    result = build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 1},
        generated_at=GENERATED_AT,
    )

    assert result.risk_decision["decision"] == "WARN"
    assert result.risk_decision["reasons"] == ["runtime source degradation present"]


def test_risk_decision_blocks_policy_gate_block() -> None:
    result = _risk_result(
        selection_report(action="BUY", policy_status="BLOCK", policy_reason="no evidence")
    )

    assert result.risk_decision["decision"] == "BLOCK"
    assert "selection policy gate blocked" in result.risk_decision["reasons"]
    assert result.lifecycle_event["status"] == "BLOCKED"


def test_risk_decisions_block_projected_exposure_cap() -> None:
    results = build_risk_decisions(
        [selection_report(action="BUY")],
        [source_health()],
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(max_gross_exposure_pct=5.0, default_position_pct=10.0),
    )

    assert results[0].risk_decision["decision"] == "BLOCK"
    assert "projected gross exposure exceeds cap" in results[0].risk_decision["reasons"]


def test_risk_decisions_do_not_spend_capacity_on_watch_rows() -> None:
    results = build_risk_decisions(
        [selection_report(action="WATCH", score=0.9) for _ in range(4)],
        [source_health()],
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(max_new_positions_per_cycle=1),
    )

    assert {result.risk_decision["decision"] for result in results} == {"WARN"}
    assert all(
        "new candidate capacity exceeded" not in result.risk_decision["reasons"]
        for result in results
    )


def _risk_result(report: dict[str, object]) -> RiskDecisionResult:
    return build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at=GENERATED_AT,
    )
