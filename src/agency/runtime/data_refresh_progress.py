from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

from agency.runtime.data_refresh_eta import eta_label, eta_seconds

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_SRC = REPO_ROOT / "research" / "src"
if str(RESEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(RESEARCH_SRC))

from data_refresh.massive_orchestrator import MASSIVE_RAW_LANE_POLICIES  # noqa: E402

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
DEFAULT_STOCK_TRADES_BACKFILL_STATUS_PATH = (
    REPO_ROOT
    / "research"
    / "results"
    / "t137-massive-stock-trade-backfill"
    / "stock-trade-backfill-status.json"
)
DEFAULT_MASSIVE_LANE_MANIFEST_ROOT = (
    REPO_ROOT / "research" / "data" / "manifests" / "massive_lanes"
)
STOCK_TRADES_PROGRESS_FILENAME = "stock-trades-progress.json"
MASSIVE_LANE_IDS = tuple(policy.lane_id for policy in MASSIVE_RAW_LANE_POLICIES)
MASSIVE_LANE_LABELS = {
    policy.lane_id: policy.label for policy in MASSIVE_RAW_LANE_POLICIES
}
MASSIVE_LANE_FRESHNESS_SECONDS = {
    policy.lane_id: policy.freshness_requirement_seconds
    for policy in MASSIVE_RAW_LANE_POLICIES
}
MASSIVE_LANE_BLOCKS_EXECUTION = {
    policy.lane_id: policy.blocks_execution for policy in MASSIVE_RAW_LANE_POLICIES
}

COMPLETE_STATES = {"complete"}
ATTENTION_STATES = {"blocked", "failed"}
STALE_RUNNING_STATUS_SECONDS = int(os.environ.get("AGENCY_STALE_PROGRESS_SECONDS", "300"))


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
    stale_reason = ""
    total_jobs = _int_value(progress.get("total_jobs"), len(jobs))
    completed_jobs = _int_value(progress.get("completed_jobs"), _completed_jobs(jobs))
    percent = _int_value(progress.get("percent_complete"), _percent(completed_jobs, total_jobs))
    eta_value = eta_seconds(progress, jobs, state) or 0
    if state == "running":
        if _running_jobs_are_orphaned(jobs):
            state = "stale"
            stale_reason = (
                "Latest data refresh is marked running, but no matching worker process "
                "is active on this host."
            )
        elif _status_payload_stale(
            payload,
            status_path,
            eta_seconds_value=eta_value,
        ):
            state = "stale"
            stale_reason = (
                "Latest data refresh stopped sending progress; verify whether the worker is still running."
            )
        if state == "stale":
            eta_value = eta_seconds(progress, jobs, state) or 0
    eta_text = eta_label(eta_value, state)
    current_dataset = progress.get("current_dataset") or _current_dataset(jobs)
    updated_at = payload.get("updated_at")
    trade_pull = _trade_pull_status(payload, status_path)
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
        "detail": _detail(state, stale_reason=stale_reason),
        "status_path": _display_path(status_path),
        "is_loading": state == "running",
        "has_failures": payload.get("has_failures") is True,
        "failed_datasets": [str(d) for d in _sequence(payload.get("failed_datasets"))],
        "trade_pull": trade_pull,
        "massive_lanes": _massive_lane_progress_rows(status_path),
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
        "massive_lanes": _massive_lane_progress_rows(status_path),
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
    progress_path, progress = _selected_stock_trade_progress(status_path)
    job_status = str(job.get("status") or "")
    progress_state = str(progress.get("state") or "")
    backfill_status_path, backfill_progress = _running_stock_trade_backfill_progress(
        status_path
    )
    if backfill_progress and not progress:
        progress = {**progress, **backfill_progress}
        progress_path = backfill_status_path
        job_status = "running"
        progress_state = str(progress.get("state") or "")
    lane_id = str(progress.get("lane_id") or "massive_live_trade_slices")
    lane_manifest = (
        _json_mapping(_massive_lane_manifest_path(lane_id))
        if progress.get("lane_id") or progress_path.name.startswith("massive_")
        else {}
    )
    manifest = lane_manifest or _json_mapping(DEFAULT_STOCK_TRADES_MANIFEST_PATH)
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
    processed = _int_value(progress.get("ticker_days_processed"), completed)
    if state in {"complete", "ready", "skipped"} and total > 0:
        completed = total
        processed = total
    ticker_count = _int_value(
        progress.get("ticker_count"),
        _int_value(manifest.get("ticker_count"), 0),
    )
    manifest_ticker_count = _int_value(manifest.get("ticker_count"), 0)
    ticker_statuses = _sequence(progress.get("ticker_statuses"))
    pipeline_ready = _strings(progress.get("pipeline_ready_tickers"))
    pipeline_usable = _strings(progress.get("pipeline_usable_tickers"))
    if not pipeline_usable:
        pipeline_usable = list(pipeline_ready)
    pipeline_pending = _strings(progress.get("pipeline_pending_tickers"))
    pipeline_failed = _strings(progress.get("pipeline_failed_tickers"))
    pipeline_ready_count = _pipeline_count(
        progress.get("pipeline_ready_count"),
        fallback_count=len(pipeline_ready),
        state=state,
        total=ticker_count,
    )
    pipeline_usable_count = _pipeline_count(
        progress.get("pipeline_usable_count"),
        fallback_count=len(pipeline_usable),
        state=state,
        total=ticker_count,
    )
    latest_as_of = _timestamp_label(
        manifest.get("max_timestamp_as_of") or manifest.get("fetched_at")
    )
    return {
        "lane_id": lane_id,
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
        "ticker_days_processed": processed,
        "ticker_days_total": total,
        "ticker_progress_label": _ticker_progress_label(processed, total),
        "job_position_label": _job_position_label(job_index, job_total),
        "row_count": manifest_rows,
        "row_count_label": _count_label(manifest_rows),
        "ticker_count": ticker_count,
        "ticker_statuses": ticker_statuses,
        "pipeline_ready_tickers": pipeline_ready,
        "pipeline_usable_tickers": pipeline_usable,
        "pipeline_pending_tickers": pipeline_pending,
        "pipeline_failed_tickers": pipeline_failed,
        "pipeline_ready_count": pipeline_ready_count,
        "pipeline_usable_count": pipeline_usable_count,
        "pipeline_pending_count": _int_value(
            progress.get("pipeline_pending_count"),
            len(pipeline_pending),
        ),
        "pipeline_failed_count": _int_value(
            progress.get("pipeline_failed_count"),
            len(pipeline_failed),
        ),
        "pipeline_ready_label": _text_value(
            progress.get("pipeline_ready_label"),
            _pipeline_ready_label(pipeline_ready_count, ticker_count),
        ),
        "pipeline_usable_label": _text_value(
            progress.get("pipeline_usable_label"),
            _pipeline_usable_label(pipeline_usable_count, ticker_count),
        ),
        "coverage_scope_label": _trade_coverage_scope_label(
            manifest_ticker_count=manifest_ticker_count,
            latest_batch_ticker_count=ticker_count,
            pipeline_usable_count=pipeline_usable_count,
        ),
        "pipeline_detail": _text_value(
            progress.get("pipeline_detail"),
            _pipeline_detail(
                pipeline_usable_count,
                pipeline_ready_count,
                pipeline_pending,
                pipeline_failed,
            ),
        ),
        "latest_as_of": latest_as_of,
        "window_label": _stock_trade_window(config, manifest, progress),
        "guardrail_label": _stock_trade_guardrail(config, job),
        "detail": _trade_detail(
            state=state,
            job=job,
            progress=progress,
            manifest=manifest,
            completed=processed,
            total=total,
            pipeline_ready_count=pipeline_ready_count,
            pipeline_usable_count=pipeline_usable_count,
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


def _lane_progress_path(status_path: Path, lane_id: str) -> Path:
    return status_path.parent / f"{lane_id}-progress.json"


def _selected_stock_trade_progress(
    status_path: Path,
) -> tuple[Path, Mapping[str, object]]:
    candidates = [
        _lane_progress_path(status_path, "massive_live_trade_slices"),
        _lane_progress_path(status_path, "massive_premarket_trade_slices"),
        _stock_trade_progress_path(status_path),
    ]
    rows = [(path, _json_mapping(path)) for path in candidates]
    running = [
        (path, payload)
        for path, payload in rows
        if str(payload.get("state") or "").lower() == "running"
    ]
    if running:
        return max(running, key=lambda item: _path_mtime(item[0]))
    available = [(path, payload) for path, payload in rows if payload]
    if available:
        live_progress = [
            (path, payload)
            for path, payload in available
            if path.name.startswith("massive_live_trade_slices")
        ]
        if live_progress:
            return live_progress[0]
        return max(available, key=lambda item: _progress_timestamp(item[0], item[1]))
    live_manifest = _json_mapping(_massive_lane_manifest_path("massive_live_trade_slices"))
    if live_manifest:
        return candidates[0], {}
    return candidates[0], {}


def _running_stock_trade_backfill_progress(
    status_path: Path,
) -> tuple[Path, Mapping[str, object]]:
    backfill_path = DEFAULT_STOCK_TRADES_BACKFILL_STATUS_PATH
    if not _same_path(status_path, DEFAULT_STATUS_PATH):
        return backfill_path, {}
    payload = _json_mapping(backfill_path)
    if not payload:
        return backfill_path, {}
    if payload.get("finished_at") is not None:
        return backfill_path, {}
    current = _mapping(payload.get("current_progress"))
    if not current:
        return backfill_path, {}
    summary = _mapping(payload.get("summary"))
    plan = _mapping(payload.get("plan_summary"))
    planned_batches = _int_value(summary.get("planned_batch_count"), 0)
    completed_batches = _int_value(summary.get("completed_batch_count"), 0)
    total = _int_value(plan.get("expected_ticker_days"), 0)
    batch_size = max(1, (total + max(planned_batches, 1) - 1) // max(planned_batches, 1))
    processed = min(total, completed_batches * batch_size)
    percent = _percent(processed, total)
    state = "stale" if _status_file_stale(backfill_path) else "running"
    return backfill_path, {
        "state": state,
        "percent_complete": max(1, min(percent, 99)) if state == "running" else percent,
        "ticker_days_completed": processed,
        "ticker_days_processed": processed,
        "ticker_days_total": total,
        "current_ticker": _text_value(current.get("ticker"), "None"),
        "current_trade_date": _text_value(current.get("trade_date"), "not active"),
        "current_pages_downloaded": _int_value(current.get("pages_downloaded"), 0),
        "current_rows_downloaded": _int_value(current.get("rows_downloaded"), 0),
        "updated_at": _text_value(current.get("updated_at"), "not recorded"),
        "start": _text_value(plan.get("start"), ""),
        "end": _text_value(plan.get("end"), ""),
        "ticker_count": _int_value(plan.get("ticker_count"), 0),
        "pipeline_ready_count": _int_value(plan.get("covered_ticker_days"), 0),
        "pipeline_pending_count": max(
            0,
            _int_value(plan.get("missing_ticker_days"), 0)
            + _int_value(plan.get("partial_ticker_days"), 0),
        ),
        "pipeline_ready_tickers": [],
        "pipeline_usable_tickers": [],
        "pipeline_pending_tickers": [],
        "pipeline_failed_tickers": [],
        "ticker_statuses": [],
        "pipeline_ready_label": (
            f"{_int_value(plan.get('covered_ticker_days'), 0)}/"
            f"{_int_value(plan.get('ticker_count'), 0)} tickers ready"
        ),
        "pipeline_detail": (
            "Massive active-universe repair is running from the stock-trade backfill "
            f"queue: {completed_batches}/{planned_batches} batch(es) completed."
        ),
    }


def _massive_lane_progress_rows(status_path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current = datetime.now(UTC)
    for lane_id in MASSIVE_LANE_IDS:
        progress_path = _lane_progress_path(status_path, lane_id)
        progress = _json_mapping(progress_path)
        if lane_id == "massive_live_trade_slices" and not progress:
            legacy_progress = _json_mapping(_stock_trade_progress_path(status_path))
            if legacy_progress and not legacy_progress.get("lane_id"):
                progress = legacy_progress
                progress_path = _stock_trade_progress_path(status_path)
        if lane_id == "massive_backtest_trade_tape":
            backfill_path, backfill_progress = _running_stock_trade_backfill_progress(status_path)
            if backfill_progress:
                progress = dict(backfill_progress)
                progress["lane_id"] = lane_id
                progress_path = backfill_path
        manifest_path = _massive_lane_manifest_path(lane_id)
        manifest = _json_mapping(manifest_path)
        if (
            str(progress.get("state") or "").lower() == "running"
            and _status_file_stale(progress_path)
        ):
            progress = dict(progress)
            progress["state"] = "stale"
        state = _massive_lane_state(lane_id, progress, manifest, now=current)
        percent = _massive_lane_percent(state, progress, manifest)
        lane_eta_seconds = _massive_lane_eta_seconds(state, progress)
        detail = _massive_lane_detail(
            lane_id,
            state,
            progress,
            manifest,
            now=current,
        )
        rows.append(
            {
                "lane_id": lane_id,
                "label": MASSIVE_LANE_LABELS.get(lane_id, lane_id.replace("_", " ").title()),
                "state": state,
                "status_label": _massive_lane_status_label(state),
                "status_class": _massive_lane_status_class(state),
                "percent_complete": percent,
                "eta_seconds": lane_eta_seconds,
                "eta_label": _massive_lane_eta_label(state, lane_eta_seconds),
                "progress_label": _massive_lane_progress_label(progress, manifest),
                "ticker_count": _int_value(
                    progress.get("ticker_count"),
                    _int_value(manifest.get("ticker_count"), 0),
                ),
                "row_count": _int_value(manifest.get("row_count"), 0),
                "row_count_label": _count_label(_int_value(manifest.get("row_count"), 0)),
                "manifest_status": _text_value(manifest.get("status"), "missing"),
                "manifest_coverage_pct": _int_value(manifest.get("coverage_pct"), 0),
                "issue_count": _int_value(manifest.get("issue_count"), 0),
                "issues": _massive_lane_issues(progress, manifest),
                "updated_at": _text_value(
                    progress.get("updated_at"),
                    _text_value(manifest.get("fetched_at"), "not recorded"),
                ),
                "latest_as_of": _timestamp_label(manifest.get("fetched_at")),
                "window_label": _lane_window_label(manifest, progress),
                "detail": detail,
                "reason": detail,
                "reason_code": _massive_lane_reason_code(state),
                "required_now": MASSIVE_LANE_BLOCKS_EXECUTION.get(lane_id, False),
                "next_due_at": _massive_lane_next_due_at(lane_id, state, progress, manifest),
                "analysis_state": _massive_lane_analysis_state(state),
                "progress_path": _display_path(progress_path),
                "manifest_path": _display_path(manifest_path),
            }
        )
    return rows


def _massive_lane_manifest_path(lane_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in lane_id)
    return DEFAULT_MASSIVE_LANE_MANIFEST_ROOT / f"{safe.strip('_') or 'unknown'}.json"


def _massive_lane_state(
    lane_id: str,
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> str:
    progress_state = str(progress.get("state") or "").lower()
    if progress_state in {"running", "failed", "blocked", "partial", "partial_usable", "stale"}:
        return progress_state
    manifest_status = _massive_lane_effective_manifest_status(manifest)
    if manifest_status in {"complete", "partial", "partial_usable", "failed", "blocked"}:
        if manifest_status in {"complete", "partial", "partial_usable"} and _massive_lane_manifest_stale(
            lane_id,
            manifest,
            now=now,
        ):
            return "stale"
        return "ready" if manifest_status == "complete" else manifest_status
    return "missing_manifest"


def _massive_lane_percent(
    state: str,
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
) -> int:
    if state == "running":
        return max(1, min(_int_value(progress.get("percent_complete"), 0), 99))
    if progress.get("percent_complete") is not None:
        return max(0, min(_int_value(progress.get("percent_complete"), 0), 100))
    if state == "ready":
        return 100
    return max(0, min(_int_value(manifest.get("coverage_pct"), 0), 100))


def _massive_lane_status_label(state: str) -> str:
    labels = {
        "idle": "No Lane Pull",
        "missing_manifest": "Manifest Missing",
        "ready": "Lane Ready",
        "running": "Lane Running",
        "partial": "Lane Partial",
        "partial_usable": "Usable Partial",
        "failed": "Lane Failed",
        "blocked": "Lane Blocked",
        "stale": "Refresh Needed",
    }
    return labels.get(state, state.replace("_", " ").title())


def _massive_lane_status_class(state: str) -> str:
    if state == "ready":
        return "pass"
    if state == "missing_manifest":
        return "warn"
    if state in {"running", "partial", "partial_usable", "idle"}:
        return "warn" if state != "idle" else "neutral"
    if state in {"failed", "blocked", "stale"}:
        return "block"
    return "neutral"


def _massive_lane_progress_label(
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
) -> str:
    total = _int_value(progress.get("ticker_days_total"), 0)
    processed = _int_value(progress.get("ticker_days_processed"), 0)
    if total:
        return _ticker_progress_label(processed, total)
    coverage = _int_value(manifest.get("coverage_pct"), 0)
    if manifest:
        return f"{coverage}% manifest coverage"
    return "not tracked"


def _massive_lane_eta_seconds(
    state: str,
    progress: Mapping[str, object],
) -> int | None:
    value = progress.get("eta_seconds")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(value, 0)
    if state != "running":
        return None
    total = _int_value(progress.get("ticker_days_total"), 0)
    processed = _int_value(progress.get("ticker_days_processed"), 0)
    if total <= 0:
        return None
    remaining = max(total - processed, 0)
    return remaining * 30


def _massive_lane_eta_label(state: str, value: int | None) -> str:
    if state == "ready":
        return "complete"
    return eta_label(value, "running" if state == "running" else state)


def _massive_lane_issues(
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for source in (manifest.get("issues"), progress.get("issues")):
        for issue in _sequence(source):
            if isinstance(issue, Mapping):
                issues.append(dict(issue))
    return issues


def _massive_lane_reason_code(state: str) -> str:
    return {
        "missing_manifest": "manifest_missing",
        "ready": "ready",
        "running": "running",
        "partial": "partial_coverage",
        "partial_usable": "partial_usable_coverage",
        "failed": "failed",
        "blocked": "blocked",
        "stale": "refresh_needed",
    }.get(state, state)


def _massive_lane_next_due_at(
    lane_id: str,
    state: str,
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
) -> str:
    if state == "running":
        return ""
    explicit = _text_value(progress.get("next_due_at"), _text_value(manifest.get("next_due_at"), ""))
    if explicit:
        return explicit
    freshness_seconds = MASSIVE_LANE_FRESHNESS_SECONDS.get(lane_id)
    fetched_at = _parse_datetime(manifest.get("fetched_at"))
    if freshness_seconds is None or fetched_at is None:
        return ""
    return (fetched_at + timedelta(seconds=freshness_seconds)).isoformat()


def _massive_lane_analysis_state(state: str) -> str:
    if state == "missing_manifest":
        return "data_void"
    if state in {"failed", "blocked"}:
        return "data_void"
    if state == "running":
        return "loading"
    if state == "ready":
        return "analyzed_current"
    if state in {"partial", "partial_usable", "stale"}:
        return "analyzed_needs_refresh"
    return "loaded_unanalyzed"


def _massive_lane_detail(
    lane_id: str,
    state: str,
    progress: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> str:
    if state == "running":
        ticker = _text_value(progress.get("current_ticker"), "current ticker")
        trade_date = _text_value(progress.get("current_trade_date"), "current date")
        return f"{MASSIVE_LANE_LABELS.get(lane_id, lane_id)} is running on {ticker} for {trade_date}."
    if state == "stale" and manifest:
        age = _massive_lane_manifest_age_seconds(manifest, now=now)
        required = MASSIVE_LANE_FRESHNESS_SECONDS.get(lane_id)
        if age is not None and required is not None:
            return (
                f"{MASSIVE_LANE_LABELS.get(lane_id, lane_id)} needs refresh: "
                f"latest proof is {age}s old, beyond the {required}s freshness SLA."
            )
        return f"{MASSIVE_LANE_LABELS.get(lane_id, lane_id)} needs refresh before execution use."
    if manifest:
        status = _massive_lane_effective_manifest_status(manifest) or _text_value(manifest.get("status"), state)
        coverage = _int_value(manifest.get("coverage_pct"), 0)
        issues = _int_value(manifest.get("issue_count"), 0)
        coverage_note = ""
        if status != str(manifest.get("status") or "").lower():
            coverage_note = " Effective status was downgraded by incomplete coverage rows."
        return (
            f"{MASSIVE_LANE_LABELS.get(lane_id, lane_id)} manifest reports "
            f"{status} with {coverage}% coverage and {issues} issue(s)."
            f"{coverage_note}"
        )
    manifest_path = _display_path(_massive_lane_manifest_path(lane_id))
    return (
        f"{MASSIVE_LANE_LABELS.get(lane_id, lane_id)} has no lane manifest yet "
        f"at {manifest_path}; lane health is not verified."
    )


def _massive_lane_manifest_stale(
    lane_id: str,
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> bool:
    required = MASSIVE_LANE_FRESHNESS_SECONDS.get(lane_id)
    if required is None or required <= 0:
        return False
    age = _massive_lane_manifest_age_seconds(manifest, now=now)
    if age is None:
        return True
    if age > required and _closed_market_manifest_current(lane_id, manifest, now=now):
        return False
    return age is not None and age > required


def _closed_market_manifest_current(
    lane_id: str,
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> bool:
    if lane_id not in {
        "massive_daily_bars",
        "massive_live_trade_slices",
        "massive_premarket_trade_slices",
        "massive_block_trade_feed",
        "massive_options_flow",
    }:
        return False
    try:
        from data_refresh.market_calendar import (
            classify_market_session,
            previous_trading_day,
        )
    except ModuleNotFoundError:
        return False
    session = classify_market_session(now)
    if session.is_open_for_extended:
        return False
    if session.is_trading_day:
        latest_completed = (
            previous_trading_day(session.market_date)
            if session.phase in {"overnight_before_pre_market", "pre_market", "regular_market"}
            else session.market_date
        )
    else:
        latest_completed = previous_trading_day(session.market_date)
    window = _mapping(manifest.get("window"))
    manifest_date = _parse_date(window.get("end")) or _parse_date(manifest.get("fetched_at"))
    return manifest_date is not None and manifest_date >= latest_completed


def _massive_lane_manifest_age_seconds(
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> int | None:
    fetched_at = _parse_datetime(manifest.get("fetched_at"))
    if fetched_at is None:
        return None
    return int((now - fetched_at).total_seconds())


def _massive_lane_effective_manifest_status(manifest: Mapping[str, object]) -> str:
    status = str(manifest.get("status") or "").lower()
    if status != "complete":
        return status
    if _massive_lane_manifest_has_incomplete_coverage(manifest):
        return "partial_usable" if _massive_lane_manifest_has_usable_rows(manifest) else "partial"
    return status


def _massive_lane_manifest_has_incomplete_coverage(manifest: Mapping[str, object]) -> bool:
    complete_pct = manifest.get("complete_coverage_pct")
    if isinstance(complete_pct, int | float) and complete_pct < 100:
        return True
    coverage = manifest.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        return False
    return any(
        not isinstance(row, Mapping)
        or str(row.get("coverage_status") or row.get("status") or "").lower() != "complete"
        or row.get("complete") is False
        or row.get("row_count_verified") is False
        for row in coverage
    )


def _massive_lane_manifest_has_usable_rows(manifest: Mapping[str, object]) -> bool:
    if _int_value(manifest.get("usable_coverage_pct"), 0) > 0:
        return True
    if _int_value(manifest.get("coverage_pct"), 0) > 0:
        return True
    return _int_value(manifest.get("row_count"), 0) > 0


def _lane_window_label(
    manifest: Mapping[str, object],
    progress: Mapping[str, object],
) -> str:
    window = _mapping(manifest.get("window"))
    start = _text_value(window.get("start"), _text_value(progress.get("start"), ""))
    end = _text_value(window.get("end"), _text_value(progress.get("end"), ""))
    if start and end:
        return start if start == end else f"{start} to {end}"
    return "not recorded"


def _json_mapping(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _progress_timestamp(path: Path, progress: Mapping[str, object]) -> float:
    parsed = _parse_datetime(progress.get("updated_at"))
    if parsed is not None:
        return parsed.timestamp()
    return _path_mtime(path)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


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
    if not has_stock_trade_job and manifest:
        if _manifest_covers_stock_trade_request(config, manifest):
            return "ready"
        return "unverified"
    if progress_state in {"blocked", "failed", "partial", "stale"}:
        return progress_state
    if job_status in {"pending", "passed", "failed", "blocked", "skipped", "planned"}:
        return "complete" if job_status == "passed" else job_status
    if progress_state:
        if progress_state == "running" and _status_file_stale(progress_path):
            return "stale"
        return progress_state
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
        "stale": "Needs Refresh",
    }
    return labels.get(state, state.replace("_", " ").title())


def _trade_status_class(state: str) -> str:
    if state in {"ready", "complete", "skipped"}:
        return "pass"
    if state in {"running", "pending", "planned", "partial", "unverified"}:
        return "warn"
    if state in {"blocked", "failed", "stale"}:
        return "block"
    return "neutral"


def _stock_trade_window(
    config: Mapping[str, object],
    manifest: Mapping[str, object],
    progress: Mapping[str, object],
) -> str:
    prefer_progress = bool(progress.get("lane_id") or progress.get("start") or progress.get("end"))
    start = _text_value(progress.get("start"), "") if prefer_progress else ""
    end = _text_value(progress.get("end"), "") if prefer_progress else ""
    if not start:
        start = _text_value(config.get("stock_trades_start"), "")
    if not end:
        end = _text_value(config.get("stock_trades_end"), "")
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
    pipeline_ready_count: int,
    pipeline_usable_count: int,
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
            f"{pipeline_usable_count} ticker(s) can pass forward to live analysis; "
            f"{pipeline_ready_count} are requested-window ready; "
            f"{partial} partial ticker-day(s), "
            f"{failed} failed ticker-day(s) remain for repair."
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
    latest = _timestamp_label(manifest.get("max_timestamp_as_of") or manifest.get("fetched_at"))
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
    date_range = _mapping(manifest.get("date_range")) or _mapping(manifest.get("window"))
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


def _parse_datetime(value: object) -> datetime | None:
    text = _text_value(value, "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def _pipeline_count(
    value: object,
    *,
    fallback_count: int,
    state: str,
    total: int,
) -> int:
    parsed = _int_value(value, fallback_count)
    if value is None and parsed == 0 and state in {"ready", "complete", "skipped"} and total > 0:
        return total
    return parsed


def _pipeline_ready_label(ready_count: int, ticker_count: int) -> str:
    total = ticker_count if ticker_count > 0 else ready_count
    return f"{ready_count}/{total} tickers ready"


def _pipeline_usable_label(usable_count: int, ticker_count: int) -> str:
    total = ticker_count if ticker_count > 0 else usable_count
    return f"{usable_count}/{total} tickers usable"


def _trade_coverage_scope_label(
    *,
    manifest_ticker_count: int,
    latest_batch_ticker_count: int,
    pipeline_usable_count: int,
) -> str:
    if manifest_ticker_count > latest_batch_ticker_count > 0:
        return (
            f"{manifest_ticker_count} stored tickers; latest batch "
            f"{pipeline_usable_count}/{latest_batch_ticker_count} usable"
        )
    if latest_batch_ticker_count > 0:
        return _pipeline_usable_label(pipeline_usable_count, latest_batch_ticker_count)
    if manifest_ticker_count > 0:
        return f"{manifest_ticker_count} stored tickers"
    return "not tracked"


def _pipeline_detail(
    usable_count: int,
    ready_count: int,
    pending: Sequence[str],
    failed: Sequence[str],
) -> str:
    return (
        f"{usable_count} ticker(s) can pass forward now; "
        f"{ready_count} have complete requested-window coverage; "
        f"{len(pending)} still extracting; {len(failed)} failed."
    )


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
        "stale": "Needs Restart",
        "unavailable": "Unavailable",
    }
    return labels.get(state, state.replace("_", " ").title())


def _status_class(state: str) -> str:
    if state in COMPLETE_STATES:
        return "pass"
    if state == "running":
        return "warn"
    if state in {"planned", "stale"}:
        return "block"
    if state in ATTENTION_STATES:
        return "block"
    return "neutral"


def _detail(state: str, *, stale_reason: str = "") -> str:
    details = {
        "running": "Data refresh is loading source datasets.",
        "complete": "Latest data refresh completed.",
        "planned": "Latest data refresh was a dry run.",
        "blocked": "Latest data refresh is blocked by missing inputs.",
        "failed": "Latest data refresh failed before all datasets loaded.",
        "stale": (
            "Latest data refresh stopped sending progress; verify whether the worker is still running."
        ),
    }
    if state == "stale" and stale_reason:
        return stale_reason
    return details.get(state, "No data refresh is running.")


def _running_jobs_are_orphaned(jobs: Sequence[object]) -> bool:
    running_commands = [
        _sequence(_mapping(job).get("command"))
        for job in jobs
        if str(_mapping(job).get("status")) == "running"
        and _sequence(_mapping(job).get("command"))
    ]
    if not running_commands:
        return False
    process_lines = tuple(_active_process_command_lines())
    if not process_lines:
        return False
    return not any(
        _command_has_live_process(command, process_lines)
        for command in running_commands
    )


def _command_has_live_process(
    command: Sequence[object],
    process_lines: Sequence[str],
) -> bool:
    needles = _command_needles(command)
    if not needles:
        return True
    return any(
        all(needle in _normalise_process_text(line) for needle in needles)
        for line in process_lines
    )


def _command_needles(command: Sequence[object]) -> tuple[str, ...]:
    for token in command:
        text = _normalise_process_text(str(token))
        if text.endswith(".py"):
            return (text.rsplit("/", maxsplit=1)[-1],)
    return ()


def _normalise_process_text(value: str) -> str:
    return value.replace("\\", "/").lower()


def _active_process_command_lines() -> tuple[str, ...]:
    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine } | "
                "Select-Object -ExpandProperty CommandLine"
            ),
        ]
    else:
        command = ["ps", "-eo", "command="]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0:
        return ()
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _status_file_stale(status_path: Path) -> bool:
    try:
        modified_at = datetime.fromtimestamp(status_path.stat().st_mtime, tz=UTC)
    except OSError:
        return False
    return (datetime.now(UTC) - modified_at).total_seconds() > STALE_RUNNING_STATUS_SECONDS


def _status_payload_stale(
    payload: Mapping[str, object],
    status_path: Path,
    *,
    eta_seconds_value: int,
) -> bool:
    updated_at = _parse_datetime(payload.get("updated_at"))
    modified_at: datetime | None = None
    try:
        modified_at = datetime.fromtimestamp(status_path.stat().st_mtime, tz=UTC)
    except OSError:
        modified_at = None
    if updated_at is None:
        if modified_at is None:
            return False
        updated_at = modified_at
    elif modified_at is not None and modified_at > updated_at:
        updated_at = modified_at
    age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    dynamic_threshold = max(5 * 60, eta_seconds_value * 4 + 60)
    return age_seconds > dynamic_threshold


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item).upper() for item in _sequence(value) if str(item).strip()]


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
