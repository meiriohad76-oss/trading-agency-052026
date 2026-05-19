from __future__ import annotations

from datetime import date
from pathlib import Path

from agency.runtime.daily_ops_report import (
    build_daily_ops_report,
    daily_ops_markdown,
    write_daily_ops_report,
)


def test_daily_ops_report_is_ready_with_clean_inputs(tmp_path: Path) -> None:
    report = build_daily_ops_report(
        report_date=date(2026, 5, 11),
        operational_readiness={
            "ready": True,
            "status_label": "Operational",
            "state": "ready",
            "blocker_count": 0,
            "warning_count": 0,
        },
        provider_readiness={
            "ready": True,
            "status_label": "Provider Keys Ready",
            "configured_count": 4,
            "provider_count": 10,
            "blocker_count": 0,
            "warning_count": 0,
        },
        pipeline_summary={
            "ok": True,
            "verdict": "agency_pipeline_passed",
            "successful_step_count": 3,
            "step_count": 3,
        },
        live_cycle_summary={
            "verdict": "watch_candidates_available",
            "cycle_id": "cycle-1",
            "evidence_packs": 10,
            "signals": 20,
        },
        massive_usage={
            "enabled": True,
            "date": "2026-05-11",
            "requests_made": 10,
            "requests_remaining": 90,
            "daily_request_budget": 100,
        },
    )

    assert report["verdict"] == "ready"
    assert report["blockers"] == []
    assert "agency_pipeline_passed" in daily_ops_markdown(report)

    write_daily_ops_report(report, tmp_path)
    assert (tmp_path / "daily-ops-report.json").exists()
    assert (tmp_path / "daily-ops-report.md").exists()


def test_daily_ops_report_blocks_failed_pipeline_and_provider() -> None:
    report = build_daily_ops_report(
        operational_readiness={"ready": True, "warning_count": 0},
        provider_readiness={"ready": False, "warning_count": 0},
        pipeline_summary={
            "ok": False,
            "verdict": "agency_pipeline_failed",
            "failed_step": "live_runtime_cycle",
        },
    )

    assert report["verdict"] == "blocked"
    assert "A required active provider key is missing." in report["blockers"]
    assert "Pipeline failed at live_runtime_cycle." in report["blockers"]
