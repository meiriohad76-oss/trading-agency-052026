from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from agency.paths import REPO_ROOT

DEFAULT_STATUS_PATH = REPO_ROOT / "research" / "results" / "latest-scheduler-runtime-status.json"
DEFAULT_TICK_STALE_SECONDS = int(
    os.environ.get("AGENCY_SCHEDULER_TICK_STALE_SECONDS", "900")
)

_RUNTIME_STATUS: dict[str, object] | None = None


def record_scheduler_runtime_status(
    *,
    state: str,
    detail: str,
    job_count: int = 0,
    extra: Mapping[str, object] | None = None,
    now: datetime | None = None,
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, object]:
    current = _utc(now)
    status = {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "enabled": _scheduler_enabled(),
        "database_configured": bool(os.environ.get("DATABASE_URL", "").strip()),
        "state": state,
        "status_label": _status_label(state),
        "status_class": _status_class(state),
        "job_count": job_count,
        "detail": detail,
    }
    if extra is not None:
        status.update(dict(extra))
    global _RUNTIME_STATUS
    _RUNTIME_STATUS = dict(status)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    return status


def load_scheduler_runtime_status(
    *,
    now: datetime | None = None,
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, object]:
    current = _utc(now)
    if _RUNTIME_STATUS is not None:
        status = _with_stale_tick_guard(dict(_RUNTIME_STATUS), now=current)
        status["checked_at"] = current.isoformat()
        return status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        status = _with_stale_tick_guard(payload, now=current)
        status["checked_at"] = current.isoformat()
        return status
    enabled = _scheduler_enabled()
    database_configured = bool(os.environ.get("DATABASE_URL", "").strip())
    if not enabled:
        state = "disabled"
        detail = "Set AGENCY_SCHEDULER_ENABLED=true to run automatic refresh jobs."
    else:
        state = "unknown"
        detail = "Scheduler runtime has not recorded a startup heartbeat in this process."
    return {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "checked_at": current.isoformat(),
        "enabled": enabled,
        "database_configured": database_configured,
        "state": state,
        "status_label": _status_label(state),
        "status_class": _status_class(state),
        "job_count": 0,
        "detail": detail,
    }


def _scheduler_enabled() -> bool:
    value = os.environ.get("AGENCY_SCHEDULER_ENABLED")
    if value is None:
        return True
    return value.lower() not in {"0", "false", "no", "off"}


def _with_stale_tick_guard(
    status: dict[str, object],
    *,
    now: datetime,
) -> dict[str, object]:
    started_at = _parse_datetime(status.get("last_tick_started_at"))
    finished_at = _parse_datetime(status.get("last_tick_finished_at"))
    if started_at is None:
        return status
    if finished_at is not None and finished_at >= started_at:
        stale_active_command = status.get("active_command") is not None
        status["tick_state"] = "idle"
        status["active_command"] = None
        if str(status.get("state") or "") == "running":
            status["state"] = "idle"
            status["status_label"] = _status_label("idle")
            status["status_class"] = _status_class("idle")
            if stale_active_command:
                status["detail"] = (
                    "Automatic lane refresh tick finished; no scheduler command is active."
                )
        return status
    age_seconds = int((now - started_at).total_seconds())
    status["last_tick_age_seconds"] = age_seconds
    status.setdefault("tick_state", "running")
    stale_seconds = _stale_threshold_seconds(status)
    if age_seconds <= stale_seconds:
        return status
    status["tick_state"] = "stale"
    status["status_label"] = "Tick Stalled"
    status["status_class"] = "block"
    detail = str(status.get("detail") or "Automatic scheduler tick is running.")
    status["detail"] = (
        f"{detail} Latest tick has not finished for {age_seconds}s; "
        "automatic data-lane health is not reliable until the worker updates again."
    )
    return status


def _stale_threshold_seconds(status: Mapping[str, object]) -> int:
    value = status.get("expected_tick_timeout_seconds")
    if isinstance(value, bool):
        return DEFAULT_TICK_STALE_SECONDS
    if isinstance(value, int) and value > 0:
        return max(DEFAULT_TICK_STALE_SECONDS, value)
    return DEFAULT_TICK_STALE_SECONDS


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _status_label(state: str) -> str:
    return {
        "running": "Running",
        "idle": "Idle",
        "starting": "Starting",
        "stopped": "Stopped",
        "disabled": "Disabled",
        "not_started": "Not Started",
        "error": "Error",
        "unknown": "Unknown",
    }.get(state, state.replace("_", " ").title())


def _status_class(state: str) -> str:
    if state in {"running", "idle"}:
        return "pass"
    if state in {"starting", "disabled", "not_started", "unknown"}:
        return "warn"
    return "block"


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler status datetimes must include timezone")
    return value.astimezone(UTC)
