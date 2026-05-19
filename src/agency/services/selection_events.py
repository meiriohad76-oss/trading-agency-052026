from __future__ import annotations

from collections.abc import Mapping

from agency.runtime import make_lifecycle_event_id


def build_lifecycle_event(
    *,
    cycle_id: str,
    ticker: str,
    event_type: str,
    event_time: str,
    status: str,
    reason: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Build a candidate lifecycle event payload with deterministic identity."""
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
        "payload": payload,
    }


def build_report_lifecycle_event(
    report: Mapping[str, object],
    *,
    event_type: str,
    status: str,
    reason: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Build a lifecycle event keyed to a selection report."""
    return build_lifecycle_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        event_type=event_type,
        event_time=str(report["generated_at"]),
        status=status,
        reason=reason,
        payload=payload,
    )


def build_llm_lifecycle_event(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    llm_review: Mapping[str, object],
    *,
    event_time: str,
) -> dict[str, object]:
    """Build an LLM_ACTION lifecycle event from a review payload."""
    action = str(llm_review.get("action", "NO_REVIEW"))
    status = "CONTEXT_ONLY" if action == "NO_REVIEW" else "RECORDED"
    reason = "llm review unavailable" if action == "NO_REVIEW" else "llm review recorded"
    return build_lifecycle_event(
        cycle_id=str(evidence_pack["cycle_id"]),
        ticker=str(evidence_pack["ticker"]),
        event_type="LLM_ACTION",
        event_time=event_time,
        status=status,
        reason=reason,
        payload={
            "llm_review": dict(llm_review),
            "deterministic_action": deterministic_decision.get("action", "UNKNOWN"),
        },
    )


def status_for_action(action: str, payload: Mapping[str, object]) -> str:
    blockers = _string_list(payload, "blockers") if "blockers" in payload else []
    if action == "WATCH":
        return "ACTIONABLE"
    if action == "CLOSE_REVIEW":
        return "WARN"
    if blockers or action == "NO_TRADE":
        return "BLOCKED"
    return "RECORDED"


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return [str(item) for item in value]
