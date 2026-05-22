"""View-model constructors for the risk page."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import cast

from agency.api.health import runtime_data_source_status
from agency.runtime import build_live_readiness
from agency.runtime.data_load_status import load_data_load_status
from agency.services import (
    PaperTradePromotionConfig,
    build_risk_decisions,
    load_active_portfolio_policy,
    promote_paper_trade_reports,
)
from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    _active_cycle_reports,
    _dashboard_selection_reports,
    _decision_class,
    _float_field,
    _format_timestamp_label,
    _human_list,
    _human_review_index,
    _int_field,
    _label_text,
    _list_field,
    _mapping_field,
    _percent,
    _runtime_payload_key,
    _source_health_origin_label,
    _source_is_degraded,
    _string_list,
    dashboard_data_health,
    live_runtime_source_health_rows,
)


async def risk_context() -> dict[str, object]:
    from agency.views.command import human_review_events_for_reports, source_status_rows
    from agency.views.market_regime import broker_status_context
    from agency.views.portfolio import (
        _broker_gross_exposure_pct,
        _broker_orders,
        _broker_positions,
        _broker_ready_for_paper_promotion,
        _pending_opening_order_exposure_pct,
    )
    raw_reports, data_sources, broker = await asyncio.gather(
        _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
        live_runtime_source_health_rows(runtime_data_source_status),
        broker_status_context(),
    )
    reports = _active_cycle_reports(raw_reports)
    policy = await load_active_portfolio_policy()
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=[],
    )
    data_load_status = load_data_load_status(
        source_health_rows=data_sources,
        source_health_origin=_source_health_origin_label(data_sources),
    )
    review_states = _human_review_index(
        await human_review_events_for_reports(reports, readiness)
    )
    promoted_reports = promote_paper_trade_reports(
        reports,
        review_states=review_states,
        positions=_broker_positions(broker),
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
    risk_rows = risk_decision_rows(
        [result.risk_decision for result in risk_results],
        selection_reports=promoted_reports,
    )
    sorted_rows = sorted(risk_rows, key=_risk_row_sort_key)
    source_last_update = _latest_source_checked_at(data_sources)
    return {
        "data_health": dashboard_data_health(
            "Risk dashboard",
            data_load_status=data_load_status,
            datasets=("prices_daily", "stock_trades", "sec_company_facts", "sec_form4", "sec_13f"),
            cycle_id=str(readiness.get("cycle_id") or ""),
            extra_rows=(
                {
                    "kind": "Runtime sources",
                    "name": "Risk source-health gate",
                    "status_label": "Source warnings" if any(_source_is_degraded(source) for source in data_sources) else "Sources fresh",
                    "status_class": "warn" if any(_source_is_degraded(source) for source in data_sources) else "pass",
                    "coverage_label": f"{len(data_sources)} sources checked",
                    "freshness_label": "latest runtime source-health",
                    "last_update": source_last_update,
                    "detail": "Risk uses source-health rows to block or warn candidates when critical evidence needs refresh.",
                },
            ),
        ),
        "risk_rows": sorted_rows,
        "allow_rows": [row for row in sorted_rows if row["decision"] == "ALLOW"],
        "warn_rows": [row for row in sorted_rows if row["decision"] == "WARN"],
        "block_rows": [row for row in sorted_rows if row["decision"] == "BLOCK"],
        "data_sources": source_status_rows(data_sources),
        "summary": risk_summary(risk_rows, data_sources),
    }


def _latest_source_checked_at(data_sources: Sequence[Mapping[str, object]]) -> str:
    values = [
        str(source.get("checked_at") or "")
        for source in data_sources
        if str(source.get("checked_at") or "").strip()
    ]
    return max(values) if values else "not checked"

def risk_decision_rows(
    decisions: Sequence[Mapping[str, object]],
    *,
    selection_reports: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    report_index = {
        _runtime_payload_key(report): report
        for report in selection_reports
        if all(_runtime_payload_key(report))
    }
    return [
        _risk_decision_row(
            decision,
            selection_report=report_index.get(_runtime_payload_key(decision)),
        )
        for decision in decisions
    ]

def risk_summary(
    rows: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    degraded_source_count = sum(1 for source in data_sources if _source_is_degraded(source))
    allow_count = sum(1 for row in rows if row["decision"] == "ALLOW")
    warn_count = sum(1 for row in rows if row["decision"] == "WARN")
    block_count = sum(1 for row in rows if row["decision"] == "BLOCK")
    return {
        "decision_count": len(rows),
        "allow_count": allow_count,
        "warn_count": warn_count,
        "block_count": block_count,
        "degraded_source_count": degraded_source_count,
        "headline": _risk_headline(len(rows), allow_count, warn_count, block_count),
        "detail": (
            "Risk converts final-selection reports into three buckets: orderable, "
            "review-only, and blocked archive."
        ),
        "warn_meaning": (
            "WARN means the candidate is reviewable, but not automatically executable. "
            "For WATCH/HOLD rows, approval records your research decision only."
        ),
        "blocked_meaning": (
            "BLOCK means policy or action gates prevent a paper order. These rows are "
            "kept for traceability and should not be worked one by one."
        ),
        "next_action": _risk_summary_next_action(allow_count, warn_count, block_count),
    }

def _risk_decision_row(
    decision: Mapping[str, object],
    *,
    selection_report: Mapping[str, object] | None = None,
) -> dict[str, object]:
    reasons = _string_list(decision, "reasons")
    checks = _check_rows(decision, "checks")
    blocking_checks = [check for check in checks if check["status"] == "BLOCK"]
    warning_checks = [check for check in checks if check["status"] == "WARN"]
    final_action = str(decision["final_action"])
    selection_gates = _gate_rows(selection_report) if selection_report is not None else []
    llm_action, llm_rationale = _risk_llm_fields(selection_report)
    return {
        "cycle_id": str(decision["cycle_id"]),
        "ticker": str(decision["ticker"]),
        "decision": str(decision["decision"]),
        "decision_class": _decision_class(str(decision["decision"])),
        "final_action": final_action,
        "conviction_pct": _percent(decision, "final_conviction"),
        "position_size_pct": _float_field(decision, "position_size_pct"),
        "projected_gross_exposure_pct": _float_field(
            decision,
            "projected_gross_exposure_pct",
        ),
        "reason": reasons[0] if reasons else "risk decision recorded",
        "decision_title": _risk_decision_title(
            str(decision["decision"]),
            final_action,
            blocking_checks,
            warning_checks,
        ),
        "decision_meaning": _risk_decision_meaning(
            str(decision["decision"]),
            final_action,
            blocking_checks,
            warning_checks,
        ),
        "decision_action": _risk_user_action(str(decision["decision"]), final_action),
        "primary_issue": _risk_primary_issue(blocking_checks, warning_checks),
        "plain_check_summary": _risk_plain_check_summary(
            str(decision["decision"]),
            blocking_checks,
            warning_checks,
        ),
        "next_step": _risk_next_step(str(decision["decision"]), final_action),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "selection_gates": selection_gates,
        "selection_gate_summary": _selection_gate_summary(selection_gates),
        "checks": checks,
        "llm_action": llm_action,
        "llm_rationale": llm_rationale,
        "llm_conflict": _risk_llm_conflict(selection_report, final_action, llm_action),
        "deterministic_score_label": _risk_deterministic_score_label(selection_report),
    }

def _risk_llm_fields(selection_report: Mapping[str, object] | None) -> tuple[str, str]:
    if selection_report is None:
        return "LLM review unavailable - rules-only", "No selection report was attached to this risk row."
    review = _mapping_field(selection_report, "llm_review")
    action = str(
        review.get("action")
        or selection_report.get("llm_action")
        or "LLM review unavailable - rules-only"
    )
    rationale = str(
        review.get("rationale")
        or review.get("reason")
        or selection_report.get("llm_rationale")
        or "No LLM rationale was available; deterministic gates produced this risk view."
    )
    return action, rationale

def _risk_llm_conflict(
    selection_report: Mapping[str, object] | None,
    final_action: str,
    llm_action: str,
) -> str:
    if selection_report is None or "unavailable" in llm_action.lower():
        return "rules-only"
    normalized = llm_action.upper()
    if normalized == final_action.upper():
        return "aligned"
    return "review conflict"

def _risk_deterministic_score_label(selection_report: Mapping[str, object] | None) -> str:
    if selection_report is None:
        return "Rules score unavailable"
    deterministic = _mapping_field(selection_report, "deterministic")
    action = str(
        selection_report.get("deterministic_action")
        or deterministic.get("action")
        or "rules"
    )
    value = (
        selection_report.get("deterministic_conviction")
        or deterministic.get("confidence")
        or deterministic.get("score")
        or selection_report.get("final_conviction")
        or 0.0
    )
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        value = 0.0
    try:
        conviction = float(value)
    except (TypeError, ValueError):
        conviction = 0.0
    if conviction <= 1.0:
        conviction *= 100.0
    return f"{action} / {conviction:.0f}% deterministic"

def _gate_status(report: Mapping[str, object]) -> str:
    gates = _list_field(report, "policy_gates")
    statuses = [
        str(cast(Mapping[str, object], gate)["status"])
        for gate in gates
        if isinstance(gate, Mapping)
    ]
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARN" in statuses:
        return "WARN"
    if "PASS" in statuses:
        return "PASS"
    return "UNKNOWN"

def _gate_rows(report: Mapping[str, object]) -> list[dict[str, str]]:
    return _check_rows(report, "policy_gates")

def _check_rows(payload: Mapping[str, object], key: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in _list_field(payload, key):
        item_payload = cast(Mapping[str, object], item)
        name = str(item_payload["name"])
        status = str(item_payload["status"])
        reason = str(item_payload["reason"])
        rows.append(
            {
                "name": name,
                "label": _gate_label(name),
                "status": status,
                "reason": reason,
                "criteria": _gate_criteria(name),
                "meaning": _gate_meaning(name, status, reason, payload),
                "next_step": _gate_next_step(name, status, payload),
                "status_class": status.lower(),
            }
        )
    return rows

def _gate_label(name: str) -> str:
    labels = {
        "cycle_capacity": "Cycle capacity",
        "evidence_breadth": "Evidence breadth",
        "final_action": "Orderable action",
        "freshness": "Data freshness",
        "gross_exposure": "Gross exposure",
        "min_conviction": "Minimum conviction",
        "policy_gates": "Selection policy gates",
        "risk_flags": "Selection risk flags",
        "runtime_sources": "Runtime source health",
    }
    return labels.get(name, _label_text(name))

def _gate_criteria(name: str) -> str:
    criteria = {
        "cycle_capacity": "New trade candidates must fit within max new positions per cycle.",
        "evidence_breadth": "The candidate needs enough independent sources and confirmed signals.",
        "final_action": "Only BUY, SELL, SHORT, or COVER can become paper orders.",
        "freshness": "Evidence should be fresh enough for the current trading decision.",
        "gross_exposure": "Projected portfolio exposure must stay below the configured cap.",
        "min_conviction": "Final conviction must meet the configured risk threshold.",
        "policy_gates": "Selection-stage gates must not contain a BLOCK state.",
        "risk_flags": "Selection risk flags require extra review before acting.",
        "runtime_sources": "Runtime source health must be available and not degraded.",
    }
    return criteria.get(name, "Risk gate must satisfy the configured policy.")

def _gate_meaning(
    name: str,
    status: str,
    reason: str,
    payload: Mapping[str, object] | None = None,
) -> str:
    if name == "freshness" and payload is not None:
        data_as_of, generated_at = _freshness_proof_labels(payload)
        if status == "PASS":
            return (
                f"Passed: evidence is marked fresh. Proof: Data as of {data_as_of}; "
                f"report generated {generated_at}."
            )
        return (
            f"{status.title()}: {reason}. Proof: Data as of {data_as_of}; "
            f"report generated {generated_at}."
        )
    if status == "PASS":
        return f"Passed: {reason}."
    meanings = {
        ("final_action", "BLOCK"): (
            "The selection engine rejected this as a trade candidate, so no paper "
            "order is allowed."
        ),
        ("final_action", "WARN"): (
            "The candidate is review-only. Human review can approve watching it, "
            "but not submit an order."
        ),
        ("policy_gates", "BLOCK"): (
            "At least one selection-stage policy gate blocked the candidate before "
            "risk sizing."
        ),
        ("policy_gates", "WARN"): (
            "A selection-stage policy gate warned; the candidate can be reviewed "
            "but needs caution."
        ),
        ("min_conviction", "BLOCK"): (
            "The final conviction is below the minimum required for an orderable "
            "paper candidate."
        ),
        ("runtime_sources", "WARN"): (
            "One or more runtime data sources are degraded or need refresh; treat the "
            "decision conservatively."
        ),
        ("risk_flags", "WARN"): (
            "The selection report carried risk flags that must be considered "
            "before approval."
        ),
    }
    selected = meanings.get((name, status))
    if selected is not None:
        return selected
    return f"{status.title()}: {reason}."

def _gate_next_step(
    name: str,
    status: str,
    payload: Mapping[str, object] | None = None,
) -> str:
    if name == "freshness" and status == "PASS":
        return "No refresh is needed only while those timestamps remain current for the trading session."
    if status == "PASS":
        return "No action needed for this gate."
    steps = {
        "final_action": (
            "Return to the candidate evidence; only a later cycle with a trade "
            "action can create an order."
        ),
        "freshness": "Run the data refresh before relying on this signal for a new action.",
        "runtime_sources": "Check source health and refresh degraded sources.",
        "policy_gates": (
            "Expand the selection policy gates to see the exact gate that warned "
            "or blocked."
        ),
        "min_conviction": "Wait for stronger evidence or a higher-conviction later cycle.",
        "risk_flags": (
            "Inspect the candidate page and verify whether the flag changes your decision."
        ),
    }
    return steps.get(name, "Review this gate before approving the candidate.")

def _freshness_proof_labels(payload: Mapping[str, object]) -> tuple[str, str]:
    return (
        _format_timestamp_label(payload.get("as_of")),
        _format_timestamp_label(payload.get("generated_at")),
    )

def _selection_gate_summary(gates: Sequence[Mapping[str, object]]) -> str:
    if not gates:
        return "Selection gate details were not attached to this risk view."
    blockers = [gate for gate in gates if gate["status"] == "BLOCK"]
    warnings = [gate for gate in gates if gate["status"] == "WARN"]
    if blockers:
        return "Blocked by " + _human_list([str(gate["label"]) for gate in blockers]) + "."
    if warnings:
        return "Warning from " + _human_list([str(gate["label"]) for gate in warnings]) + "."
    return "All selection gates passed."

def _risk_decision_title(
    decision: str,
    final_action: str,
    blocking_checks: Sequence[Mapping[str, object]],
    warning_checks: Sequence[Mapping[str, object]],
) -> str:
    if decision == "ALLOW":
        return "Allowed for paper preview"
    if decision == "WARN":
        return f"Review required: {final_action} is not automatically executable"
    if blocking_checks:
        return "Blocked by " + _human_list([str(check["label"]) for check in blocking_checks])
    if warning_checks:
        return "Blocked after warnings"
    return "Blocked by risk policy"

def _risk_decision_meaning(
    decision: str,
    final_action: str,
    blocking_checks: Sequence[Mapping[str, object]],
    warning_checks: Sequence[Mapping[str, object]],
) -> str:
    if decision == "ALLOW":
        return "Risk did not find a blocker; paper preview can be reviewed next."
    if decision == "WARN":
        return (
            f"{final_action} remains review-only or cautionary. Inspect the warning gates, "
            "then approve, defer, or reject the candidate."
        )
    if blocking_checks:
        first = blocking_checks[0]
        return f"{first['meaning']} Main blocker: {first['reason']}."
    if warning_checks:
        return "Warnings escalated this candidate out of the executable queue."
    return "Risk policy prevented this candidate from moving toward a paper order."

def _risk_user_action(decision: str, final_action: str) -> str:
    if decision == "ALLOW":
        return (
            "Inspect the execution preview. If it is READY and approved, submit "
            "paper intentionally."
        )
    if decision == "WARN":
        if final_action in {"WATCH", "HOLD"}:
            return (
                "Treat this as research review only: open the candidate, approve watch, "
                "defer, or reject. It will not place an order."
            )
        return "Review warning gates before any paper order is allowed."
    if final_action == "NO_TRADE":
        return "No user action is required; this row is kept only for audit traceability."
    return "This cannot proceed until the blocking gate is cleared by a later cycle."

def _risk_primary_issue(
    blocking_checks: Sequence[Mapping[str, object]],
    warning_checks: Sequence[Mapping[str, object]],
) -> str:
    if blocking_checks:
        first = blocking_checks[0]
        return f"{first['label']}: {first['meaning']}"
    if warning_checks:
        first = warning_checks[0]
        return f"{first['label']}: {first['meaning']}"
    return "All risk gates passed."

def _risk_plain_check_summary(
    decision: str,
    blocking_checks: Sequence[Mapping[str, object]],
    warning_checks: Sequence[Mapping[str, object]],
) -> str:
    if decision == "ALLOW":
        return "No blocker or warning gate is active for this risk row."
    if blocking_checks:
        labels = _human_list([str(check["label"]) for check in blocking_checks])
        return f"Blocked by {labels}."
    if warning_checks:
        labels = _human_list([str(check["label"]) for check in warning_checks])
        return f"Warnings to inspect: {labels}."
    return "Risk policy stopped the row without a detailed check list."

def _risk_next_step(decision: str, final_action: str) -> str:
    if decision == "ALLOW":
        return "Open execution preview and inspect the paper order artifact."
    if decision == "WARN":
        if final_action in {"WATCH", "HOLD"}:
            return "Open the candidate page and record human review; no paper order is created yet."
        return "Review the warning gates before approving any paper preview."
    if final_action == "NO_TRADE":
        return "No execution action. Revisit only if a later cycle changes the final action."
    return "Resolve the blocking gate before this can move toward paper execution."

def _risk_row_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    decision_priority = {"WARN": 0, "ALLOW": 1, "BLOCK": 2}
    return (
        decision_priority.get(str(row["decision"]), 3),
        -_int_field(row, "conviction_pct"),
        str(row["ticker"]),
    )

def _risk_headline(
    decision_count: int,
    allow_count: int,
    warn_count: int,
    block_count: int,
) -> str:
    if decision_count == 0:
        return "No risk decisions yet."
    return f"{allow_count} allowed, {warn_count} warned, {block_count} blocked."

def _risk_summary_next_action(allow_count: int, warn_count: int, block_count: int) -> str:
    if allow_count > 0:
        return "Start with allowed rows; they are the only rows that can become paper previews."
    if warn_count > 0:
        return "Start with WARN rows in the review queue; they are research approvals, not orders."
    if block_count > 0:
        return "There is no actionable risk queue in this cycle; blocked rows are archive material."
    return "Wait for the next runtime cycle to produce risk decisions."

def _risk_flag_count(report: Mapping[str, object]) -> int:
    return len(_list_field(report, "risk_flags"))
