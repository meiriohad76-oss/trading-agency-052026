from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.runtime import (
    record_candidate_lifecycle_event,
    record_execution_state,
    record_risk_snapshot,
    upsert_agent_run,
    upsert_risk_decision,
    upsert_selection_report,
    upsert_source_health,
)
from agency.services.evidence_pack import build_evidence_pack
from agency.services.execution_preview import build_execution_previews
from agency.services.final_selection import build_final_selection
from agency.services.risk import build_risk_decisions
from agency.services.runtime_audit import build_runtime_audit_artifacts
from agency.services.selection_events import build_report_lifecycle_event, status_for_action
from agency.services.signal_adapters import build_signal_result

DEMO_CYCLE_ID = "demo-cycle-1"
DEMO_AS_OF = "2026-05-07T" "14:" "30:00Z"
DEMO_GENERATED_AT = "2026-05-07T14:31:00Z"


RuntimePayloadWriter = Callable[[AsyncSession, Mapping[str, object]], Awaitable[None]]


@dataclass(frozen=True)
class DemoRuntimeSeed:
    """Schema-valid runtime artifacts for local dashboard demos."""

    source_health: list[dict[str, object]]
    evidence_packs: list[dict[str, object]]
    selection_reports: list[dict[str, object]]
    selection_lifecycle_events: list[dict[str, object]]
    risk_decisions: list[dict[str, object]]
    risk_lifecycle_events: list[dict[str, object]]
    execution_previews: list[dict[str, object]]
    execution_lifecycle_events: list[dict[str, object]]

    @property
    def all_lifecycle_events(self) -> list[dict[str, object]]:
        return [
            *self.selection_lifecycle_events,
            *self.risk_lifecycle_events,
            *self.execution_lifecycle_events,
        ]


async def persist_demo_runtime_seed(
    session: AsyncSession,
    seed: DemoRuntimeSeed | None = None,
    *,
    source_writer: RuntimePayloadWriter = upsert_source_health,
    report_writer: RuntimePayloadWriter = upsert_selection_report,
    risk_writer: RuntimePayloadWriter = upsert_risk_decision,
    lifecycle_writer: RuntimePayloadWriter = record_candidate_lifecycle_event,
    agent_run_writer: RuntimePayloadWriter = upsert_agent_run,
    risk_snapshot_writer: RuntimePayloadWriter = record_risk_snapshot,
    execution_state_writer: RuntimePayloadWriter = record_execution_state,
) -> DemoRuntimeSeed:
    """Persist a deterministic paper/demo runtime cycle for local development."""
    runtime_seed = build_demo_runtime_seed() if seed is None else seed
    _validate_seed(runtime_seed)
    audit = build_runtime_audit_artifacts(
        cycle_id=DEMO_CYCLE_ID,
        as_of=DEMO_AS_OF,
        generated_at=DEMO_GENERATED_AT,
        source_health=runtime_seed.source_health,
        evidence_packs=runtime_seed.evidence_packs,
        selection_reports=runtime_seed.selection_reports,
        risk_decisions=runtime_seed.risk_decisions,
        execution_previews=runtime_seed.execution_previews,
        trigger="SYSTEM",
        started_at=DEMO_GENERATED_AT,
        finished_at=DEMO_GENERATED_AT,
    )
    await agent_run_writer(session, audit.agent_run)
    for source in runtime_seed.source_health:
        await source_writer(session, source)
    for report in runtime_seed.selection_reports:
        await report_writer(session, report)
    for decision in runtime_seed.risk_decisions:
        await risk_writer(session, decision)
    for event in runtime_seed.all_lifecycle_events:
        await lifecycle_writer(session, event)
    for snapshot in audit.risk_snapshots:
        await risk_snapshot_writer(session, snapshot)
    for state in audit.execution_states:
        await execution_state_writer(session, state)
    return runtime_seed


def build_demo_runtime_seed() -> DemoRuntimeSeed:
    """Build deterministic sample data that exercises dashboard states."""
    source_health = [_source_health("demo-runtime-seed"), _source_health("yfinance-daily")]
    selection_reports = [
        _selection_report(
            ticker="NVDA",
            score=0.82,
            final_action="BUY",
            final_conviction=0.82,
            policy_status="PASS",
            policy_reason="confirmed evidence present",
            rationale="Strong fundamentals and fresh market confirmation.",
        ),
        _selection_report(
            ticker="HD",
            score=0.71,
            final_action="NO_TRADE",
            final_conviction=0.0,
            policy_status="BLOCK",
            policy_reason="sector exposure cap reached",
            risk_flags=["sector_exposure_cap"],
            rationale="Constructive setup, blocked by portfolio policy.",
        ),
        _selection_report(
            ticker="UNH",
            score=0.64,
            final_action="WATCH",
            final_conviction=0.64,
            policy_status="WARN",
            policy_reason="thin evidence breadth",
            risk_flags=["evidence_breadth_low"],
            rationale="Watch-only setup with incomplete corroboration.",
        ),
    ]
    selection_lifecycle_events = [
        event
        for report in selection_reports
        for event in _selection_lifecycle_events(report)
    ]
    risk_results = build_risk_decisions(
        selection_reports,
        source_health,
        generated_at=DEMO_GENERATED_AT,
    )
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results],
        generated_at=DEMO_GENERATED_AT,
    )
    seed = DemoRuntimeSeed(
        source_health=source_health,
        evidence_packs=_evidence_packs_from_reports(selection_reports),
        selection_reports=selection_reports,
        selection_lifecycle_events=selection_lifecycle_events,
        risk_decisions=[result.risk_decision for result in risk_results],
        risk_lifecycle_events=[result.lifecycle_event for result in risk_results],
        execution_previews=[result.preview for result in preview_results],
        execution_lifecycle_events=[result.lifecycle_event for result in preview_results],
    )
    _validate_seed(seed)
    return seed


def _selection_report(
    *,
    ticker: str,
    score: float,
    final_action: str,
    final_conviction: float,
    policy_status: str,
    policy_reason: str,
    rationale: str,
    risk_flags: Sequence[str] | None = None,
) -> dict[str, object]:
    report = build_final_selection(_evidence_pack(ticker=ticker, score=score)).selection_report
    deterministic = _mapping_field(report, "deterministic")
    llm_review = _mapping_field(report, "llm_review")
    deterministic["action"] = final_action
    deterministic["conviction"] = final_conviction
    llm_review["action"] = final_action
    llm_review["confidence"] = min(0.95, final_conviction)
    llm_review["rationale"] = rationale
    report["final_action"] = final_action
    report["final_conviction"] = final_conviction
    report["policy_gates"] = [
        {"name": "demo_policy", "status": policy_status, "reason": policy_reason}
    ]
    report["risk_flags"] = list(risk_flags or [])
    is_buy = final_action == "BUY"
    report["schema_version"] = "0.2.0"
    report["trade_plan"] = {
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "trailing_stop_pct": 0.03 if is_buy else None,
        "position_size": 10.0 if is_buy else None,
        "position_pct": 0.1 if is_buy else None,
        "time_in_force": "DAY" if is_buy else None,
        "notes": ["demo-only paper artifact"],
    }
    validate_contract("selection-report", report)
    return report


def _selection_lifecycle_events(report: Mapping[str, object]) -> list[dict[str, object]]:
    deterministic = _mapping_field(report, "deterministic")
    llm_review = _mapping_field(report, "llm_review")
    action = str(report["final_action"])
    events = [
        build_report_lifecycle_event(
            report,
            event_type="DETERMINISTIC_ACTION",
            status=status_for_action(str(deterministic["action"]), deterministic),
            reason="demo deterministic decision",
            payload={"deterministic": dict(deterministic)},
        ),
        build_report_lifecycle_event(
            report,
            event_type="LLM_ACTION",
            status="CONTEXT_ONLY",
            reason="demo llm review recorded",
            payload={"llm_review": dict(llm_review)},
        ),
        build_report_lifecycle_event(
            report,
            event_type="FINAL_ACTION",
            status=status_for_action(action, report),
            reason="demo final selection recorded",
            payload={
                "final_action": action,
                "final_conviction": report["final_conviction"],
                "risk_flags": report["risk_flags"],
            },
        ),
    ]
    for event in events:
        validate_contract("candidate-lifecycle-event", event)
    return events


def _evidence_pack(*, ticker: str, score: float) -> dict[str, object]:
    return build_evidence_pack(
        cycle_id=DEMO_CYCLE_ID,
        ticker=ticker,
        as_of=DEMO_AS_OF,
        generated_at=DEMO_GENERATED_AT,
        signals=[
            build_signal_result(
                cycle_id=DEMO_CYCLE_ID,
                ticker=ticker,
                as_of=DEMO_AS_OF,
                lane="fundamentals",
                score=score,
                provenance=_provenance(ticker, "fundamentals"),
                confidence=0.9,
            ),
            build_signal_result(
                cycle_id=DEMO_CYCLE_ID,
                ticker=ticker,
                as_of=DEMO_AS_OF,
                lane="insider",
                score=score,
                provenance=_provenance(ticker, "insider"),
                confidence=0.9,
            ),
        ],
    )


def _source_health(source: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "0.1.0",
        "source": source,
        "source_tier": "MARKET_DATA",
        "status": "HEALTHY",
        "checked_at": DEMO_GENERATED_AT,
        "freshness": "FRESH",
        "last_success_at": DEMO_AS_OF,
        "observed_lag_seconds": 60,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": ["demo runtime seed"],
    }
    validate_contract("data-source-health", payload)
    return payload


def _provenance(ticker: str, lane: str) -> dict[str, object]:
    return {
        "source": "demo-runtime-seed",
        "source_tier": "MARKET_DATA",
        "source_id": f"{ticker}-{lane}",
        "source_url": None,
        "timestamp_observed": DEMO_GENERATED_AT,
        "timestamp_as_of": DEMO_AS_OF,
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }


def _validate_seed(seed: DemoRuntimeSeed) -> None:
    for source in seed.source_health:
        validate_contract("data-source-health", source)
    for pack in seed.evidence_packs:
        validate_contract("evidence-pack", pack)
    for report in seed.selection_reports:
        validate_contract("selection-report", report)
    for decision in seed.risk_decisions:
        validate_contract("risk-decision", decision)
    for preview in seed.execution_previews:
        validate_contract("execution-preview", preview)
    for event in seed.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)


def _mapping_field(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a dict")
    return value


def _evidence_packs_from_reports(
    reports: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [_mapping_field(report, "evidence_pack") for report in reports]
