from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agency.contracts import validate_contract
from agency.services.deterministic_rules import (
    DeterministicRuleResult,
    evaluate_deterministic_rules,
)
from agency.services.llm_review import build_llm_review_stub, normalize_llm_review
from agency.services.selection_events import (
    build_llm_lifecycle_event,
    build_report_lifecycle_event,
    status_for_action,
)

PROMOTING_LLM_ACTIONS = {"WATCH"}
DEMOTING_LLM_ACTIONS = {"NO_TRADE", "CLOSE_REVIEW", "DEFER", "DISAGREE", "NEEDS_MORE_EVIDENCE"}
LLM_ACTION_RISK_FLAGS = {
    "CLOSE_REVIEW": "llm_requested_close_review",
    "DEFER": "llm_deferred_review",
    "DISAGREE": "llm_disagreed",
    "NEEDS_MORE_EVIDENCE": "llm_needs_more_evidence",
    "NO_TRADE": "llm_demoted_watch",
}


@dataclass(frozen=True)
class FinalSelectionResult:
    """Final selection report plus lifecycle audit events."""

    selection_report: dict[str, object]
    lifecycle_events: list[dict[str, object]]


@dataclass(frozen=True)
class _FinalDecision:
    action: str
    conviction: float
    risk_flags: list[str]
    reason: str


def build_final_selection(
    evidence_pack: Mapping[str, object],
    *,
    generated_at: str | None = None,
    llm_review: Mapping[str, object] | None = None,
    llm_lifecycle_event: Mapping[str, object] | None = None,
) -> FinalSelectionResult:
    """Build the v0 final selection report and audit trail."""
    validate_contract("evidence-pack", evidence_pack)
    pack = dict(evidence_pack)
    report_generated_at = generated_at or str(pack["generated_at"])
    rule_result = evaluate_deterministic_rules(pack)
    review, llm_event = _llm_review_and_event(
        pack,
        rule_result.decision,
        llm_review=llm_review,
        llm_lifecycle_event=llm_lifecycle_event,
        event_time=report_generated_at,
    )
    final_decision = _final_decision(rule_result, review)

    report = _selection_report(
        pack,
        rule_result,
        review,
        final_decision,
        generated_at=report_generated_at,
    )
    validate_contract("selection-report", report)
    lifecycle_events = [
        _deterministic_event(report),
        llm_event,
        _final_event(report, final_decision),
    ]
    for event in lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)
    return FinalSelectionResult(report, lifecycle_events)


def _llm_review_and_event(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    *,
    llm_review: Mapping[str, object] | None,
    llm_lifecycle_event: Mapping[str, object] | None,
    event_time: str,
) -> tuple[dict[str, object], dict[str, object]]:
    if llm_lifecycle_event is not None:
        event = dict(llm_lifecycle_event)
        payload = event.get("payload")
        event_review = (
            payload.get("llm_review")
            if isinstance(payload, Mapping)
            and isinstance(payload.get("llm_review"), Mapping)
            else None
        )
        review = normalize_llm_review(
            llm_review or event_review or build_context_only_review_payload()
        )
        return review, event
    if llm_review is None:
        result = build_llm_review_stub(
            evidence_pack,
            deterministic_decision,
            generated_at=event_time,
        )
        return result.review, result.lifecycle_event
    review = normalize_llm_review(llm_review)
    return review, build_llm_lifecycle_event(
        evidence_pack,
        deterministic_decision,
        review,
        event_time=event_time,
    )


def build_context_only_review_payload() -> dict[str, object]:
    return {
        "action": "NO_REVIEW",
        "confidence": 0.0,
        "rationale": "LLM review unavailable.",
        "supporting_factors": [],
        "concerns": [],
    }


def _selection_report(
    evidence_pack: Mapping[str, object],
    rule_result: DeterministicRuleResult,
    llm_review: Mapping[str, object],
    final_decision: _FinalDecision,
    *,
    generated_at: str,
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": str(evidence_pack["cycle_id"]),
        "ticker": str(evidence_pack["ticker"]),
        "as_of": str(evidence_pack["as_of"]),
        "generated_at": generated_at,
        "final_action": final_decision.action,
        "final_conviction": final_decision.conviction,
        "deterministic": rule_result.decision,
        "llm_review": dict(llm_review),
        "policy_gates": rule_result.policy_gates,
        "risk_flags": final_decision.risk_flags,
        "evidence_pack": dict(evidence_pack),
        "trade_plan": None,
    }


def _final_decision(
    rule_result: DeterministicRuleResult,
    llm_review: Mapping[str, object],
) -> _FinalDecision:
    deterministic = rule_result.decision
    blockers = _blocking_reasons(rule_result.policy_gates)
    if blockers:
        return _FinalDecision("NO_TRADE", 0.0, ["policy_gate_blocked"], blockers[0])

    deterministic_action = str(deterministic["action"])
    deterministic_conviction = _float_field(deterministic, "conviction")
    llm_action = str(llm_review.get("action", "NO_REVIEW")).upper()
    if deterministic_action == "NO_TRADE" and llm_action in PROMOTING_LLM_ACTIONS:
        return _FinalDecision(
            "NO_TRADE",
            deterministic_conviction,
            ["llm_promotion_blocked"],
            "deterministic no-trade preserved",
        )
    if deterministic_action == "WATCH" and llm_action in DEMOTING_LLM_ACTIONS:
        return _FinalDecision(
            "CLOSE_REVIEW",
            deterministic_conviction,
            [LLM_ACTION_RISK_FLAGS.get(llm_action, "llm_demoted_watch")],
            "llm review requested closer review",
        )
    return _FinalDecision(
        deterministic_action,
        deterministic_conviction,
        [],
        _first_reason(deterministic),
    )


def _deterministic_event(report: Mapping[str, object]) -> dict[str, object]:
    deterministic = _mapping_field(report, "deterministic")
    return _event(
        report,
        event_type="DETERMINISTIC_ACTION",
        status=status_for_action(str(deterministic["action"]), deterministic),
        reason=_first_reason(deterministic),
        payload={"deterministic": dict(deterministic)},
    )


def _final_event(report: Mapping[str, object], final_decision: _FinalDecision) -> dict[str, object]:
    return _event(
        report,
        event_type="FINAL_ACTION",
        status=status_for_action(final_decision.action, report),
        reason=final_decision.reason,
        payload={
            "final_action": final_decision.action,
            "final_conviction": final_decision.conviction,
            "risk_flags": final_decision.risk_flags,
        },
    )


def _event(
    report: Mapping[str, object],
    *,
    event_type: str,
    status: str,
    reason: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return build_report_lifecycle_event(
        report,
        event_type=event_type,
        status=status,
        reason=reason,
        payload=payload,
    )


def _blocking_reasons(policy_gates: list[dict[str, object]]) -> list[str]:
    return [str(gate["reason"]) for gate in policy_gates if gate["status"] == "BLOCK"]


def _first_reason(payload: Mapping[str, object]) -> str:
    reasons = _string_list(payload, "reason_codes")
    if reasons:
        return reasons[0]
    return "final selection recorded"


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return value


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return [str(item) for item in value]


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)
