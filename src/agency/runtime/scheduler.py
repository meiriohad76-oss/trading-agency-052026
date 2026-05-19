from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

SchedulerAction = Callable[[], Awaitable[Mapping[str, object]]]


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    interval_seconds: int
    action: SchedulerAction
    last_run_at: datetime | None = None
    enabled: bool = True


@dataclass(frozen=True)
class SchedulerJobResult:
    name: str
    status: str
    reason: str
    payload: dict[str, object]


async def run_due_jobs(
    jobs: Sequence[ScheduledJob],
    *,
    now: datetime | None = None,
) -> list[SchedulerJobResult]:
    current_time = _utc(now)
    results: list[SchedulerJobResult] = []
    for job in jobs:
        if not job.enabled:
            results.append(_result(job.name, "SKIPPED", "disabled"))
        elif not is_due(job, now=current_time):
            results.append(_result(job.name, "SKIPPED", "not due"))
        else:
            results.append(await _run_job(job))
    return results


def scheduler_summary(results: Sequence[SchedulerJobResult]) -> dict[str, object]:
    counts = {
        "succeeded": sum(1 for result in results if result.status == "SUCCEEDED"),
        "failed": sum(1 for result in results if result.status == "FAILED"),
        "skipped": sum(1 for result in results if result.status == "SKIPPED"),
    }
    state = "blocked" if counts["failed"] else "ready"
    return {
        "schema_version": "0.1.0",
        "ready": counts["failed"] == 0,
        "state": state,
        "job_count": len(results),
        "counts": counts,
        "jobs": [
            {
                "name": result.name,
                "status": result.status,
                "reason": result.reason,
                "payload": result.payload,
            }
            for result in results
        ],
    }


def is_due(job: ScheduledJob, *, now: datetime | None = None) -> bool:
    if job.interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    if job.last_run_at is None:
        return True
    current_time = _utc(now)
    last_run_at = _utc(job.last_run_at)
    return current_time - last_run_at >= timedelta(seconds=job.interval_seconds)


async def _run_job(job: ScheduledJob) -> SchedulerJobResult:
    try:
        payload = await job.action()
    except Exception as exc:
        return _result(job.name, "FAILED", str(exc))
    return _result(job.name, "SUCCEEDED", "job completed", dict(payload))


def _result(
    name: str,
    status: str,
    reason: str,
    payload: dict[str, object] | None = None,
) -> SchedulerJobResult:
    return SchedulerJobResult(name, status, reason, payload or {})


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler datetimes must include timezone")
    return value.astimezone(UTC)
