"""View-model constructors for the final_selection page."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _format_timestamp_label,
    _human_list,
    _human_review_index,
    _human_review_summary,
    _int_field,
    _is_actionable_candidate,
    _label_text,
    _latest_selection_cycle_id,
    _lifecycle_events_for_reports,
    _mapping_field,
    _matching_payload,
    _percent,
    _plural,
    _reason_summary,
    _reason_text,
    _selection_reports_for_cycle,
    _short_cycle_label,
    _string_list,
    dashboard_data_health,
    live_dashboard_data_load_status,
)


async def final_selection_context() -> dict[str, object]:
    reports = await _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT)
    cycle_id = _latest_selection_cycle_id(reports)
    cycle_reports = _selection_reports_for_cycle(reports, cycle_id)
    review_events = await _lifecycle_events_for_reports(
        cycle_reports,
        {"cycle_id": cycle_id},
        event_type="HUMAN_REVIEW",
        limit_per_ticker=1,
    )
    risk_decisions = await _dashboard_risk_decisions(limit=len(cycle_reports) or 1)
    rows = final_selection_rows(
        cycle_reports,
        review_events=review_events,
        risk_decisions=risk_decisions,
    )
    actionable_rows = [row for row in rows if _is_actionable_candidate(row)]
    watch_rows = [row for row in rows if str(row["action"]) == "WATCH"]
    no_trade_rows = [row for row in rows if str(row["action"]) == "NO_TRADE"]
    blocked_rows = [
        row
        for row in rows
        if str(row["gate_status"]) == "BLOCK"
        or str(row["action"]) in {"BLOCK", "BLOCKED"}
    ]
    trace_rows = [row for row in rows if not _is_actionable_candidate(row)]
    data_load_status = await live_dashboard_data_load_status()
    return {
        "data_health": dashboard_data_health(
            "Final selection dashboard",
            data_load_status=data_load_status,
            datasets=(
                "prices_daily",
                "stock_trades",
                "sec_company_facts",
                "sec_form4",
                "sec_13f",
                "news_rss",
                "subscription_emails",
            ),
            cycle_id=cycle_id,
        ),
        "final_rows": rows,
        "actionable_rows": actionable_rows,
        "watch_rows": watch_rows,
        "no_trade_rows": no_trade_rows,
        "blocked_rows": blocked_rows,
        "trace_rows": trace_rows,
        "summary": final_selection_summary(
            rows,
            all_report_count=len(reports),
            cycle_id=cycle_id,
        ),
    }

def final_selection_rows(
    reports: Sequence[Mapping[str, object]],
    *,
    review_events: Sequence[Mapping[str, object]] = (),
    risk_decisions: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    review_index = _human_review_index(review_events)
    rows = [
        _final_selection_row(
            report,
            review_event=review_index.get(
                (
                    str(report.get("cycle_id", "")),
                    str(report.get("ticker", "")),
                    str(report.get("as_of", "")),
                )
            ),
            risk_decision=_matching_payload(risk_decisions, report),
        )
        for report in reports
    ]
    return sorted(rows, key=_final_selection_sort_key)

def final_selection_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    all_report_count: int | None = None,
    cycle_id: str | None = None,
) -> dict[str, object]:
    total_report_count = len(rows) if all_report_count is None else all_report_count
    historical_count = max(total_report_count - len(rows), 0)
    actionable_count = sum(1 for row in rows if _is_actionable_candidate(row))
    blocked_count = sum(1 for row in rows if row["gate_status"] == "BLOCK")
    no_trade_count = sum(1 for row in rows if row["action"] == "NO_TRADE")
    return {
        "report_count": len(rows),
        "all_report_count": total_report_count,
        "selected_count": actionable_count,
        "actionable_count": actionable_count,
        "blocked_count": blocked_count,
        "no_trade_count": no_trade_count,
        "historical_count": historical_count,
        "cycle_id": cycle_id or "None",
        "cycle_label": _short_cycle_label(cycle_id),
        "topbar_label": _final_selection_topbar(len(rows), cycle_id),
        "headline": _final_selection_headline(len(rows), actionable_count),
        "detail": _final_selection_detail(len(rows), historical_count, cycle_id),
        "scope_detail": _final_selection_scope_detail(historical_count, cycle_id),
    }

def _final_selection_row(
    report: Mapping[str, object],
    *,
    review_event: Mapping[str, object] | None = None,
    risk_decision: Mapping[str, object] | None = None,
) -> dict[str, object]:
    from agency.views.candidates import (
        _candidate_row,
        _review_action_url,
        _review_caution,
    )
    from agency.views.risk import _gate_rows, _selection_gate_summary
    from agency.views.signals import (
        _context_signal_rows,
        _decision_explanation,
        _signal_group_summary,
        _signal_rows,
    )
    base = _candidate_row(report)
    deterministic = _mapping_field(report, "deterministic")
    llm_review = _mapping_field(report, "llm_review")
    llm_status = _llm_status(llm_review)
    evidence_pack = _mapping_field(report, "evidence_pack")
    data_quality = _mapping_field(evidence_pack, "data_quality")
    risk_flags = _string_list(report, "risk_flags")
    actionable = _is_actionable_candidate(base)
    gates = _gate_rows(report)
    generated_at_label = _format_timestamp_label(report["generated_at"])
    as_of_label = _format_timestamp_label(report["as_of"])
    cycle_id = str(report["cycle_id"])
    actionable_signals = _signal_rows(evidence_pack, "actionable_signals")
    context_signals = _context_signal_rows(evidence_pack)
    suppressed_signals = _signal_rows(evidence_pack, "suppressed_signals")
    deterministic_reason = _reason_text(deterministic)
    human_review = _human_review_summary(review_event)
    ticker = str(base["ticker"])
    caution = _review_caution(report, risk_decision)
    return {
        **base,
        "cycle_id": cycle_id,
        "generated_at": str(report["generated_at"]),
        "generated_at_label": generated_at_label,
        "as_of_label": as_of_label,
        "freshness_proof_label": _freshness_proof_label(
            as_of_label=as_of_label,
            generated_at_label=generated_at_label,
        ),
        "provenance_items": _selection_provenance_items(
            generated_at_label=generated_at_label,
            as_of_label=as_of_label,
            cycle_id=cycle_id,
        ),
        "deterministic_action": str(deterministic["action"]),
        "deterministic_conviction_pct": _percent(deterministic, "conviction"),
        "deterministic_reason": deterministic_reason,
        "llm_action": str(llm_review["action"]),
        "llm_confidence_pct": _percent(llm_review, "confidence"),
        "llm_rationale": str(llm_review["rationale"]),
        "llm_status_label": llm_status["label"],
        "llm_status_class": llm_status["status_class"],
        "llm_status_detail": llm_status["detail"],
        "policy_gates": gates,
        "policy_gate_summary": _selection_gate_summary(gates),
        "risk_flags": risk_flags,
        "risk_flag_text": ", ".join(risk_flags) if risk_flags else "none",
        "action_class": _action_status_class(str(base["action"]), str(base["gate_status"])),
        "review_bucket": "Actionable review" if actionable else "Traceability",
        "review_bucket_class": "pass" if actionable else "neutral",
        "review_next_step": _final_selection_next_step(base, risk_flags),
        "freshness": str(data_quality["freshness"]),
        "source_count": _int_field(data_quality, "source_count"),
        "confirmed_signal_count": _int_field(data_quality, "confirmed_signal_count"),
        "context_signals": context_signals,
        "actionable_signals": actionable_signals,
        "suppressed_signals": suppressed_signals,
        "decision_explanation": _decision_explanation(base, deterministic, data_quality),
        "decision_takeaway": _final_selection_takeaway(base, data_quality, actionable),
        "support_summary": _signal_group_summary(actionable_signals, positive=True),
        "context_summary": _signal_group_summary(context_signals, positive=True),
        "caution_summary": _final_caution_summary(
            suppressed_signals=suppressed_signals,
            risk_flags=risk_flags,
            gates=gates,
        ),
        "plain_reason_rows": _plain_reason_rows(
            deterministic_reason=deterministic_reason,
            risk_flags=risk_flags,
        ),
        "human_review_decision": human_review["decision"],
        "human_review_class": human_review["status_class"],
        "human_review_reason": human_review["reason"],
        "human_review_time": human_review["event_time"],
        "human_review_time_label": _format_timestamp_label(human_review["event_time"]),
        "caution_acknowledgement_required": caution["required"],
        "caution_acknowledgement_text": caution["text"],
        "caution_recommendation": caution["recommendation"],
        "approve_review_action": _review_action_url(
            ticker=ticker,
            cycle_id=cycle_id,
            as_of=str(report["as_of"]),
            decision="APPROVE",
        ),
        "defer_review_action": _review_action_url(
            ticker=ticker,
            cycle_id=cycle_id,
            as_of=str(report["as_of"]),
            decision="DEFER",
        ),
        "reject_review_action": _review_action_url(
            ticker=ticker,
            cycle_id=cycle_id,
            as_of=str(report["as_of"]),
            decision="REJECT",
        ),
    }

def _freshness_proof_label(*, as_of_label: str, generated_at_label: str) -> str:
    return f"Data as of {as_of_label}; report generated {generated_at_label}."

def _selection_provenance_items(
    *,
    generated_at_label: str,
    as_of_label: str,
    cycle_id: str,
) -> list[dict[str, str]]:
    return [
        {"label": "Generated", "value": generated_at_label},
        {"label": "Data as of", "value": as_of_label},
        {"label": "Cycle", "value": cycle_id},
    ]

def _llm_status(llm_review: Mapping[str, object]) -> dict[str, str]:
    action = str(llm_review.get("action", "NO_REVIEW")).strip().upper()
    rationale = str(llm_review.get("rationale") or "").strip()
    concerns = " ".join(_string_list(llm_review, "concerns")).lower()
    rationale_lower = rationale.lower()
    detail = rationale or "No LLM review rationale was recorded."
    if action != "NO_REVIEW":
        return {"label": "Included", "status_class": "pass", "detail": detail}
    if "not enabled" in rationale_lower or "skipped by policy" in rationale_lower:
        return {"label": "Skipped By Policy", "status_class": "neutral", "detail": detail}
    if (
        "missing api key" in rationale_lower
        or "openai_api_key" in rationale_lower
        or "not configured" in rationale_lower
    ):
        return {"label": "Not Configured", "status_class": "block", "detail": detail}
    if any(
        token in f"{rationale_lower} {concerns}"
        for token in ("failed", "error", "unauthorized", "forbidden", "rate_limited")
    ):
        return {"label": "Failed", "status_class": "block", "detail": detail}
    return {"label": "Skipped", "status_class": "neutral", "detail": detail}


def _action_status_class(action: str, gate_status: str) -> str:
    if gate_status == "BLOCK":
        return "block"
    if action == "NO_TRADE":
        return "neutral"
    if action in {"WATCH", "BUY", "SELL", "SHORT", "COVER"}:
        return "pass"
    return "warn"

def _final_selection_takeaway(
    base: Mapping[str, object],
    data_quality: Mapping[str, object],
    actionable: bool,
) -> str:
    ticker = str(base["ticker"])
    action = str(base["action"])
    conviction = _int_field(base, "conviction_pct")
    source_count = _int_field(data_quality, "source_count")
    confirmed_count = _int_field(data_quality, "confirmed_signal_count")
    gate_status = str(base["gate_status"])
    if actionable:
        return (
            f"{ticker} is in the human-review queue as {action} at {conviction}% "
            f"conviction. The report has {source_count} independent source(s), "
            f"{confirmed_count} confirmed signal(s), and gate state {gate_status}."
        )
    if action == "NO_TRADE":
        return (
            f"{ticker} is not a trade candidate in this cycle. Keep it as audit "
            f"context unless a later cycle upgrades the action."
        )
    return (
        f"{ticker} is traceability-only right now because the latest policy or "
        f"risk state is {gate_status}."
    )

def _final_caution_summary(
    *,
    suppressed_signals: Sequence[Mapping[str, object]],
    risk_flags: Sequence[str],
    gates: Sequence[Mapping[str, object]],
) -> str:
    from agency.views.signals import _signal_group_summary
    blockers = [gate for gate in gates if gate["status"] == "BLOCK"]
    warnings = [gate for gate in gates if gate["status"] == "WARN"]
    if blockers:
        return "Blocking gate: " + _human_list([str(gate["label"]) for gate in blockers]) + "."
    if risk_flags:
        labels = _human_list([_label_text(flag) for flag in risk_flags])
        return f"Risk flag to review: {labels}."
    if warnings:
        return "Warning gate: " + _human_list([str(gate["label"]) for gate in warnings]) + "."
    return _signal_group_summary(suppressed_signals, positive=False)

def _plain_reason_rows(
    *,
    deterministic_reason: str,
    risk_flags: Sequence[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for code in _split_reason_codes(deterministic_reason):
        rows.append(
            {
                "label": _label_text(code),
                "detail": _reason_summary(code),
                "tone": _reason_tone(code),
            }
        )
    for flag in risk_flags:
        rows.append(
            {
                "label": _label_text(flag),
                "detail": "Selection carried this risk flag into the review workflow.",
                "tone": "warn",
            }
        )
    if not rows:
        rows.append(
            {
                "label": "No coded reason",
                "detail": "The report did not attach an extra deterministic reason code.",
                "tone": "neutral",
            }
        )
    return rows

def _split_reason_codes(value: str) -> list[str]:
    if value == "none":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]

def _reason_tone(code: str) -> str:
    lowered = code.lower()
    if "bearish" in lowered or "negative" in lowered or "blocked" in lowered:
        return "block"
    if "warn" in lowered or "risk" in lowered or "limited" in lowered:
        return "warn"
    if "bullish" in lowered or "positive" in lowered or "met" in lowered:
        return "pass"
    return "neutral"

def _final_selection_next_step(
    base: Mapping[str, object],
    risk_flags: Sequence[str],
) -> str:
    action = str(base["action"])
    gate_status = str(base["gate_status"])
    if _is_actionable_candidate(base):
        if gate_status == "WARN":
            return (
                "Open the candidate page, inspect warnings and evidence, then approve, "
                "defer, or reject."
            )
        return "Open the candidate page and complete human review before risk/execution."
    if action == "NO_TRADE":
        return "No human approval is needed now; keep it visible only for traceability."
    if gate_status == "BLOCK":
        return "Blocked by selection policy; inspect the policy gates before reconsidering."
    if risk_flags:
        return "Risk flags are present; wait for stronger evidence or a later cycle."
    return "No immediate review action."

def _final_selection_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    actionable_priority = 0 if _is_actionable_candidate(row) else 1
    return (actionable_priority, -_int_field(row, "conviction_pct"), str(row["ticker"]))

def _candidate_detail_sort_key(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        _descending_text_timestamp(str(row.get("generated_at", ""))),
        _descending_text_timestamp(str(row.get("as_of", ""))),
    )

def _descending_text_timestamp(value: str) -> str:
    return "".join(chr(255 - ord(char)) for char in value)

def _final_selection_headline(report_count: int, actionable_count: int) -> str:
    if report_count == 0:
        return "No final selection reports yet."
    return f"{actionable_count} final candidates ready for human review."

def _final_selection_topbar(report_count: int, cycle_id: str | None) -> str:
    if report_count == 0:
        return "no latest-cycle reports / read-only"
    return f"{report_count} latest-cycle {_plural('report', report_count)} / read-only"

def _final_selection_detail(
    report_count: int,
    historical_count: int,
    cycle_id: str | None,
) -> str:
    if report_count == 0:
        return "The runtime has not persisted selection reports for a current cycle yet."
    if historical_count == 0:
        return (
            "Showing the active runtime cycle so this page matches Command; "
            "the full cycle id is shown in the queue header and row provenance."
        )
    return (
        "Showing the active runtime cycle so this page matches Command; "
        f"{historical_count} {_plural('older report', historical_count)} remain in history. "
        "The full cycle id is shown in the queue header and row provenance."
    )

def _final_selection_scope_detail(historical_count: int, cycle_id: str | None) -> str:
    if cycle_id is None:
        return "Waiting for the first persisted runtime cycle."
    if historical_count == 0:
        return "Latest cycle only; full cycle id appears in the queue header."
    return (
        "Latest cycle only. "
        f"{historical_count} {_plural('older report', historical_count)} are hidden "
        "from this decision queue; full cycle id appears in the queue header."
    )
