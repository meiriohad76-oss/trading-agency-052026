from __future__ import annotations

from service_fixtures import source_health

from agency.contracts import validate_contract
from agency.services import build_runtime_audit_artifacts, build_runtime_cycle, build_signal_result
from agency.services.runtime_audit import runtime_run_id

CYCLE_ID = "cycle-2026-05-08T143000Z"
AS_OF = "2026-05-08T14:30:00Z"
GENERATED_AT = "2026-05-08T14:31:00Z"
STARTED_AT = "2026-05-08T14:30:10Z"
FINISHED_AT = "2026-05-08T14:31:20Z"


def test_runtime_audit_artifacts_are_contract_valid() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal()],
    )

    audit = build_runtime_audit_artifacts(
        cycle_id=cycle.cycle_id,
        as_of=cycle.as_of,
        generated_at=cycle.generated_at,
        source_health=cycle.source_health,
        evidence_packs=cycle.evidence_packs,
        selection_reports=cycle.selection_reports,
        risk_decisions=cycle.risk_decisions,
        execution_previews=cycle.execution_previews,
        trigger="SCHEDULED",
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
    )

    validate_contract("agent-run", audit.agent_run)
    validate_contract("risk-snapshot", audit.risk_snapshots[0])
    validate_contract("execution-state", audit.execution_states[0])
    assert audit.agent_run["run_id"] == runtime_run_id(
        cycle_id=CYCLE_ID,
        trigger="SCHEDULED",
    )
    assert audit.agent_run["payload"]["selection_report_count"] == 1
    assert audit.risk_snapshots[0]["ticker"] == "AAPL"
    assert audit.execution_states[0]["execution_id"] == f"{CYCLE_ID}:AAPL:paper-preview"


def _signal() -> dict[str, object]:
    return build_signal_result(
        cycle_id=CYCLE_ID,
        ticker="AAPL",
        as_of=AS_OF,
        lane="fundamentals",
        score=0.7,
        provenance={
            "source": "sec-edgar",
            "source_tier": "OFFICIAL_FILING",
            "source_id": "CIK0000320193",
            "source_url": None,
            "timestamp_observed": "2026-05-08T14:00:00Z",
            "timestamp_as_of": "2026-05-08T13:59:00Z",
            "freshness": "FRESH",
            "confidence": 1.0,
            "verification_level": "CONFIRMED",
        },
        confidence=0.9,
    )
