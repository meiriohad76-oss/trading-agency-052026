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

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

ACTIONABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
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
    reports, data_sources = await asyncio.gather(
        runtime_selection_reports(limit=10),
        runtime_data_source_status(),
    )
    candidates = candidate_rows(reports)
    contracts = contract_summaries()
    summary = command_summary(
        candidates=candidates,
        data_sources=data_sources,
        contracts=contracts,
    )
    return {
        "actions": command_actions(),
        "contracts": contracts,
        "data_sources": source_status_rows(data_sources),
        "candidates": candidates,
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
        await disabled_workflow_context("risk"),
    )


@router.get("/execution-preview")
async def execution_preview(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "execution_preview.html",
        await disabled_workflow_context("execution"),
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


async def disabled_workflow_context(workflow: str) -> dict[str, object]:
    reports, data_sources = await asyncio.gather(
        runtime_selection_reports(limit=10),
        runtime_data_source_status(),
    )
    candidates = candidate_rows(reports)
    return {
        "candidates": candidates,
        "data_sources": source_status_rows(data_sources),
        "summary": disabled_workflow_summary(workflow, candidates, data_sources),
    }


def command_summary(
    *,
    candidates: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
    contracts: Sequence[Mapping[str, object]],
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
        "hero_class": _command_hero_class(candidate_count, degraded_source_count),
        "headline": _command_headline(candidate_count, actionable_candidate_count),
        "detail": _command_detail(candidate_count, degraded_source_count),
    }


def command_actions() -> list[dict[str, str]]:
    return [
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


def disabled_workflow_summary(
    workflow: str,
    candidates: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    degraded_source_count = sum(1 for source in data_sources if _source_is_degraded(source))
    title = "Risk aggregation" if workflow == "risk" else "Execution preview"
    return {
        "title": title,
        "candidate_count": len(candidates),
        "degraded_source_count": degraded_source_count,
        "headline": f"{title} is read-only until its backend service exists.",
        "detail": "No broker, order, or risk decision is generated from this page.",
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
    rows: list[dict[str, str]] = []
    for gate in _list_field(report, "policy_gates"):
        gate_payload = cast(Mapping[str, object], gate)
        rows.append(
            {
                "name": str(gate_payload["name"]),
                "status": str(gate_payload["status"]),
                "reason": str(gate_payload["reason"]),
                "status_class": str(gate_payload["status"]).lower(),
            }
        )
    return rows


def _is_actionable_candidate(candidate: Mapping[str, object]) -> bool:
    return str(candidate["action"]) in ACTIONABLE_ACTIONS and candidate["gate_status"] != "BLOCK"


def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source["status"]) in DEGRADED_SOURCE_STATUSES
        or str(source["freshness"]) in DEGRADED_FRESHNESS
    )


def _source_status_class(source: Mapping[str, object]) -> str:
    return "warn" if _source_is_degraded(source) else "pass"


def _command_hero_class(candidate_count: int, degraded_source_count: int) -> str:
    if degraded_source_count > 0:
        return "hero-watch"
    if candidate_count > 0:
        return "hero-success"
    return "hero-info"


def _command_headline(candidate_count: int, actionable_candidate_count: int) -> str:
    if candidate_count == 0:
        return "Runtime online. No final candidates yet."
    return f"Runtime online. {actionable_candidate_count} candidates ready to review."


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
