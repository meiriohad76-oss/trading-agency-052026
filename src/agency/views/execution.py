"""View-model constructors for the execution page."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlencode
import asyncio

from agency.api.health import runtime_data_source_status
from agency.db import get_session
from agency.runtime import build_live_readiness
from agency.services import PaperTradePromotionConfig, PortfolioPolicy, TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG, build_execution_previews, build_leveraged_alternative_review, build_risk_decisions, persist_order_execution_state, promote_paper_trade_reports

from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    _active_cycle_reports,
    _dashboard_selection_reports,
    _env_bool_text,
    _float_field,
    _human_review_index,
    _human_review_key,
    _human_review_summary,
    _int_field,
    _lifecycle_events_for_reports,
    _mapping_field,
    _mapping_list_field,
    _optional_float_field,
    _runtime_payload_key,
    _string_list,
)


async def execution_preview_context(
    *,
    raw_reports: Sequence[Mapping[str, object]] | None = None,
    data_sources: Sequence[Mapping[str, object]] | None = None,
    broker: Mapping[str, object] | None = None,
) -> dict[str, object]:
    from agency.views.command import human_review_events_for_reports
    from agency.views.market_regime import broker_status_context
    from agency.views.portfolio import _broker_account, _broker_gross_exposure_pct, _broker_orders, _broker_positions, _broker_ready_for_paper_promotion, _pending_opening_order_exposure_pct
    if raw_reports is None or data_sources is None or broker is None:
        fetched_reports, fetched_sources, fetched_broker = await asyncio.gather(
            _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
            runtime_data_source_status(),
            broker_status_context(),
        )
        if raw_reports is None:
            raw_reports = fetched_reports
        if data_sources is None:
            data_sources = fetched_sources
        if broker is None:
            broker = fetched_broker
    reports = _active_cycle_reports(raw_reports)
    policy = PortfolioPolicy.from_env()
    broker_positions = _broker_positions(broker)
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=[],
    )
    review_states = _human_review_index(
        await human_review_events_for_reports(reports, readiness)
    )
    promoted_reports = promote_paper_trade_reports(
        reports,
        review_states=review_states,
        positions=broker_positions,
        open_orders=_broker_orders(broker),
        broker_ready=_broker_ready_for_paper_promotion(broker),
        config=PaperTradePromotionConfig.from_env(),
    )
    risk_results = build_risk_decisions(
        promoted_reports,
        data_sources,
        policy=policy,
        current_gross_exposure_pct=_broker_gross_exposure_pct(broker),
        pending_opening_order_exposure_pct=_pending_opening_order_exposure_pct(broker),
    )
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results],
        policy=policy,
        account=_broker_account(broker),
        positions=broker_positions,
        open_orders=_broker_orders(broker),
    )
    research_approval_keys = await execution_approval_keys(
        reports=promoted_reports,
        data_sources=data_sources,
        risk_decisions=[result.risk_decision for result in risk_results],
    )
    order_approval_keys = await order_approval_keys_for_reports(
        reports=promoted_reports,
        data_sources=data_sources,
        previews=[result.preview for result in preview_results],
    )
    preview_rows = execution_preview_rows(
        [result.preview for result in preview_results],
        approval_keys=research_approval_keys,
        order_approval_keys=order_approval_keys,
        review_states=review_states,
    )
    leveraged_reviews = [
        build_leveraged_alternative_review(
            report,
            risk_decision=risk_result.risk_decision,
        )
        for report, risk_result in zip(promoted_reports, risk_results, strict=True)
    ]
    return {
        "broker": broker,
        "preview_rows": preview_rows,
        "orderable_rows": [row for row in preview_rows if row["preview_state"] == "READY"],
        "review_only_rows": [row for row in preview_rows if row["preview_state"] == "DISABLED"],
        "blocked_rows": [row for row in preview_rows if row["preview_state"] == "BLOCKED"],
        "leveraged_alternatives": leveraged_alternative_panel(leveraged_reviews),
        "summary": execution_preview_summary(preview_rows, broker=broker, policy=policy),
    }

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
    if not _env_bool_text("AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS", default=True):
        return {_runtime_payload_key(report) for report in reports}
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=risk_decisions,
    )
    events = await human_review_events_for_reports(reports, readiness)
    approved: set[tuple[str, str, str]] = set()
    for event in events:
        payload = _mapping_field(event, "payload")
        if str(payload.get("review_decision", "")).upper() == "APPROVE":
            approved.add(_human_review_key(event))
    return approved

async def order_approval_keys_for_reports(
    *,
    reports: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
    previews: Sequence[Mapping[str, object]],
) -> set[tuple[str, str, str, str]]:
    if not _env_bool_text("AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS", default=True):
        return {_order_approval_key_from_preview(preview) for preview in previews}
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=[],
    )
    events = await order_approval_events_for_reports(reports, readiness)
    approved: set[tuple[str, str, str, str]] = set()
    for event in events:
        if str(event.get("status")) != "PASSED":
            continue
        payload = _mapping_field(event, "payload")
        if str(payload.get("approval_type")) == "ORDER_APPROVAL":
            approved.add(_order_approval_key(event))
    return approved

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
) -> None:
    async with get_session() as session:
        await persist_order_execution_state(
            session,
            cycle_id=str(preview_row["cycle_id"]),
            order=order,
            reason="Alpaca paper order submitted from execution preview",
            payload_extra={"preview": dict(preview_row)},
        )
        await session.commit()

def execution_preview_rows(
    previews: Sequence[Mapping[str, object]],
    *,
    approval_keys: set[tuple[str, str, str]] | None = None,
    order_approval_keys: set[tuple[str, str, str, str]] | None = None,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    research_approved = set() if approval_keys is None else approval_keys
    order_approved = set() if order_approval_keys is None else order_approval_keys
    review_lookup = {} if review_states is None else review_states
    rows = [
        _execution_preview_row(
            preview,
            human_approved=_runtime_payload_key(preview) in research_approved,
            order_approved=_order_approval_key_from_preview(preview) in order_approved,
            review_event=review_lookup.get(_runtime_payload_key(preview)),
        )
        for preview in previews
    ]
    return sorted(rows, key=_execution_preview_sort_key)

def execution_preview_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    broker: Mapping[str, object] | None = None,
    policy: PortfolioPolicy | None = None,
) -> dict[str, object]:
    from agency.views.portfolio import _broker_account, _broker_gross_exposure_pct, _broker_positions, _portfolio_execution_detail
    normalized_policy = policy or PortfolioPolicy()
    ready_count = sum(1 for row in rows if row["preview_state"] == "READY")
    blocked_count = sum(1 for row in rows if row["preview_state"] == "BLOCKED")
    disabled_count = sum(1 for row in rows if row["preview_state"] == "DISABLED")
    submit_ready_count = sum(1 for row in rows if row["submit_enabled"] is True)
    broker_connected = bool(broker is not None and broker.get("connected") is True)
    broker_mode = str(broker.get("mode", "paper")) if broker is not None else "paper"
    submit_gate_open = normalized_policy.broker_submit_enabled and broker_connected
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
        "detail": _execution_detail(submit_gate_open, broker_connected),
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
) -> dict[str, object]:
    reasons = _string_list(preview, "reasons")
    raw_reason = reasons[0] if reasons else "preview recorded"
    preview_submit_enabled = preview["submit_enabled"] is True
    submit_enabled = preview_submit_enabled and order_approved
    order_approval_available = (
        str(preview["preview_state"]) == "READY"
        and str(preview["side"]) in {"BUY", "SELL", "SHORT", "COVER"}
        and (
            isinstance(preview["quantity"], int | float)
            or isinstance(preview["notional"], int | float)
        )
    )
    submit_blocker = _submit_blocker(
        preview=preview,
        preview_submit_enabled=preview_submit_enabled,
        order_approved=order_approved,
    )
    human_review = _human_review_summary(review_event)
    ticker = str(preview["ticker"])
    cycle_id = str(preview["cycle_id"])
    as_of = str(preview["as_of"])
    order_intent_hash = str(preview["order_intent_hash"])
    return {
        "preview": dict(preview),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "as_of": as_of,
        "order_intent_version": str(preview["order_intent_version"]),
        "order_intent_hash": order_intent_hash,
        "order_intent_hash_label": order_intent_hash[:12],
        "preview_state": str(preview["preview_state"]),
        "state_class": _preview_state_class(str(preview["preview_state"])),
        "side": str(preview["side"]),
        "risk_decision": str(preview["risk_decision"]),
        "submit_enabled": submit_enabled,
        "order_approval_available": order_approval_available,
        "submit_label": (
            "Submit paper order"
            if submit_enabled
            else _submit_label(
                submit_blocker,
                human_approved=human_approved,
                order_approved=order_approved,
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
        "human_approved": human_approved,
        "order_approved": order_approved,
        "quantity": preview["quantity"],
        "notional": preview["notional"],
        "order_value_label": _order_value_label(preview),
        "entry": preview["entry"],
        "position_size_pct": _float_field(preview, "position_size_pct"),
        "size_label": _execution_size_label(preview),
        "time_in_force": preview["time_in_force"] or "None",
        "reason": _execution_reason_text(preview, raw_reason),
        "order_intent": _execution_order_intent(preview, raw_reason),
        "approval_label": _execution_approval_label(
            preview,
            human_approved=human_approved,
            order_approved=order_approved,
            review_decision=str(human_review["decision"]),
        ),
        "next_step": _execution_next_step(
            submit_blocker,
            preview=preview,
            raw_reason=raw_reason,
            human_approved=human_approved,
            order_approved=order_approved,
            review_decision=str(human_review["decision"]),
        ),
    }

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

def _preview_state_class(state: str) -> str:
    if state == "READY":
        return "pass"
    if state == "DISABLED":
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

def _submit_blocker(
    *,
    preview: Mapping[str, object],
    preview_submit_enabled: bool,
    order_approved: bool,
) -> str:
    if preview_submit_enabled and order_approved:
        return "ready"
    if str(preview["preview_state"]) != "READY":
        return _not_ready_submit_blocker(preview)
    if preview_submit_enabled and not order_approved:
        return "order approval required"
    if preview["quantity"] is None and preview["notional"] is None:
        return "missing order size"
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
) -> str:
    if human_approved and blocker == "review-only action":
        return "Research approved"
    if order_approved and blocker == "broker submit gate closed":
        return "Order approved"
    labels = {
        "broker submit gate closed": "Closed",
        "final action is no trade": "Not orderable",
        "missing order size": "No size",
        "order approval required": "Approve order",
        "preview is not ready": "Blocked",
        "review-only action": "Review only",
        "risk blocked": "Risk blocked",
    }
    return labels.get(blocker, "Closed")

def _order_value_label(preview: Mapping[str, object]) -> str:
    if str(preview["side"]) == "NONE":
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
        return "final action is not a trade"
    if str(preview["preview_state"]) == "BLOCKED":
        return "blocked by risk"
    if side in {"SELL", "COVER"} and isinstance(preview["quantity"], int | float):
        return f"close {float(preview['quantity']):.4f} shares"
    if side in {"BUY", "SHORT"} and isinstance(preview["notional"], int | float):
        return f"{size_pct:.0f}% target position"
    return "waiting for broker/account size"

def _execution_order_intent(preview: Mapping[str, object], raw_reason: str) -> str:
    side = str(preview["side"])
    if side in {"BUY", "SELL", "SHORT", "COVER"}:
        return f"Paper {side.lower()} preview"
    if raw_reason.startswith("NO_TRADE"):
        return "No order: final selection rejected this ticker"
    if raw_reason.startswith(("WATCH", "HOLD")):
        return "Research-only watch: no paper order"
    return "No order side available"

def _execution_reason_text(preview: Mapping[str, object], raw_reason: str) -> str:
    if str(preview["side"]) == "NONE":
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
        return "Research only"
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
    if human_approved and blocker == "review-only action":
        return (
            "Research approval is recorded. Nothing else is required on this screen "
            "for this ticker; it can create a paper order only if a later cycle "
            "upgrades it to BUY, SELL, SHORT, or COVER."
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

def _execution_detail(submit_gate_open: bool, broker_connected: bool) -> str:
    if submit_gate_open:
        return "Alpaca paper broker is connected; approved READY previews can be submitted."
    if broker_connected:
        return "Alpaca paper broker is connected, but broker submission remains gated."
    return "Broker is offline or not configured; previews stay local until Alpaca connects."
