from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_refresh.types import RefreshBatchResult


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
    lines = [
        "# Data Refresh Batch Status",
        "",
        f"Window: {result.config.start.isoformat()} to {result.config.end.isoformat()}",
        f"Mode: {'dry-run' if result.config.dry_run else 'execute'}",
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
            "workers": result.config.workers,
            "include_etfs": result.config.include_etfs,
            "refresh": result.config.refresh,
            "dry_run": result.config.dry_run,
            "market_data_provider": result.config.market_data_provider,
            "market_data_feed": result.config.market_data_feed,
            "market_data_adjustment": result.config.market_data_adjustment,
            "market_data_base_url": result.config.market_data_base_url,
            "market_data_credentials_present": result.config.market_data_credentials_present,
        },
        "jobs": [asdict(job) for job in result.jobs],
        "blocked": result.blocked,
        "failed": result.failed,
        "written_paths": list(result.written_paths),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _command_text(command: tuple[str, ...]) -> str:
    return " ".join(command)


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


def _portable_path(path: Path, repo_root: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()
