from __future__ import annotations

from service_fixtures import selection_report, source_health

from agency.contracts import validate_contract
from agency.services import (
    PortfolioPolicy,
    build_execution_preview,
    build_risk_decision,
    build_risk_decisions,
)
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


def test_risk_decision_blocks_float_missing_source_count() -> None:
    result = build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 0, "missing_source_count": 3.0},
        generated_at=GENERATED_AT,
    )

    assert result.risk_decision["decision"] == "BLOCK"
    assert "missing runtime source health" in result.risk_decision["reasons"]


def test_execution_preview_for_warned_trade_candidate_is_ready_with_caution() -> None:
    risk = build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 1},
        generated_at=GENERATED_AT,
    ).risk_decision

    preview = build_execution_preview(risk).preview

    validate_contract("execution-preview", preview)
    assert preview["risk_decision"] == "WARN"
    assert preview["preview_state"] == "READY"
    assert preview["side"] == "BUY"
    assert preview["submit_enabled"] is False
    assert "runtime source degradation present" in preview["reasons"]


def test_risk_decisions_block_missing_report_source_health() -> None:
    unrelated_source = {**source_health(), "source": "daily-market-bars"}

    results = build_risk_decisions(
        [selection_report(action="BUY")],
        [unrelated_source],
        generated_at=GENERATED_AT,
    )

    decision = results[0].risk_decision
    assert decision["decision"] == "BLOCK"
    assert decision["source_health"]["missing_sources"] == ["sec-edgar"]
    assert "missing runtime source health: sec-edgar" in decision["reasons"]


def test_risk_decision_blocks_policy_gate_block() -> None:
    result = _risk_result(
        selection_report(action="BUY", policy_status="BLOCK", policy_reason="no evidence")
    )

    assert result.risk_decision["decision"] == "BLOCK"
    assert any(
        "selection policy gate blocked" in str(reason)
        for reason in result.risk_decision["reasons"]
    )
    assert result.lifecycle_event["status"] == "BLOCKED"


def test_risk_decision_warns_watch_policy_block_as_acknowledgeable_caution() -> None:
    result = _risk_result(
        selection_report(action="WATCH", policy_status="BLOCK", policy_reason="no evidence")
    )

    validate_contract("risk-decision", result.risk_decision)
    assert result.risk_decision["decision"] == "WARN"
    assert result.lifecycle_event["status"] == "WARN"
    assert "BLOCK" not in {
        check["status"] for check in result.risk_decision["checks"]  # type: ignore[index]
    }
    assert any(
        "Caution:" in str(reason) and "selection policy gate blocked" in str(reason)
        for reason in result.risk_decision["reasons"]
    )


def test_execution_preview_for_cautionary_watch_is_review_only_not_blocked() -> None:
    risk = _risk_result(
        selection_report(action="WATCH", policy_status="BLOCK", policy_reason="no evidence")
    ).risk_decision

    preview = build_execution_preview(risk).preview

    validate_contract("execution-preview", preview)
    assert preview["risk_decision"] == "WARN"
    assert preview["preview_state"] == "DISABLED"
    assert preview["side"] == "NONE"
    assert preview["submit_enabled"] is False
    assert "Caution:" in str(preview["reasons"][0])  # type: ignore[index]


def test_risk_decision_blocks_short_opening_order_unless_enabled() -> None:
    blocked = _risk_result(selection_report(action="SHORT"))
    cover_blocked = _risk_result(selection_report(action="COVER"))
    allowed = build_risk_decision(
        selection_report(action="SHORT"),
        {"source_count": 1, "degraded_source_count": 0},
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(allow_short_trades=True),
    )

    assert blocked.risk_decision["decision"] == "BLOCK"
    assert "SHORT orders are disabled by short-sale policy" in blocked.risk_decision["reasons"]
    assert cover_blocked.risk_decision["decision"] == "BLOCK"
    assert (
        "COVER orders are disabled by short-sale policy"
        in cover_blocked.risk_decision["reasons"]
    )
    assert allowed.risk_decision["decision"] == "ALLOW"


def test_risk_decisions_block_projected_exposure_cap() -> None:
    results = build_risk_decisions(
        [selection_report(action="BUY")],
        [source_health()],
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(max_gross_exposure_pct=5.0, default_position_pct=10.0),
    )

    assert results[0].risk_decision["decision"] == "BLOCK"
    assert "projected gross exposure exceeds cap" in results[0].risk_decision["reasons"]


def test_risk_decisions_reserve_pending_opening_order_exposure() -> None:
    results = build_risk_decisions(
        [selection_report(action="BUY")],
        [source_health()],
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(max_gross_exposure_pct=80.0, default_position_pct=10.0),
        current_gross_exposure_pct=65.0,
        pending_opening_order_exposure_pct=10.0,
    )

    assert results[0].risk_decision["projected_gross_exposure_pct"] == 85.0
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
