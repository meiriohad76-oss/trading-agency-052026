from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

from agency.runtime.data_refresh_eta import eta_label, eta_seconds

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATUS_PATH = (
    REPO_ROOT
    / "research"
    / "results"
    / "latest-data-refresh"
    / "data-refresh-status.json"
)

COMPLETE_STATES = {"complete", "planned"}
ATTENTION_STATES = {"blocked", "failed"}


def load_data_refresh_progress(path: Path | None = None) -> dict[str, object]:
    status_path = path or data_refresh_status_path()
    if not status_path.is_file():
        return _idle_progress(status_path)
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _unavailable_progress(status_path)
    if not isinstance(payload, Mapping):
        return _unavailable_progress(status_path)
    return _progress_from_payload(cast(Mapping[str, object], payload), status_path)


def data_refresh_status_path() -> Path:
    load_dotenv()
    value = os.environ.get("DATA_REFRESH_STATUS_PATH")
    if value is None or value.strip() == "":
        return DEFAULT_STATUS_PATH
    return Path(value)


def _progress_from_payload(payload: Mapping[str, object], status_path: Path) -> dict[str, object]:
    progress = _mapping(payload.get("progress"))
    jobs = _sequence(payload.get("jobs"))
    state = _state(payload, progress, jobs)
    total_jobs = _int_value(progress.get("total_jobs"), len(jobs))
    completed_jobs = _int_value(progress.get("completed_jobs"), _completed_jobs(jobs))
    percent = _int_value(progress.get("percent_complete"), _percent(completed_jobs, total_jobs))
    eta_value = eta_seconds(progress, jobs, state)
    eta_text = eta_label(eta_value, state)
    current_dataset = progress.get("current_dataset") or _current_dataset(jobs)
    updated_at = payload.get("updated_at")
    return {
        "state": state,
        "status_label": _status_label(state),
        "status_class": _status_class(state),
        "percent_complete": max(0, min(percent, 100)),
        "completed_jobs": completed_jobs,
        "total_jobs": total_jobs,
        "current_dataset": str(current_dataset or "None"),
        "eta_seconds": eta_value,
        "eta_label": eta_text,
        "updated_at": str(updated_at or "Not recorded"),
        "detail": _detail(state),
        "status_path": _display_path(status_path),
        "is_loading": state == "running",
    }


def _idle_progress(status_path: Path) -> dict[str, object]:
    return {
        "state": "idle",
        "status_label": "Idle",
        "status_class": "neutral",
        "percent_complete": 0,
        "completed_jobs": 0,
        "total_jobs": 0,
        "current_dataset": "None",
        "eta_label": "not available",
        "updated_at": "Not recorded",
        "detail": "No data refresh is running.",
        "status_path": _display_path(status_path),
        "is_loading": False,
    }


def _unavailable_progress(status_path: Path) -> dict[str, object]:
    progress = _idle_progress(status_path)
    progress.update(
        {
            "state": "unavailable",
            "status_label": "Unavailable",
            "status_class": "warn",
            "detail": "The latest data refresh status could not be read.",
        }
    )
    return progress


def _state(
    payload: Mapping[str, object],
    progress: Mapping[str, object],
    jobs: Sequence[object],
) -> str:
    state = progress.get("state")
    if isinstance(state, str) and state:
        return state
    statuses = [str(_mapping(job).get("status")) for job in jobs]
    derived = "idle"
    if any(status in {"pending", "running"} for status in statuses):
        derived = "running"
    elif payload.get("failed") is True or "failed" in statuses:
        derived = "failed"
    elif payload.get("blocked") is True or "blocked" in statuses:
        derived = "blocked"
    elif statuses and all(status == "planned" for status in statuses):
        derived = "planned"
    elif statuses:
        derived = "complete"
    return derived


def _status_label(state: str) -> str:
    labels = {
        "idle": "Idle",
        "running": "Loading",
        "complete": "Complete",
        "planned": "Planned",
        "blocked": "Blocked",
        "failed": "Failed",
        "unavailable": "Unavailable",
    }
    return labels.get(state, state.replace("_", " ").title())


def _status_class(state: str) -> str:
    if state in COMPLETE_STATES:
        return "pass"
    if state == "running":
        return "warn"
    if state in ATTENTION_STATES:
        return "block"
    return "neutral"


def _detail(state: str) -> str:
    if state == "running":
        return "Data refresh is loading source datasets."
    if state == "complete":
        return "Latest data refresh completed."
    if state == "planned":
        return "Latest data refresh was a dry run."
    if state == "blocked":
        return "Latest data refresh is blocked by missing inputs."
    if state == "failed":
        return "Latest data refresh failed before all datasets loaded."
    return "No data refresh is running."


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else []


def _completed_jobs(jobs: Sequence[object]) -> int:
    return sum(
        1
        for job in jobs
        if str(_mapping(job).get("status")) in {"planned", "passed", "failed", "blocked"}
    )


def _current_dataset(jobs: Sequence[object]) -> str | None:
    for status in ("running", "pending"):
        for job in jobs:
            payload = _mapping(job)
            if payload.get("status") == status and isinstance(payload.get("dataset"), str):
                return str(payload["dataset"])
    return None


def _int_value(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    return fallback


def _percent(completed_jobs: int, total_jobs: int) -> int:
    if total_jobs == 0:
        return 0
    return round(completed_jobs / total_jobs * 100)


def _display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
