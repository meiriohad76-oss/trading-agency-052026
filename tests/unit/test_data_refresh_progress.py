from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agency.runtime.data_refresh_progress as progress_module
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
STALE_STATUS_SECONDS = 45 * 60
EXPECTED_STOCK_TRADE_PERCENT = 25


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


def test_load_data_refresh_progress_does_not_mark_planned_dry_run_as_pass(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "planned"},
                "jobs": [{"dataset": "prices_daily", "status": "planned"}],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "planned"
    assert progress["status_class"] == "block"


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


def test_load_data_refresh_progress_marks_old_running_file_stale(tmp_path: Path) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "running"},
                "jobs": [{"dataset": "sec_form4", "status": "running"}],
            }
        ),
        encoding="utf-8",
    )
    stale_timestamp = (datetime.now(UTC) - timedelta(seconds=STALE_STATUS_SECONDS)).timestamp()
    os.utime(status_path, (stale_timestamp, stale_timestamp))

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "stale"
    assert progress["is_loading"] is False


def test_load_data_refresh_progress_marks_orphaned_running_command_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "progress": {"state": "running", "current_dataset": "sec_form4"},
                "jobs": [
                    {
                        "dataset": "sec_form4",
                        "status": "running",
                        "command": [
                            "$PYTHON",
                            "research/scripts/pull_sec_form4.py",
                            "--tickers",
                            "HON",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        progress_module,
        "_active_process_command_lines",
        lambda: ("python unrelated_worker.py",),
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "stale"
    assert progress["is_loading"] is False
    assert "no matching worker process" in str(progress["detail"])


def test_load_data_refresh_progress_prioritizes_failed_job_over_pending_job(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"dataset": "prices_daily", "status": "failed"},
                    {"dataset": "stock_trades", "status": "pending"},
                ],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)

    assert progress["state"] == "failed"
    assert progress["status_class"] == "block"


def test_load_data_refresh_progress_includes_stock_trade_subprogress(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "running"},
                "config": {
                    "stock_trades_start": "2026-05-12",
                    "stock_trades_end": "2026-05-12",
                    "stock_trades_limit": 50000,
                    "stock_trades_max_pages_per_day": 1,
                    "stock_trades_order": "desc",
                },
                "jobs": [
                    {
                        "dataset": "stock_trades",
                        "status": "running",
                        "command": ["$PYTHON", "pull.py", "--ticker", "AAPL"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps(
                {
                    "state": "running",
                    "percent_complete": EXPECTED_STOCK_TRADE_PERCENT,
                    "ticker_days_completed": 1,
                    "ticker_days_total": 4,
                    "start": "2026-05-12",
                    "end": "2026-05-12",
                    "current_ticker": "AAPL",
                    "current_trade_date": "2026-05-12",
                    "current_pages_downloaded": 2,
                "current_rows_downloaded": 100000,
                "updated_at": "2026-05-12T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert isinstance(trade_pull, dict)
    assert trade_pull["state"] == "running"
    assert trade_pull["status_label"] == "Pulling Trades"
    assert trade_pull["percent_complete"] == EXPECTED_STOCK_TRADE_PERCENT
    assert trade_pull["current_ticker"] == "AAPL"
    assert trade_pull["ticker_progress_label"] == "1/4 ticker-days"
    assert trade_pull["guardrail_label"] == "limit 50000; pages/day 1; order desc"


def test_stock_trade_manifest_without_current_job_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "stock_trades.json"
    manifest_path.write_text(
        json.dumps(
            {
                "row_count": 100,
                "ticker_count": 1,
                "tickers": ["AAPL"],
                "date_range": {"start": "2026-05-01", "end": "2026-05-01"},
                "max_timestamp_as_of": "2026-05-01T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_STOCK_TRADES_MANIFEST_PATH", manifest_path)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "complete"},
                "config": {
                    "tickers": ["AAPL", "MSFT"],
                    "stock_trades_start": "2026-05-08",
                    "stock_trades_end": "2026-05-08",
                },
                "jobs": [{"dataset": "prices_daily", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert isinstance(trade_pull, dict)
    assert trade_pull["state"] == "unverified"
    assert trade_pull["status_class"] == "warn"
    assert trade_pull["percent_complete"] == 0


def test_stock_trade_partial_progress_overrides_passed_batch_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "stock_trades.json"
    manifest_path.write_text(
        json.dumps({"row_count": 50_000, "ticker_count": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_STOCK_TRADES_MANIFEST_PATH", manifest_path)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "complete"},
                "jobs": [{"dataset": "stock_trades", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps(
            {
                "state": "partial",
                "ticker_days_completed": 0,
                "ticker_days_processed": 1,
                "ticker_days_total": 1,
                "ticker_days_partial": 1,
                "ticker_days_failed": 0,
                "percent_complete": 100,
                "pipeline_ready_tickers": [],
                "pipeline_usable_tickers": ["AAPL"],
                "pipeline_ready_count": 0,
                "pipeline_usable_count": 1,
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert isinstance(trade_pull, dict)
    assert trade_pull["state"] == "partial"
    assert trade_pull["status_class"] == "warn"
    assert trade_pull["percent_complete"] == 100
    assert trade_pull["pipeline_ready_tickers"] == []
    assert trade_pull["pipeline_usable_tickers"] == ["AAPL"]
    assert trade_pull["pipeline_usable_label"] == "1/1 tickers usable"
    assert "1 ticker(s) can pass forward" in str(trade_pull["detail"])


def test_stock_trade_progress_exposes_pipeline_ready_tickers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "stock_trades.json"
    manifest_path.write_text(
        json.dumps({"row_count": 50_000, "ticker_count": 2}),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_STOCK_TRADES_MANIFEST_PATH", manifest_path)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "running", "current_dataset": "stock_trades"},
                "jobs": [{"dataset": "stock_trades", "status": "running"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps(
                {
                    "state": "running",
                    "ticker_count": 2,
                    "start": "2026-05-12",
                    "end": "2026-05-12",
                    "pipeline_ready_tickers": ["AAPL"],
                    "pipeline_usable_tickers": ["AAPL", "MSFT"],
                    "pipeline_pending_tickers": ["MSFT"],
                "pipeline_ready_count": 1,
                "pipeline_usable_count": 2,
                "ticker_statuses": [
                    {"ticker": "AAPL", "status": "complete"},
                    {"ticker": "MSFT", "status": "partial"},
                ],
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert isinstance(trade_pull, dict)
    assert trade_pull["pipeline_ready_tickers"] == ["AAPL"]
    assert trade_pull["pipeline_usable_tickers"] == ["AAPL", "MSFT"]
    assert trade_pull["pipeline_pending_tickers"] == ["MSFT"]
    assert trade_pull["pipeline_ready_label"] == "1/2 tickers ready"
    assert trade_pull["pipeline_usable_label"] == "2/2 tickers usable"


def test_data_refresh_progress_exposes_massive_lane_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial",
                "coverage_pct": 50,
                "ticker_count": 2,
                "row_count": 100,
                "fetched_at": "2026-05-12T12:00:00+00:00",
                "window": {"start": "2026-05-12", "end": "2026-05-12"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "running", "current_dataset": "stock_trades"},
                "jobs": [{"dataset": "stock_trades", "status": "running"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "massive_live_trade_slices-progress.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "state": "running",
                "percent_complete": 25,
                "eta_seconds": 90,
                "ticker_days_processed": 1,
                "ticker_days_total": 4,
                "current_ticker": "AAPL",
                "current_trade_date": "2026-05-12",
                "start": "2026-05-12",
                "end": "2026-05-12",
                "updated_at": "2026-05-12T12:01:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    lane = next(
        row
        for row in progress["massive_lanes"]
        if row["lane_id"] == "massive_live_trade_slices"
    )

    assert progress["trade_pull"]["lane_id"] == "massive_live_trade_slices"
    assert lane["state"] == "running"
    assert lane["percent_complete"] == 25
    assert lane["manifest_status"] == "partial"
    assert lane["progress_label"] == "1/4 ticker-days"
    assert lane["eta_seconds"] == 90
    assert lane["eta_label"] == "2m"
    assert lane["issues"] == []
    assert lane["reason_code"] == "running"
    assert lane["reason"] == lane["detail"]
    assert lane["required_now"] is True
    assert lane["next_due_at"] == ""
    assert lane["analysis_state"] == "loading"


def test_data_refresh_progress_ignores_legacy_live_progress_without_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial",
                "coverage_pct": 50,
                "ticker_count": 2,
                "row_count": 100,
                "fetched_at": "2026-05-22T20:00:00+00:00",
                "window": {"start": "2026-05-22", "end": "2026-05-22"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "complete", "current_dataset": "prices_daily"},
                "jobs": [{"dataset": "prices_daily", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps(
            {
                "state": "running",
                "percent_complete": 25,
                "ticker_days_processed": 1,
                "ticker_days_total": 4,
                "updated_at": "2026-05-24T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    lane = next(
        row
        for row in progress["massive_lanes"]
        if row["lane_id"] == "massive_live_trade_slices"
    )

    assert progress["trade_pull"]["state"] != "running"
    assert lane["state"] == "partial"
    assert lane["percent_complete"] == 50
    assert lane["window_label"] == "2026-05-22"


def test_trade_pull_summary_prefers_live_lane_over_newer_premarket_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    for lane_id, ticker_count in (
        ("massive_live_trade_slices", 168),
        ("massive_premarket_trade_slices", 50),
    ):
        (lane_root / f"{lane_id}.json").write_text(
            json.dumps(
                {
                    "lane_id": lane_id,
                    "status": "complete",
                    "coverage_pct": 100,
                    "ticker_count": ticker_count,
                    "row_count": ticker_count * 10,
                    "fetched_at": "2026-05-15T22:00:00+00:00",
                    "window": {"start": "2026-05-15", "end": "2026-05-15"},
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))
    (tmp_path / "massive_live_trade_slices-progress.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "state": "complete",
                "ticker_days_processed": 168,
                "ticker_days_total": 168,
                "ticker_count": 168,
                "updated_at": "2026-05-15T22:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "massive_premarket_trade_slices-progress.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_premarket_trade_slices",
                "state": "complete",
                "ticker_days_processed": 50,
                "ticker_days_total": 50,
                "ticker_count": 50,
                "updated_at": "2026-05-15T22:05:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert trade_pull["lane_id"] == "massive_live_trade_slices"
    assert trade_pull["ticker_days_total"] == 168
    assert trade_pull["ticker_count"] == 168


def test_trade_pull_summary_distinguishes_stored_scope_from_latest_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "coverage_pct": 100,
                "ticker_count": 168,
                "row_count": 1_239_948,
                "fetched_at": "2026-05-16T09:36:31+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))
    (tmp_path / "massive_live_trade_slices-progress.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "state": "complete",
                "ticker_count": 24,
                "pipeline_usable_count": 24,
            }
        ),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert trade_pull["coverage_scope_label"] == (
        "168 stored tickers; latest batch 24/24 usable"
    )


def test_data_refresh_progress_exposes_every_declared_massive_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))

    progress = load_data_refresh_progress(status_path)
    lane_ids = {row["lane_id"] for row in progress["massive_lanes"]}

    assert lane_ids == set(progress_module.MASSIVE_LANE_IDS)
    assert all("status_class" in row for row in progress["massive_lanes"])
    assert all("manifest_path" in row for row in progress["massive_lanes"])
    assert all(row["state"] == "missing_manifest" for row in progress["massive_lanes"])
    assert all(row["status_class"] == "warn" for row in progress["massive_lanes"])
    assert all("manifest" in str(row["detail"]).lower() for row in progress["massive_lanes"])


def test_data_refresh_progress_marks_stale_complete_massive_lane_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "complete",
                "coverage_pct": 100,
                "ticker_count": 1,
                "row_count": 1000,
                "fetched_at": "2026-05-01T12:00:00+00:00",
                "window": {"start": "2026-05-01", "end": "2026-05-01"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))

    progress = load_data_refresh_progress(status_path)
    lane = next(
        row
        for row in progress["massive_lanes"]
        if row["lane_id"] == "massive_live_trade_slices"
    )

    assert lane["state"] == "stale"
    assert lane["status_class"] == "block"
    assert "freshness SLA" in str(lane["detail"])
    assert "stale" not in str(lane["status_label"]).lower()
    assert "stale" not in str(lane["detail"]).lower()


def test_data_refresh_progress_marks_stale_partial_usable_massive_lane_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "coverage_pct": 50,
                "ticker_count": 2,
                "row_count": 1000,
                "fetched_at": "2026-05-01T12:00:00+00:00",
                "window": {"start": "2026-05-01", "end": "2026-05-01"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))

    progress = load_data_refresh_progress(status_path)
    lane = next(
        row
        for row in progress["massive_lanes"]
        if row["lane_id"] == "massive_live_trade_slices"
    )

    assert lane["state"] == "stale"
    assert lane["status_class"] == "block"
    assert "freshness SLA" in str(lane["detail"])


def test_data_refresh_progress_terminal_progress_does_not_mask_stale_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "coverage_pct": 100,
                "ticker_count": 2,
                "row_count": 1000,
                "fetched_at": "2026-05-01T12:00:00+00:00",
                "window": {"start": "2026-05-01", "end": "2026-05-01"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "massive_live_trade_slices-progress.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "state": "partial_usable",
                "percent_complete": 100,
                "updated_at": "2026-05-01T12:01:00+00:00",
                "start": "2026-05-01",
                "end": "2026-05-01",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))

    progress = load_data_refresh_progress(status_path)
    lane = next(
        row
        for row in progress["massive_lanes"]
        if row["lane_id"] == "massive_live_trade_slices"
    )

    assert lane["state"] == "stale"
    assert lane["status_class"] == "block"
    assert "freshness SLA" in str(lane["detail"])


def test_data_refresh_progress_keeps_latest_closed_market_live_lane_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosedMarketDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            value = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
            return value if tz is not None else value.replace(tzinfo=None)

    lane_root = tmp_path / "massive_lanes"
    lane_root.mkdir()
    (lane_root / "massive_live_trade_slices.json").write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "complete",
                "coverage_pct": 100,
                "ticker_count": 1,
                "row_count": 1000,
                "fetched_at": "2026-05-15T22:00:00+00:00",
                "window": {"start": "2026-05-15", "end": "2026-05-15"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_MASSIVE_LANE_MANIFEST_ROOT", lane_root)
    monkeypatch.setattr(progress_module, "datetime", ClosedMarketDateTime)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(json.dumps({"progress": {"state": "idle"}, "jobs": []}))

    progress = load_data_refresh_progress(status_path)
    lane = next(
        row
        for row in progress["massive_lanes"]
        if row["lane_id"] == "massive_live_trade_slices"
    )

    assert lane["state"] == "ready"
    assert lane["status_class"] == "pass"


def test_stale_orphan_stock_trade_progress_does_not_block_non_trade_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "stock_trades.json"
    manifest_path.write_text(
        json.dumps(
            {
                "row_count": 100,
                "ticker_count": 1,
                "tickers": ["AAPL"],
                "date_range": {"start": "2026-05-08", "end": "2026-05-08"},
                "max_timestamp_as_of": "2026-05-08T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(progress_module, "DEFAULT_STOCK_TRADES_MANIFEST_PATH", manifest_path)
    status_path = tmp_path / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "progress": {"state": "complete"},
                "config": {
                    "tickers": ["AAPL"],
                    "stock_trades_start": "2026-05-08",
                    "stock_trades_end": "2026-05-08",
                },
                "jobs": [{"dataset": "prices_daily", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps({"state": "stale", "percent_complete": 25}),
        encoding="utf-8",
    )

    progress = load_data_refresh_progress(status_path)
    trade_pull = progress["trade_pull"]

    assert isinstance(trade_pull, dict)
    assert trade_pull["state"] == "ready"
    assert trade_pull["status_class"] == "pass"


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
