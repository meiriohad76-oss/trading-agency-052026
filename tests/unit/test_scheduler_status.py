from __future__ import annotations

from datetime import UTC, datetime, timedelta

import agency.runtime.scheduler_status as scheduler_status
from agency.app import _scheduler_enabled_for_app


def test_scheduler_enabled_defaults_to_basic_app_automation(monkeypatch) -> None:
    monkeypatch.delenv("AGENCY_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert scheduler_status._scheduler_enabled() is True  # noqa: SLF001
    assert _scheduler_enabled_for_app("") is True


def test_scheduler_runtime_status_marks_stale_running_tick(tmp_path, monkeypatch) -> None:
    path = tmp_path / "scheduler.json"
    now = datetime(2026, 5, 15, 18, 0, tzinfo=UTC)
    scheduler_status.record_scheduler_runtime_status(
        state="running",
        detail="Automatic lane refresh tick is evaluating the scheduler work queue.",
        extra={"last_tick_started_at": (now - timedelta(minutes=20)).isoformat()},
        now=now - timedelta(minutes=20),
        path=path,
    )
    monkeypatch.setattr(scheduler_status, "_RUNTIME_STATUS", None)

    status = scheduler_status.load_scheduler_runtime_status(now=now, path=path)

    assert status["tick_state"] == "stale"
    assert status["status_class"] == "block"
    assert "has not finished" in str(status["detail"])


def test_scheduler_runtime_status_uses_expected_tick_timeout(tmp_path, monkeypatch) -> None:
    path = tmp_path / "scheduler.json"
    now = datetime(2026, 5, 15, 18, 0, tzinfo=UTC)
    started_at = now - timedelta(minutes=16)
    monkeypatch.setattr(scheduler_status, "DEFAULT_TICK_STALE_SECONDS", 900)
    scheduler_status.record_scheduler_runtime_status(
        state="running",
        detail="Automatic lane refresh is running a bounded command batch.",
        extra={
            "last_tick_started_at": started_at.isoformat(),
            "expected_tick_timeout_seconds": 1200,
        },
        now=started_at,
        path=path,
    )
    monkeypatch.setattr(scheduler_status, "_RUNTIME_STATUS", None)

    status = scheduler_status.load_scheduler_runtime_status(now=now, path=path)

    assert status["tick_state"] == "running"
    assert status["status_class"] == "pass"
