from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_refresh.output_validation import validate_live_refresh_outputs


def test_validate_live_refresh_outputs_returns_manifest_row_counts(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    manifest_root = tmp_path / "manifests"
    _write_status(status_path, datasets=["prices_daily"])
    _write_manifest(manifest_root / "prices_daily.json", row_count=10, issues=[])

    rows = validate_live_refresh_outputs(
        status_path=status_path,
        manifest_root=manifest_root,
    )

    assert rows == {"prices_daily": 10}


def test_validate_live_refresh_outputs_rejects_manifest_issues(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    manifest_root = tmp_path / "manifests"
    _write_status(status_path, datasets=["sec_13f"])
    _write_manifest(
        manifest_root / "sec_13f.json",
        row_count=1,
        issues=[{"reason": "missing table"}],
    )

    with pytest.raises(RuntimeError, match="issue"):
        validate_live_refresh_outputs(status_path=status_path, manifest_root=manifest_root)


def _write_status(path: Path, *, datasets: list[str]) -> None:
    jobs = [{"dataset": dataset, "status": "passed"} for dataset in datasets]
    path.write_text(
        json.dumps(
            {
                "blocked": False,
                "failed": False,
                "config": {"datasets": datasets},
                "jobs": jobs,
            }
        ),
        encoding="utf-8",
    )


def _write_manifest(path: Path, *, row_count: int, issues: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"dataset": path.stem, "row_count": row_count, "issues": issues}),
        encoding="utf-8",
    )
