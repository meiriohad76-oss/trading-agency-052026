from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.runtime import (
    record_candidate_lifecycle_event,
    record_execution_state,
    record_prompt_audit,
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
from agency.services.paper_trade_promotion import (
    PaperTradePromotionConfig,
    promote_paper_trade_reports,
)
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
    prompt_audits: list[dict[str, object]] = field(default_factory=list)
    news_consumption_items: list[dict[str, object]] = field(default_factory=list)

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
    account: Mapping[str, object] | None = None,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    pending_opening_order_exposure_pct: float = 0.0,
    llm_reviews: Mapping[str, Mapping[str, object]] | None = None,
    llm_lifecycle_events: Sequence[Mapping[str, object]] = (),
    llm_prompt_audits: Sequence[Mapping[str, object]] = (),
    paper_trade_review_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    paper_trade_broker_ready: bool = False,
    paper_trade_promotion_config: PaperTradePromotionConfig | None = None,
    market_regime_snapshot: Mapping[str, object] | None = None,
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
    return build_runtime_cycle_from_evidence_packs(
        cycle_id=cycle_id,
        as_of=as_of,
        generated_at=generated_at,
        source_health=normalized_sources,
        evidence_packs=evidence_packs,
        policy=policy,
        current_gross_exposure_pct=current_gross_exposure_pct,
        account=account,
        positions=positions,
        open_orders=open_orders,
        pending_opening_order_exposure_pct=pending_opening_order_exposure_pct,
        llm_reviews=llm_reviews,
        llm_lifecycle_events=llm_lifecycle_events,
        llm_prompt_audits=llm_prompt_audits,
        paper_trade_review_states=paper_trade_review_states,
        paper_trade_broker_ready=paper_trade_broker_ready,
        paper_trade_promotion_config=paper_trade_promotion_config,
        market_regime_snapshot=market_regime_snapshot,
    )


def build_runtime_cycle_from_evidence_packs(
    *,
    cycle_id: str,
    as_of: str,
    generated_at: str,
    source_health: Sequence[Mapping[str, object]],
    evidence_packs: Sequence[Mapping[str, object]],
    policy: PortfolioPolicy | None = None,
    current_gross_exposure_pct: float = 0.0,
    account: Mapping[str, object] | None = None,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    pending_opening_order_exposure_pct: float = 0.0,
    llm_reviews: Mapping[str, Mapping[str, object]] | None = None,
    llm_lifecycle_events: Sequence[Mapping[str, object]] = (),
    llm_prompt_audits: Sequence[Mapping[str, object]] = (),
    paper_trade_review_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    paper_trade_broker_ready: bool = False,
    paper_trade_promotion_config: PaperTradePromotionConfig | None = None,
    market_regime_snapshot: Mapping[str, object] | None = None,
) -> RuntimeCycleResult:
    """Run the paper cycle over prebuilt evidence packs and optional LLM reviews."""
    normalized_sources = [_validated_source(source) for source in source_health]
    normalized_packs = [_validated_evidence_pack(pack) for pack in evidence_packs]
    review_index = _llm_review_index(llm_reviews)
    event_index = _llm_lifecycle_event_index(cycle_id, llm_lifecycle_events)
    final_results = [
        build_final_selection(
            pack,
            generated_at=generated_at,
            llm_review=review_index.get(str(pack["ticker"]).upper()),
            llm_lifecycle_event=event_index.get(str(pack["ticker"]).upper()),
        )
        for pack in normalized_packs
    ]
    selection_reports = [result.selection_report for result in final_results]
    execution_selection_reports = _paper_trade_execution_reports(
        selection_reports,
        review_states=paper_trade_review_states,
        positions=positions,
        open_orders=open_orders,
        broker_ready=paper_trade_broker_ready,
        config=paper_trade_promotion_config,
    )
    risk_source_health = relevant_source_health(
        normalized_sources,
        used_sources=used_sources(execution_selection_reports),
    )
    risk_results = build_risk_decisions(
        execution_selection_reports,
        risk_source_health,
        generated_at=generated_at,
        policy=policy,
        market_regime_snapshot=market_regime_snapshot,
        current_gross_exposure_pct=current_gross_exposure_pct,
        pending_opening_order_exposure_pct=pending_opening_order_exposure_pct,
    )
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results],
        generated_at=generated_at,
        policy=policy,
        account=account,
        positions=positions,
        open_orders=open_orders,
    )
    cycle = RuntimeCycleResult(
        cycle_id=cycle_id,
        as_of=as_of,
        generated_at=generated_at,
        source_health=normalized_sources,
        evidence_packs=normalized_packs,
        selection_reports=selection_reports,
        selection_lifecycle_events=[
            event for result in final_results for event in result.lifecycle_events
        ],
        risk_decisions=[result.risk_decision for result in risk_results],
        risk_lifecycle_events=[result.lifecycle_event for result in risk_results],
        execution_previews=[result.preview for result in preview_results],
        execution_lifecycle_events=[result.lifecycle_event for result in preview_results],
        prompt_audits=[
            _validated_prompt_audit(audit, cycle_id=cycle_id)
            for audit in llm_prompt_audits
        ],
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
    prompt_audit_writer: RuntimePayloadWriter = record_prompt_audit,
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
    for prompt_audit in cycle.prompt_audits:
        await prompt_audit_writer(session, _prompt_audit_with_run_id(prompt_audit, audit.agent_run))
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


def _validated_evidence_pack(evidence_pack: Mapping[str, object]) -> dict[str, object]:
    validate_contract("evidence-pack", evidence_pack)
    return dict(evidence_pack)


def _llm_review_index(
    llm_reviews: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, object]]:
    if llm_reviews is None:
        return {}
    return {ticker.upper(): dict(review) for ticker, review in llm_reviews.items()}


def _paper_trade_execution_reports(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None,
    positions: Sequence[Mapping[str, object]],
    open_orders: Sequence[Mapping[str, object]],
    broker_ready: bool,
    config: PaperTradePromotionConfig | None,
) -> list[dict[str, object]]:
    if review_states is None and not broker_ready and config is None:
        return [dict(report) for report in selection_reports]
    return promote_paper_trade_reports(
        selection_reports,
        review_states={} if review_states is None else review_states,
        positions=positions,
        open_orders=open_orders,
        broker_ready=broker_ready,
        config=config,
    )


def _llm_lifecycle_event_index(
    cycle_id: str,
    llm_lifecycle_events: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for event in llm_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)
        if str(event.get("event_type", "")).upper() == "LLM_ACTION":
            if str(event.get("cycle_id", "")) != cycle_id:
                raise ValueError("LLM lifecycle event cycle_id does not match runtime cycle")
            output[str(event.get("ticker", "")).upper()] = dict(event)
    return output


def _validated_prompt_audit(
    prompt_audit: Mapping[str, object],
    *,
    cycle_id: str,
) -> dict[str, object]:
    validate_contract("prompt-audit", prompt_audit)
    if str(prompt_audit.get("cycle_id", "")) != cycle_id:
        raise ValueError("LLM prompt audit cycle_id does not match runtime cycle")
    return dict(prompt_audit)


def _prompt_audit_with_run_id(
    prompt_audit: Mapping[str, object],
    agent_run: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(prompt_audit)
    if payload.get("run_id") is None:
        payload["run_id"] = str(agent_run["run_id"])
    validate_contract("prompt-audit", payload)
    return payload


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
    for prompt_audit in cycle.prompt_audits:
        validate_contract("prompt-audit", prompt_audit)
