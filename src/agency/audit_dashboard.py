from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from agency.api.audit import (
    runtime_agent_runs,
    runtime_execution_states,
    runtime_prompt_audits,
    runtime_risk_snapshots,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@router.get("/audit")
async def audit(request: Request) -> Response:
    return templates.TemplateResponse(request, "audit.html", await audit_context())


async def audit_context() -> dict[str, object]:
    agent_runs, prompts, snapshots, states = await asyncio.gather(
        runtime_agent_runs(limit=25),
        runtime_prompt_audits(limit=25),
        runtime_risk_snapshots(limit=50),
        runtime_execution_states(limit=50),
    )
    return {
        "agent_runs": agent_run_rows(agent_runs),
        "prompt_audits": prompt_audit_rows(prompts),
        "risk_snapshots": risk_snapshot_rows(snapshots),
        "execution_states": execution_state_rows(states),
        "summary": audit_summary(agent_runs, prompts, snapshots, states),
    }


def audit_summary(
    agent_runs: Sequence[Mapping[str, object]],
    prompts: Sequence[Mapping[str, object]],
    snapshots: Sequence[Mapping[str, object]],
    states: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    running_count = sum(1 for run in agent_runs if run["status"] == "RUNNING")
    failed_count = sum(1 for run in agent_runs if run["status"] == "FAILED")
    return {
        "run_count": len(agent_runs),
        "running_count": running_count,
        "failed_count": failed_count,
        "prompt_count": len(prompts),
        "risk_snapshot_count": len(snapshots),
        "execution_state_count": len(states),
        "headline": _audit_headline(len(agent_runs), failed_count),
        "detail": "Runtime audit rows are read-only trace records for paper cycles.",
    }


def agent_run_rows(runs: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "run_id": str(run["run_id"]),
            "cycle_id": str(run["cycle_id"]),
            "agent_name": str(run["agent_name"]),
            "status": str(run["status"]),
            "status_class": _status_class(str(run["status"])),
            "trigger": str(run["trigger"]),
            "started_at": str(run["started_at"]),
            "finished_at": run["finished_at"] or "running",
            "selection_count": _payload_int(run, "selection_report_count"),
            "risk_count": _payload_int(run, "risk_decision_count"),
        }
        for run in runs
    ]


def prompt_audit_rows(prompts: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "prompt_id": str(prompt["prompt_id"]),
            "cycle_id": str(prompt["cycle_id"]),
            "agent_name": str(prompt["agent_name"]),
            "model": str(prompt["model"]),
            "prompt_class": str(prompt["prompt_class"]),
            "redaction_status": str(prompt["redaction_status"]),
            "created_at": str(prompt["created_at"]),
        }
        for prompt in prompts
    ]


def risk_snapshot_rows(snapshots: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "cycle_id": str(snapshot["cycle_id"]),
            "ticker": snapshot["ticker"] or "ALL",
            "risk_level": str(snapshot["risk_level"]),
            "risk_class": _risk_class(str(snapshot["risk_level"])),
            "gross_exposure_pct": _float_field(snapshot, "gross_exposure_pct"),
            "generated_at": str(snapshot["generated_at"]),
        }
        for snapshot in snapshots
    ]


def execution_state_rows(states: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "cycle_id": str(state["cycle_id"]),
            "ticker": state["ticker"] or "ALL",
            "state": str(state["state"]),
            "state_class": _execution_class(str(state["state"])),
            "event_time": str(state["event_time"]),
            "reason": state["reason"] or "state recorded",
        }
        for state in states
    ]


def _audit_headline(run_count: int, failed_count: int) -> str:
    if run_count == 0:
        return "No runtime audit rows yet."
    if failed_count > 0:
        return f"{failed_count} runtime runs need attention."
    return f"{run_count} runtime runs are recorded."


def _payload_int(row: Mapping[str, object], key: str) -> int:
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        raise TypeError("audit payload must be a mapping")
    value = payload.get(key, 0)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _float_field(row: Mapping[str, object], key: str) -> float:
    value = row[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _status_class(status: str) -> str:
    if status == "SUCCEEDED":
        return "pass"
    if status == "RUNNING":
        return "neutral"
    return "block"


def _risk_class(level: str) -> str:
    if level == "LOW":
        return "pass"
    if level == "MEDIUM":
        return "warn"
    return "block"


def _execution_class(state: str) -> str:
    if state == "READY":
        return "pass"
    if state in {"DISABLED", "PLANNED"}:
        return "neutral"
    return "block"
