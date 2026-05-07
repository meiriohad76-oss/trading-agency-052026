from __future__ import annotations

import subprocess
from collections.abc import Sequence
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
) -> RefreshBatchResult:
    jobs = build_refresh_jobs(config)
    run_command = runner or _subprocess_runner
    results: list[RefreshJobResult] = []
    for job in jobs:
        if job.blocked_reasons:
            results.append(_blocked_result(job))
        elif config.dry_run:
            results.append(_planned_result(job))
        else:
            results.append(_run_job(job, config.repo_root, run_command))
    result = RefreshBatchResult(
        config=config,
        jobs=tuple(results),
        written_paths=("data-refresh-status.json", "data-refresh-status.md"),
    )
    write_status_files(result, config.output_root)
    return result


def _run_job(job: RefreshJob, repo_root: Path, runner: Runner) -> RefreshJobResult:
    completed = runner(job.command, repo_root)
    if completed.returncode == 0:
        return RefreshJobResult(
            job.dataset,
            "passed",
            "refresh command completed",
            job.display_command,
            0,
        )
    return RefreshJobResult(
        job.dataset,
        "failed",
        "refresh command failed",
        job.display_command,
        completed.returncode,
        _tail(completed.stdout),
        _tail(completed.stderr),
    )


def _blocked_result(job: RefreshJob) -> RefreshJobResult:
    return RefreshJobResult(
        job.dataset,
        "blocked",
        "; ".join(job.blocked_reasons),
        job.display_command,
    )


def _planned_result(job: RefreshJob) -> RefreshJobResult:
    return RefreshJobResult(job.dataset, "planned", "dry-run only", job.display_command)


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
