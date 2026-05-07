from __future__ import annotations

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


@router.get("/")
async def dashboard(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        await dashboard_context(),
    )


async def dashboard_context() -> dict[str, object]:
    reports = await runtime_selection_reports(limit=10)
    return {
        "contracts": contract_summaries(),
        "data_sources": await runtime_data_source_status(),
        "candidates": candidate_rows(reports),
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
    return {
        "ticker": normalized_ticker,
        "reports": candidate_rows(reports),
        "timeline": timeline_rows(timeline),
    }


def candidate_rows(reports: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_candidate_row(report) for report in reports]


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


def _risk_flag_count(report: Mapping[str, object]) -> int:
    return len(_list_field(report, "risk_flags"))


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)
