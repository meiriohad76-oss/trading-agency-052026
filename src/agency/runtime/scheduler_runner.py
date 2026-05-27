from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from dotenv import load_dotenv

from agency.runtime.portfolio_news_agent_bridge import (
    ensure_portfolio_news_agent_agency_config,
    portfolio_news_agent_env_path,
    portfolio_news_agent_python,
    portfolio_news_agent_root,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = os.environ.get("AGENCY_PYTHON", str(REPO_ROOT / ".venv" / "Scripts" / "python"))
WORK_QUEUE_TICK_SECONDS = int(os.environ.get("AGENCY_WORK_QUEUE_TICK_SECONDS", "60"))
WORK_QUEUE_MAX_COMMANDS = int(os.environ.get("AGENCY_WORK_QUEUE_MAX_COMMANDS", "3"))
COMMAND_TIMEOUT_SECONDS = int(os.environ.get("AGENCY_SCHEDULER_COMMAND_TIMEOUT_SECONDS", "240"))
RUNTIME_CYCLE_MAX_TICKERS = int(os.environ.get("AGENCY_SCHEDULER_RUNTIME_MAX_TICKERS", "250"))
CANONICAL_RUNTIME_OUTPUT_ROOT = "research\\results\\latest-live-runtime-cycle"
MINI_RUNTIME_OUTPUT_ROOT = "research\\results\\latest-mini-runtime-cycle"
RUNTIME_CYCLE_AFTER_DATA_REFRESH = (
    os.environ.get("AGENCY_SCHEDULER_REFRESH_RUNTIME_CYCLE", "true").lower()
    not in {"0", "false", "no", "off"}
)
RUNTIME_CYCLE_PERSIST = (
    os.environ.get("AGENCY_SCHEDULER_RUNTIME_PERSIST", "true").lower()
    not in {"0", "false", "no", "off"}
)
SCHEDULER_ENABLE_LLM_REVIEW = (
    os.environ.get(
        "AGENCY_SCHEDULER_ENABLE_LLM_REVIEW",
        os.environ.get("AGENCY_ENABLE_LLM_REVIEW", "false"),
    ).lower()
    in {"1", "true", "yes", "on"}
)
PERSIST_SCHEDULER_JOBS = (
    os.environ.get("AGENCY_SCHEDULER_PERSIST_JOBS", "false").lower()
    in {"1", "true", "yes", "on"}
)
_WORK_QUEUE_TICK_RUNNING = False

_PHASE_JOBS: dict[str, list[dict[str, Any]]] = {
    "pre_market": [
        {"name": "stock_trades",        "interval_minutes": 15},
        {"name": "subscription_emails", "interval_minutes": 10},
        {"name": "news_rss",            "interval_minutes": 30},
    ],
    "regular_market": [
        {"name": "stock_trades",        "interval_minutes": 10},
        {"name": "news_rss",            "interval_minutes": 30},
        {"name": "subscription_emails", "interval_minutes": 10},
    ],
    "after_hours": [
        {"name": "prices_daily",        "interval_minutes": 30},
        {"name": "stock_trades",        "interval_minutes": 20},
        {"name": "subscription_emails", "interval_minutes": 15},
    ],
    "overnight_after_hours": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
        {"name": "sec_13f",             "interval_minutes": 720},
        {"name": "news_rss",            "interval_minutes": 60},
        {"name": "prices_daily",        "interval_minutes": 60},
    ],
    "overnight_before_pre_market": [
        {"name": "stock_trades",        "interval_minutes": 60},
        {"name": "prices_daily",        "interval_minutes": 60},
        {"name": "sec_form4",           "interval_minutes": 180},
        {"name": "news_rss",            "interval_minutes": 60},
    ],
    "closed_weekend": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
        {"name": "sec_13f",             "interval_minutes": 720},
        {"name": "news_rss",            "interval_minutes": 60},
    ],
    "closed_holiday": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
        {"name": "sec_13f",             "interval_minutes": 720},
    ],
}
_PHASE_ALIASES = {
    "overnight": "overnight_after_hours",
    "holiday": "closed_holiday",
    "closed": "closed_weekend",
}


def jobs_for_phase(phase: str) -> list[dict[str, Any]]:
    """Return the job specs active for the given market phase."""
    normalized = _PHASE_ALIASES.get(phase, phase)
    return _PHASE_JOBS.get(normalized, [])


def _run_dataset_refresh(dataset: str) -> None:
    if dataset == "stock_trades":
        print(
            "[scheduler] skipped stock_trades direct batch; Massive trade data is "
            "owned by raw lanes in the scheduler work queue.",
            flush=True,
        )
        return
    config_path = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
    if not config_path.is_file():
        print(f"[scheduler] WARNING: live-refresh config not found at {config_path}", flush=True)
        return
    cmd = [
        PYTHON,
        str(REPO_ROOT / "research" / "scripts" / "run_data_refresh_batch.py"),
        "--config", str(config_path),
        "--dataset", dataset,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    status = "ok" if result.returncode == 0 else "FAILED"
    print(f"[scheduler] {dataset} refresh {status} (exit {result.returncode})", flush=True)
    if result.returncode != 0:
        print(f"[scheduler] stderr: {result.stderr[:500]}", flush=True)


def _run_phase_gated_dataset_refresh(dataset: str, phase: str) -> None:
    current_phase = _current_market_phase()
    active_names = {str(spec["name"]) for spec in jobs_for_phase(current_phase)}
    if dataset not in active_names:
        print(
            f"[scheduler] skipped {dataset}; registered for {phase}, "
            f"current phase={current_phase}",
            flush=True,
        )
        return
    _run_dataset_refresh(dataset)


def build_scheduler(db_url: str | None = None) -> Any:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

    jobstores = {}
    if db_url and PERSIST_SCHEDULER_JOBS:
        from apscheduler.jobstores.sqlalchemy import (  # type: ignore[import-untyped]
            SQLAlchemyJobStore,
        )

        jobstores["default"] = SQLAlchemyJobStore(url=db_url)
    scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
    # _register_phase_jobs() is intentionally disabled. The live system routes
    # automatic refresh decisions through the market-aware work queue so each
    # lane has one source of priority, cadence, budget, ETA, and status truth.
    _register_work_queue_jobs(scheduler)
    return scheduler


def _register_work_queue_jobs(scheduler: Any) -> None:
    scheduler.remove_all_jobs()
    scheduler.add_job(
        _run_work_queue_tick,
        "interval",
        seconds=WORK_QUEUE_TICK_SECONDS,
        id="refresh_scheduler_work_queue",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
        name="refresh:scheduler-work-queue",
    )
    print("[scheduler] registered scheduler-work-queue lane refresh job", flush=True)


def _register_phase_jobs(scheduler: Any) -> None:
    registered = 0
    seen_ids: set[str] = set()
    for phase, specs in _PHASE_JOBS.items():
        for spec in specs:
            job_id = f"refresh_{phase}_{spec['name']}"
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            scheduler.add_job(
                _run_phase_gated_dataset_refresh,
                "interval",
                minutes=spec["interval_minutes"],
                args=[spec["name"], phase],
                id=job_id,
                replace_existing=True,
                name=f"refresh:{phase}:{spec['name']}",
            )
            registered += 1
    print(f"[scheduler] registered {registered} phase-gated refresh jobs", flush=True)


def _run_work_queue_tick() -> None:
    global _WORK_QUEUE_TICK_RUNNING
    from agency.runtime.data_load_status import load_data_load_status
    from agency.runtime.data_refresh_progress import load_data_refresh_progress
    from agency.runtime.scheduler_status import (
        load_scheduler_runtime_status,
        record_scheduler_runtime_status,
    )

    if _WORK_QUEUE_TICK_RUNNING:
        previous = load_scheduler_runtime_status()
        skipped_extra: dict[str, object] = {
            "last_tick_skipped_at": datetime.now(UTC).isoformat(),
            "expected_tick_timeout_seconds": _expected_tick_timeout_seconds(),
        }
        previous_started = previous.get("last_tick_started_at")
        previous_finished = previous.get("last_tick_finished_at")
        if previous_started and not previous_finished:
            skipped_extra["last_tick_started_at"] = previous_started
            skipped_extra["tick_state"] = previous.get("tick_state", "running")
            if previous.get("active_command") is not None:
                skipped_extra["active_command"] = previous["active_command"]
        record_scheduler_runtime_status(
            state="running",
            detail="Automatic lane refresh tick skipped because the previous tick is still running.",
            job_count=1,
            extra=skipped_extra,
        )
        return
    _WORK_QUEUE_TICK_RUNNING = True
    started_at = datetime.now(UTC)
    executed: list[dict[str, object]] = []
    errors: list[str] = []
    refreshed_tickers: list[str] = []
    previous_status = load_scheduler_runtime_status()
    job_last_success_at = _job_last_success_map(previous_status)
    try:
        record_scheduler_runtime_status(
            state="running",
            detail="Automatic lane refresh tick is evaluating the scheduler work queue.",
            job_count=1,
            extra={
                "tick_state": "running",
                "last_tick_started_at": started_at.isoformat(),
                "expected_tick_timeout_seconds": _expected_tick_timeout_seconds(),
            },
        )
        executed_job_ids: set[str] = set()
        data_commands_executed = False
        while len(executed) < WORK_QUEUE_MAX_COMMANDS:
            data_load = load_data_load_status()
            progress = load_data_refresh_progress()
            queue = _work_queue_for_runner(
                data_load_status=data_load,
                data_refresh_progress=progress,
            )
            command_row = _next_command_for_tick(
                queue,
                executed_job_ids=executed_job_ids,
            )
            if command_row is None:
                break
            command = _string_list(command_row.get("command"))
            if not command:
                executed_job_ids.add(str(command_row.get("job_id") or command_row.get("name") or "unknown"))
                continue
            command_started_at = datetime.now(UTC)
            command_name = str(
                command_row.get("name") or command_row.get("lane_id") or "unknown"
            )
            job_id = str(command_row.get("job_id") or command_row.get("name") or "unknown")
            executed_job_ids.add(job_id)
            record_scheduler_runtime_status(
                state="running",
                detail=f"Automatic lane refresh is running {command_name}.",
                job_count=1,
                extra={
                    "tick_state": "running",
                    "last_tick_started_at": started_at.isoformat(),
                    "expected_tick_timeout_seconds": _expected_tick_timeout_seconds(),
                    "active_command": {
                        "job_id": job_id,
                        "kind": str(command_row.get("kind") or "unknown"),
                        "name": command_name,
                        "started_at": command_started_at.isoformat(),
                    },
                    "last_tick_commands": executed,
                },
            )
            result = _run_queue_command(command)
            refreshed_tickers = _ordered_unique(
                [*refreshed_tickers, *_tickers_from_command(command)]
            )
            command_finished_at = datetime.now(UTC)
            executed.append(
                {
                    "job_id": job_id,
                    "kind": str(command_row.get("kind") or "unknown"),
                    "name": command_name,
                    "exit_code": result.returncode,
                    "duration_seconds": int((command_finished_at - command_started_at).total_seconds()),
                    "stdout_tail": (result.stdout or "")[-500:],
                    "stderr_tail": (result.stderr or "")[-500:],
                }
            )
            if result.returncode != 0:
                _record_failed_data_refresh_status(
                    command_row,
                    result,
                    command_started_at=command_started_at,
                    command_finished_at=command_finished_at,
                )
                errors.append(
                    f"{job_id}: exit {result.returncode}"
                )
                break
            data_commands_executed = True
        if data_commands_executed and not errors and RUNTIME_CYCLE_AFTER_DATA_REFRESH:
            runtime_command = _runtime_cycle_command(tickers=refreshed_tickers)
            runtime_started_at = datetime.now(UTC)
            record_scheduler_runtime_status(
                state="running",
                detail="Automatic lane refresh is updating live runtime artifacts.",
                job_count=1,
                extra={
                    "tick_state": "running",
                    "last_tick_started_at": started_at.isoformat(),
                    "expected_tick_timeout_seconds": _expected_tick_timeout_seconds(),
                    "active_command": {
                        "job_id": "runtime:live_cycle_after_data_refresh",
                        "kind": "runtime_cycle",
                        "name": "live_runtime_cycle",
                        "ticker_count": len(refreshed_tickers),
                        "started_at": runtime_started_at.isoformat(),
                    },
                    "last_tick_commands": executed,
                },
            )
            result = _run_queue_command(runtime_command)
            executed.append(
                {
                    "job_id": "runtime:live_cycle_after_data_refresh",
                    "kind": "runtime_cycle",
                    "name": "live_runtime_cycle",
                    "exit_code": result.returncode,
                    "duration_seconds": int((datetime.now(UTC) - runtime_started_at).total_seconds()),
                    "ticker_count": len(refreshed_tickers),
                    "stdout_tail": (result.stdout or "")[-500:],
                    "stderr_tail": (result.stderr or "")[-500:],
                }
            )
            if result.returncode != 0:
                errors.append(f"live runtime cycle: exit {result.returncode}")
        finished_at = datetime.now(UTC)
        state = "error" if errors else "idle"
        detail = (
            f"Automatic lane refresh tick ran {len(executed)} command(s)."
            if executed
            else "Automatic lane refresh tick found no due lane/data commands."
        )
        if errors:
            detail = f"{detail} Errors: {'; '.join(errors)}"
        record_scheduler_runtime_status(
            state=state,
            detail=detail,
            job_count=1,
            extra={
                "last_tick_started_at": started_at.isoformat(),
                "last_tick_finished_at": finished_at.isoformat(),
                "tick_state": "idle",
                "expected_tick_timeout_seconds": _expected_tick_timeout_seconds(),
                "active_command": None,
                "last_tick_command_count": len(executed),
                "last_tick_errors": errors,
                "last_tick_commands": executed,
                "last_tick_refreshed_tickers": refreshed_tickers,
                "job_last_success_at": _updated_job_last_success_at(
                    job_last_success_at,
                    executed,
                    finished_at=finished_at,
                ),
            },
        )
    except Exception as exc:
        record_scheduler_runtime_status(
            state="error",
            detail=f"Automatic lane refresh tick failed before completion: {exc}",
            job_count=1,
            extra={
                "last_tick_started_at": started_at.isoformat(),
                "last_tick_finished_at": datetime.now(UTC).isoformat(),
                "tick_state": "failed",
                "expected_tick_timeout_seconds": _expected_tick_timeout_seconds(),
                "active_command": None,
                "job_last_success_at": job_last_success_at,
            },
        )
    finally:
        _WORK_QUEUE_TICK_RUNNING = False


def _job_last_success_map(status: dict[str, object]) -> dict[str, str]:
    value = status.get("job_last_success_at")
    if not isinstance(value, dict):
        return {}
    return {
        str(job_id): str(timestamp)
        for job_id, timestamp in value.items()
        if str(job_id).strip() and str(timestamp).strip()
    }


def _updated_job_last_success_at(
    previous: dict[str, str],
    executed: list[dict[str, object]],
    *,
    finished_at: datetime,
) -> dict[str, str]:
    updated = dict(previous)
    for row in executed:
        job_id = str(row.get("job_id") or "").strip()
        exit_code = row.get("exit_code")
        if not job_id or not isinstance(exit_code, int) or exit_code != 0:
            continue
        updated[job_id] = finished_at.isoformat()
    return updated


def _commands_for_tick(queue: dict[str, object]) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []
    massive = queue.get("massive_orchestrator")
    if isinstance(massive, dict):
        for row in _mapping_rows(massive.get("lanes")):
            if row.get("status") == "DUE_NOW" and row.get("command"):
                commands.append(dict(row))
    for row in _mapping_rows(queue.get("jobs")):
        if row.get("kind") != "dataset":
            continue
        if row.get("status") != "DUE_NOW" or not row.get("command"):
            continue
        commands.append(dict(row))
    return commands


def run_manual_massive_lane_refresh(
    lane_id: str,
    *,
    queue_provider: Callable[[], Mapping[str, object]] | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    """Run exactly one Massive lane when current trade-aware policy allows it."""
    from agency.runtime import scheduler_status

    requested_lane_id = str(lane_id).strip()
    if not requested_lane_id:
        return _record_manual_lane_refresh_refused(
            "unknown",
            "Manual lane refresh was not started because no lane id was provided.",
            recorder=scheduler_status.record_scheduler_runtime_status,
        )
    if _WORK_QUEUE_TICK_RUNNING:
        return _record_manual_lane_refresh_refused(
            requested_lane_id,
            (
                "Manual lane refresh was not started because the automatic scheduler "
                "tick is already running. Wait for the current lane command to finish."
            ),
            recorder=scheduler_status.record_scheduler_runtime_status,
        )
    try:
        queue = dict(queue_provider() if queue_provider is not None else _manual_lane_queue())
    except Exception as exc:
        return _record_manual_lane_refresh_refused(
            requested_lane_id,
            f"Manual lane refresh could not load the scheduler work queue: {exc}",
            recorder=scheduler_status.record_scheduler_runtime_status,
        )

    lane = _manual_massive_lane(queue, requested_lane_id)
    if lane is None:
        return _record_manual_lane_refresh_refused(
            requested_lane_id,
            f"Manual lane refresh was not started because {requested_lane_id} is not in the current Massive lane plan.",
            recorder=scheduler_status.record_scheduler_runtime_status,
        )

    status = str(lane.get("status") or "").upper()
    command = _string_list(lane.get("command"))
    if status != "DUE_NOW" or not command:
        label = _manual_lane_label(lane)
        reason = str(lane.get("reason") or "No lane reason recorded.")
        return _record_manual_lane_refresh_refused(
            requested_lane_id,
            (
                f"Manual lane refresh for {label} was not started because the "
                f"current trade-aware policy marks the lane {status or 'UNKNOWN'} "
                f"and does not expose a runnable lane command. {reason}"
            ),
            lane=lane,
            recorder=scheduler_status.record_scheduler_runtime_status,
        )

    run_command = runner or _run_queue_command
    started_at = datetime.now(UTC)
    previous_status = scheduler_status.load_scheduler_runtime_status()
    job_id = str(lane.get("job_id") or f"massive:{requested_lane_id}")
    label = _manual_lane_label(lane)
    active_command = {
        "job_id": job_id,
        "kind": str(lane.get("kind") or "massive_lane"),
        "name": label,
        "lane_id": requested_lane_id,
        "manual": True,
        "started_at": started_at.isoformat(),
    }
    scheduler_status.record_scheduler_runtime_status(
        state="running",
        detail=f"Manual lane refresh is running {label}.",
        job_count=1,
        extra={
            "tick_state": "running",
            "last_tick_started_at": started_at.isoformat(),
            "expected_tick_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "active_command": active_command,
            "manual_lane_refresh": {
                "lane_id": requested_lane_id,
                "job_id": job_id,
                "label": label,
                "status": "running",
                "policy_status": status,
                "started_at": started_at.isoformat(),
            },
        },
    )

    try:
        result = run_command(command)
    except Exception as exc:
        result = subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"Manual lane refresh command failed before completion: {exc}",
        )

    finished_at = datetime.now(UTC)
    refreshed_tickers = _tickers_from_command(command)
    command_result = {
        "job_id": job_id,
        "kind": str(lane.get("kind") or "massive_lane"),
        "name": label,
        "lane_id": requested_lane_id,
        "exit_code": result.returncode,
        "duration_seconds": int((finished_at - started_at).total_seconds()),
        "ticker_count": len(refreshed_tickers),
        "stdout_tail": (result.stdout or "")[-500:],
        "stderr_tail": (result.stderr or "")[-500:],
        "manual": True,
    }
    errors = [] if result.returncode == 0 else [f"{job_id}: exit {result.returncode}"]
    state = "idle" if result.returncode == 0 else "error"
    manual_status = "completed" if result.returncode == 0 else "failed"
    detail = (
        f"Manual lane refresh for {label} completed."
        if result.returncode == 0
        else f"Manual lane refresh for {label} failed with exit {result.returncode}."
    )
    job_last_success_at = _job_last_success_map(previous_status)
    if result.returncode == 0:
        job_last_success_at[job_id] = finished_at.isoformat()
    scheduler_status.record_scheduler_runtime_status(
        state=state,
        detail=detail,
        job_count=1,
        extra={
            "tick_state": "idle",
            "last_tick_started_at": started_at.isoformat(),
            "last_tick_finished_at": finished_at.isoformat(),
            "expected_tick_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "active_command": None,
            "last_tick_command_count": 1,
            "last_tick_errors": errors,
            "last_tick_commands": [command_result],
            "last_tick_refreshed_tickers": refreshed_tickers,
            "job_last_success_at": job_last_success_at,
            "manual_lane_refresh": {
                "lane_id": requested_lane_id,
                "job_id": job_id,
                "label": label,
                "status": manual_status,
                "policy_status": status,
                "exit_code": result.returncode,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
            },
        },
    )
    return {
        "state": manual_status,
        "lane_id": requested_lane_id,
        "job_id": job_id,
        "exit_code": result.returncode,
        "detail": detail,
        "refreshed_tickers": refreshed_tickers,
    }


def run_manual_dataset_refresh(
    dataset: str,
    *,
    queue_provider: Callable[[], Mapping[str, object]] | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    """Run one non-Massive dataset refresh when the scheduler policy exposes it."""
    from agency.runtime import scheduler_status

    requested_dataset = str(dataset).strip()
    if not requested_dataset:
        return _record_manual_dataset_refresh_refused(
            "unknown",
            "Manual dataset refresh was not started because no dataset was provided.",
            recorder=scheduler_status.record_scheduler_runtime_status,
        )
    if _WORK_QUEUE_TICK_RUNNING:
        return _record_manual_dataset_refresh_refused(
            requested_dataset,
            (
                "Manual dataset refresh was not started because the automatic "
                "scheduler tick is already running. Wait for the current command "
                "to finish."
            ),
            recorder=scheduler_status.record_scheduler_runtime_status,
        )
    try:
        queue = dict(queue_provider() if queue_provider is not None else _manual_lane_queue())
    except Exception as exc:
        return _record_manual_dataset_refresh_refused(
            requested_dataset,
            f"Manual dataset refresh could not load the scheduler work queue: {exc}",
            recorder=scheduler_status.record_scheduler_runtime_status,
        )

    job = _manual_dataset_job(queue, requested_dataset)
    if job is None:
        return _record_manual_dataset_refresh_refused(
            requested_dataset,
            (
                f"Manual dataset refresh was not started because {requested_dataset} "
                "is not in the current scheduler job plan."
            ),
            recorder=scheduler_status.record_scheduler_runtime_status,
        )

    status = str(job.get("status") or "").upper()
    command = _string_list(job.get("command"))
    if status != "DUE_NOW" or not command:
        label = _manual_job_label(job)
        reason = str(job.get("reason") or "No job reason recorded.")
        return _record_manual_dataset_refresh_refused(
            requested_dataset,
            (
                f"Manual dataset refresh for {label} was not started because the "
                f"current trade-aware policy marks it {status or 'UNKNOWN'} and "
                f"does not expose a runnable command. {reason}"
            ),
            job=job,
            recorder=scheduler_status.record_scheduler_runtime_status,
        )

    run_command = runner or _run_queue_command
    started_at = datetime.now(UTC)
    previous_status = scheduler_status.load_scheduler_runtime_status()
    job_id = str(job.get("job_id") or f"dataset:{requested_dataset}")
    label = _manual_job_label(job)
    active_command = {
        "job_id": job_id,
        "kind": str(job.get("kind") or "dataset"),
        "name": label,
        "dataset": requested_dataset,
        "manual": True,
        "started_at": started_at.isoformat(),
    }
    scheduler_status.record_scheduler_runtime_status(
        state="running",
        detail=f"Manual dataset refresh is running {label}.",
        job_count=1,
        extra={
            "tick_state": "running",
            "last_tick_started_at": started_at.isoformat(),
            "expected_tick_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "active_command": active_command,
            "manual_dataset_refresh": {
                "dataset": requested_dataset,
                "job_id": job_id,
                "label": label,
                "status": "running",
                "policy_status": status,
                "started_at": started_at.isoformat(),
            },
        },
    )

    try:
        result = run_command(command)
    except Exception as exc:
        result = subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"Manual dataset refresh command failed before completion: {exc}",
        )

    finished_at = datetime.now(UTC)
    command_result = {
        "job_id": job_id,
        "kind": str(job.get("kind") or "dataset"),
        "name": label,
        "dataset": requested_dataset,
        "exit_code": result.returncode,
        "duration_seconds": int((finished_at - started_at).total_seconds()),
        "ticker_count": len(_tickers_from_command(command)),
        "stdout_tail": (result.stdout or "")[-500:],
        "stderr_tail": (result.stderr or "")[-500:],
        "manual": True,
    }
    errors = [] if result.returncode == 0 else [f"{job_id}: exit {result.returncode}"]
    state = "idle" if result.returncode == 0 else "error"
    manual_status = "completed" if result.returncode == 0 else "failed"
    detail = (
        f"Manual dataset refresh for {label} completed."
        if result.returncode == 0
        else f"Manual dataset refresh for {label} failed with exit {result.returncode}."
    )
    job_last_success_at = _job_last_success_map(previous_status)
    if result.returncode == 0:
        job_last_success_at[job_id] = finished_at.isoformat()
    scheduler_status.record_scheduler_runtime_status(
        state=state,
        detail=detail,
        job_count=1,
        extra={
            "tick_state": "idle",
            "last_tick_started_at": started_at.isoformat(),
            "last_tick_finished_at": finished_at.isoformat(),
            "expected_tick_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "active_command": None,
            "last_tick_command_count": 1,
            "last_tick_errors": errors,
            "last_tick_commands": [command_result],
            "job_last_success_at": job_last_success_at,
            "manual_dataset_refresh": {
                "dataset": requested_dataset,
                "job_id": job_id,
                "label": label,
                "status": manual_status,
                "policy_status": status,
                "exit_code": result.returncode,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
            },
        },
    )
    return {
        "state": manual_status,
        "dataset": requested_dataset,
        "job_id": job_id,
        "exit_code": result.returncode,
        "detail": detail,
    }


def launch_subscription_email_login_refresh() -> dict[str, object]:
    """Open a visible local shell for the login-gated email/article refresh."""
    from agency.runtime import scheduler_status

    command = _subscription_email_login_refresh_shell_command()
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        process = subprocess.Popen(  # noqa: S603 - local operator-launched tool.
            command,
            cwd=str(REPO_ROOT),
            creationflags=creationflags,
        )
    except Exception as exc:
        detail = f"Could not open the subscription email login refresh window: {exc}"
        scheduler_status.record_scheduler_runtime_status(
            state="idle",
            detail=detail,
            job_count=0,
            extra={
                "manual_subscription_email_login_refresh": {
                    "status": "failed_to_start",
                    "reason": detail,
                }
            },
        )
        return {"state": "failed_to_start", "detail": detail}

    detail = (
        "Opened the Portfolio News Agent SA browser check. It starts the dedicated "
        "Chrome/Edge session, verifies Seeking Alpha access, and prompts for login "
        "only when needed."
    )
    scheduler_status.record_scheduler_runtime_status(
        state="idle",
        detail=detail,
        job_count=1,
        extra={
            "manual_subscription_email_login_refresh": {
                "status": "started",
                "process_id": process.pid,
                "dataset": "subscription_emails",
            }
        },
    )
    return {"state": "started", "process_id": process.pid, "detail": detail}


def launch_subscription_email_article_analysis_after_login() -> dict[str, object]:
    """Open a visible local shell that continues article analysis after login."""
    from agency.runtime import scheduler_status

    command = _subscription_email_after_login_shell_command()
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        process = subprocess.Popen(  # noqa: S603 - local operator-launched tool.
            command,
            cwd=str(REPO_ROOT),
            creationflags=creationflags,
        )
    except Exception as exc:
        detail = f"Could not open the subscription email article-analysis window: {exc}"
        scheduler_status.record_scheduler_runtime_status(
            state="idle",
            detail=detail,
            job_count=0,
            extra={
                "manual_subscription_email_article_analysis": {
                    "status": "failed_to_start",
                    "reason": detail,
                }
            },
        )
        return {"state": "failed_to_start", "detail": detail}

    detail = (
        "Opened the Portfolio News Agent email/article run. It scans unread Seeking "
        "Alpha emails, opens article tabs in the dedicated browser session, runs LLM "
        "analysis, stores results in SQLite, and syncs usable evidence back to the agency."
    )
    scheduler_status.record_scheduler_runtime_status(
        state="idle",
        detail=detail,
        job_count=1,
        extra={
            "manual_subscription_email_article_analysis": {
                "status": "started",
                "process_id": process.pid,
                "dataset": "subscription_emails",
            }
        },
    )
    return {"state": "started", "process_id": process.pid, "detail": detail}


def _manual_lane_queue() -> Mapping[str, object]:
    live_queue = _load_live_scheduler_work_queue()
    if live_queue is not None:
        return live_queue
    from agency.runtime.data_load_status import load_data_load_status
    from agency.runtime.data_refresh_progress import load_data_refresh_progress
    from agency.runtime.scheduler_work_queue import scheduler_work_queue_context

    return scheduler_work_queue_context(
        data_load_status=load_data_load_status(),
        data_refresh_progress=load_data_refresh_progress(),
    )


def _work_queue_for_runner(
    *,
    data_load_status: Mapping[str, object],
    data_refresh_progress: Mapping[str, object],
) -> dict[str, object]:
    live_queue = _load_live_scheduler_work_queue()
    if live_queue is not None:
        return dict(live_queue)
    from agency.runtime.scheduler_work_queue import scheduler_work_queue_context

    return scheduler_work_queue_context(
        data_load_status=data_load_status,
        data_refresh_progress=data_refresh_progress,
    )


def _load_live_scheduler_work_queue() -> Mapping[str, object] | None:
    # This function is called from APScheduler worker threads, outside the
    # FastAPI request loop. Build the same queue from synchronous runtime
    # artifacts instead of probing or starting an event loop.
    try:
        from agency.runtime.data_load_status import load_data_load_status
        from agency.runtime.data_refresh_progress import load_data_refresh_progress
        from agency.runtime.scheduler_work_queue import scheduler_work_queue_context

        return scheduler_work_queue_context(
            data_load_status=load_data_load_status(),
            data_refresh_progress=load_data_refresh_progress(),
        )
    except Exception:
        return None


def _manual_massive_lane(
    queue: Mapping[str, object],
    lane_id: str,
) -> dict[str, object] | None:
    massive = queue.get("massive_orchestrator")
    if not isinstance(massive, Mapping):
        return None
    for row in _mapping_rows(massive.get("lanes")):
        if lane_id in {str(row.get("lane_id") or ""), str(row.get("name") or "")}:
            return row
    return None


def _manual_dataset_job(
    queue: Mapping[str, object],
    dataset: str,
) -> dict[str, object] | None:
    for row in _mapping_rows(queue.get("jobs")):
        if str(row.get("kind") or "") != "dataset":
            continue
        if dataset in {str(row.get("dataset") or ""), str(row.get("name") or "")}:
            return row
    return None


def _manual_lane_label(lane: Mapping[str, object]) -> str:
    return str(
        lane.get("label")
        or lane.get("lane_id")
        or lane.get("name")
        or "Massive lane"
    )


def _manual_job_label(job: Mapping[str, object]) -> str:
    name = str(job.get("label") or job.get("name") or job.get("dataset") or "dataset")
    return name.replace("_", " ").title()


def _record_manual_lane_refresh_refused(
    lane_id: str,
    detail: str,
    *,
    recorder: Callable[..., dict[str, object]],
    lane: Mapping[str, object] | None = None,
) -> dict[str, object]:
    policy_status = str(lane.get("status") or "UNKNOWN") if lane else "UNKNOWN"
    recorder(
        state="idle",
        detail=detail,
        job_count=0,
        extra={
            "tick_state": "idle",
            "active_command": None,
            "manual_lane_refresh": {
                "lane_id": lane_id,
                "job_id": str(lane.get("job_id") or f"massive:{lane_id}") if lane else f"massive:{lane_id}",
                "label": _manual_lane_label(lane or {"lane_id": lane_id}),
                "status": "refused",
                "policy_status": policy_status,
                "reason": detail,
            },
        },
    )
    return {
        "state": "refused",
        "lane_id": lane_id,
        "detail": detail,
        "policy_status": policy_status,
    }


def _record_manual_dataset_refresh_refused(
    dataset: str,
    detail: str,
    *,
    recorder: Callable[..., dict[str, object]],
    job: Mapping[str, object] | None = None,
) -> dict[str, object]:
    policy_status = str(job.get("status") or "UNKNOWN") if job else "UNKNOWN"
    recorder(
        state="idle",
        detail=detail,
        job_count=0,
        extra={
            "tick_state": "idle",
            "active_command": None,
            "manual_dataset_refresh": {
                "dataset": dataset,
                "job_id": str(job.get("job_id") or f"dataset:{dataset}") if job else f"dataset:{dataset}",
                "label": _manual_job_label(job or {"dataset": dataset}),
                "status": "refused",
                "policy_status": policy_status,
                "reason": detail,
            },
        },
    )
    return {
        "state": "refused",
        "dataset": dataset,
        "detail": detail,
        "policy_status": policy_status,
    }


def _subscription_email_login_refresh_shell_command() -> list[str]:
    return _portfolio_news_agent_shell_command(
        "--check-sa-browser",
        final_message="Portfolio News Agent SA browser check finished. Press Enter to close.",
    )


def _subscription_email_after_login_shell_command() -> list[str]:
    return _portfolio_news_agent_shell_command(
        "--once",
        final_message="Portfolio News Agent email/article analysis finished. Press Enter to close.",
        sync_after_success=True,
    )


def _portfolio_news_agent_shell_command(
    agent_mode: str,
    *,
    final_message: str,
    sync_after_success: bool = False,
) -> list[str]:
    repo = _ps_quote(REPO_ROOT)
    agent_root = portfolio_news_agent_root()
    agent_root_text = _ps_quote(agent_root)
    agent_python = _ps_quote(portfolio_news_agent_python(agent_root))
    agent_config = _ps_quote(
        ensure_portfolio_news_agent_agency_config(root=agent_root)
    )
    agent_env = _ps_quote(portfolio_news_agent_env_path(agent_root))
    agency_python = _ps_quote(PYTHON)
    sync_script = (
        f"if ($exitCode -eq 0) {{ Set-Location -LiteralPath '{repo}'; "
        f"& '{agency_python}' research\\scripts\\run_portfolio_news_agent_post_sync.py "
        f"--agent-root '{agent_root_text}' --run-mini-cycles; $exitCode = $LASTEXITCODE; }} "
        if sync_after_success
        else ""
    )
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f"Set-Location -LiteralPath '{agent_root_text}'; "
        f"& '{agent_python}' run_agent.py {agent_mode} --config '{agent_config}' --env-file '{agent_env}'; "
        "$exitCode = $LASTEXITCODE; "
        f"{sync_script}"
        "Write-Host ''; "
        f"Write-Host '{_ps_message(final_message)}'; "
        "Read-Host; "
        "exit $exitCode"
    )
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-NoExit",
        "-Command",
        script,
    ]


def _ps_quote(value: Path | str) -> str:
    return str(value).replace("'", "''")


def _ps_message(value: str) -> str:
    return value.replace("'", "''")


def _next_command_for_tick(
    queue: dict[str, object],
    *,
    executed_job_ids: set[str],
) -> dict[str, object] | None:
    for row in _commands_for_tick(queue):
        job_id = str(row.get("job_id") or row.get("name") or "unknown")
        if job_id not in executed_job_ids:
            return row
    return None


def _run_queue_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    normalized = _normalize_command(command)
    try:
        return subprocess.run(
            normalized,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            normalized,
            124,
            stdout=str(exc.stdout or ""),
            stderr=f"Command timed out after {COMMAND_TIMEOUT_SECONDS}s.",
        )


def _record_failed_data_refresh_status(
    command_row: dict[str, object],
    result: subprocess.CompletedProcess[str],
    *,
    command_started_at: datetime,
    command_finished_at: datetime,
) -> None:
    if str(command_row.get("kind") or "") != "dataset":
        return
    dataset = str(command_row.get("dataset") or command_row.get("name") or "").strip()
    if not dataset:
        return
    status_path = (
        REPO_ROOT
        / "research"
        / "results"
        / "latest-data-refresh"
        / "data-refresh-status.json"
    )
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    jobs = payload.get("jobs")
    job_rows = [dict(job) for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []
    command = _string_list(command_row.get("command"))
    duration = max(0, (command_finished_at - command_started_at).total_seconds())
    failure = {
        "dataset": dataset,
        "status": "failed",
        "reason": f"Scheduler command failed with exit {result.returncode}.",
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "started_at": command_started_at.isoformat(),
        "finished_at": command_finished_at.isoformat(),
        "duration_seconds": duration,
    }
    replaced = False
    updated_jobs: list[dict[str, object]] = []
    for job in job_rows:
        if str(job.get("dataset") or "") == dataset:
            updated = {**job, **failure}
            updated_jobs.append(updated)
            replaced = True
        else:
            updated_jobs.append(job)
    if not replaced:
        updated_jobs.append(failure)
    total = len(updated_jobs)
    complete_statuses = {"planned", "passed", "failed", "blocked", "skipped"}
    completed = sum(1 for job in updated_jobs if str(job.get("status")) in complete_statuses)
    running = sum(1 for job in updated_jobs if str(job.get("status")) == "running")
    pending = sum(1 for job in updated_jobs if str(job.get("status")) == "pending")
    progress_value = payload.get("progress")
    progress = dict(progress_value) if isinstance(progress_value, dict) else {}
    progress.update(
        {
            "state": "failed",
            "total_jobs": total,
            "completed_jobs": completed,
            "running_jobs": running,
            "pending_jobs": pending,
            "percent_complete": round(completed / total * 100) if total else 0,
            "current_dataset": None,
            "eta_seconds": 0,
            "eta_label": "failed",
        }
    )
    failed_datasets = sorted(
        {
            str(job.get("dataset"))
            for job in updated_jobs
            if str(job.get("status")) == "failed" and str(job.get("dataset") or "")
        }
    )
    payload.update(
        {
            "jobs": updated_jobs,
            "progress": progress,
            "updated_at": command_finished_at.isoformat(),
            "failed": True,
            "has_failures": True,
            "failed_datasets": failed_datasets,
            "in_progress": any(str(job.get("status")) in {"pending", "running"} for job in updated_jobs),
        }
    )
    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _expected_tick_timeout_seconds() -> int:
    runtime_slots = 1 if RUNTIME_CYCLE_AFTER_DATA_REFRESH else 0
    command_slots = max(WORK_QUEUE_MAX_COMMANDS, 0) + runtime_slots
    return max(COMMAND_TIMEOUT_SECONDS * command_slots + WORK_QUEUE_TICK_SECONDS, 1)


def _normalize_command(command: list[str]) -> list[str]:
    if not command:
        return command
    first = command[0].replace("/", "\\").lower()
    if first.endswith(("\\.venv\\scripts\\python", "\\.venv\\scripts\\python.exe")):
        return [PYTHON, *command[1:]]
    return command


def _runtime_cycle_command(*, tickers: list[str] | None = None) -> list[str]:
    scoped_tickers = _ordered_unique(tickers or [])[:RUNTIME_CYCLE_MAX_TICKERS]
    output_root = MINI_RUNTIME_OUTPUT_ROOT if scoped_tickers else CANONICAL_RUNTIME_OUTPUT_ROOT
    command = [
        PYTHON,
        "scripts\\run_live_runtime_cycle.py",
        "--config",
        "research\\config\\live-refresh.local.json",
        "--cycle-id",
        f"auto-lane-refresh-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "--audit-trigger",
        "SCHEDULED",
        "--output-root",
        output_root,
    ]
    command.append("--enable-llm-review" if _scheduler_enable_llm_review() else "--no-enable-llm-review")
    command.extend(["--llm-review-max-candidates", "10"])
    should_persist = RUNTIME_CYCLE_PERSIST and not scoped_tickers
    if should_persist:
        command.append("--persist")
    else:
        command.append("--no-persist")
    if scoped_tickers:
        for ticker in scoped_tickers:
            command.extend(["--ticker", ticker])
    else:
        command.extend(["--runtime-universe", "active", "--max-tickers", str(RUNTIME_CYCLE_MAX_TICKERS)])
    return command


def _scheduler_enable_llm_review() -> bool:
    load_dotenv(REPO_ROOT / ".env", override=False)
    raw_value = os.environ.get("AGENCY_SCHEDULER_ENABLE_LLM_REVIEW")
    if raw_value is None:
        raw_value = os.environ.get("AGENCY_ENABLE_LLM_REVIEW")
    if raw_value is None:
        return SCHEDULER_ENABLE_LLM_REVIEW
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _tickers_from_command(command: list[str]) -> list[str]:
    tickers: list[str] = []
    index = 0
    while index < len(command):
        item = command[index]
        if item == "--ticker" and index + 1 < len(command):
            tickers.append(command[index + 1])
            index += 2
            continue
        if item == "--tickers":
            index += 1
            while index < len(command) and not command[index].startswith("--"):
                tickers.append(command[index])
                index += 1
            continue
        index += 1
    return _ordered_unique(tickers)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).upper().strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _current_market_phase() -> str:
    import sys
    from datetime import UTC, datetime

    research_src = str(REPO_ROOT / "research" / "src")
    added = False
    if research_src not in sys.path:
        sys.path.insert(0, research_src)
        added = True
    try:
        from data_refresh.market_calendar import classify_market_session
        session = classify_market_session(datetime.now(UTC))
        return str(session.phase)
    finally:
        if added:
            sys.path.remove(research_src)
