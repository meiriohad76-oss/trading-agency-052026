from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from agency.contracts import validate_contract
from agency.runtime import make_lifecycle_event_id

WATCH_THRESHOLD = 0.5


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
    deterministic = _engine_decision(pack)
    policy_gates = [_evidence_breadth_gate(pack)]

    report: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": str(pack["cycle_id"]),
        "ticker": str(pack["ticker"]),
        "as_of": str(pack["as_of"]),
        "generated_at": report_generated_at,
        "final_action": deterministic["action"],
        "final_conviction": deterministic["conviction"],
        "deterministic": deterministic,
        "llm_review": _llm_not_enabled_review(),
        "policy_gates": policy_gates,
        "risk_flags": [],
        "evidence_pack": pack,
        "trade_plan": None,
    }
    validate_contract("selection-report", report)

    lifecycle_event = _deterministic_lifecycle_event(report)
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return DeterministicSelectionResult(report, lifecycle_event)


def _engine_decision(evidence_pack: Mapping[str, object]) -> dict[str, object]:
    blockers = _data_quality_blockers(evidence_pack)
    signals = _actionable_signals(evidence_pack)
    if blockers:
        return _decision("NO_TRADE", 0.0, 0.0, ["data_quality_blocked"], blockers)
    if not signals:
        return _decision("NO_TRADE", 0.0, 0.0, ["no_actionable_signals"], [])

    score = sum(_signal_score(signal) for signal in signals) / len(signals)
    conviction = _clamp(abs(score))
    if score >= WATCH_THRESHOLD:
        return _decision("WATCH", score, conviction, _reason_codes(signals), [])
    if score <= -WATCH_THRESHOLD:
        return _decision("NO_TRADE", score, conviction, ["bearish_action_not_enabled"], [])
    return _decision("NO_TRADE", score, conviction, ["signal_strength_below_threshold"], [])


def _decision(
    action: str,
    score: float,
    conviction: float,
    reason_codes: list[str],
    blockers: list[str],
) -> dict[str, object]:
    return {
        "action": action,
        "score": round(score, 6),
        "conviction": round(conviction, 6),
        "reason_codes": reason_codes,
        "blockers": blockers,
    }


def _evidence_breadth_gate(evidence_pack: Mapping[str, object]) -> dict[str, object]:
    data_quality = _data_quality(evidence_pack)
    blockers = _data_quality_blockers(evidence_pack)
    source_count = _int_field(data_quality, "source_count")
    confirmed_count = _int_field(data_quality, "confirmed_signal_count")
    if blockers:
        return {"name": "evidence_breadth", "status": "BLOCK", "reason": blockers[0]}
    if source_count < 1 or confirmed_count < 1:
        return {
            "name": "evidence_breadth",
            "status": "WARN",
            "reason": "insufficient confirmed evidence",
        }
    return {"name": "evidence_breadth", "status": "PASS", "reason": "confirmed evidence present"}


def _llm_not_enabled_review() -> dict[str, object]:
    return {
        "action": "NO_REVIEW",
        "confidence": 0.0,
        "rationale": "LLM review is not enabled for the deterministic stub.",
        "supporting_factors": [],
        "concerns": [],
    }


def _deterministic_lifecycle_event(report: Mapping[str, object]) -> dict[str, object]:
    event_time = str(report["generated_at"])
    event_type = "DETERMINISTIC_ACTION"
    final_action = str(report["final_action"])
    status = "ACTIONABLE" if final_action == "WATCH" else "BLOCKED"
    deterministic = _mapping_field(report, "deterministic")
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


def _data_quality(evidence_pack: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping_field(evidence_pack, "data_quality")


def _data_quality_blockers(evidence_pack: Mapping[str, object]) -> list[str]:
    return _string_list(_data_quality(evidence_pack), "blockers")


def _actionable_signals(evidence_pack: Mapping[str, object]) -> list[Mapping[str, object]]:
    items = _list_field(evidence_pack, "actionable_signals")
    return [cast(Mapping[str, object], item) for item in items]


def _reason_codes(signals: list[Mapping[str, object]]) -> list[str]:
    codes: list[str] = []
    for signal in signals:
        codes.extend(_string_list(signal, "reason_codes"))
    return codes or ["actionable_signal_present"]


def _first_reason(deterministic: Mapping[str, object]) -> str:
    reasons = _string_list(deterministic, "reason_codes")
    if reasons:
        return reasons[0]
    return "deterministic selection recorded"


def _signal_score(signal: Mapping[str, object]) -> float:
    return _float_field(signal, "score")


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


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
