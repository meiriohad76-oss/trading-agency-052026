from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
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
DEFAULT_STOCK_TRADES_MANIFEST_PATH = (
    REPO_ROOT / "research" / "data" / "manifests" / "stock_trades.json"
)
STOCK_TRADES_PROGRESS_FILENAME = "stock-trades-progress.json"

COMPLETE_STATES = {"complete"}
ATTENTION_STATES = {"blocked", "failed"}
STALE_RUNNING_STATUS_SECONDS = 30 * 60


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
    if state == "running" and _status_file_stale(status_path):
        state = "stale"
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
        "has_failures": payload.get("has_failures") is True,
        "failed_datasets": [str(d) for d in _sequence(payload.get("failed_datasets"))],
        "trade_pull": _trade_pull_status(payload, status_path),
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
        "has_failures": False,
        "failed_datasets": [],
        "trade_pull": _trade_pull_status({}, status_path),
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


def _trade_pull_status(
    payload: Mapping[str, object],
    status_path: Path,
) -> dict[str, object]:
    config = _mapping(payload.get("config"))
    jobs = _sequence(payload.get("jobs"))
    job_index, job_total, job = _stock_trade_job(jobs)
    progress_path = _stock_trade_progress_path(status_path)
    progress = _json_mapping(progress_path)
    manifest = _json_mapping(DEFAULT_STOCK_TRADES_MANIFEST_PATH)
    job_status = str(job.get("status") or "")
    progress_state = str(progress.get("state") or "")
    state = _trade_state(
        job_status=job_status,
        progress_state=progress_state,
        progress_path=progress_path,
        config=config,
        manifest=manifest,
        has_stock_trade_job=bool(job),
    )
    percent = _trade_percent(state=state, progress=progress)
    rows_written = _int_value(progress.get("rows_written"), 0)
    manifest_rows = _int_value(manifest.get("row_count"), rows_written)
    total = _int_value(
        progress.get("ticker_days_total"),
        _command_ticker_count(job) or _int_value(manifest.get("ticker_count"), 0),
    )
    completed = _int_value(progress.get("ticker_days_completed"), 0)
    if state in {"complete", "ready", "skipped"} and total > 0:
        completed = total
    ticker_count = _int_value(
        progress.get("ticker_count"),
        _int_value(manifest.get("ticker_count"), 0),
    )
    latest_as_of = _timestamp_label(
        manifest.get("max_timestamp_as_of") or manifest.get("fetched_at")
    )
    return {
        "state": state,
        "status_label": _trade_status_label(state),
        "status_class": _trade_status_class(state),
        "percent_complete": percent,
        "is_running": state == "running",
        "current_ticker": _text_value(progress.get("current_ticker"), "None"),
        "current_trade_date": _text_value(progress.get("current_trade_date"), "not active"),
        "current_pages_downloaded": _int_value(progress.get("current_pages_downloaded"), 0),
        "current_rows_downloaded": _int_value(progress.get("current_rows_downloaded"), 0),
        "ticker_days_completed": completed,
        "ticker_days_total": total,
        "ticker_progress_label": _ticker_progress_label(completed, total),
        "job_position_label": _job_position_label(job_index, job_total),
        "row_count": manifest_rows,
        "row_count_label": _count_label(manifest_rows),
        "ticker_count": ticker_count,
        "latest_as_of": latest_as_of,
        "window_label": _stock_trade_window(config, manifest, progress),
        "guardrail_label": _stock_trade_guardrail(config, job),
        "detail": _trade_detail(
            state=state,
            job=job,
            progress=progress,
            manifest=manifest,
            completed=completed,
            total=total,
        ),
        "updated_at": _text_value(
            progress.get("updated_at"),
            _text_value(payload.get("updated_at"), "not recorded"),
        ),
        "progress_path": _display_path(progress_path),
        "status_path": _display_path(status_path),
    }


def _stock_trade_job(jobs: Sequence[object]) -> tuple[int | None, int, Mapping[str, object]]:
    total = len(jobs)
    for index, value in enumerate(jobs, start=1):
        job = _mapping(value)
        if job.get("dataset") == "stock_trades":
            return index, total, job
    return None, total, {}


def _stock_trade_progress_path(status_path: Path) -> Path:
    return status_path.parent / STOCK_TRADES_PROGRESS_FILENAME


def _json_mapping(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _trade_state(
    *,
    job_status: str,
    progress_state: str,
    progress_path: Path,
    config: Mapping[str, object],
    manifest: Mapping[str, object],
    has_stock_trade_job: bool,
) -> str:
    if job_status == "running":
        return "stale" if _status_file_stale(progress_path) else "running"
    if progress_state in {"blocked", "failed", "partial", "stale"}:
        return progress_state
    if job_status in {"pending", "passed", "failed", "blocked", "skipped", "planned"}:
        return "complete" if job_status == "passed" else job_status
    if progress_state:
        if progress_state == "running" and _status_file_stale(progress_path):
            return "stale"
        return progress_state
    if not has_stock_trade_job and manifest:
        if _manifest_covers_stock_trade_request(config, manifest):
            return "ready"
        return "unverified"
    if manifest:
        return "ready"
    return "idle"


def _trade_percent(*, state: str, progress: Mapping[str, object]) -> int:
    if state in {"complete", "ready", "skipped"}:
        return 100
    value = _int_value(progress.get("percent_complete"), 0)
    if state == "running":
        return max(1, min(value, 99))
    if state == "stale":
        return max(0, min(value, 99))
    return max(0, min(value, 100))


def _trade_status_label(state: str) -> str:
    labels = {
        "idle": "No Pull",
        "ready": "Trades Ready",
        "running": "Pulling Trades",
        "complete": "Pull Complete",
        "pending": "Queued",
        "skipped": "Fresh",
        "planned": "Planned",
        "partial": "Partial",
        "unverified": "Unverified",
        "blocked": "Blocked",
        "failed": "Failed",
        "stale": "Stale",
    }
    return labels.get(state, state.replace("_", " ").title())


def _trade_status_class(state: str) -> str:
    if state in {"ready", "complete", "skipped"}:
        return "pass"
    if state in {"running", "pending", "planned", "unverified"}:
        return "warn"
    if state in {"blocked", "failed", "partial", "stale"}:
        return "block"
    return "neutral"


def _stock_trade_window(
    config: Mapping[str, object],
    manifest: Mapping[str, object],
    progress: Mapping[str, object],
) -> str:
    start = _text_value(
        config.get("stock_trades_start"),
        _text_value(progress.get("start"), ""),
    )
    end = _text_value(
        config.get("stock_trades_end"),
        _text_value(progress.get("end"), ""),
    )
    if not start or not end:
        date_range = _mapping(manifest.get("date_range"))
        start = _text_value(date_range.get("start"), "")
        end = _text_value(date_range.get("end"), "")
    if start and end:
        if start == end:
            return start
        return f"{start} to {end}"
    return "not recorded"


def _stock_trade_guardrail(
    config: Mapping[str, object],
    job: Mapping[str, object],
) -> str:
    limit = _text_value(
        config.get("stock_trades_limit"),
        _command_option(job, "--limit") or "unknown limit",
    )
    pages = config.get("stock_trades_max_pages_per_day")
    if pages is None:
        pages = _command_option(job, "--max-pages-per-day")
    page_text = "unbounded" if pages is None else str(pages)
    order = _text_value(
        config.get("stock_trades_order"),
        _command_option(job, "--order") or "not recorded",
    )
    return f"limit {limit}; pages/day {page_text}; order {order}"


def _trade_detail(
    *,
    state: str,
    job: Mapping[str, object],
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
    completed: int,
    total: int,
) -> str:
    if state == "running":
        return _running_trade_detail(progress, completed=completed, total=total)
    if state in {"complete", "ready", "skipped", "planned", "unverified"}:
        return _available_trade_detail(state=state, progress=progress, manifest=manifest)
    if state == "partial":
        partial = _int_value(progress.get("ticker_days_partial"), 0)
        failed = _int_value(progress.get("ticker_days_failed"), 0)
        return (
            "Massive stock-trades pull finished with incomplete coverage: "
            f"{partial} partial ticker-day(s), {failed} failed ticker-day(s)."
        )
    if state in {"blocked", "failed"}:
        return _text_value(job.get("reason"), "Massive stock-trades pull needs attention.")
    if state == "stale":
        return "Massive stock-trades progress stopped updating; verify the refresh worker."
    if state == "pending":
        return "Massive stock-trades pull is queued behind earlier refresh jobs."
    return "No Massive stock-trades pull status is available yet."


def _running_trade_detail(
    progress: Mapping[str, object],
    *,
    completed: int,
    total: int,
) -> str:
    ticker = _text_value(progress.get("current_ticker"), "current ticker")
    trade_date = _text_value(progress.get("current_trade_date"), "current date")
    rows = _int_value(progress.get("current_rows_downloaded"), 0)
    pages = _int_value(progress.get("current_pages_downloaded"), 0)
    return (
        f"Massive stock-trades pull is active on {ticker} for {trade_date}: "
        f"{_count_label(rows)} rows over {pages} page(s); "
        f"{completed}/{total} ticker-days complete."
    )


def _available_trade_detail(
    *,
    state: str,
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
) -> str:
    if state == "skipped":
        return "Massive stock-trades pull was skipped because local coverage is already fresh."
    if state == "planned":
        return "Massive stock-trades pull was planned only; no trade data was loaded."
    if state == "unverified":
        return (
            "An existing Massive trade manifest is present, but the latest refresh did "
            "not verify that it covers the current requested trade window and ticker set."
        )
    rows = _int_value(
        manifest.get("row_count"),
        _int_value(progress.get("rows_written"), 0),
    )
    tickers = _int_value(
        manifest.get("ticker_count"),
        _int_value(progress.get("ticker_count"), 0),
    )
    latest = _timestamp_label(manifest.get("max_timestamp_as_of"))
    return (
        f"Massive trade data is available: {_count_label(rows)} rows across "
        f"{tickers} ticker(s), latest as-of {latest}."
    )


def _command_ticker_count(job: Mapping[str, object]) -> int:
    command = _sequence(job.get("command"))
    return sum(1 for item in command if item == "--ticker")


def _command_option(job: Mapping[str, object], flag: str) -> str | None:
    command = [str(item) for item in _sequence(job.get("command"))]
    for index, item in enumerate(command):
        if item == flag and index + 1 < len(command):
            return command[index + 1]
    return None


def _manifest_covers_stock_trade_request(
    config: Mapping[str, object],
    manifest: Mapping[str, object],
) -> bool:
    date_range = _mapping(manifest.get("date_range"))
    requested_start = _parse_date(config.get("stock_trades_start"))
    requested_end = _parse_date(config.get("stock_trades_end"))
    manifest_start = _parse_date(date_range.get("start"))
    manifest_end = _parse_date(date_range.get("end"))
    if (
        requested_start is None
        or requested_end is None
        or manifest_start is None
        or manifest_end is None
    ):
        return False
    if manifest_start > requested_start or manifest_end < requested_end:
        return False
    requested_tickers = {
        str(ticker).upper()
        for ticker in _sequence(config.get("tickers"))
        if str(ticker).strip()
    }
    if not requested_tickers:
        return True
    manifest_tickers = {
        str(ticker).upper()
        for ticker in _sequence(manifest.get("tickers"))
        if str(ticker).strip()
    }
    return requested_tickers.issubset(manifest_tickers)


def _parse_date(value: object) -> date | None:
    text = _text_value(value, "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.removesuffix("Z")).date()
    except ValueError:
        return None


def _ticker_progress_label(completed: int, total: int) -> str:
    if total <= 0:
        return "not tracked"
    return f"{completed}/{total} ticker-days"


def _job_position_label(index: int | None, total: int) -> str:
    if index is None or total <= 0:
        return "not in latest batch"
    return f"job {index}/{total}"


def _count_label(value: int) -> str:
    return f"{value:,}"


def _text_value(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _timestamp_label(value: object) -> str:
    text = _text_value(value, "not recorded")
    if text == "not recorded":
        return text
    label = text.replace("T", " ")
    if label.endswith("+00:00"):
        label = label.removesuffix("+00:00")
        if "." in label:
            label = label.split(".", maxsplit=1)[0]
        return f"{label} UTC"
    if label.endswith("Z"):
        label = label.removesuffix("Z")
        if "." in label:
            label = label.split(".", maxsplit=1)[0]
        return f"{label} UTC"
    return label


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
    if payload.get("failed") is True or "failed" in statuses:
        derived = "failed"
    elif payload.get("blocked") is True or "blocked" in statuses:
        derived = "blocked"
    elif any(status in {"pending", "running"} for status in statuses):
        derived = "running"
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
        "stale": "Stale",
        "unavailable": "Unavailable",
    }
    return labels.get(state, state.replace("_", " ").title())


def _status_class(state: str) -> str:
    if state in COMPLETE_STATES:
        return "pass"
    if state == "running":
        return "warn"
    if state == "stale":
        return "block"
    if state in ATTENTION_STATES:
        return "block"
    return "neutral"


def _detail(state: str) -> str:
    details = {
        "running": "Data refresh is loading source datasets.",
        "complete": "Latest data refresh completed.",
        "planned": "Latest data refresh was a dry run.",
        "blocked": "Latest data refresh is blocked by missing inputs.",
        "failed": "Latest data refresh failed before all datasets loaded.",
        "stale": (
            "Latest data refresh stopped updating; verify whether the worker is still running."
        ),
    }
    return details.get(state, "No data refresh is running.")


def _status_file_stale(status_path: Path) -> bool:
    try:
        modified_at = datetime.fromtimestamp(status_path.stat().st_mtime, tz=UTC)
    except OSError:
        return False
    return (datetime.now(UTC) - modified_at).total_seconds() > STALE_RUNNING_STATUS_SECONDS


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else []


def _completed_jobs(jobs: Sequence[object]) -> int:
    return sum(
        1
        for job in jobs
        if str(_mapping(job).get("status"))
        in {"planned", "passed", "failed", "blocked", "skipped"}
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
