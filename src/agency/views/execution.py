"""View-model constructors for the execution page."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from urllib.parse import urlencode

from data_refresh.market_calendar import classify_market_session

from agency.api.audit import runtime_execution_states
from agency.api.health import runtime_data_source_status
from agency.db import get_session
from agency.runtime import (
    build_live_readiness,
    execution_freshness_gate,
    scheduler_work_queue_context,
)
from agency.runtime.data_load_status import load_data_load_status
from agency.runtime.data_refresh_progress import load_data_refresh_progress
from agency.services import (
    TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG,
    LeveragedAlternativePolicy,
    PaperTradePromotionConfig,
    PortfolioPolicy,
    build_execution_previews,
    build_leveraged_alternative_review,
    build_risk_decisions,
    load_active_portfolio_policy,
    load_leveraged_etf_catalog,
    paper_trade_promotion_evaluations,
    persist_order_execution_state,
    persist_order_intent_execution_state,
    promote_paper_trade_reports,
)
from agency.services.human_review import selection_report_hash
from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    _active_cycle_reports,
    _dashboard_selection_reports,
    _float_field,
    _format_timestamp_label,
    _human_review_index,
    _human_review_key,
    _human_review_summary,
    _int_field,
    _lifecycle_events_for_reports,
    _mapping_field,
    _mapping_list_field,
    _mapping_list_field_or_empty,
    _optional_float_field,
    _runtime_payload_key,
    _source_health_origin_label,
    _string_list,
    dashboard_data_health,
    live_runtime_source_health_rows,
)

EXECUTION_PREVIEW_BROKER_MAX_AGE_SECONDS = 60
RECORDED_ORDER_STATES = {
    "ACCEPTED",
    "SUBMITTED",
    "PENDING_CANCEL",
    "FILLED",
    "CANCELED",
    "REJECTED",
    "EXPIRED",
}


async def execution_preview_context(
    *,
    raw_reports: Sequence[Mapping[str, object]] | None = None,
    data_sources: Sequence[Mapping[str, object]] | None = None,
    broker: Mapping[str, object] | None = None,
    validate_contracts: bool = False,
) -> dict[str, object]:
    from agency.views.command import human_review_events_for_reports
    from agency.views.market_regime import broker_status_context
    from agency.views.portfolio import (
        _broker_account,
        _broker_gross_exposure_pct,
        _broker_orders,
        _broker_positions,
        _broker_ready_for_paper_promotion,
        _pending_opening_order_exposure_pct,
    )
    if raw_reports is None or data_sources is None or broker is None:
        fetched_reports, fetched_sources, fetched_broker = await asyncio.gather(
            _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
            live_runtime_source_health_rows(runtime_data_source_status),
            _execution_preview_broker_status_context(broker_status_context),
        )
        if raw_reports is None:
            raw_reports = fetched_reports
        if data_sources is None:
            data_sources = fetched_sources
        if broker is None:
            broker = fetched_broker
    reports = _active_cycle_reports(raw_reports)
    policy = await load_active_portfolio_policy()
    broker_positions = _broker_positions(broker)
    data_load_status = load_data_load_status(
        source_health_rows=data_sources,
        source_health_origin=_source_health_origin_label(data_sources),
    )
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=[],
        lane_states=_mapping_list_field_or_empty(data_load_status, "lane_states"),
    )
    review_states = _human_review_index(
        await human_review_events_for_reports(reports, readiness)
    )
    operator_advance_states = _human_review_index(
        await operator_manual_advance_events_for_reports(reports, readiness)
    )
    promotion_config = PaperTradePromotionConfig.from_env()
    promotion_evaluations = paper_trade_promotion_evaluations(
        reports,
        review_states=review_states,
        operator_advance_states=operator_advance_states,
        positions=broker_positions,
        open_orders=_broker_orders(broker),
        broker_ready=_broker_ready_for_paper_promotion(broker),
        config=promotion_config,
    )
    promoted_reports = promote_paper_trade_reports(
        reports,
        review_states=review_states,
        operator_advance_states=operator_advance_states,
        positions=broker_positions,
        open_orders=_broker_orders(broker),
        broker_ready=_broker_ready_for_paper_promotion(broker),
        config=promotion_config,
    )
    risk_results = build_risk_decisions(
        promoted_reports,
        data_sources,
        policy=policy,
        current_gross_exposure_pct=_broker_gross_exposure_pct(broker),
        pending_opening_order_exposure_pct=_pending_opening_order_exposure_pct(broker),
        validate_contracts=validate_contracts,
    )
    research_approval_keys = await execution_approval_keys(
        reports=reports,
        data_sources=data_sources,
        risk_decisions=[result.risk_decision for result in risk_results],
    )
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results],
        policy=policy,
        account=_broker_account(broker),
        positions=broker_positions,
        open_orders=_broker_orders(broker),
        research_approval_required=True,
        research_approval_records=dict.fromkeys(research_approval_keys, True),
        validate_contracts=validate_contracts,
    )
    current_time = datetime.now(UTC)
    market_phase = classify_market_session(current_time).phase
    freshness_gate = execution_freshness_gate(
        broker,
        data_sources,
        now=current_time,
        max_broker_age_seconds=EXECUTION_PREVIEW_BROKER_MAX_AGE_SECONDS,
        market_phase=market_phase,
    )
    scheduler_gate = scheduler_work_queue_context(
        reports=promoted_reports,
        review_queue=_review_queue_from_reports(promoted_reports, review_states),
        source_health=data_sources,
        broker=broker,
        data_load_status=data_load_status,
        data_refresh_progress=load_data_refresh_progress(),
    )
    execution_gate = execution_operational_gate(
        freshness_gate=freshness_gate,
        scheduler_status=scheduler_gate,
    )
    order_approval_keys = await order_approval_keys_for_reports(
        reports=promoted_reports,
        data_sources=data_sources,
        previews=[result.preview for result in preview_results],
    )
    execution_states = await execution_states_for_previews(
        [result.preview for result in preview_results]
    )
    preview_rows = execution_preview_rows(
        [result.preview for result in preview_results],
        approval_keys=research_approval_keys,
        order_approval_keys=order_approval_keys,
        review_states=review_states,
        execution_gate=execution_gate,
        promotion_evaluations=promotion_evaluations,
        execution_states=execution_states,
    )
    leveraged_policy = LeveragedAlternativePolicy.from_env()
    leveraged_catalog = load_leveraged_etf_catalog()
    leveraged_reviews = [
        build_leveraged_alternative_review(
            report,
            risk_decision=risk_result.risk_decision,
            policy=leveraged_policy,
            etf_catalog=leveraged_catalog,
        )
        for report, risk_result in zip(promoted_reports, risk_results, strict=True)
    ]
    return {
        "broker": broker,
        "data_health": dashboard_data_health(
            "Execution preview dashboard",
            data_load_status=data_load_status,
            datasets=("prices_daily", "stock_trades"),
            lanes=(
                "abnormal_volume",
                "technical_analysis",
                "buy_sell_pressure",
                "block_trade_pressure",
                "unusual_trade_activity",
                "pre_market_unusual_activity",
                "market_flow_trend",
            ),
            cycle_id=str(readiness.get("cycle_id") or ""),
            extra_rows=(
                {
                    "kind": "Broker",
                    "name": "Alpaca paper account",
                    "status_label": str(broker.get("status_label") or "Broker unknown"),
                    "status_class": str(broker.get("status_class") or "neutral"),
                    "coverage_label": f"{len(_broker_positions(broker))} positions / {len(_broker_orders(broker))} open orders",
                    "freshness_label": "broker snapshot",
                    "last_update": str(broker.get("checked_at") or "not checked"),
                    "detail": str(broker.get("detail") or "No broker detail available."),
                },
                {
                    "kind": "Execution gate",
                    "name": "Freshness and scheduler tradability",
                    "status_label": str(execution_gate.get("status_label") or "Unknown"),
                    "status_class": str(execution_gate.get("status_class") or "neutral"),
                    "coverage_label": f"{execution_gate.get('blocker_count', 0)} blocker(s)",
                    "freshness_label": "required immediately before submit",
                    "last_update": str(broker.get("checked_at") or "not checked"),
                    "detail": str(execution_gate.get("detail") or "No execution gate detail available."),
                },
            ),
        ),
        "preview_rows": preview_rows,
        "orderable_rows": [row for row in preview_rows if row["preview_state"] == "READY"],
        "review_only_rows": [row for row in preview_rows if row["preview_state"] == "DISABLED"],
        "approved_review_only_rows": [
            row
            for row in preview_rows
            if row["preview_state"] == "DISABLED" and row["human_approved"] is True
        ],
        "blocked_rows": [row for row in preview_rows if row["preview_state"] == "BLOCKED"],
        "leveraged_alternatives": leveraged_alternative_panel(leveraged_reviews),
        "summary": execution_preview_summary(
            preview_rows,
            broker=broker,
            policy=policy,
            execution_gate=execution_gate,
        ),
        "execution_freshness_gate": execution_gate,
        "freshness_gate": freshness_gate,
        "scheduler_tradability": _mapping_field(scheduler_gate, "tradability"),
    }


async def _execution_preview_broker_status_context(
    broker_status_context_fn: Callable[..., Awaitable[dict[str, object]]],
) -> dict[str, object]:
    try:
        context = await broker_status_context_fn(use_cache=True)
    except TypeError:
        return await broker_status_context_fn()
    if not _execution_preview_broker_context_needs_refresh(context):
        return context
    try:
        return await broker_status_context_fn(use_cache=False)
    except TypeError:
        return await broker_status_context_fn()


def _execution_preview_broker_context_needs_refresh(
    context: Mapping[str, object],
    *,
    now: datetime | None = None,
    max_age_seconds: int = EXECUTION_PREVIEW_BROKER_MAX_AGE_SECONDS,
) -> bool:
    if str(context.get("status_label") or "") == "Broker Check Delayed":
        return True
    checked_at = _parse_execution_preview_timestamp(context.get("checked_at"))
    if checked_at is None:
        return True
    current = now or datetime.now(UTC)
    return (current - checked_at).total_seconds() > max_age_seconds


def _parse_execution_preview_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def execution_preview_order_row(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    broker: Mapping[str, object] | None = None,
    data_sources: Sequence[Mapping[str, object]] | None = None,
) -> Mapping[str, object] | None:
    context = await execution_preview_context(broker=broker, data_sources=data_sources)
    for row in _mapping_list_field(context, "preview_rows"):
        if (
            row["cycle_id"] == cycle_id
            and row["ticker"] == ticker.upper()
            and row["as_of"] == as_of
        ):
            return row
    return None

async def execution_approval_keys(
    *,
    reports: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
) -> set[tuple[str, str, str]]:
    from agency.views.command import human_review_events_for_reports
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=risk_decisions,
    )
    events = await human_review_events_for_reports(reports, readiness)
    approved: set[tuple[str, str, str]] = set()
    for event in events:
        payload = _mapping_field(event, "payload")
        report = _matching_report_for_event(reports, event)
        if (
            report is not None
            and str(payload.get("review_decision", "")).upper() == "APPROVE"
            and str(payload.get("selection_report_hash") or "")
            == selection_report_hash(report)
        ):
            approved.add(_human_review_key(event))
    return approved


async def execution_states_for_previews(
    previews: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, str, str], Mapping[str, object]]:
    if not previews:
        return {}
    cycle_id = str(previews[0].get("cycle_id") or "")
    if not cycle_id:
        return {}
    try:
        states = await runtime_execution_states(cycle_id=cycle_id, limit=500)
    except Exception:  # noqa: BLE001
        return {}
    return _execution_state_index(states)


def _execution_state_index(
    states: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, str, str], Mapping[str, object]]:
    indexed: dict[tuple[str, str, str, str], Mapping[str, object]] = {}
    for state in states:
        key = _execution_state_key(state)
        if all(key) and key not in indexed:
            indexed[key] = state
    return indexed


def _execution_state_key(state: Mapping[str, object]) -> tuple[str, str, str, str]:
    payload_value = state.get("payload")
    if not isinstance(payload_value, Mapping):
        return ("", "", "", "")
    payload = payload_value
    preview_value = payload.get("preview")
    if not isinstance(preview_value, Mapping):
        preview_value = payload.get("execution_preview")
    if not isinstance(preview_value, Mapping):
        return ("", "", "", "")
    preview = preview_value
    order_intent_hash = str(
        preview.get("order_intent_hash") or payload.get("order_intent_hash") or ""
    )
    return (
        str(state.get("cycle_id") or preview.get("cycle_id") or ""),
        str(state.get("ticker") or preview.get("ticker") or "").upper(),
        str(preview.get("as_of") or payload.get("as_of") or ""),
        order_intent_hash,
    )

async def order_approval_keys_for_reports(
    *,
    reports: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
    previews: Sequence[Mapping[str, object]],
) -> set[tuple[str, str, str, str]]:
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=[],
    )
    events = await order_approval_events_for_reports(reports, readiness)
    current_previews = {
        _order_approval_key_from_preview(preview): str(preview.get("order_intent_version", ""))
        for preview in previews
    }
    approved: set[tuple[str, str, str, str]] = set()
    for event in events:
        if str(event.get("status")) != "PASSED":
            continue
        payload = _mapping_field(event, "payload")
        key = _order_approval_key(event)
        if key not in current_previews:
            continue
        if str(payload.get("approval_type")) != "ORDER_APPROVAL":
            continue
        if payload.get("paper_only") is not True:
            continue
        if str(payload.get("order_intent_version", "")) != current_previews[key]:
            continue
        approved.add(key)
    return approved


def execution_operational_gate(
    *,
    freshness_gate: Mapping[str, object],
    scheduler_status: Mapping[str, object],
) -> dict[str, object]:
    """Close execution when either freshness or scheduler tradability is not ready."""
    gate = dict(freshness_gate)
    tradability = _mapping_field(scheduler_status, "tradability")
    if gate.get("ready") is not True:
        return gate
    if str(tradability.get("state")) == "tradable":
        return gate
    detail = str(tradability.get("detail") or "Scheduler marks this cycle context-only.")
    checks = list(_mapping_list_field(gate, "checks"))
    checks.append(
        {
            "label": "Scheduler tradability",
            "status": "BLOCK",
            "status_class": "block",
            "detail": detail,
        }
    )
    gate.update(
        {
            "ready": False,
            "state": "blocked",
            "status_label": "Blocked",
            "status_class": "block",
            "checks": checks,
            "blocker_count": _int_field(gate, "blocker_count") + 1,
            "detail": detail,
        }
    )
    return gate


def row_from_execution_context(
    context: Mapping[str, object],
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> Mapping[str, object] | None:
    for row in _mapping_list_field(context, "preview_rows"):
        if (
            row["cycle_id"] == cycle_id
            and row["ticker"] == ticker.upper()
            and row["as_of"] == as_of
        ):
            return row
    return None


def _matching_report_for_event(
    reports: Sequence[Mapping[str, object]],
    event: Mapping[str, object],
) -> Mapping[str, object] | None:
    key = _human_review_key(event)
    if not all(key):
        return None
    return next((report for report in reports if _runtime_payload_key(report) == key), None)


def _review_queue_from_reports(
    reports: Sequence[Mapping[str, object]],
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for report in reports:
        row = dict(report)
        review = review_states.get(_runtime_payload_key(report))
        if review is not None:
            payload = _mapping_field(review, "payload")
            row["human_review_decision"] = str(payload.get("review_decision", ""))
        rows.append(row)
    return rows

async def order_approval_events_for_reports(
    reports: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
) -> list[dict[str, object]]:
    return await _lifecycle_events_for_reports(
        reports,
        readiness,
        event_type="ORDER_APPROVAL",
        limit_per_ticker=100,
    )


async def operator_manual_advance_events_for_reports(
    reports: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
) -> list[dict[str, object]]:
    return await _lifecycle_events_for_reports(
        reports,
        readiness,
        event_type="OPERATOR_MANUAL_ADVANCE",
        limit_per_ticker=100,
    )

def _remove_research_only_promoted_order_approvals(
    approval_keys: set[tuple[str, str, str]],
    reports: Sequence[Mapping[str, object]],
) -> set[tuple[str, str, str]]:
    blocked_keys = {
        _runtime_payload_key(report)
        for report in reports
        if _report_requires_separate_order_approval(report)
    }
    if not blocked_keys:
        return approval_keys
    return {key for key in approval_keys if key not in blocked_keys}

def _report_requires_separate_order_approval(report: Mapping[str, object]) -> bool:
    trade_plan = report.get("trade_plan")
    if not isinstance(trade_plan, Mapping):
        return False
    notes = trade_plan.get("notes", [])
    if not isinstance(notes, list):
        return False
    return TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG in {str(note) for note in notes}

async def _record_submitted_order(
    preview_row: Mapping[str, object],
    order: Mapping[str, object],
    reconciliation: Mapping[str, object] | None = None,
) -> None:
    payload_extra: dict[str, object] = {"preview": dict(preview_row)}
    if reconciliation is not None:
        payload_extra["reconciliation"] = dict(reconciliation)
    async with get_session() as session:
        await persist_order_execution_state(
            session,
            cycle_id=str(preview_row["cycle_id"]),
            order=order,
            payload_extra=payload_extra,
        )
        await session.commit()


async def _record_order_submission_intent(
    preview_row: Mapping[str, object],
    order_payload: Mapping[str, object],
) -> None:
    async with get_session() as session:
        await persist_order_intent_execution_state(
            session,
            cycle_id=str(preview_row["cycle_id"]),
            preview=_mapping_field(preview_row, "preview"),
            order_payload=order_payload,
            state="READY",
        )
        await session.commit()


async def _record_failed_order_submission(
    preview_row: Mapping[str, object],
    order_payload: Mapping[str, object],
    error: str,
) -> None:
    async with get_session() as session:
        await persist_order_intent_execution_state(
            session,
            cycle_id=str(preview_row["cycle_id"]),
            preview=_mapping_field(preview_row, "preview"),
            order_payload=order_payload,
            state="FAILED",
            error=error,
        )
        await session.commit()

def execution_preview_rows(
    previews: Sequence[Mapping[str, object]],
    *,
    approval_keys: set[tuple[str, str, str]] | None = None,
    order_approval_keys: set[tuple[str, str, str, str]] | None = None,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    execution_gate: Mapping[str, object] | None = None,
    promotion_evaluations: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    execution_states: Mapping[tuple[str, str, str, str], Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    research_approved = set() if approval_keys is None else approval_keys
    order_approved = set() if order_approval_keys is None else order_approval_keys
    review_lookup = {} if review_states is None else review_states
    promotion_lookup = {} if promotion_evaluations is None else promotion_evaluations
    execution_lookup = {} if execution_states is None else execution_states
    gate = {} if execution_gate is None else execution_gate
    submit_gate_ready = not gate or gate.get("ready") is True
    gate_detail = (
        None
        if submit_gate_ready
        else str(gate.get("detail", "execution freshness gate is closed"))
    )
    rows = [
        _execution_preview_row(
            preview,
            human_approved=_runtime_payload_key(preview) in research_approved,
            order_approved=_order_approval_key_from_preview(preview) in order_approved,
            review_event=review_lookup.get(_runtime_payload_key(preview)),
            submit_gate_ready=submit_gate_ready,
            submit_gate_detail=gate_detail,
            promotion_evaluation=promotion_lookup.get(_runtime_payload_key(preview)),
            execution_state=execution_lookup.get(_order_approval_key_from_preview(preview)),
        )
        for preview in previews
    ]
    return sorted(rows, key=_execution_preview_sort_key)

def execution_preview_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    broker: Mapping[str, object] | None = None,
    policy: PortfolioPolicy | None = None,
    execution_gate: Mapping[str, object] | None = None,
) -> dict[str, object]:
    from agency.views.portfolio import (
        _broker_account,
        _broker_gross_exposure_pct,
        _broker_positions,
        _portfolio_execution_detail,
    )
    normalized_policy = policy or PortfolioPolicy()
    ready_count = sum(1 for row in rows if row["preview_state"] == "READY")
    blocked_count = sum(1 for row in rows if row["preview_state"] == "BLOCKED")
    disabled_count = sum(1 for row in rows if row["preview_state"] == "DISABLED")
    submit_ready_count = sum(1 for row in rows if row["submit_enabled"] is True)
    broker_connected = bool(broker is not None and broker.get("connected") is True)
    broker_mode = str(broker.get("mode", "paper")) if broker is not None else "paper"
    freshness_ready = execution_gate is None or execution_gate.get("ready") is True
    submit_gate_open = (
        normalized_policy.broker_submit_enabled
        and broker_connected
        and broker_mode == "paper"
        and freshness_ready
    )
    broker_account = _broker_account(broker or {})
    broker_positions = _broker_positions(broker or {})
    gross_exposure_pct = _broker_gross_exposure_pct(broker or {})
    return {
        "preview_count": len(rows),
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "disabled_count": disabled_count,
        "submit_ready_count": submit_ready_count,
        "broker_connected": broker_connected,
        "broker_mode": broker_mode,
        "submit_gate_open": submit_gate_open,
        "submit_gate_label": "Open" if submit_gate_open else "Closed",
        "submit_gate_class": "pass" if submit_gate_open else "block",
        "portfolio_check_label": "Checked" if broker_connected else "Broker Offline",
        "portfolio_check_class": "pass" if broker_connected else "block",
        "portfolio_check_detail": _portfolio_execution_detail(
            broker_connected=broker_connected,
            position_count=len(broker_positions),
            gross_exposure_pct=gross_exposure_pct,
            policy=normalized_policy,
        ),
        "portfolio_equity_label": _money_label(
            _optional_float_field(broker_account, "equity")
            if broker_account is not None
            else None
        ),
        "portfolio_buying_power_label": _money_label(
            _optional_float_field(broker_account, "buying_power")
            if broker_account is not None
            else None
        ),
        "portfolio_position_count": len(broker_positions),
        "portfolio_gross_exposure_label": f"{gross_exposure_pct:.2f}%",
        "policy_default_position_label": (
            f"{normalized_policy.default_position_pct:.1f}% of equity"
        ),
        "policy_max_exposure_label": f"{normalized_policy.max_gross_exposure_pct:.1f}%",
        "policy_exit_rules_label": (
            f"take profit {normalized_policy.take_profit_pct:.1f}%, "
            f"stop loss {normalized_policy.stop_loss_pct:.1f}%"
        ),
        "headline": _execution_headline(len(rows), ready_count),
        "detail": _execution_detail(
            submit_gate_open,
            broker_connected,
            broker_mode=broker_mode,
            freshness_ready=freshness_ready,
            freshness_detail=str((execution_gate or {}).get("detail", "")),
        ),
        "workflow_guidance": _execution_workflow_guidance(
            ready_count=ready_count,
            disabled_count=disabled_count,
            blocked_count=blocked_count,
            submit_ready_count=submit_ready_count,
        ),
        "no_order_explanation": (
            "A paper transaction can be approved only when a row is READY, has side "
            "BUY/SELL/SHORT/COVER, has an order value or quantity, passes risk, and "
            "has human approval. WATCH, HOLD, and NO_TRADE rows cannot be submitted."
        ),
    }

def leveraged_alternative_panel(
    reviews: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows = [
        dict(review)
        for review in reviews
        if review.get("eligible") is True
        or review.get("triggered") is True
        or _int_field(review, "available_alternative_count") > 0
    ]
    rows = sorted(rows, key=_leveraged_review_sort_key)
    enabled = any(review.get("enabled") is True for review in reviews)
    available_count = sum(_int_field(review, "available_alternative_count") for review in reviews)
    triggered_count = sum(1 for review in reviews if review.get("triggered") is True)
    if not reviews:
        status_label = "No Candidates"
        status_class = "neutral"
        headline = "No leveraged-alternative review can run without selection reports."
    elif not enabled:
        status_label = "Disabled"
        status_class = "neutral"
        headline = "Leveraged alternative advisor is disabled by local policy."
    elif available_count > 0:
        status_label = "Advisory Available"
        status_class = "warn"
        headline = f"{available_count} leveraged alternative(s) are available for review."
    elif triggered_count > 0:
        status_label = "No Match"
        status_class = "warn"
        headline = "High-conviction candidates exist, but no eligible alternative passed."
    else:
        status_label = "Waiting"
        status_class = "neutral"
        headline = "No candidate currently meets the 85% leveraged-review trigger."
    return {
        "rows": rows,
        "review_count": len(reviews),
        "triggered_count": triggered_count,
        "available_count": available_count,
        "status_label": status_label,
        "status_class": status_class,
        "headline": headline,
        "detail": (
            "This panel is advisory only. It never submits leveraged ETF or options orders, "
            "and it requires a separate policy opt-in."
        ),
    }

def _execution_preview_row(
    preview: Mapping[str, object],
    *,
    human_approved: bool = False,
    order_approved: bool = False,
    review_event: Mapping[str, object] | None = None,
    submit_gate_ready: bool = True,
    submit_gate_detail: str | None = None,
    promotion_evaluation: Mapping[str, object] | None = None,
    execution_state: Mapping[str, object] | None = None,
) -> dict[str, object]:
    reasons = _string_list(preview, "reasons")
    raw_reason = reasons[0] if reasons else "preview recorded"
    caution = _execution_preview_caution(preview, raw_reason)
    preview_submit_enabled = preview["submit_enabled"] is True and submit_gate_ready
    effective_order_approved = order_approved and human_approved
    execution_summary = _execution_state_summary(execution_state)
    execution_state_name = str(execution_summary["state"])
    execution_blocks_submit = execution_state_name in RECORDED_ORDER_STATES
    submit_enabled = (
        preview_submit_enabled
        and effective_order_approved
        and not execution_blocks_submit
    )
    order_approval_available = (
        str(preview["preview_state"]) == "READY"
        and str(preview["side"]) in {"BUY", "SELL", "SHORT", "COVER"}
        and (
            isinstance(preview["quantity"], int | float)
            or isinstance(preview["notional"], int | float)
        )
        and preview["submit_enabled"] is True
        and human_approved
        and not execution_blocks_submit
    )
    submit_blocker = (
        str(execution_summary["submit_blocker"])
        if execution_blocks_submit
        else _submit_blocker(
            preview=preview,
            preview_submit_enabled=preview_submit_enabled,
            human_approved=human_approved,
            order_approved=effective_order_approved,
            submit_gate_detail=submit_gate_detail,
        )
    )
    human_review = _human_review_summary(review_event)
    ticker = str(preview["ticker"])
    cycle_id = str(preview["cycle_id"])
    as_of = str(preview["as_of"])
    order_intent_hash = str(preview["order_intent_hash"])
    llm_action = str(preview.get("llm_action") or "LLM review unavailable - rules-only")
    deterministic_score_label = _execution_deterministic_score_label(preview)
    review_decision = str(human_review["decision"])
    display_preview_state = (
        execution_state_name
        if execution_blocks_submit
        else str(preview["preview_state"])
    )
    research_approval_available = (
        submit_blocker == "review-only action"
        and not human_approved
        and _can_promote_after_approval(promotion_evaluation)
    )
    return {
        "preview": dict(preview),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "as_of": as_of,
        "order_intent_version": str(preview["order_intent_version"]),
        "order_intent_hash": order_intent_hash,
        "order_intent_hash_label": order_intent_hash[:12],
        "preview_state": display_preview_state,
        "state_class": _preview_state_class(display_preview_state),
        "side": str(preview["side"]),
        "risk_decision": str(preview["risk_decision"]),
        "submit_enabled": submit_enabled,
        "order_approval_available": order_approval_available,
        "submit_label": (
            str(execution_summary["status_label"])
            if execution_blocks_submit
            else "Submit paper order"
            if submit_enabled
            else _submit_label(
                submit_blocker,
                human_approved=human_approved,
                order_approved=order_approved,
                promotion_evaluation=promotion_evaluation,
            )
        ),
        "submit_blocker": submit_blocker,
        "submit_action": _execution_submit_url(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
            order_intent_hash=order_intent_hash,
        ),
        "approve_order_action": _execution_approve_order_url(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
            order_intent_hash=order_intent_hash,
        ),
        "operator_manual_advance_action": _execution_operator_advance_url(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
        ),
        "research_approval_available": research_approval_available,
        "approve_research_action": _execution_approve_research_url(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
        ),
        "human_approved": human_approved,
        "human_review_decision": review_decision,
        "human_review_class": str(human_review["status_class"]),
        "human_review_reason": str(human_review["reason"]),
        "human_review_time": str(human_review["event_time"]),
        "human_review_time_label": _format_timestamp_label(human_review["event_time"]),
        "order_approved": effective_order_approved,
        "stale_order_approval_recorded": order_approved and not human_approved,
        "quantity": preview["quantity"],
        "notional": preview["notional"],
        "order_value_label": _order_value_label(preview),
        "entry": preview["entry"],
        "position_size_pct": _float_field(preview, "position_size_pct"),
        "size_label": _execution_size_label(preview),
        "time_in_force": preview["time_in_force"] or "None",
        "reason": _execution_reason_text(
            preview,
            raw_reason,
            promotion_evaluation,
            human_approved=human_approved,
        ),
        "order_intent": _execution_order_intent(
            preview,
            raw_reason,
            promotion_evaluation,
            human_approved=human_approved,
            review_decision=review_decision,
        ),
        "llm_action": llm_action,
        "llm_rationale": str(
            preview.get("llm_rationale")
            or "No LLM rationale was attached to this preview; deterministic risk and portfolio gates are shown."
        ),
        "llm_conflict": (
            "rules-only"
            if "unavailable" in llm_action.lower()
            else "aligned"
            if llm_action.upper() == str(preview["side"]).upper()
            else "review conflict"
        ),
        "llm_status_label": (
            "LLM review unavailable - rules-only"
            if "unavailable" in llm_action.lower()
            else "LLM review available"
        ),
        "deterministic_score_label": deterministic_score_label,
        "execution_state": execution_state_name or "NONE",
        "execution_status_label": str(execution_summary["status_label"]),
        "execution_status_class": str(execution_summary["status_class"]),
        "execution_reason": str(execution_summary["reason"]),
        "execution_event_time": str(execution_summary["event_time"]),
        "execution_event_time_label": _format_timestamp_label(
            execution_summary["event_time"],
        ),
        "client_order_id": str(execution_summary["client_order_id"]),
        "filled_qty": execution_summary["filled_qty"],
        "filled_avg_price": execution_summary["filled_avg_price"],
        "submission_confirmation_label": str(execution_summary["confirmation_label"]),
        "paper_promotion_state": _promotion_text(promotion_evaluation, "state", "not_evaluated"),
        "paper_promotion_status_label": _promotion_status_label_for_card(
            promotion_evaluation,
        ),
        "paper_promotion_status_class": _promotion_text(
            promotion_evaluation,
            "status_class",
            "neutral",
        ),
        "paper_promotion_detail": _promotion_text(
            promotion_evaluation,
            "detail",
            "Paper promotion was not evaluated for this row.",
        ),
        "paper_promotion_reasons": _promotion_reasons(promotion_evaluation),
        "paper_promotion_blockers": _promotion_reasons(promotion_evaluation),
        "paper_promotion_primary_blocker": _promotion_first_reason(
            promotion_evaluation,
        ),
        "paper_promotion_checks": _promotion_check_rows(promotion_evaluation),
        "paper_promotion_check_summary": _promotion_check_summary(
            promotion_evaluation,
        ),
        "operator_manual_advance_available": bool(
            promotion_evaluation is not None
            and promotion_evaluation.get("manual_advance_available") is True
        ),
        "operator_manual_advance_status_label": _operator_manual_advance_status_label(
            promotion_evaluation,
        ),
        "operator_manual_advance_detail": _operator_manual_advance_detail(
            promotion_evaluation,
        ),
        "caution_acknowledgement_required": caution["required"],
        "caution_acknowledgement_text": caution["text"],
        "caution_recommendation": caution["recommendation"],
        "approval_label": _execution_approval_label(
            preview,
            human_approved=human_approved,
            order_approved=effective_order_approved,
            review_decision=review_decision,
        ),
        "next_step": _execution_next_step(
            submit_blocker,
            preview=preview,
            raw_reason=raw_reason,
            human_approved=human_approved,
            order_approved=effective_order_approved,
            review_decision=review_decision,
            promotion_evaluation=promotion_evaluation,
        ),
    }

def _execution_deterministic_score_label(preview: Mapping[str, object]) -> str:
    side = str(preview["side"])
    risk = str(preview["risk_decision"])
    size = _float_field(preview, "position_size_pct")
    if side in {"BUY", "SELL", "SHORT", "COVER"}:
        return f"{risk} risk / {size:.0f}% target size"
    action = _execution_final_action_label(preview)
    if action:
        return f"{risk} risk / final action is {action}"
    return f"{risk} risk / no order side"


def _execution_final_action_label(
    preview: Mapping[str, object],
    raw_reason: str | None = None,
) -> str:
    side = str(preview["side"])
    if side in {"BUY", "SELL", "SHORT", "COVER"}:
        return side
    reason = raw_reason
    if reason is None:
        reasons = _string_list(preview, "reasons")
        reason = reasons[0] if reasons else ""
    token = reason.strip().split(maxsplit=1)[0].strip(":").upper() if reason else ""
    if token in {"WATCH", "HOLD", "NO_TRADE"}:
        return token
    return ""

def _order_approval_key(event: Mapping[str, object]) -> tuple[str, str, str, str]:
    payload = event.get("payload", {})
    as_of = ""
    order_hash = ""
    if isinstance(payload, Mapping):
        as_of = str(payload.get("as_of", ""))
        order_hash = str(payload.get("order_intent_hash", ""))
    return (
        str(event.get("cycle_id", "")),
        str(event.get("ticker", "")),
        as_of,
        order_hash,
    )

def _order_approval_key_from_preview(
    preview: Mapping[str, object],
) -> tuple[str, str, str, str]:
    return (
        str(preview.get("cycle_id", "")),
        str(preview.get("ticker", "")),
        str(preview.get("as_of", "")),
        str(preview.get("order_intent_hash", "")),
    )

def _execution_preview_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    if row["submit_enabled"] is True:
        priority = 0
    elif row.get("order_approved") is True:
        priority = 1
    elif row["human_approved"] is True:
        priority = 2
    else:
        priority = {"READY": 3, "DISABLED": 4, "BLOCKED": 5}.get(
            str(row["preview_state"]),
            6,
        )
    return (priority, -round(_float_field(row, "position_size_pct")), str(row["ticker"]))

def _leveraged_review_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    available_priority = 0 if _int_field(row, "available_alternative_count") > 0 else 1
    return (
        available_priority,
        -_int_field(_mapping_field(row, "baseline"), "conviction_pct"),
        str(row["ticker"]),
    )

def _execution_headline(preview_count: int, ready_count: int) -> str:
    if preview_count == 0:
        return "No execution previews yet."
    return f"{ready_count} orderable paper previews are ready."

def _execution_workflow_guidance(
    *,
    ready_count: int,
    disabled_count: int,
    blocked_count: int,
    submit_ready_count: int,
) -> str:
    if submit_ready_count > 0:
        return (
            "Review the READY approved order cards first; those are the only rows "
            "with submit buttons."
        )
    if ready_count > 0:
        return "READY rows exist, but they still need human approval or an open broker submit gate."
    if disabled_count > 0:
        return (
            "This cycle has review-only WATCH/HOLD rows. Approving them records research "
            "approval and waits for a later cycle to upgrade to a trade action."
        )
    if blocked_count > 0:
        return "No transaction is available; all previews are blocked before sizing."
    return "Execution previews will appear after final selection and risk run."


def _execution_state_summary(
    execution_state: Mapping[str, object] | None,
) -> dict[str, object]:
    if not execution_state:
        return {
            "state": "",
            "status_label": "No broker order recorded",
            "status_class": "neutral",
            "reason": "No submitted paper order has been recorded for this intent.",
            "event_time": "",
            "submit_blocker": "",
            "client_order_id": "",
            "filled_qty": None,
            "filled_avg_price": None,
            "confirmation_label": "Submitted paper order appears here after Alpaca accepts it.",
        }
    state = str(execution_state.get("state") or "").upper()
    payload = _mapping_field(execution_state, "payload")
    order = _mapping_field(payload, "order")
    filled_qty = _optional_float_field(order, "filled_qty")
    filled_avg_price = _optional_float_field(order, "filled_avg_price")
    return {
        "state": state,
        "status_label": _execution_state_status_label(state),
        "status_class": _execution_state_status_class(state),
        "reason": str(execution_state.get("reason") or _execution_state_status_label(state)),
        "event_time": str(execution_state.get("event_time") or ""),
        "submit_blocker": _execution_state_submit_blocker(state),
        "client_order_id": str(order.get("client_order_id") or payload.get("client_order_id") or ""),
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "confirmation_label": _execution_confirmation_label(
            state,
            filled_qty=filled_qty,
            filled_avg_price=filled_avg_price,
        ),
    }


def _execution_state_status_label(state: str) -> str:
    labels = {
        "ACCEPTED": "Paper order accepted",
        "SUBMITTED": "Paper order submitted",
        "PENDING_CANCEL": "Paper order cancel pending",
        "FILLED": "Paper order filled",
        "CANCELED": "Paper order canceled",
        "REJECTED": "Paper order rejected",
        "EXPIRED": "Paper order expired",
    }
    return labels.get(state, "Broker order state recorded")


def _execution_state_status_class(state: str) -> str:
    if state == "FILLED":
        return "pass"
    if state in {"ACCEPTED", "SUBMITTED", "PENDING_CANCEL"}:
        return "warn"
    if state in {"CANCELED", "REJECTED", "EXPIRED"}:
        return "block"
    return "neutral"


def _execution_state_submit_blocker(state: str) -> str:
    if state == "FILLED":
        return "paper order already filled"
    if state in {"ACCEPTED", "SUBMITTED", "PENDING_CANCEL"}:
        return "paper order already submitted"
    if state in {"CANCELED", "REJECTED", "EXPIRED"}:
        return "broker terminal state recorded"
    return ""


def _execution_confirmation_label(
    state: str,
    *,
    filled_qty: float | None,
    filled_avg_price: float | None,
) -> str:
    if state == "FILLED":
        if filled_qty is not None and filled_avg_price is not None:
            return f"Filled {filled_qty} @ {filled_avg_price}"
        return "Paper order filled at broker"
    if state:
        return _execution_state_status_label(state)
    return "Submitted paper order appears here after Alpaca accepts it."


def _preview_state_class(state: str) -> str:
    if state in {"READY", "FILLED"}:
        return "pass"
    if state in {"DISABLED", "ACCEPTED", "SUBMITTED", "PENDING_CANCEL"}:
        return "neutral"
    return "block"

def _execution_submit_url(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> str:
    query = urlencode(
        {
            "cycle_id": cycle_id,
            "ticker": ticker,
            "as_of": as_of,
            "order_intent_hash": order_intent_hash,
        }
    )
    return f"/execution-preview/orders?{query}"

def _execution_approve_order_url(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> str:
    query = urlencode(
        {
            "cycle_id": cycle_id,
            "ticker": ticker,
            "as_of": as_of,
            "order_intent_hash": order_intent_hash,
        }
    )
    return f"/execution-preview/orders/approve?{query}"


def _execution_approve_research_url(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> str:
    query = urlencode(
        {
            "cycle_id": cycle_id,
            "as_of": as_of,
            "decision": "APPROVE",
        }
    )
    return f"/candidates/{ticker}/reviews?{query}"


def _execution_operator_advance_url(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> str:
    query = urlencode(
        {
            "cycle_id": cycle_id,
            "ticker": ticker,
            "as_of": as_of,
        }
    )
    return f"/execution-preview/operator-advance?{query}"


def _submit_blocker(
    *,
    preview: Mapping[str, object],
    preview_submit_enabled: bool,
    human_approved: bool,
    order_approved: bool,
    submit_gate_detail: str | None = None,
) -> str:
    if preview_submit_enabled and order_approved:
        return "ready"
    if str(preview["preview_state"]) != "READY":
        return _not_ready_submit_blocker(preview)
    if preview_submit_enabled and not human_approved:
        return "current human approval required"
    if preview_submit_enabled and not order_approved:
        return "order approval required"
    if preview["quantity"] is None and preview["notional"] is None:
        return "missing order size"
    if submit_gate_detail:
        return submit_gate_detail
    return "broker submit gate closed"

def _not_ready_submit_blocker(preview: Mapping[str, object]) -> str:
    side = str(preview["side"])
    raw_reason = " ".join(_string_list(preview, "reasons"))
    if side == "NONE" and raw_reason.startswith("NO_TRADE"):
        return "final action is no trade"
    if side == "NONE" and raw_reason.startswith(("WATCH", "HOLD")):
        return "review-only action"
    if str(preview["risk_decision"]) == "BLOCK":
        return "risk blocked"
    return "preview is not ready"

def _submit_label(
    blocker: str,
    *,
    human_approved: bool = False,
    order_approved: bool = False,
    promotion_evaluation: Mapping[str, object] | None = None,
) -> str:
    if human_approved and blocker == "review-only action":
        return "Research approved"
    if blocker == "review-only action" and _can_promote_after_approval(promotion_evaluation):
        return "Approve research first"
    if order_approved and blocker == "broker submit gate closed":
        return "Order approved"
    if _is_freshness_blocker(blocker):
        return "Refresh first"
    labels = {
        "broker submit gate closed": "Closed",
        "current human approval required": "Human approval required",
        "final action is no trade": "Not orderable",
        "missing order size": "No size",
        "order approval required": "Approve order",
        "preview is not ready": "Blocked",
        "review-only action": "Review only",
        "risk blocked": "Risk blocked",
    }
    return labels.get(blocker, "Closed")

def _is_freshness_blocker(blocker: str) -> bool:
    text = blocker.lower()
    return any(
        marker in text
        for marker in (
            "freshness",
            "checked_at",
            "broker snapshot",
            "source-health",
            "source health",
            "critical evidence",
        )
    )

def _order_value_label(preview: Mapping[str, object]) -> str:
    if str(preview["side"]) == "NONE":
        action = _execution_final_action_label(preview)
        if action in {"WATCH", "HOLD"}:
            return "No order - research only"
        if action == "NO_TRADE":
            return "No order - no trade"
        return "No paper order"
    if str(preview["preview_state"]) == "BLOCKED":
        return "Blocked before sizing"
    notional = preview["notional"]
    quantity = preview["quantity"]
    if isinstance(notional, int | float):
        return f"${float(notional):.2f}"
    if isinstance(quantity, int | float):
        return f"{float(quantity):.4f} shares"
    return "No order size"

def _money_label(value: float | None) -> str:
    if value is None:
        return "Not available"
    return f"${value:,.2f}"

def _execution_size_label(preview: Mapping[str, object]) -> str:
    size_pct = _float_field(preview, "position_size_pct")
    side = str(preview["side"])
    if side == "NONE":
        action = _execution_final_action_label(preview)
        if action in {"WATCH", "HOLD"}:
            return "Not sized until trade action"
        if action == "NO_TRADE":
            return "No sizing for no-trade"
        return "No order sizing"
    if str(preview["preview_state"]) == "BLOCKED":
        return "blocked by risk"
    if side in {"SELL", "COVER"} and isinstance(preview["quantity"], int | float):
        return f"close {float(preview['quantity']):.4f} shares"
    if side in {"BUY", "SHORT"} and isinstance(preview["notional"], int | float):
        return f"{size_pct:.0f}% target position"
    return "waiting for broker/account size"

def _execution_order_intent(
    preview: Mapping[str, object],
    raw_reason: str,
    promotion_evaluation: Mapping[str, object] | None = None,
    *,
    human_approved: bool = False,
    review_decision: str = "Pending",
) -> str:
    side = str(preview["side"])
    action = _execution_final_action_label(preview, raw_reason)
    if side in {"BUY", "SELL", "SHORT", "COVER"}:
        return f"Paper {side.lower()} preview"
    if raw_reason.startswith("NO_TRADE"):
        return "No order: final selection rejected this ticker"
    if raw_reason.startswith(("WATCH", "HOLD")) and _can_promote_after_approval(
        promotion_evaluation
    ):
        return "Eligible paper BUY after research approval"
    if raw_reason.startswith(("WATCH", "HOLD")) and promotion_evaluation is not None:
        if human_approved:
            return "Research approved: blocked by promotion checks"
        if review_decision in {"Defer", "Reject"}:
            return f"{action} review {review_decision.lower()}: not orderable"
        return f"{action} review pending: not orderable yet"
    if raw_reason.startswith(("WATCH", "HOLD")):
        if human_approved:
            return f"{action} research approved: no paper order"
        return f"{action} review pending: no paper order"
    return "No order side available"

def _execution_reason_text(
    preview: Mapping[str, object],
    raw_reason: str,
    promotion_evaluation: Mapping[str, object] | None = None,
    *,
    human_approved: bool = False,
) -> str:
    if str(preview["side"]) == "NONE":
        if _can_promote_after_approval(promotion_evaluation):
            detail = _promotion_text(
                promotion_evaluation,
                "detail",
                "This WATCH can become a paper BUY preview after current research approval.",
            )
            if not human_approved:
                return f"Review is pending. {detail}"
            return f"{detail} {raw_reason}" if "Caution:" in raw_reason else detail
        if promotion_evaluation is not None:
            detail = _promotion_text(
                promotion_evaluation,
                "detail",
                "This WATCH/HOLD row is research-only and has no paper order.",
            )
            reason = _promotion_primary_reason(promotion_evaluation)
            if not human_approved:
                if reason:
                    return f"Review is pending. {detail} Blocked check: {reason}."
                return f"Review is pending. {detail}"
            if "Caution:" in raw_reason:
                if reason:
                    return f"{detail} Blocker: {reason}. {raw_reason}"
                return f"{detail} {raw_reason}"
            if reason:
                return f"{detail} Blocker: {reason}."
            return detail
        if "Caution:" in raw_reason:
            return raw_reason
        return _execution_order_intent(preview, raw_reason)
    if str(preview["preview_state"]) == "BLOCKED":
        return f"Risk blocked this paper order: {raw_reason}."
    return raw_reason

def _execution_approval_label(
    preview: Mapping[str, object],
    *,
    human_approved: bool,
    order_approved: bool,
    review_decision: str,
) -> str:
    if str(preview["preview_state"]) == "READY" and str(preview["side"]) in {
        "BUY",
        "SELL",
        "SHORT",
        "COVER",
    }:
        if order_approved:
            return "Order approved"
        if human_approved:
            return "Research approved"
        return "Needs order approval"
    review_labels = {
        "Approve": "Approved",
        "Defer": "Deferred",
        "Reject": "Rejected",
    }
    if review_decision in review_labels:
        return review_labels[review_decision]
    if human_approved:
        return "Approved"
    if str(preview["side"]) == "NONE":
        return "Needs research review"
    if str(preview["preview_state"]) == "BLOCKED":
        return "Blocked first"
    return "Needs approval"

def _execution_next_step(
    blocker: str,
    *,
    preview: Mapping[str, object],
    raw_reason: str,
    human_approved: bool = False,
    order_approved: bool = False,
    review_decision: str = "Pending",
    promotion_evaluation: Mapping[str, object] | None = None,
) -> str:
    del preview
    if review_decision == "Defer":
        return (
            "Human review deferred this candidate. Keep it out of execution until a "
            "later review or runtime cycle changes the decision."
        )
    if review_decision == "Reject":
        return (
            "Human review rejected this candidate. It should stay out of execution "
            "unless a later cycle produces a new reviewable setup."
        )
    if blocker == "review-only action" and "Caution:" in raw_reason:
        return (
            "Acknowledge the caution before approving this research item. Check the "
            "named gate or data issue, confirm fresh evidence, and do not place a "
            "paper order unless a later cycle upgrades the ticker to BUY, SELL, "
            "SHORT, or COVER."
        )
    if human_approved and blocker == "review-only action":
        reason = _promotion_primary_reason(promotion_evaluation)
        if reason:
            return (
                "Research approval is recorded. No paper order can be submitted for "
                f"this ticker because {reason}. Wait for a later cycle with enough "
                "confirmed evidence, or change policy intentionally before re-running."
            )
        return (
            "Research approval is recorded. Nothing else is required on this screen "
            "for this ticker; it can create a paper order only if a later cycle "
            "upgrades it to BUY, SELL, SHORT, or COVER."
        )
    if blocker == "review-only action" and _can_promote_after_approval(promotion_evaluation):
        return _promotion_text(
            promotion_evaluation,
            "next_step",
            (
                "Approve the current research report; the portfolio manager will "
                "recalculate risk and create a paper BUY order-intent preview if "
                "state remains fresh."
            ),
        )
    if blocker == "review-only action" and promotion_evaluation is not None:
        reasons = _promotion_reasons(promotion_evaluation)
        if reasons:
            return (
                "Open the candidate page and record approve, defer, or reject. This "
                "row remains research-only until the blocked checks clear: "
                f"{'; '.join(reason.rstrip('.') for reason in reasons)}."
            )
        return (
            "Open the candidate page and record approve, defer, or reject. This row "
            "remains research-only until the portfolio manager can promote it."
        )
    if order_approved and blocker == "broker submit gate closed":
        return (
            "Order intent is approved and hash-bound, but broker submission is still "
            "closed by local policy or broker state."
        )
    steps = {
        "ready": "Paper submit is available. Review the order value, then submit intentionally.",
        "order approval required": (
            "Approve this exact order intent here. If size, policy, account, or evidence "
            "changes, approval must be recorded again."
        ),
        "current human approval required": (
            "The latest human review is not an approval for this exact research report. "
            "Re-open the candidate, approve the current thesis, then approve the order intent."
        ),
        "missing order size": (
            "Connect broker account data or position data so the preview can size the order."
        ),
        "final action is no trade": (
            "No execution action. Return to research only if new evidence changes the final action."
        ),
        "review-only action": (
            "Open the candidate page and record approve, defer, or reject. A WATCH/HOLD "
            "row is research-only and does not create an order."
        ),
        "risk blocked": (
            "No button can override this. Inspect the risk gates; then refresh data or "
            "wait for a later cycle with stronger evidence."
        ),
        "preview is not ready": f"This preview is informational only. Reason: {raw_reason}.",
        "broker submit gate closed": (
            "Keep reviewing; broker submission is disabled by local policy."
        ),
    }
    return steps.get(blocker, "Review broker and risk state before taking action.")


def _can_promote_after_approval(
    promotion_evaluation: Mapping[str, object] | None,
) -> bool:
    return bool(
        promotion_evaluation is not None
        and promotion_evaluation.get("can_promote_after_approval") is True
    )


def _execution_preview_caution(
    preview: Mapping[str, object],
    raw_reason: str,
) -> dict[str, object]:
    required = bool(
        str(preview["side"]) == "NONE"
        and str(preview["risk_decision"]) == "WARN"
        and "Caution:" in raw_reason
    )
    recommendation = (
        "This is a research-only candidate. Acknowledge the caution, inspect the "
        "named gate or data issue, and wait for a later orderable cycle before "
        "trading."
        if required
        else ""
    )
    return {
        "required": required,
        "text": raw_reason if required else "",
        "recommendation": recommendation,
    }


def _promotion_text(
    promotion_evaluation: Mapping[str, object] | None,
    key: str,
    default: str,
) -> str:
    if promotion_evaluation is None:
        return default
    value = promotion_evaluation.get(key)
    if value is None:
        return default
    text = " ".join(str(value).split())
    return text or default


def _promotion_status_label_for_card(
    promotion_evaluation: Mapping[str, object] | None,
) -> str:
    label = _promotion_text(promotion_evaluation, "status_label", "Not evaluated")
    state = _promotion_text(promotion_evaluation, "state", "")
    if state == "not_eligible" and _promotion_reasons(promotion_evaluation):
        return "Blocked checks"
    return label


def _promotion_reasons(
    promotion_evaluation: Mapping[str, object] | None,
) -> list[str]:
    if promotion_evaluation is None:
        return []
    reasons = promotion_evaluation.get("reasons")
    if not isinstance(reasons, Sequence) or isinstance(reasons, str | bytes):
        return []
    return [str(reason) for reason in reasons]


def _operator_manual_advance_status_label(
    promotion_evaluation: Mapping[str, object] | None,
) -> str:
    advance = _promotion_mapping(promotion_evaluation, "operator_manual_advance")
    if advance is not None:
        return "Advanced with caution"
    if (
        promotion_evaluation is not None
        and promotion_evaluation.get("manual_advance_available") is True
    ):
        return "Manual advance available"
    return ""


def _operator_manual_advance_detail(
    promotion_evaluation: Mapping[str, object] | None,
) -> str:
    advance = _promotion_mapping(promotion_evaluation, "operator_manual_advance")
    if advance is not None:
        return (
            "Operator manual advance is recorded for this exact selection report. "
            f"Reason: {advance.get('reason', 'not recorded')}"
        )
    if (
        promotion_evaluation is not None
        and promotion_evaluation.get("manual_advance_available") is True
    ):
        reasons = _promotion_reasons(promotion_evaluation)
        blocker = reasons[0] if reasons else "paper-promotion checks blocked this row"
        return (
            "A human operator can advance this paper workflow with caution. "
            f"Current blocker: {blocker}"
        )
    return ""


def _promotion_mapping(
    promotion_evaluation: Mapping[str, object] | None,
    key: str,
) -> Mapping[str, object] | None:
    if promotion_evaluation is None:
        return None
    value = promotion_evaluation.get(key)
    return value if isinstance(value, Mapping) else None


def _promotion_primary_reason(
    promotion_evaluation: Mapping[str, object] | None,
) -> str:
    reasons = _promotion_reasons(promotion_evaluation)
    return reasons[0].rstrip(". ") if reasons else ""


def _promotion_first_reason(
    promotion_evaluation: Mapping[str, object] | None,
) -> str:
    reasons = _promotion_reasons(promotion_evaluation)
    return reasons[0] if reasons else ""


def _promotion_check_rows(
    promotion_evaluation: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    if promotion_evaluation is None:
        return []
    checks = promotion_evaluation.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, str | bytes):
        return []
    rows: list[dict[str, object]] = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        status = str(check.get("status") or "UNKNOWN").upper()
        observed = _clean_text(check.get("observed"), default="not reported")
        required = _clean_text(check.get("required"), default="policy requirement")
        rows.append(
            {
                "name": _clean_text(check.get("name"), default="promotion_check"),
                "label": _clean_text(check.get("label"), default="Promotion check"),
                "status": status,
                "status_class": _promotion_check_status_class(status),
                "detail": _clean_text(check.get("detail"), default="No detail reported."),
                "observed": observed,
                "required": required,
                "value_detail": _clean_text(
                    check.get("value_detail"),
                    default=f"{observed} / required {required}",
                ),
            }
        )
    return rows


def _promotion_check_summary(
    promotion_evaluation: Mapping[str, object] | None,
) -> str:
    rows = _promotion_check_rows(promotion_evaluation)
    if not rows:
        return "Not evaluated"
    passed = sum(1 for row in rows if row["status"] == "PASS")
    blocked = sum(1 for row in rows if row["status"] == "BLOCK")
    warnings = sum(1 for row in rows if row["status"] == "WARN")
    parts = [f"{passed} passed"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if warnings:
        parts.append(f"{warnings} warning")
    return ", ".join(parts)


def _promotion_check_status_class(status: str) -> str:
    if status == "PASS":
        return "pass"
    if status == "BLOCK":
        return "block"
    if status == "WARN":
        return "warn"
    return "neutral"


def _clean_text(value: object, *, default: str) -> str:
    if value is None:
        return default
    text = " ".join(str(value).split())
    return text or default

def _execution_detail(
    submit_gate_open: bool,
    broker_connected: bool,
    *,
    broker_mode: str = "paper",
    freshness_ready: bool = True,
    freshness_detail: str = "",
) -> str:
    if submit_gate_open:
        return "Alpaca paper broker is connected; approved READY previews can be submitted."
    if broker_connected:
        if broker_mode != "paper":
            return "Broker reads are not from Alpaca paper mode; paper submit remains closed."
        if not freshness_ready:
            return freshness_detail or "Critical broker or evidence freshness must be refreshed."
        return "Alpaca paper broker is connected, but broker submission remains gated."
    return "Broker is offline or not configured; previews stay local until Alpaca connects."
