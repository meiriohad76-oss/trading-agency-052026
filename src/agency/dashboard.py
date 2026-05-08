from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from agency.api.candidates import runtime_candidate_timeline
from agency.api.health import contract_summaries, runtime_data_source_status
from agency.api.reports import runtime_selection_reports
from agency.api.risk import runtime_risk_decisions
from agency.runtime import build_live_readiness
from agency.runtime.data_refresh_progress import load_data_refresh_progress
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.services import (
    build_execution_previews,
    build_learning_outcome,
    build_portfolio_monitor,
    build_risk_decisions,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

ACTIONABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
OPEN_RISK_DECISIONS = {"ALLOW", "WARN"}
DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}


@router.get("/")
async def dashboard(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        await dashboard_context(),
    )


async def dashboard_context() -> dict[str, object]:
    reports, data_sources, risk_decisions = await asyncio.gather(
        runtime_selection_reports(limit=10),
        runtime_data_source_status(),
        runtime_risk_decisions(limit=25),
    )
    candidates = candidate_rows(reports)
    contracts = contract_summaries()
    readiness = readiness_view(
        build_live_readiness(
            source_health=data_sources,
            selection_reports=reports,
            risk_decisions=risk_decisions,
        )
    )
    review_queue = paper_review_queue(reports, risk_decisions, readiness)
    summary = command_summary(
        candidates=candidates,
        data_sources=data_sources,
        contracts=contracts,
        review_queue=review_queue,
    )
    return {
        "actions": command_actions(),
        "contracts": contracts,
        "data_sources": source_status_rows(data_sources),
        "candidates": candidates,
        "data_refresh": data_refresh_progress_view(load_data_refresh_progress()),
        "live_config": live_config_view(load_live_config_readiness()),
        "readiness": readiness,
        "review_queue": review_queue,
        "summary": summary,
    }


@router.get("/candidates/{ticker}")
async def candidate_detail(request: Request, ticker: str) -> Response:
    return templates.TemplateResponse(
        request,
        "candidate_detail.html",
        await candidate_detail_context(ticker),
    )


async def candidate_detail_context(ticker: str) -> dict[str, object]:
    normalized_ticker = ticker.upper()
    reports = await runtime_selection_reports(ticker=normalized_ticker, limit=5)
    timeline = await runtime_candidate_timeline(ticker=normalized_ticker, limit=25)
    report_rows = final_selection_rows(reports)
    return {
        "ticker": normalized_ticker,
        "reports": report_rows,
        "timeline": timeline_rows(timeline),
        "summary": candidate_detail_summary(normalized_ticker, report_rows, timeline),
    }


@router.get("/final-selection")
async def final_selection(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "final_selection.html",
        await final_selection_context(),
    )


async def final_selection_context() -> dict[str, object]:
    reports = await runtime_selection_reports(limit=25)
    rows = final_selection_rows(reports)
    return {
        "final_rows": rows,
        "summary": final_selection_summary(rows),
    }


@router.get("/risk")
async def risk(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "risk.html",
        await risk_context(),
    )


@router.get("/execution-preview")
async def execution_preview(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "execution_preview.html",
        await execution_preview_context(),
    )


@router.get("/policy")
async def policy(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "policy.html",
        {
            "policy_sections": policy_sections(),
            "summary": policy_summary(),
        },
    )


@router.get("/portfolio-monitor")
async def portfolio_monitor(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "portfolio_monitor.html",
        await portfolio_monitor_context(),
    )


@router.get("/learning")
async def learning(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "learning.html",
        learning_context(),
    )


async def risk_context() -> dict[str, object]:
    reports, data_sources = await asyncio.gather(
        runtime_selection_reports(limit=10),
        runtime_data_source_status(),
    )
    risk_results = build_risk_decisions(reports, data_sources)
    risk_rows = risk_decision_rows([result.risk_decision for result in risk_results])
    return {
        "risk_rows": risk_rows,
        "data_sources": source_status_rows(data_sources),
        "summary": risk_summary(risk_rows, data_sources),
    }


async def execution_preview_context() -> dict[str, object]:
    reports, data_sources = await asyncio.gather(
        runtime_selection_reports(limit=10),
        runtime_data_source_status(),
    )
    risk_results = build_risk_decisions(reports, data_sources)
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results]
    )
    preview_rows = execution_preview_rows([result.preview for result in preview_results])
    return {
        "preview_rows": preview_rows,
        "summary": execution_preview_summary(preview_rows),
    }


async def portfolio_monitor_context() -> dict[str, object]:
    reports = await runtime_selection_reports(limit=25)
    demo_positions = [str(report["ticker"]) for report in reports[:5]]
    snapshot = build_portfolio_monitor(reports, positions=demo_positions)
    return {
        "positions": snapshot["positions"],
        "summary": portfolio_monitor_summary(snapshot),
    }


def learning_context() -> dict[str, object]:
    outcome = build_learning_outcome()
    return {
        "outcome": outcome,
        "summary": learning_summary(outcome),
    }


def command_summary(
    *,
    candidates: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
    contracts: Sequence[Mapping[str, object]],
    review_queue: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    degraded_source_count = sum(1 for source in data_sources if _source_is_degraded(source))
    candidate_count = len(candidates)
    actionable_candidate_count = sum(
        1 for candidate in candidates if _is_actionable_candidate(candidate)
    )
    blocked_candidate_count = sum(
        1 for candidate in candidates if candidate["gate_status"] == "BLOCK"
    )
    return {
        "candidate_count": candidate_count,
        "actionable_candidate_count": actionable_candidate_count,
        "blocked_candidate_count": blocked_candidate_count,
        "source_count": len(data_sources),
        "degraded_source_count": degraded_source_count,
        "contract_count": len(contracts),
        "review_queue_count": len(review_queue),
        "hero_class": _command_hero_class(candidate_count, degraded_source_count),
        "headline": _command_headline(candidate_count, actionable_candidate_count),
        "detail": _command_detail(candidate_count, degraded_source_count),
    }


def command_actions() -> list[dict[str, str]]:
    return [
        {"label": "Review config", "href": "#live-config-heading"},
        {"label": "Review readiness", "href": "#readiness-heading"},
        {"label": "Review queue", "href": "#review-queue-heading"},
        {"label": "Review candidates", "href": "#candidates-heading"},
        {"label": "Review data sources", "href": "#source-heading"},
        {"label": "Review contracts", "href": "#contracts-heading"},
    ]


def candidate_rows(reports: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_candidate_row(report) for report in reports]


def source_status_rows(sources: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "source": str(source["source"]),
            "status": str(source["status"]),
            "freshness": str(source["freshness"]),
            "reliability_pct": round(_float_field(source, "reliability_score") * 100),
            "status_class": _source_status_class(source),
            "checked_at": str(source["checked_at"]),
        }
        for source in sources
    ]


def final_selection_rows(reports: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_final_selection_row(report) for report in reports]


def risk_decision_rows(decisions: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_risk_decision_row(decision) for decision in decisions]


def execution_preview_rows(previews: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_execution_preview_row(preview) for preview in previews]


def readiness_view(summary: Mapping[str, object]) -> dict[str, object]:
    view = dict(summary)
    verdict = str(summary["verdict"])
    view["verdict_label"] = _label_text(verdict)
    view["status_class"] = _readiness_status_class(verdict)
    view["blocker_rows"] = _readiness_blocker_rows(summary)
    return view


def data_refresh_progress_view(progress: Mapping[str, object]) -> dict[str, object]:
    view = dict(progress)
    view["progress_style"] = f"width: {_int_field(progress, 'percent_complete')}%"
    return view


def live_config_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    view["check_rows"] = _list_field(readiness, "checks")
    return view


def paper_review_queue(
    reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
) -> list[dict[str, object]]:
    cycle_id = readiness.get("cycle_id")
    if not isinstance(cycle_id, str) or not cycle_id:
        return []
    risks = _risk_decision_index(risk_decisions)
    rows = [
        _paper_review_row(report, risks.get(_runtime_payload_key(report)))
        for report in reports
        if report.get("cycle_id") == cycle_id
        and str(report.get("final_action")) in ACTIONABLE_ACTIONS
    ]
    return sorted(rows, key=_paper_review_sort_key)


def final_selection_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    actionable_count = sum(1 for row in rows if _is_actionable_candidate(row))
    blocked_count = sum(1 for row in rows if row["gate_status"] == "BLOCK")
    return {
        "report_count": len(rows),
        "actionable_count": actionable_count,
        "blocked_count": blocked_count,
        "headline": _final_selection_headline(len(rows), actionable_count),
        "detail": "Selection reports are read-only runtime artifacts.",
    }


def candidate_detail_summary(
    ticker: str,
    reports: Sequence[Mapping[str, object]],
    timeline: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    latest_action = str(reports[0]["action"]) if reports else "None"
    return {
        "ticker": ticker,
        "report_count": len(reports),
        "event_count": len(timeline),
        "latest_action": latest_action,
        "headline": _candidate_detail_headline(ticker, latest_action),
    }


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
        "detail": "V0 risk checks use final selection, policy defaults, and runtime health.",
    }


def execution_preview_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    ready_count = sum(1 for row in rows if row["preview_state"] == "READY")
    blocked_count = sum(1 for row in rows if row["preview_state"] == "BLOCKED")
    disabled_count = sum(1 for row in rows if row["preview_state"] == "DISABLED")
    return {
        "preview_count": len(rows),
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "disabled_count": disabled_count,
        "headline": _execution_headline(len(rows), ready_count),
        "detail": "Previews are paper-only artifacts; broker submission remains gated.",
    }


def portfolio_monitor_summary(snapshot: Mapping[str, object]) -> dict[str, object]:
    summary = _mapping_field(snapshot, "summary")
    position_count = _int_field(summary, "position_count")
    return {
        **dict(summary),
        "headline": _portfolio_headline(position_count),
        "detail": "Monitor output is read-only and never closes positions automatically.",
    }


def learning_summary(outcome: Mapping[str, object]) -> dict[str, object]:
    sample_count = _int_field(outcome, "sample_count")
    required_count = _int_field(outcome, "required_sample_count")
    return {
        "status": str(outcome["status"]),
        "sample_count": sample_count,
        "required_sample_count": required_count,
        "headline": str(outcome["message"]),
        "detail": "Learning feedback is advisory until audit persistence and review exist.",
    }


def policy_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Targets and Discipline",
            "items": [
                {"label": "Weekly planning target", "value": "3.0%"},
                {"label": "Minimum final conviction", "value": "0.62"},
                {"label": "Maximum weekly drawdown", "value": "6.0%"},
                {"label": "Minimum hold", "value": "2 days"},
            ],
        },
        {
            "title": "Capacity",
            "items": [
                {"label": "Maximum positions", "value": "10"},
                {"label": "Maximum new per cycle", "value": "3"},
                {"label": "Maximum single name", "value": "25%"},
                {"label": "Maximum sector exposure", "value": "30%"},
                {"label": "Cash reserve", "value": "10%"},
                {"label": "Maximum gross exposure", "value": "100%"},
            ],
        },
        {
            "title": "Trade Defaults",
            "items": [
                {"label": "Default stop", "value": "5%"},
                {"label": "Default take profit", "value": "9%"},
                {"label": "Trailing stop", "value": "3%"},
                {"label": "Bracket orders", "value": "Enabled for preview design"},
            ],
        },
        {
            "title": "Permissions",
            "items": [
                {"label": "Shorts", "value": "Disabled"},
                {"label": "Live trading", "value": "Disabled"},
                {"label": "Broker submission", "value": "Disabled"},
                {"label": "Policy editing", "value": "Disabled until audit persistence exists"},
            ],
        },
    ]


def policy_summary() -> dict[str, str]:
    return {
        "headline": "Portfolio policy is read-only.",
        "detail": "Editable controls wait for validation, audit logging, and persistence.",
    }


def timeline_rows(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "event_type": str(event["event_type"]),
            "event_time": str(event["event_time"]),
            "status": str(event["status"]),
            "reason": event["reason"],
        }
        for event in events
    ]


def _final_selection_row(report: Mapping[str, object]) -> dict[str, object]:
    base = _candidate_row(report)
    deterministic = _mapping_field(report, "deterministic")
    llm_review = _mapping_field(report, "llm_review")
    evidence_pack = _mapping_field(report, "evidence_pack")
    data_quality = _mapping_field(evidence_pack, "data_quality")
    risk_flags = _string_list(report, "risk_flags")
    return {
        **base,
        "cycle_id": str(report["cycle_id"]),
        "generated_at": str(report["generated_at"]),
        "deterministic_action": str(deterministic["action"]),
        "deterministic_conviction_pct": _percent(deterministic, "conviction"),
        "deterministic_reason": _reason_text(deterministic),
        "llm_action": str(llm_review["action"]),
        "llm_confidence_pct": _percent(llm_review, "confidence"),
        "llm_rationale": str(llm_review["rationale"]),
        "policy_gates": _gate_rows(report),
        "risk_flags": risk_flags,
        "risk_flag_text": ", ".join(risk_flags) if risk_flags else "none",
        "freshness": str(data_quality["freshness"]),
        "source_count": _int_field(data_quality, "source_count"),
        "confirmed_signal_count": _int_field(data_quality, "confirmed_signal_count"),
    }


def _risk_decision_row(decision: Mapping[str, object]) -> dict[str, object]:
    reasons = _string_list(decision, "reasons")
    return {
        "cycle_id": str(decision["cycle_id"]),
        "ticker": str(decision["ticker"]),
        "decision": str(decision["decision"]),
        "decision_class": _decision_class(str(decision["decision"])),
        "final_action": str(decision["final_action"]),
        "conviction_pct": _percent(decision, "final_conviction"),
        "position_size_pct": _float_field(decision, "position_size_pct"),
        "projected_gross_exposure_pct": _float_field(
            decision,
            "projected_gross_exposure_pct",
        ),
        "reason": reasons[0] if reasons else "risk decision recorded",
        "checks": _check_rows(decision, "checks"),
    }


def _paper_review_row(
    report: Mapping[str, object],
    risk_decision: Mapping[str, object] | None,
) -> dict[str, object]:
    candidate = _candidate_row(report)
    evidence_pack = _mapping_field(report, "evidence_pack")
    data_quality = _mapping_field(evidence_pack, "data_quality")
    decision = "PENDING"
    decision_class = "neutral"
    reason = "waiting for risk decision"
    if risk_decision is not None:
        decision = str(risk_decision["decision"])
        decision_class = _decision_class(decision)
        reasons = _string_list(risk_decision, "reasons")
        reason = reasons[0] if reasons else "risk decision recorded"
    ticker = str(candidate["ticker"])
    return {
        **candidate,
        "cycle_id": str(report["cycle_id"]),
        "candidate_href": f"/candidates/{ticker}",
        "risk_href": "/risk",
        "final_selection_href": "/final-selection",
        "risk_decision": decision,
        "risk_class": decision_class,
        "review_state": _paper_review_state(decision),
        "review_class": _paper_review_class(decision),
        "reason": reason,
        "source_count": _int_field(data_quality, "source_count"),
        "confirmed_signal_count": _int_field(data_quality, "confirmed_signal_count"),
    }


def _execution_preview_row(preview: Mapping[str, object]) -> dict[str, object]:
    reasons = _string_list(preview, "reasons")
    return {
        "ticker": str(preview["ticker"]),
        "preview_state": str(preview["preview_state"]),
        "state_class": _preview_state_class(str(preview["preview_state"])),
        "side": str(preview["side"]),
        "risk_decision": str(preview["risk_decision"]),
        "submit_enabled": preview["submit_enabled"],
        "position_size_pct": _float_field(preview, "position_size_pct"),
        "time_in_force": preview["time_in_force"] or "None",
        "reason": reasons[0] if reasons else "preview recorded",
    }


def _candidate_row(report: Mapping[str, object]) -> dict[str, object]:
    conviction = _float_field(report, "final_conviction")
    return {
        "ticker": str(report["ticker"]),
        "action": str(report["final_action"]),
        "conviction_pct": round(conviction * 100),
        "gate_status": _gate_status(report),
        "as_of": str(report["as_of"]),
        "risk_flag_count": _risk_flag_count(report),
    }


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
        rows.append(
            {
                "name": str(item_payload["name"]),
                "status": str(item_payload["status"]),
                "reason": str(item_payload["reason"]),
                "status_class": str(item_payload["status"]).lower(),
            }
        )
    return rows


def _is_actionable_candidate(candidate: Mapping[str, object]) -> bool:
    return str(candidate["action"]) in ACTIONABLE_ACTIONS and candidate["gate_status"] != "BLOCK"


def _risk_decision_index(
    risk_decisions: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    indexed: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for decision in risk_decisions:
        key = _runtime_payload_key(decision)
        if all(key) and key not in indexed:
            indexed[key] = decision
    return indexed


def _runtime_payload_key(payload: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(payload.get("cycle_id", "")),
        str(payload.get("ticker", "")),
        str(payload.get("as_of", "")),
    )


def _paper_review_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    decision = str(row["risk_decision"])
    if decision in OPEN_RISK_DECISIONS:
        priority = 0
    elif decision == "PENDING":
        priority = 1
    else:
        priority = 2
    return (priority, -_int_field(row, "conviction_pct"), str(row["ticker"]))


def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source["status"]) in DEGRADED_SOURCE_STATUSES
        or str(source["freshness"]) in DEGRADED_FRESHNESS
    )


def _source_status_class(source: Mapping[str, object]) -> str:
    return "warn" if _source_is_degraded(source) else "pass"


def _readiness_status_class(verdict: str) -> str:
    if verdict == "ready_for_paper_validation":
        return "pass"
    if verdict == "context_only_source_health":
        return "warn"
    return "block"


def _readiness_blocker_rows(summary: Mapping[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for blocker in _list_field(summary, "blockers"):
        payload = cast(Mapping[str, object], blocker)
        kind = str(payload["kind"])
        rows.append(
            {
                "kind": _label_text(kind),
                "item": str(payload["item"]),
                "reason": str(payload["reason"]),
                "status_class": "warn" if kind == "source_health" else "block",
            }
        )
    return rows


def _label_text(value: str) -> str:
    return value.replace("_", " ").title()


def _command_hero_class(candidate_count: int, degraded_source_count: int) -> str:
    if degraded_source_count > 0:
        return "hero-watch"
    if candidate_count > 0:
        return "hero-success"
    return "hero-info"


def _command_headline(candidate_count: int, actionable_candidate_count: int) -> str:
    if candidate_count == 0:
        return "Runtime online. No final candidates yet."
    return (
        f"Runtime online. {actionable_candidate_count} "
        f"{_plural('actionable candidate', actionable_candidate_count)} across "
        f"{candidate_count} {_plural('report', candidate_count)}."
    )


def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"


def _command_detail(candidate_count: int, degraded_source_count: int) -> str:
    if degraded_source_count == 0:
        source_note = "All runtime sources look ready"
    elif degraded_source_count == 1:
        source_note = "1 source needs attention"
    else:
        source_note = f"{degraded_source_count} sources need attention"
    if candidate_count == 0:
        return f"{source_note}; candidate rows will appear after selection reports persist."
    return f"{source_note}; dashboard counts are backed by runtime readers."


def _final_selection_headline(report_count: int, actionable_count: int) -> str:
    if report_count == 0:
        return "No final selection reports yet."
    return f"{actionable_count} final candidates ready for human review."


def _candidate_detail_headline(ticker: str, latest_action: str) -> str:
    if latest_action == "None":
        return f"{ticker} has no persisted selection reports yet."
    return f"{ticker} latest action: {latest_action}."


def _risk_headline(
    decision_count: int,
    allow_count: int,
    warn_count: int,
    block_count: int,
) -> str:
    if decision_count == 0:
        return "No risk decisions yet."
    return f"{allow_count} allowed, {warn_count} warned, {block_count} blocked."


def _execution_headline(preview_count: int, ready_count: int) -> str:
    if preview_count == 0:
        return "No execution previews yet."
    return f"{ready_count} paper previews are ready."


def _portfolio_headline(position_count: int) -> str:
    if position_count == 0:
        return "No portfolio positions are tracked yet."
    return f"{position_count} positions reviewed."


def _decision_class(decision: str) -> str:
    if decision == "ALLOW":
        return "pass"
    if decision == "WARN":
        return "warn"
    return "block"


def _paper_review_state(decision: str) -> str:
    if decision in OPEN_RISK_DECISIONS:
        return "Ready"
    if decision == "PENDING":
        return "Waiting"
    return "Blocked"


def _paper_review_class(decision: str) -> str:
    if decision in OPEN_RISK_DECISIONS:
        return _decision_class(decision)
    if decision == "PENDING":
        return "neutral"
    return "block"


def _preview_state_class(state: str) -> str:
    if state == "READY":
        return "pass"
    if state == "DISABLED":
        return "neutral"
    return "block"


def _reason_text(payload: Mapping[str, object]) -> str:
    reasons = _string_list(payload, "reason_codes")
    return ", ".join(reasons) if reasons else "none"


def _risk_flag_count(report: Mapping[str, object]) -> int:
    return len(_list_field(report, "risk_flags"))


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _percent(payload: Mapping[str, object], key: str) -> int:
    return round(_float_field(payload, key) * 100)
