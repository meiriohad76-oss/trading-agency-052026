from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from agency.contracts import validate_contract
from agency.services.risk import PortfolioPolicy
from agency.services.selection_events import build_lifecycle_event

ORDER_SIDES = {"BUY", "SELL", "SHORT", "COVER"}


@dataclass(frozen=True)
class ExecutionPreviewResult:
    """Execution preview plus lifecycle audit event."""

    preview: dict[str, object]
    lifecycle_event: dict[str, object]


def build_execution_previews(
    risk_decisions: Sequence[Mapping[str, object]],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
) -> list[ExecutionPreviewResult]:
    return [
        build_execution_preview(
            risk_decision,
            generated_at=generated_at,
            policy=policy,
        )
        for risk_decision in risk_decisions
    ]


def build_execution_preview(
    risk_decision: Mapping[str, object],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
) -> ExecutionPreviewResult:
    """Build a no-submit paper execution preview from a risk decision."""
    validate_contract("risk-decision", risk_decision)
    normalized_policy = policy or PortfolioPolicy()
    final_action = str(risk_decision["final_action"])
    risk_state = str(risk_decision["decision"])
    side = final_action if final_action in ORDER_SIDES else "NONE"
    preview_state = _preview_state(risk_state, side)
    reasons = _preview_reasons(risk_decision, preview_state, side)
    generated = generated_at or _now_utc()
    preview: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": str(risk_decision["cycle_id"]),
        "ticker": str(risk_decision["ticker"]),
        "as_of": str(risk_decision["as_of"]),
        "generated_at": generated,
        "preview_state": preview_state,
        "side": side,
        "quantity": None,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "notional": None,
        "position_size_pct": risk_decision["position_size_pct"],
        "time_in_force": "DAY" if preview_state == "READY" else None,
        "risk_decision": risk_state,
        "submit_enabled": normalized_policy.broker_submit_enabled and preview_state == "READY",
        "reasons": reasons,
    }
    validate_contract("execution-preview", preview)
    lifecycle_event = build_lifecycle_event(
        cycle_id=str(preview["cycle_id"]),
        ticker=str(preview["ticker"]),
        event_type="EXECUTION_PREVIEW",
        event_time=generated,
        status=_lifecycle_status(preview_state),
        reason=reasons[0],
        payload={"execution_preview": dict(preview)},
    )
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return ExecutionPreviewResult(preview, lifecycle_event)


def _preview_state(risk_state: str, side: str) -> str:
    if risk_state == "BLOCK":
        return "BLOCKED"
    if side == "NONE":
        return "DISABLED"
    return "READY" if risk_state == "ALLOW" else "BLOCKED"


def _preview_reasons(
    risk_decision: Mapping[str, object],
    preview_state: str,
    side: str,
) -> list[str]:
    if preview_state == "READY":
        return ["paper preview generated; broker submission remains gated"]
    if side == "NONE":
        return [f"{risk_decision['final_action']} has no order side"]
    return [str(reason) for reason in _list_field(risk_decision, "reasons")]


def _lifecycle_status(preview_state: str) -> str:
    if preview_state == "READY":
        return "RECORDED"
    if preview_state == "DISABLED":
        return "SUPPRESSED"
    return "BLOCKED"


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
