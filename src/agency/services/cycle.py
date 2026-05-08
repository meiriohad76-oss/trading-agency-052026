from __future__ import annotations

from collections import defaultdict
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
from agency.runtime.readiness_sources import relevant_source_health, used_sources
from agency.services.evidence_pack import build_evidence_pack
from agency.services.execution_preview import build_execution_previews
from agency.services.final_selection import build_final_selection
from agency.services.risk import PortfolioPolicy, build_risk_decisions
from agency.services.runtime_audit import build_runtime_audit_artifacts

RuntimePayloadWriter = Callable[[AsyncSession, Mapping[str, object]], Awaitable[None]]


@dataclass(frozen=True)
class RuntimeCycleResult:
    cycle_id: str
    as_of: str
    generated_at: str
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


def build_runtime_cycle(
    *,
    cycle_id: str,
    as_of: str,
    generated_at: str,
    source_health: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
    tickers: Sequence[str] = (),
    policy: PortfolioPolicy | None = None,
    current_gross_exposure_pct: float = 0.0,
) -> RuntimeCycleResult:
    """Run the local paper cycle over validated signal-result payloads."""
    normalized_sources = [_validated_source(source) for source in source_health]
    normalized_signals = [_validated_signal(signal) for signal in signals]
    evidence_packs = _evidence_packs(
        cycle_id=cycle_id,
        as_of=as_of,
        generated_at=generated_at,
        tickers=tickers,
        signals=normalized_signals,
    )
    final_results = [
        build_final_selection(pack, generated_at=generated_at) for pack in evidence_packs
    ]
    selection_reports = [result.selection_report for result in final_results]
    risk_source_health = relevant_source_health(
        normalized_sources,
        used_sources=used_sources(selection_reports),
    )
    risk_results = build_risk_decisions(
        selection_reports,
        risk_source_health,
        generated_at=generated_at,
        policy=policy,
        current_gross_exposure_pct=current_gross_exposure_pct,
    )
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results],
        generated_at=generated_at,
        policy=policy,
    )
    cycle = RuntimeCycleResult(
        cycle_id=cycle_id,
        as_of=as_of,
        generated_at=generated_at,
        source_health=normalized_sources,
        evidence_packs=evidence_packs,
        selection_reports=selection_reports,
        selection_lifecycle_events=[
            event for result in final_results for event in result.lifecycle_events
        ],
        risk_decisions=[result.risk_decision for result in risk_results],
        risk_lifecycle_events=[result.lifecycle_event for result in risk_results],
        execution_previews=[result.preview for result in preview_results],
        execution_lifecycle_events=[result.lifecycle_event for result in preview_results],
    )
    _validate_cycle(cycle)
    return cycle


async def persist_runtime_cycle(
    session: AsyncSession,
    cycle: RuntimeCycleResult,
    *,
    source_writer: RuntimePayloadWriter = upsert_source_health,
    report_writer: RuntimePayloadWriter = upsert_selection_report,
    risk_writer: RuntimePayloadWriter = upsert_risk_decision,
    lifecycle_writer: RuntimePayloadWriter = record_candidate_lifecycle_event,
    agent_run_writer: RuntimePayloadWriter = upsert_agent_run,
    risk_snapshot_writer: RuntimePayloadWriter = record_risk_snapshot,
    execution_state_writer: RuntimePayloadWriter = record_execution_state,
    audit_trigger: str = "MANUAL",
    audit_started_at: str | None = None,
    audit_finished_at: str | None = None,
) -> RuntimeCycleResult:
    _validate_cycle(cycle)
    audit = build_runtime_audit_artifacts(
        cycle_id=cycle.cycle_id,
        as_of=cycle.as_of,
        generated_at=cycle.generated_at,
        source_health=cycle.source_health,
        evidence_packs=cycle.evidence_packs,
        selection_reports=cycle.selection_reports,
        risk_decisions=cycle.risk_decisions,
        execution_previews=cycle.execution_previews,
        trigger=audit_trigger,
        started_at=audit_started_at,
        finished_at=audit_finished_at,
    )
    await agent_run_writer(session, audit.agent_run)
    for source in cycle.source_health:
        await source_writer(session, source)
    for report in cycle.selection_reports:
        await report_writer(session, report)
    for decision in cycle.risk_decisions:
        await risk_writer(session, decision)
    for event in cycle.all_lifecycle_events:
        await lifecycle_writer(session, event)
    for snapshot in audit.risk_snapshots:
        await risk_snapshot_writer(session, snapshot)
    for state in audit.execution_states:
        await execution_state_writer(session, state)
    return cycle


def _evidence_packs(
    *,
    cycle_id: str,
    as_of: str,
    generated_at: str,
    tickers: Sequence[str],
    signals: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for signal in signals:
        grouped[str(signal["ticker"]).upper()].append(signal)
    requested_tickers = {ticker.upper() for ticker in tickers}
    requested_tickers.update(grouped)
    return [
        build_evidence_pack(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
            generated_at=generated_at,
            signals=grouped[ticker],
        )
        for ticker in sorted(requested_tickers)
    ]


def _validated_source(source: Mapping[str, object]) -> dict[str, object]:
    validate_contract("data-source-health", source)
    return dict(source)


def _validated_signal(signal: Mapping[str, object]) -> dict[str, object]:
    validate_contract("signal-result", signal)
    return dict(signal)


def _validate_cycle(cycle: RuntimeCycleResult) -> None:
    for source in cycle.source_health:
        validate_contract("data-source-health", source)
    for pack in cycle.evidence_packs:
        validate_contract("evidence-pack", pack)
    for report in cycle.selection_reports:
        validate_contract("selection-report", report)
    for decision in cycle.risk_decisions:
        validate_contract("risk-decision", decision)
    for preview in cycle.execution_previews:
        validate_contract("execution-preview", preview)
    for event in cycle.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)
