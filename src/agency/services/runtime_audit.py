from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from agency.contracts import validate_contract


@dataclass(frozen=True)
class RuntimeAuditArtifacts:
    agent_run: dict[str, object]
    risk_snapshots: list[dict[str, object]]
    execution_states: list[dict[str, object]]


def build_runtime_audit_artifacts(
    *,
    cycle_id: str,
    as_of: str,
    generated_at: str,
    source_health: Sequence[Mapping[str, object]],
    evidence_packs: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    execution_previews: Sequence[Mapping[str, object]],
    trigger: str = "MANUAL",
    status: str = "SUCCEEDED",
    started_at: str | None = None,
    finished_at: str | None = None,
) -> RuntimeAuditArtifacts:
    run_id = runtime_run_id(cycle_id=cycle_id, trigger=trigger)
    artifacts = RuntimeAuditArtifacts(
        agent_run=_agent_run(
            run_id=run_id,
            cycle_id=cycle_id,
            trigger=trigger,
            status=status,
            started_at=started_at or generated_at,
            finished_at=finished_at or generated_at,
            source_health=source_health,
            evidence_packs=evidence_packs,
            selection_reports=selection_reports,
            risk_decisions=risk_decisions,
            execution_previews=execution_previews,
        ),
        risk_snapshots=[
            _risk_snapshot(decision, as_of=as_of, generated_at=generated_at)
            for decision in risk_decisions
        ],
        execution_states=[_execution_state(preview) for preview in execution_previews],
    )
    _validate_artifacts(artifacts)
    return artifacts


def runtime_run_id(*, cycle_id: str, trigger: str) -> str:
    return f"{cycle_id}:{trigger.lower()}:runtime-cycle"


def _agent_run(
    *,
    run_id: str,
    cycle_id: str,
    trigger: str,
    status: str,
    started_at: str,
    finished_at: str,
    source_health: Sequence[Mapping[str, object]],
    evidence_packs: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    execution_previews: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "cycle_id": cycle_id,
        "agent_name": "runtime-cycle",
        "status": status,
        "trigger": trigger,
        "started_at": started_at,
        "finished_at": finished_at,
        "payload": {
            "source_count": len(source_health),
            "evidence_pack_count": len(evidence_packs),
            "selection_report_count": len(selection_reports),
            "risk_decision_count": len(risk_decisions),
            "execution_preview_count": len(execution_previews),
        },
    }


def _risk_snapshot(
    decision: Mapping[str, object],
    *,
    as_of: str,
    generated_at: str,
) -> dict[str, object]:
    ticker = str(decision["ticker"])
    return {
        "schema_version": "0.1.0",
        "snapshot_id": f"{decision['cycle_id']}:{ticker}:risk-snapshot",
        "cycle_id": str(decision["cycle_id"]),
        "ticker": ticker,
        "as_of": as_of,
        "generated_at": generated_at,
        "gross_exposure_pct": _float_field(decision, "projected_gross_exposure_pct"),
        "risk_level": _risk_level(str(decision["decision"])),
        "payload": {"risk_decision": dict(decision)},
    }


def _execution_state(preview: Mapping[str, object]) -> dict[str, object]:
    ticker = str(preview["ticker"])
    return {
        "schema_version": "0.1.0",
        "state_id": f"{preview['cycle_id']}:{ticker}:execution-preview",
        "cycle_id": str(preview["cycle_id"]),
        "ticker": ticker,
        "execution_id": f"{preview['cycle_id']}:{ticker}:paper-preview",
        "state": str(preview["preview_state"]),
        "event_time": str(preview["generated_at"]),
        "reason": _first_reason(preview),
        "payload": {"execution_preview": dict(preview)},
    }


def _risk_level(decision: str) -> str:
    if decision == "ALLOW":
        return "LOW"
    if decision == "WARN":
        return "MEDIUM"
    return "BLOCKED"


def _first_reason(preview: Mapping[str, object]) -> str:
    reasons = preview["reasons"]
    if not isinstance(reasons, list) or not reasons:
        return "paper preview state recorded"
    return str(reasons[0])


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _validate_artifacts(artifacts: RuntimeAuditArtifacts) -> None:
    validate_contract("agent-run", artifacts.agent_run)
    for snapshot in artifacts.risk_snapshots:
        validate_contract("risk-snapshot", snapshot)
    for state in artifacts.execution_states:
        validate_contract("execution-state", state)


def now_utc_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
