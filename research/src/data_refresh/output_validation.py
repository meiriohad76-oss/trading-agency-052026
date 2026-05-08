from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_live_refresh_outputs(
    *,
    status_path: Path,
    manifest_root: Path,
    datasets: tuple[str, ...] = (),
) -> dict[str, int]:
    """Validate that live refresh status and manifests are healthy."""
    status = _json_object(status_path)
    if status.get("blocked") is True:
        raise RuntimeError("live refresh status is blocked")
    if status.get("failed") is True:
        raise RuntimeError("live refresh status failed")
    expected = datasets or _status_datasets(status)
    _validate_jobs(status, expected)
    return {
        dataset: _validated_manifest_rows(manifest_root / f"{dataset}.json")
        for dataset in expected
    }


def _validate_jobs(status: dict[str, Any], datasets: tuple[str, ...]) -> None:
    jobs = status.get("jobs")
    if not isinstance(jobs, list):
        raise TypeError("status jobs must be a list")
    jobs_by_dataset = {
        str(job.get("dataset")): job for job in jobs if isinstance(job, dict)
    }
    for dataset in datasets:
        job = jobs_by_dataset.get(dataset)
        if job is None:
            raise RuntimeError(f"missing status job for {dataset}")
        if job.get("status") != "passed":
            raise RuntimeError(f"{dataset} did not pass: {job.get('status')}")


def _validated_manifest_rows(path: Path) -> int:
    manifest = _json_object(path)
    row_count = manifest.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int):
        raise TypeError(f"{path.name} row_count must be an integer")
    if row_count <= 0:
        raise RuntimeError(f"{path.name} row_count must be positive")
    issues = manifest.get("issues", [])
    if not isinstance(issues, list):
        raise TypeError(f"{path.name} issues must be a list")
    if issues:
        raise RuntimeError(f"{path.name} has {len(issues)} issue(s)")
    return row_count


def _status_datasets(status: dict[str, Any]) -> tuple[str, ...]:
    config = status.get("config")
    if not isinstance(config, dict):
        raise TypeError("status config must be an object")
    datasets = config.get("datasets")
    if not isinstance(datasets, list) or not all(isinstance(item, str) for item in datasets):
        raise TypeError("status config datasets must be a list of strings")
    return tuple(datasets)


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload
