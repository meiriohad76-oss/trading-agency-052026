from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

COMPLETE_STATES = {"complete", "planned"}
ATTENTION_STATES = {"blocked", "failed"}
SECONDS_PER_MINUTE = 60
ESTIMATED_JOB_SECONDS = {
    "prices_daily": 90.0,
    "sec_company_facts": 60.0,
    "sec_form4": 600.0,
    "sec_13f": 90.0,
    "news_rss": 20.0,
    "stock_trades": 180.0,
    "options_chains": 60.0,
    "unusual_activity_alerts": 10.0,
}


def eta_seconds(
    progress: Mapping[str, object],
    jobs: Sequence[object],
    state: str,
) -> int | None:
    if state != "running":
        return _progress_eta_seconds(progress)
    if not any(str(_mapping(job).get("status")) in {"pending", "running"} for job in jobs):
        return _progress_eta_seconds(progress)
    completed_durations = [
        duration
        for job in jobs
        if str(_mapping(job).get("status")) == "passed"
        for duration in [_duration_seconds(job)]
        if duration is not None
    ]
    fallback = _average(completed_durations)
    remaining = 0.0
    now = datetime.now(UTC)
    for job in jobs:
        payload = _mapping(job)
        dataset = str(payload.get("dataset") or "")
        status = str(payload.get("status") or "")
        if status == "pending":
            remaining += _job_estimate(dataset, fallback)
        elif status == "running":
            estimate = _job_estimate(dataset, fallback)
            remaining += max(estimate - _running_elapsed(payload, now), 5.0)
    return round(remaining)


def _job_estimate(dataset: str, fallback: float | None) -> float:
    baseline = ESTIMATED_JOB_SECONDS.get(dataset, 60.0)
    if fallback is None:
        return baseline
    return max(baseline, fallback)


def eta_label(eta_value: int | None, state: str) -> str:
    if state in COMPLETE_STATES:
        return "complete"
    if state in ATTENTION_STATES:
        return "not available"
    if state == "running":
        if eta_value is None:
            return "calculating"
        if eta_value < SECONDS_PER_MINUTE:
            return f"{eta_value}s"
        return f"{round(eta_value / SECONDS_PER_MINUTE)}m"
    return "not available"


def _progress_eta_seconds(progress: Mapping[str, object]) -> int | None:
    value = progress.get("eta_seconds")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _duration_seconds(job: object) -> float | None:
    value = _mapping(job).get("duration_seconds")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _running_elapsed(payload: Mapping[str, object], now: datetime) -> float:
    started_at = payload.get("started_at")
    if not isinstance(started_at, str):
        return 0.0
    parsed = _parse_time(started_at)
    if parsed is None:
        return 0.0
    return max((now - parsed).total_seconds(), 0.0)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
