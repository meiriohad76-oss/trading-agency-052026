from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_refresh.output_validation import validate_live_refresh_outputs


def write_live_refresh_summary(
    *,
    status_path: Path,
    manifest_root: Path,
    output_root: Path,
    datasets: tuple[str, ...] = (),
) -> dict[str, Any]:
    summary = build_live_refresh_summary(
        status_path=status_path,
        manifest_root=manifest_root,
        datasets=datasets,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "live-refresh-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "live-refresh-summary.md").write_text(
        summary_to_markdown(summary),
        encoding="utf-8",
    )
    return summary


def build_live_refresh_summary(
    *,
    status_path: Path,
    manifest_root: Path,
    datasets: tuple[str, ...] = (),
) -> dict[str, Any]:
    row_counts = validate_live_refresh_outputs(
        status_path=status_path,
        manifest_root=manifest_root,
        datasets=datasets,
    )
    status = _json_object(status_path)
    config = _dict_field(status, "config")
    selected = tuple(row_counts)
    return {
        "source_status": _display_path(status_path),
        "window": {"start": config["start"], "end": config["end"]},
        "datasets": [_manifest_summary(manifest_root / f"{dataset}.json") for dataset in selected],
        "jobs": [
            {
                "dataset": str(job["dataset"]),
                "status": str(job["status"]),
                "reason": str(job["reason"]),
            }
            for job in _job_dicts(status)
            if str(job["dataset"]) in selected
        ],
        "input_counts": {
            "ticker_count": len(_list_field(config, "tickers")),
            "rss_feed_count": int(config["rss_feed_count"]),
            "filer_cik_count": len(_list_field(config, "filer_ciks")),
        },
        "verdict": "ready_for_research_batch",
    }


def summary_to_markdown(summary: dict[str, Any]) -> str:
    datasets = _list_field(summary, "datasets")
    window = _dict_field(summary, "window")
    lines = [
        "# T72 Live Refresh Summary",
        "",
        f"Source status: `{summary['source_status']}`",
        f"Window: {window['start']} to {window['end']}",
        f"Verdict: `{summary['verdict']}`",
        "",
        "| Dataset | Rows | Issues | Max as-of |",
        "| --- | ---: | ---: | --- |",
    ]
    for dataset in datasets:
        item = _dict_value(dataset)
        lines.append(
            f"| {item['dataset']} | {item['row_count']} | "
            f"{item['issue_count']} | {item['max_timestamp_as_of']} |"
        )
    return "\n".join(lines) + "\n"


def _manifest_summary(path: Path) -> dict[str, Any]:
    manifest = _json_object(path)
    issues = manifest.get("issues", [])
    return {
        "dataset": manifest["dataset"],
        "row_count": manifest["row_count"],
        "issue_count": len(issues) if isinstance(issues, list) else 0,
        "max_timestamp_as_of": manifest["max_timestamp_as_of"],
        "checksum": manifest["checksum"],
        "source_url": manifest.get("source_url"),
    }


def _job_dicts(status: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = status.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise TypeError("status jobs must be a list of objects")
    return jobs


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    return value


def _dict_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("summary dataset items must be objects")
    return value


def _list_field(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _display_path(path: Path) -> str:
    return path.as_posix()
