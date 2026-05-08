from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from agency.runtime import ScheduledJob, is_due, run_due_jobs

NOW = datetime(2026, 5, 8, 10, 30, tzinfo=UTC)


def test_scheduler_due_checks_use_timezone_aware_datetimes() -> None:
    job = ScheduledJob("refresh", 60, _successful_action, last_run_at=NOW - timedelta(seconds=60))

    assert is_due(job, now=NOW)


def test_scheduler_skips_recent_jobs() -> None:
    job = ScheduledJob("refresh", 60, _successful_action, last_run_at=NOW - timedelta(seconds=30))

    assert not is_due(job, now=NOW)


def test_scheduler_rejects_invalid_timing() -> None:
    job = ScheduledJob("refresh", 0, _successful_action)

    with pytest.raises(ValueError, match="interval_seconds"):
        is_due(job, now=NOW)


def test_scheduler_rejects_naive_datetimes() -> None:
    job = ScheduledJob("refresh", 60, _successful_action, last_run_at=NOW)

    with pytest.raises(ValueError, match="timezone"):
        is_due(job, now=datetime(2026, 5, 8, 10, 30))


async def test_run_due_jobs_reports_success_skips_and_failures() -> None:
    jobs = [
        ScheduledJob("ready", 60, _successful_action, last_run_at=NOW - timedelta(seconds=60)),
        ScheduledJob("recent", 60, _successful_action, last_run_at=NOW - timedelta(seconds=30)),
        ScheduledJob("disabled", 60, _successful_action, enabled=False),
        ScheduledJob("failing", 60, _failing_action),
    ]

    results = await run_due_jobs(jobs, now=NOW)

    assert [(result.name, result.status) for result in results] == [
        ("ready", "SUCCEEDED"),
        ("recent", "SKIPPED"),
        ("disabled", "SKIPPED"),
        ("failing", "FAILED"),
    ]
    assert results[0].payload == {"rows": 1}
    assert results[-1].reason == "boom"


async def _successful_action() -> Mapping[str, object]:
    return {"rows": 1}


async def _failing_action() -> Mapping[str, object]:
    raise RuntimeError("boom")
