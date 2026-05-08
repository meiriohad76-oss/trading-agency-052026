from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agency.app import create_app
from agency.runtime.data_refresh_progress import load_data_refresh_progress

HTTP_OK = 200
EXPECTED_PERCENT = 40
COMPLETE_PERCENT = 100
EXPECTED_COMPLETED_JOBS = 2
EXPECTED_ETA_SECONDS = 180
MAX_PRICE_ETA_SECONDS = 90
MIN_FORM4_ETA_SECONDS = 500
RUNNING_ELAPSED_SECONDS = 30


def test_load_data_refresh_progress_reports_running_eta(tmp_path: Path) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-05-08T12:00:10+00:00",
                "progress": {
                    "state": "running",
                    "total_jobs": 5,
                    "completed_jobs": 2,
                    "percent_complete": EXPECTED_PERCENT,
                    "current_dataset": "sec_form4",
                    "eta_seconds": EXPECTED_ETA_SECONDS,
                    "eta_label": "3m",
                },
                "jobs": [],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "running"
    assert progress["status_label"] == "Loading"
    assert progress["percent_complete"] == EXPECTED_PERCENT
    assert progress["current_dataset"] == "sec_form4"
    assert progress["eta_label"] == "3m"


def test_load_data_refresh_progress_derives_complete_state_from_old_status(tmp_path: Path) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "blocked": False,
                "failed": False,
                "jobs": [
                    {"dataset": "prices_daily", "status": "passed"},
                    {"dataset": "news_rss", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "complete"
    assert progress["percent_complete"] == COMPLETE_PERCENT
    assert progress["completed_jobs"] == EXPECTED_COMPLETED_JOBS


def test_load_data_refresh_progress_recomputes_running_eta(tmp_path: Path) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    started_at = datetime.now(UTC) - timedelta(seconds=RUNNING_ELAPSED_SECONDS)
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "running"},
                "jobs": [
                    {
                        "dataset": "prices_daily",
                        "status": "running",
                        "started_at": started_at.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "running"
    assert 0 < progress["eta_seconds"] <= MAX_PRICE_ETA_SECONDS


def test_load_data_refresh_progress_keeps_slow_dataset_eta_baseline(tmp_path: Path) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    started_at = datetime.now(UTC) - timedelta(seconds=RUNNING_ELAPSED_SECONDS)
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "running"},
                "jobs": [
                    {
                        "dataset": "prices_daily",
                        "status": "passed",
                        "duration_seconds": 3,
                    },
                    {
                        "dataset": "sec_form4",
                        "status": "running",
                        "started_at": started_at.isoformat(),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["eta_seconds"] >= MIN_FORM4_ETA_SECONDS


def test_data_refresh_status_endpoint_reads_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {
                    "state": "blocked",
                    "total_jobs": 1,
                    "completed_jobs": 1,
                    "percent_complete": 100,
                    "eta_label": "not available",
                },
                "blocked": True,
                "failed": False,
                "jobs": [{"dataset": "prices_daily", "status": "blocked"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(status_path))
    client = TestClient(create_app())

    response = client.get("/status/data-refresh")

    assert response.status_code == HTTP_OK
    assert response.json()["state"] == "blocked"
