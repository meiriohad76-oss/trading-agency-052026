"""View-model constructors for the final_selection page."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    _dashboard_selection_reports,
    _human_list,
    _int_field,
    _is_actionable_candidate,
    _label_text,
    _latest_selection_cycle_id,
    _mapping_field,
    _percent,
    _plural,
    _reason_summary,
    _reason_text,
    _selection_reports_for_cycle,
    _short_cycle_label,
    _string_list,
)


async def final_selection_context() -> dict[str, object]:
    reports = await _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT)
    cycle_id = _latest_selection_cycle_id(reports)
    cycle_reports = _selection_reports_for_cycle(reports, cycle_id)
    rows = final_selection_rows(cycle_reports)
    actionable_rows = [row for row in rows if _is_actionable_candidate(row)]
    trace_rows = [row for row in rows if not _is_actionable_candidate(row)]
    return {
        "final_rows": rows,
        "actionable_rows": actionable_rows,
        "trace_rows": trace_rows,
        "summary": final_selection_summary(
            rows,
            all_report_count=len(reports),
            cycle_id=cycle_id,
        ),
    }

def final_selection_rows(reports: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows = [_final_selection_row(report) for report in reports]
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
    return {
        "report_count": len(rows),
        "all_report_count": total_report_count,
        "actionable_count": actionable_count,
        "blocked_count": blocked_count,
        "historical_count": historical_count,
        "cycle_id": cycle_id or "None",
        "cycle_label": _short_cycle_label(cycle_id),
        "topbar_label": _final_selection_topbar(len(rows), cycle_id),
        "headline": _final_selection_headline(len(rows), actionable_count),
        "detail": _final_selection_detail(len(rows), historical_count, cycle_id),
        "scope_detail": _final_selection_scope_detail(historical_count, cycle_id),
    }

def _final_selection_row(report: Mapping[str, object]) -> dict[str, object]:
    from agency.views.candidates import _candidate_row
    from agency.views.risk import _gate_rows, _selection_gate_summary
    from agency.views.signals import _context_signal_rows, _decision_explanation, _signal_group_summary, _signal_rows
    base = _candidate_row(report)
    deterministic = _mapping_field(report, "deterministic")
    llm_review = _mapping_field(report, "llm_review")
    evidence_pack = _mapping_field(report, "evidence_pack")
    data_quality = _mapping_field(evidence_pack, "data_quality")
    risk_flags = _string_list(report, "risk_flags")
    actionable = _is_actionable_candidate(base)
    gates = _gate_rows(report)
    actionable_signals = _signal_rows(evidence_pack, "actionable_signals")
    context_signals = _context_signal_rows(evidence_pack)
    suppressed_signals = _signal_rows(evidence_pack, "suppressed_signals")
    deterministic_reason = _reason_text(deterministic)
    return {
        **base,
        "cycle_id": str(report["cycle_id"]),
        "generated_at": str(report["generated_at"]),
        "deterministic_action": str(deterministic["action"]),
        "deterministic_conviction_pct": _percent(deterministic, "conviction"),
        "deterministic_reason": deterministic_reason,
        "llm_action": str(llm_review["action"]),
        "llm_confidence_pct": _percent(llm_review, "confidence"),
        "llm_rationale": str(llm_review["rationale"]),
        "policy_gates": gates,
        "policy_gate_summary": _selection_gate_summary(gates),
        "risk_flags": risk_flags,
        "risk_flag_text": ", ".join(risk_flags) if risk_flags else "none",
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
    }

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
    cycle_label = _short_cycle_label(cycle_id)
    return f"{report_count} latest-cycle reports / {cycle_label} / read-only"

def _final_selection_detail(
    report_count: int,
    historical_count: int,
    cycle_id: str | None,
) -> str:
    if report_count == 0:
        return "The runtime has not persisted selection reports for a current cycle yet."
    scope = _short_cycle_label(cycle_id)
    if historical_count == 0:
        return f"Showing the active runtime cycle ({scope}) so this page matches Command."
    return (
        f"Showing the active runtime cycle ({scope}) so this page matches Command; "
        f"{historical_count} {_plural('older report', historical_count)} remain in history."
    )

def _final_selection_scope_detail(historical_count: int, cycle_id: str | None) -> str:
    cycle_label = _short_cycle_label(cycle_id)
    if cycle_id is None:
        return "Waiting for the first persisted runtime cycle."
    if historical_count == 0:
        return f"Latest cycle only: {cycle_label}."
    return (
        f"Latest cycle only: {cycle_label}. "
        f"{historical_count} {_plural('older report', historical_count)} are hidden "
        "from this decision queue."
    )
