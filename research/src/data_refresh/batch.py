from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from data_refresh.jobs import build_refresh_jobs
from data_refresh.status import write_status_files
from data_refresh.types import (
    DATASETS,
    CommandResult,
    RefreshBatchConfig,
    RefreshBatchResult,
    RefreshJob,
    RefreshJobResult,
    Runner,
)

__all__ = [
    "DATASETS",
    "CommandResult",
    "RefreshBatchConfig",
    "RefreshBatchResult",
    "RefreshJob",
    "RefreshJobResult",
    "Runner",
    "build_refresh_jobs",
    "run_refresh_batch",
]


def run_refresh_batch(
    config: RefreshBatchConfig,
    *,
    runner: Runner | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RefreshBatchResult:
    jobs = build_refresh_jobs(config)
    run_command = runner or _subprocess_runner
    get_now = clock or (lambda: datetime.now(UTC))
    started_at = get_now().isoformat()
    results = [_pending_result(job) for job in jobs]
    _write_progress(config, results, started_at=started_at, updated_at=started_at)
    for index, job in enumerate(jobs):
        if job.blocked_reasons:
            results[index] = _blocked_result(job, updated_at=get_now().isoformat())
        elif config.dry_run:
            results[index] = _planned_result(job, updated_at=get_now().isoformat())
        else:
            job_started_at = get_now()
            results[index] = _running_result(job, started_at=job_started_at.isoformat())
            _write_progress(
                config,
                results,
                started_at=started_at,
                updated_at=job_started_at.isoformat(),
            )
            results[index] = _run_job(
                job,
                config.repo_root,
                run_command,
                started_at=job_started_at,
                clock=get_now,
            )
        _write_progress(
            config,
            results,
            started_at=started_at,
            updated_at=get_now().isoformat(),
        )
    result = RefreshBatchResult(
        config=config,
        jobs=tuple(results),
        written_paths=("data-refresh-status.json", "data-refresh-status.md"),
        started_at=started_at,
        updated_at=get_now().isoformat(),
    )
    write_status_files(result, config.output_root)
    return result


def _run_job(
    job: RefreshJob,
    repo_root: Path,
    runner: Runner,
    *,
    started_at: datetime,
    clock: Callable[[], datetime],
) -> RefreshJobResult:
    completed = runner(job.command, repo_root)
    finished_at = clock()
    duration_seconds = round((finished_at - started_at).total_seconds(), 3)
    if completed.returncode == 0:
        return RefreshJobResult(
            dataset=job.dataset,
            status="passed",
            reason="refresh command completed",
            command=job.display_command,
            returncode=0,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=duration_seconds,
        )
    return RefreshJobResult(
        dataset=job.dataset,
        status="failed",
        reason="refresh command failed",
        command=job.display_command,
        returncode=completed.returncode,
        stdout=_tail(completed.stdout),
        stderr=_tail(completed.stderr),
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_seconds=duration_seconds,
    )


def _pending_result(job: RefreshJob) -> RefreshJobResult:
    return RefreshJobResult(
        dataset=job.dataset,
        status="pending",
        reason="waiting for previous refresh jobs",
        command=job.display_command,
    )


def _running_result(job: RefreshJob, *, started_at: str) -> RefreshJobResult:
    return RefreshJobResult(
        dataset=job.dataset,
        status="running",
        reason="refresh command running",
        command=job.display_command,
        started_at=started_at,
    )


def _blocked_result(job: RefreshJob, *, updated_at: str) -> RefreshJobResult:
    return RefreshJobResult(
        dataset=job.dataset,
        status="blocked",
        reason="; ".join(job.blocked_reasons),
        command=job.display_command,
        finished_at=updated_at,
        duration_seconds=0.0,
    )


def _planned_result(job: RefreshJob, *, updated_at: str) -> RefreshJobResult:
    return RefreshJobResult(
        dataset=job.dataset,
        status="planned",
        reason="dry-run only",
        command=job.display_command,
        finished_at=updated_at,
        duration_seconds=0.0,
    )


def _write_progress(
    config: RefreshBatchConfig,
    results: list[RefreshJobResult],
    *,
    started_at: str,
    updated_at: str,
) -> None:
    result = RefreshBatchResult(
        config=config,
        jobs=tuple(results),
        written_paths=("data-refresh-status.json", "data-refresh-status.md"),
        started_at=started_at,
        updated_at=updated_at,
    )
    write_status_files(result, config.output_root)


def _subprocess_runner(command: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _tail(value: str, limit: int = 1000) -> str:
    return value if len(value) <= limit else value[-limit:]
