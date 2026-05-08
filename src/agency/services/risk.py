from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from agency.contracts import validate_contract
from agency.services.selection_events import build_report_lifecycle_event

TRADE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}
REVIEW_ACTIONS = {"WATCH", "HOLD"}
DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}


@dataclass(frozen=True)
class PortfolioPolicy:
    """Conservative v0 policy values used before editable policy persistence exists."""

    min_final_conviction: float = 0.62
    max_new_positions_per_cycle: int = 3
    max_gross_exposure_pct: float = 100.0
    default_position_pct: float = 10.0
    broker_submit_enabled: bool = False


@dataclass(frozen=True)
class RiskDecisionResult:
    """Risk decision plus lifecycle audit event."""

    risk_decision: dict[str, object]
    lifecycle_event: dict[str, object]


def build_risk_decisions(
    selection_reports: Sequence[Mapping[str, object]],
    source_health: Sequence[Mapping[str, object]],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
    current_gross_exposure_pct: float = 0.0,
) -> list[RiskDecisionResult]:
    """Build v0 risk decisions for selection reports without broker calls."""
    normalized_policy = policy or PortfolioPolicy()
    source_summary = _source_health_summary(source_health)
    results: list[RiskDecisionResult] = []
    trade_index = 0
    for report in selection_reports:
        is_trade = _is_trade_action(report)
        projected_exposure = current_gross_exposure_pct
        if is_trade:
            projected_exposure += (trade_index + 1) * normalized_policy.default_position_pct
        results.append(
            build_risk_decision(
                report,
                source_summary,
                generated_at=generated_at,
                policy=normalized_policy,
                candidate_index=trade_index,
                projected_gross_exposure_pct=projected_exposure,
            )
        )
        if is_trade:
            trade_index += 1
    return results


def build_risk_decision(
    selection_report: Mapping[str, object],
    source_health_summary: Mapping[str, object],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
    candidate_index: int = 0,
    projected_gross_exposure_pct: float | None = None,
) -> RiskDecisionResult:
    """Build one schema-valid v0 risk decision and audit event."""
    validate_contract("selection-report", selection_report)
    normalized_policy = policy or PortfolioPolicy()
    projected_exposure = (
        normalized_policy.default_position_pct
        if projected_gross_exposure_pct is None
        else projected_gross_exposure_pct
    )
    checks = _risk_checks(
        selection_report,
        source_health_summary,
        policy=normalized_policy,
        candidate_index=candidate_index,
        projected_gross_exposure_pct=projected_exposure,
    )
    decision = _decision_from_checks(checks, selection_report)
    reasons = _decision_reasons(checks, selection_report)
    risk_decision: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": str(selection_report["cycle_id"]),
        "ticker": str(selection_report["ticker"]),
        "as_of": str(selection_report["as_of"]),
        "generated_at": generated_at or _now_utc(),
        "decision": decision,
        "final_action": str(selection_report["final_action"]),
        "final_conviction": _float_field(selection_report, "final_conviction"),
        "position_size_pct": normalized_policy.default_position_pct,
        "projected_gross_exposure_pct": round(projected_exposure, 6),
        "checks": checks,
        "reasons": reasons,
        "risk_flags": _string_list(selection_report, "risk_flags"),
        "source_health": dict(source_health_summary),
    }
    validate_contract("risk-decision", risk_decision)
    lifecycle_event = build_report_lifecycle_event(
        risk_decision,
        event_type="RISK_DECISION",
        status=_lifecycle_status(decision),
        reason=reasons[0],
        payload={"risk_decision": dict(risk_decision)},
    )
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return RiskDecisionResult(risk_decision, lifecycle_event)


def _risk_checks(
    selection_report: Mapping[str, object],
    source_health_summary: Mapping[str, object],
    *,
    policy: PortfolioPolicy,
    candidate_index: int,
    projected_gross_exposure_pct: float,
) -> list[dict[str, str]]:
    return [
        _action_check(selection_report),
        _policy_gate_check(selection_report),
        _conviction_check(selection_report, policy),
        _runtime_source_check(source_health_summary),
        _capacity_check(selection_report, candidate_index, policy),
        _gross_exposure_check(selection_report, projected_gross_exposure_pct, policy),
        _risk_flag_check(selection_report),
    ]


def _action_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    action = str(selection_report["final_action"])
    if action in TRADE_ACTIONS:
        return _check("final_action", "PASS", f"{action} is eligible for preview")
    if action in REVIEW_ACTIONS:
        return _check("final_action", "WARN", f"{action} is review-only")
    return _check("final_action", "BLOCK", f"{action} is not orderable")


def _policy_gate_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    statuses = [
        str(gate["status"])
        for gate in _mapping_list(selection_report, "policy_gates")
    ]
    if "BLOCK" in statuses:
        return _check("policy_gates", "BLOCK", "selection policy gate blocked")
    if "WARN" in statuses:
        return _check("policy_gates", "WARN", "selection policy gate warned")
    return _check("policy_gates", "PASS", "selection policy gates passed")


def _conviction_check(
    selection_report: Mapping[str, object],
    policy: PortfolioPolicy,
) -> dict[str, str]:
    conviction = _float_field(selection_report, "final_conviction")
    if conviction < policy.min_final_conviction:
        return _check("min_conviction", "BLOCK", "below minimum final conviction")
    return _check("min_conviction", "PASS", "minimum final conviction met")


def _runtime_source_check(source_health_summary: Mapping[str, object]) -> dict[str, str]:
    source_count = _int_field(source_health_summary, "source_count")
    degraded_count = _int_field(source_health_summary, "degraded_source_count")
    if source_count == 0:
        return _check("runtime_sources", "BLOCK", "no runtime source health available")
    if degraded_count > 0:
        return _check("runtime_sources", "WARN", "runtime source degradation present")
    return _check("runtime_sources", "PASS", "runtime sources healthy")


def _capacity_check(
    selection_report: Mapping[str, object],
    candidate_index: int,
    policy: PortfolioPolicy,
) -> dict[str, str]:
    if not _is_trade_action(selection_report):
        return _check("cycle_capacity", "PASS", "no trade capacity required")
    if candidate_index >= policy.max_new_positions_per_cycle:
        return _check("cycle_capacity", "BLOCK", "new candidate capacity exceeded")
    return _check("cycle_capacity", "PASS", "within new candidate capacity")


def _gross_exposure_check(
    selection_report: Mapping[str, object],
    projected_gross_exposure_pct: float,
    policy: PortfolioPolicy,
) -> dict[str, str]:
    if not _is_trade_action(selection_report):
        return _check("gross_exposure", "PASS", "no trade exposure added")
    if projected_gross_exposure_pct > policy.max_gross_exposure_pct:
        return _check("gross_exposure", "BLOCK", "projected gross exposure exceeds cap")
    return _check("gross_exposure", "PASS", "projected gross exposure within cap")


def _risk_flag_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    risk_flags = _string_list(selection_report, "risk_flags")
    if risk_flags:
        return _check("risk_flags", "WARN", "selection report has risk flags")
    return _check("risk_flags", "PASS", "no selection risk flags")


def _source_health_summary(source_health: Sequence[Mapping[str, object]]) -> dict[str, object]:
    for source in source_health:
        validate_contract("data-source-health", source)
    return {
        "source_count": len(source_health),
        "degraded_source_count": sum(1 for source in source_health if _source_is_degraded(source)),
    }


def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source["status"]) in DEGRADED_SOURCE_STATUSES
        or str(source["freshness"]) in DEGRADED_FRESHNESS
    )


def _is_trade_action(selection_report: Mapping[str, object]) -> bool:
    return str(selection_report["final_action"]) in TRADE_ACTIONS


def _decision_from_checks(
    checks: Sequence[Mapping[str, str]],
    selection_report: Mapping[str, object],
) -> str:
    statuses = [check["status"] for check in checks]
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARN" in statuses or _string_list(selection_report, "risk_flags"):
        return "WARN"
    return "ALLOW"


def _decision_reasons(
    checks: Sequence[Mapping[str, str]],
    selection_report: Mapping[str, object],
) -> list[str]:
    reasons = [
        check["reason"]
        for check in checks
        if check["status"] in {"BLOCK", "WARN"}
    ]
    return reasons or [f"{selection_report['ticker']} passed v0 risk checks"]


def _lifecycle_status(decision: str) -> str:
    if decision == "ALLOW":
        return "PASSED"
    if decision == "WARN":
        return "WARN"
    return "BLOCKED"


def _check(name: str, status: str, reason: str) -> dict[str, str]:
    return {"name": name, "status": status, "reason": reason}


def _mapping_list(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [cast(Mapping[str, object], item) for item in _list_field(payload, key)]


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
