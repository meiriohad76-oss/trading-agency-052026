from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_refresh.types import RefreshBatchResult, RefreshJobResult

COMPLETE_STATUSES = {"planned", "passed", "failed", "blocked", "skipped"}
IN_PROGRESS_STATUSES = {"pending", "running"}
SECONDS_PER_MINUTE = 60
ESTIMATED_JOB_SECONDS = {
    "prices_daily": 90.0,
    "sec_company_facts": 60.0,
    "sec_form4": 600.0,
    "sec_13f": 90.0,
    "news_rss": 20.0,
    "subscription_emails": 15.0,
    "stock_trades": 180.0,
    "options_chains": 60.0,
    "unusual_activity_alerts": 10.0,
}


def write_status_files(result: RefreshBatchResult, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "data-refresh-status.json").write_text(
        result_to_json(result),
        encoding="utf-8",
    )
    (output_root / "data-refresh-status.md").write_text(
        result_to_markdown(result),
        encoding="utf-8",
    )


def result_to_markdown(result: RefreshBatchResult) -> str:
    progress = result_progress(result)
    lines = [
        "# Data Refresh Batch Status",
        "",
        f"Window: {result.config.start.isoformat()} to {result.config.end.isoformat()}",
        f"Mode: {'dry-run' if result.config.dry_run else 'execute'}",
        f"Extraction mode: {result.config.extraction_mode}",
        *_stock_trade_guardrail_lines(result),
        f"Progress: {progress['percent_complete']}%",
        f"ETA: {progress['eta_label']}",
        "",
        "| Dataset | Status | Reason |",
        "| --- | --- | --- |",
        *[f"| {job.dataset} | {job.status} | {job.reason} |" for job in result.jobs],
        "",
        "## Commands",
        "",
    ]
    for job in result.jobs:
        lines.extend([f"### {job.dataset}", "", f"`{_command_text(job.command)}`", ""])
    return "\n".join(lines).rstrip() + "\n"


def result_to_json(result: RefreshBatchResult) -> str:
    payload = {
        "config": {
            "start": result.config.start.isoformat(),
            "end": result.config.end.isoformat(),
            "datasets": list(result.config.datasets),
            "tickers": list(result.config.tickers),
            "rss_feed_count": len(result.config.rss_feeds),
            "filer_ciks": list(result.config.filer_ciks),
            "cusip_map": _optional_path(result),
            "activity_alerts_csv": _optional_activity_alerts_path(result),
            "subscription_email_config": _optional_subscription_email_path(result),
            "workers": result.config.workers,
            "include_etfs": result.config.include_etfs,
            "refresh": result.config.refresh,
            "dry_run": result.config.dry_run,
            "market_data_provider": result.config.market_data_provider,
            "market_data_feed": result.config.market_data_feed,
            "market_data_adjustment": result.config.market_data_adjustment,
            "market_data_base_url": result.config.market_data_base_url,
            "market_data_credentials_present": result.config.market_data_credentials_present,
            "massive_base_url": result.config.massive_base_url,
            "massive_credentials_present": result.config.massive_credentials_present,
            "stock_trades_start": (
                None
                if result.config.stock_trades_start is None
                else result.config.stock_trades_start.isoformat()
            ),
            "stock_trades_end": (
                None
                if result.config.stock_trades_end is None
                else result.config.stock_trades_end.isoformat()
            ),
            "stock_trades_limit": result.config.stock_trades_limit,
            "stock_trades_max_pages_per_day": result.config.stock_trades_max_pages_per_day,
            "stock_trades_order": result.config.stock_trades_order,
            "extraction_mode": result.config.extraction_mode,
            "sec_company_facts_max_age_days": (
                result.config.sec_company_facts_max_age_days
            ),
            "sec_form4_max_age_days": result.config.sec_form4_max_age_days,
            "sec_13f_max_age_days": result.config.sec_13f_max_age_days,
            "news_rss_max_age_minutes": result.config.news_rss_max_age_minutes,
            "subscription_email_max_age_minutes": (
                result.config.subscription_email_max_age_minutes
            ),
        },
        "jobs": [asdict(job) for job in result.jobs],
        "progress": result_progress(result),
        "started_at": result.started_at,
        "updated_at": result.updated_at,
        "blocked": result.blocked,
        "failed": result.failed,
        "has_failures": result.failed,
        "failed_datasets": [job.dataset for job in result.jobs if job.status == "failed"],
        "in_progress": result.in_progress,
        "written_paths": list(result.written_paths),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def result_progress(result: RefreshBatchResult) -> dict[str, object]:
    total = len(result.jobs)
    completed = sum(1 for job in result.jobs if job.status in COMPLETE_STATUSES)
    running = sum(1 for job in result.jobs if job.status == "running")
    pending = sum(1 for job in result.jobs if job.status == "pending")
    eta_seconds = _eta_seconds(result.jobs, result.updated_at)
    state = _state(result)
    return {
        "state": state,
        "total_jobs": total,
        "completed_jobs": completed,
        "running_jobs": running,
        "pending_jobs": pending,
        "percent_complete": _percent(completed, total),
        "current_dataset": _current_dataset(result.jobs),
        "eta_seconds": eta_seconds,
        "eta_label": _eta_label(eta_seconds, state),
    }


def _command_text(command: tuple[str, ...]) -> str:
    return " ".join(command)


def _stock_trade_guardrail_lines(result: RefreshBatchResult) -> list[str]:
    if "stock_trades" not in result.config.datasets:
        return []
    pages = result.config.stock_trades_max_pages_per_day
    page_text = "unbounded" if pages is None else str(pages)
    return [
        (
            "Stock-trades coverage: "
            f"page size {result.config.stock_trades_limit}; "
            f"max pages/day {page_text}; order {result.config.stock_trades_order}"
        )
    ]


def _state(result: RefreshBatchResult) -> str:
    if result.failed:
        return "failed"
    if result.blocked:
        return "blocked"
    if result.in_progress:
        return "running"
    if all(job.status == "planned" for job in result.jobs):
        return "planned"
    return "complete"


def _percent(completed: int, total: int) -> int:
    if total == 0:
        return 100
    return round(completed / total * 100)


def _current_dataset(jobs: tuple[RefreshJobResult, ...]) -> str | None:
    for status in ("running", "pending"):
        for job in jobs:
            if job.status == status:
                return job.dataset
    return None


def _eta_seconds(jobs: tuple[RefreshJobResult, ...], updated_at: str | None) -> int | None:
    if not any(job.status in IN_PROGRESS_STATUSES for job in jobs):
        return 0
    updated = _parse_time(updated_at)
    completed_durations = [
        job.duration_seconds
        for job in jobs
        if job.status == "passed" and job.duration_seconds is not None and job.duration_seconds > 0
    ]
    fallback = sum(completed_durations) / len(completed_durations) if completed_durations else None
    remaining = 0.0
    for job in jobs:
        if job.status == "pending":
            remaining += _job_estimate(job.dataset, fallback)
        elif job.status == "running":
            estimate = _job_estimate(job.dataset, fallback)
            elapsed = _running_elapsed_seconds(job, updated)
            remaining += max(estimate - elapsed, 5.0)
    return round(remaining)


def _job_estimate(dataset: str, fallback: float | None) -> float:
    baseline = ESTIMATED_JOB_SECONDS.get(dataset, 60.0)
    if fallback is None:
        return baseline
    return max(baseline, fallback)


def _running_elapsed_seconds(job: RefreshJobResult, updated_at: datetime | None) -> float:
    if updated_at is None or job.started_at is None:
        return 0.0
    started_at = _parse_time(job.started_at)
    if started_at is None:
        return 0.0
    return max((updated_at - started_at).total_seconds(), 0.0)


def _eta_label(eta_seconds: int | None, state: str) -> str:
    if state in {"complete", "planned"}:
        return "complete"
    if state in {"failed", "blocked"}:
        return "not available"
    if eta_seconds is None:
        return "calculating"
    if eta_seconds < SECONDS_PER_MINUTE:
        return f"{eta_seconds}s"
    minutes = round(eta_seconds / SECONDS_PER_MINUTE)
    return f"{minutes}m"


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_path(result: RefreshBatchResult) -> str | None:
    if result.config.cusip_map is None:
        return None
    path = result.config.cusip_map
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve(strict=False).relative_to(
            result.config.repo_root.resolve(strict=False)
        ).as_posix()
    except ValueError:
        return path.as_posix()


def _optional_activity_alerts_path(result: RefreshBatchResult) -> str | None:
    if result.config.activity_alerts_csv is None:
        return None
    return _portable_path(result.config.activity_alerts_csv, result.config.repo_root)


def _optional_subscription_email_path(result: RefreshBatchResult) -> str | None:
    if result.config.subscription_email_config is None:
        return None
    return _portable_path(result.config.subscription_email_config, result.config.repo_root)


def _portable_path(path: Path, repo_root: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()
