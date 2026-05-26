from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from agency.api.audit import (
    runtime_agent_runs,
    runtime_execution_states,
    runtime_portfolio_snapshots,
    runtime_prompt_audits,
    runtime_risk_snapshots,
)
from agency.views._shared import (
    _operator_text,
    dashboard_data_health,
    live_dashboard_data_load_status,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _operator_template_finalize(value: object) -> object:
    if isinstance(value, Markup):
        return value
    if isinstance(value, str):
        return _operator_text(value)
    return value


templates.env.finalize = _operator_template_finalize


@router.get("/audit")
async def audit(request: Request) -> Response:
    return templates.TemplateResponse(request, "audit.html", await audit_context())


async def audit_context() -> dict[str, object]:
    agent_runs, prompts, snapshots, states, portfolio, data_load_status = await asyncio.gather(
        runtime_agent_runs(limit=25),
        runtime_prompt_audits(limit=25),
        runtime_risk_snapshots(limit=50),
        runtime_execution_states(limit=50),
        runtime_portfolio_snapshots(limit=25),
        live_dashboard_data_load_status(),
    )
    return {
        "agent_runs": agent_run_rows(agent_runs),
        "prompt_audits": prompt_audit_rows(prompts),
        "risk_snapshots": risk_snapshot_rows(snapshots),
        "execution_states": execution_state_rows(states),
        "portfolio_snapshots": portfolio_snapshot_rows(portfolio),
        "summary": audit_summary(agent_runs, prompts, snapshots, states, portfolio),
        "data_health": dashboard_data_health(
            "Audit dashboard",
            data_load_status=data_load_status,
            extra_rows=(
                {
                    "kind": "Audit storage",
                    "name": "Runtime audit trail",
                    "status_label": "Rows loaded" if _audit_row_count(agent_runs, prompts, snapshots, states, portfolio) else "No rows",
                    "status_class": "pass" if _audit_row_count(agent_runs, prompts, snapshots, states, portfolio) else "neutral",
                    "coverage_label": (
                        f"{len(agent_runs)} runs, {len(prompts)} prompts, "
                        f"{len(states)} execution state(s)"
                    ),
                    "freshness_label": "read-only DB/runtime audit",
                    "last_update": _latest_audit_update(agent_runs, prompts, snapshots, states, portfolio),
                    "detail": (
                        "Audit uses persisted runtime rows. Empty tables are shown "
                        "explicitly so storage gaps are not confused with healthy activity."
                    ),
                },
            ),
        ),
    }


def _audit_row_count(
    agent_runs: Sequence[Mapping[str, object]],
    prompts: Sequence[Mapping[str, object]],
    snapshots: Sequence[Mapping[str, object]],
    states: Sequence[Mapping[str, object]],
    portfolio: Sequence[Mapping[str, object]],
) -> int:
    return len(agent_runs) + len(prompts) + len(snapshots) + len(states) + len(portfolio)


def _latest_audit_update(
    agent_runs: Sequence[Mapping[str, object]],
    prompts: Sequence[Mapping[str, object]],
    snapshots: Sequence[Mapping[str, object]],
    states: Sequence[Mapping[str, object]],
    portfolio: Sequence[Mapping[str, object]],
) -> str:
    values: list[str] = []
    for row in agent_runs:
        values.append(str(row.get("finished_at") or row.get("started_at") or ""))
    for row in prompts:
        values.append(str(row.get("created_at") or ""))
    for row in snapshots:
        values.append(str(row.get("generated_at") or ""))
    for row in states:
        values.append(str(row.get("event_time") or ""))
    for row in portfolio:
        values.append(str(row.get("captured_at") or ""))
    return max([value for value in values if value.strip()], default="no audit rows")


def audit_summary(
    agent_runs: Sequence[Mapping[str, object]],
    prompts: Sequence[Mapping[str, object]],
    snapshots: Sequence[Mapping[str, object]],
    states: Sequence[Mapping[str, object]],
    portfolio: Sequence[Mapping[str, object]] = (),
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
        "portfolio_snapshot_count": len(portfolio),
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
    rows: list[dict[str, object]] = []
    for prompt in prompts:
        payload = _mapping_payload(prompt)
        status = str(payload.get("response_status", "recorded"))
        action = str(payload.get("llm_action", "NO_REVIEW"))
        rows.append(
            {
                "prompt_id": str(prompt["prompt_id"]),
                "cycle_id": str(prompt["cycle_id"]),
                "ticker": str(payload.get("ticker", "ALL")),
                "agent_name": str(prompt["agent_name"]),
                "model": str(prompt["model"]),
                "prompt_class": str(prompt["prompt_class"]),
                "redaction_status": str(prompt["redaction_status"]),
                "created_at": str(prompt["created_at"]),
                "response_status": status,
                "status_class": _prompt_status_class(status, action),
                "llm_action": action,
                "llm_rationale": str(payload.get("llm_rationale", "No rationale recorded.")),
            }
        )
    return rows


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


def portfolio_snapshot_rows(snapshots: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "captured_at": str(snapshot["captured_at"]),
            "mode": str(snapshot["mode"]),
            "account_status": str(snapshot["account_status"]),
            "equity": _float_field(snapshot, "equity"),
            "cash": _float_field(snapshot, "cash"),
            "position_count": _int_field(snapshot, "position_count"),
            "open_order_count": _int_field(snapshot, "open_order_count"),
            "gross_exposure_pct": _float_field(snapshot, "gross_exposure_pct"),
        }
        for snapshot in snapshots
    ]


def _audit_headline(run_count: int, failed_count: int) -> str:
    if run_count == 0:
        return "No runtime audit rows yet."
    if failed_count > 0:
        return f"{failed_count} runtime runs need attention."
    return f"{run_count} runtime runs are recorded."


def _payload_int(row: Mapping[str, object], key: str) -> int:
    payload = _mapping_payload(row)
    value = payload.get(key, 0)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _mapping_payload(row: Mapping[str, object]) -> Mapping[str, object]:
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        raise TypeError("audit payload must be a mapping")
    return payload


def _float_field(row: Mapping[str, object], key: str) -> float:
    value = row[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _int_field(row: Mapping[str, object], key: str) -> int:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


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
    if state in {"READY", "ACCEPTED", "FILLED"}:
        return "pass"
    if state in {"DISABLED", "PLANNED", "CANCELED", "EXPIRED", "PENDING_CANCEL"}:
        return "neutral"
    return "block"


def _prompt_status_class(status: str, action: str) -> str:
    if status == "succeeded" and action not in {"NO_REVIEW", "DEFER", "NEEDS_MORE_EVIDENCE"}:
        return "pass"
    if status in {"failed", "missing_api_key"} or action in {"NO_REVIEW", "NEEDS_MORE_EVIDENCE"}:
        return "warn"
    return "neutral"
