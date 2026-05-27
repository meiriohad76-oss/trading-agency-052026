from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from agency.contracts import validate_contract
from agency.runtime import make_lifecycle_event_id
from agency.services.deterministic_rules import evaluate_deterministic_rules
from agency.services.llm_review import build_context_only_llm_review
from agency.services.selection_events import status_for_action


@dataclass(frozen=True)
class DeterministicSelectionResult:
    """Contract-valid outputs from the deterministic selection service."""

    selection_report: dict[str, object]
    lifecycle_event: dict[str, object]


def build_deterministic_selection(
    evidence_pack: Mapping[str, object],
    *,
    generated_at: str | None = None,
) -> DeterministicSelectionResult:
    """Build deterministic selection artifacts from one validated evidence pack."""
    validate_contract("evidence-pack", evidence_pack)
    pack = dict(evidence_pack)
    report_generated_at = generated_at or str(pack["generated_at"])
    rule_result = evaluate_deterministic_rules(pack)

    report: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": str(pack["cycle_id"]),
        "ticker": str(pack["ticker"]),
        "as_of": str(pack["as_of"]),
        "generated_at": report_generated_at,
        "final_action": rule_result.decision["action"],
        "final_conviction": rule_result.decision["conviction"],
        "deterministic": rule_result.decision,
        "llm_review": build_context_only_llm_review(),
        "policy_gates": rule_result.policy_gates,
        "risk_flags": [],
        "evidence_pack": pack,
        "trade_plan": None,
    }
    validate_contract("selection-report", report)

    lifecycle_event = _deterministic_lifecycle_event(report)
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return DeterministicSelectionResult(report, lifecycle_event)


def _deterministic_lifecycle_event(report: Mapping[str, object]) -> dict[str, object]:
    event_time = str(report["generated_at"])
    event_type = "DETERMINISTIC_ACTION"
    final_action = str(report["final_action"])
    deterministic = _mapping_field(report, "deterministic")
    status = status_for_action(final_action, deterministic)
    reason = _first_reason(deterministic)
    ticker = str(report["ticker"])
    cycle_id = str(report["cycle_id"])
    return {
        "schema_version": "0.1.0",
        "event_id": make_lifecycle_event_id(
            cycle_id=cycle_id,
            ticker=ticker,
            event_type=event_type,
            event_time=event_time,
        ),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "event_type": event_type,
        "event_time": event_time,
        "status": status,
        "reason": reason,
        "payload": {
            "final_action": final_action,
            "final_conviction": report["final_conviction"],
            "deterministic": dict(deterministic),
        },
    }


def _first_reason(deterministic: Mapping[str, object]) -> str:
    reasons = _string_list(deterministic, "reason_codes")
    if reasons:
        return reasons[0]
    return "deterministic selection recorded"


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]
