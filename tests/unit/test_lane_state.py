from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agency.runtime.lane_state import build_lane_states

NOW = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)


def test_lane_states_report_raw_lane_running() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "running",
                    "status_label": "Lane Running",
                    "status_class": "warn",
                    "required_now": True,
                    "blocks_execution": True,
                    "eta_seconds": 420,
                    "eta_label": "7m",
                    "progress_label": "6/29 ticker-days",
                    "detail": "Massive Live Trade Slices is running on APP.",
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "massive_live_trade_slices")
    assert lane["state"] == "loading"
    assert lane["status_label"] == "Data is still loading"
    assert lane["blocks_execution"] is True
    assert lane["ready_for_review"] is False
    assert lane["ready_for_paper_execution"] is False
    assert lane["eta_label"] == "7m"
    assert "still loading" in str(lane["operator_message"])


def test_lane_states_report_raw_ready_but_derived_not_analyzed() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_daily_bars",
                    "label": "Massive Daily Bars",
                    "state": "complete",
                    "status_class": "pass",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "100% manifest coverage",
                    "latest_as_of": NOW.isoformat(),
                }
            ]
        },
        dataset_rows=[
            {
                "dataset": "prices_daily",
                "status": "ready",
                "status_class": "pass",
                "analysis_state": "analyzed_current",
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        lane_rows=[
            {
                "lane": "technical_analysis",
                "label": "Technical Analysis",
                "group": "critical",
                "source_dataset": "prices_daily",
                "status": "blocked",
                "status_class": "block",
                "analysis_state": "data_void",
                "produced_count": 0,
                "expected_count": 2,
                "required_now": True,
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "technical_analysis")
    assert lane["state"] == "loaded_unanalyzed"
    assert lane["status_label"] == "Data exists but agent has not analyzed it"
    assert lane["blocks_execution"] is True
    assert lane["ready_for_review"] is False
    assert lane["ready_for_paper_execution"] is False
    assert "Run the Technical Analysis agent" in str(lane["recommended_action"])


def test_lane_states_treat_partial_raw_lane_as_review_usable() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "partial_usable",
                    "status_class": "warn",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "18/29 ticker-days",
                    "latest_as_of": NOW.isoformat(),
                    "issues": ["11 ticker-days are still loading."],
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "massive_live_trade_slices")
    assert lane["state"] == "ready_for_review"
    assert lane["status_label"] == "Ready for review"
    assert lane["blocks_execution"] is True
    assert lane["ready_for_review"] is True
    assert lane["ready_for_paper_execution"] is False
    assert "partial" in str(lane["operator_message"]).lower()


def test_lane_states_block_execution_when_required_lane_needs_refresh() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_block_trade_feed",
                    "label": "Massive Block Trade Feed",
                    "state": "stale",
                    "status_class": "block",
                    "required_now": True,
                    "blocks_execution": True,
                    "freshness_seconds": 900,
                    "latest_as_of": (NOW - timedelta(minutes=15)).isoformat(),
                    "detail": "Lane proof is older than the 600 second policy.",
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "massive_block_trade_feed")
    assert lane["state"] == "needs_refresh"
    assert lane["status_label"] == "Analysis exists but needs refresh"
    assert lane["blocks_execution"] is True
    assert lane["ready_for_review"] is False
    assert lane["ready_for_paper_execution"] is False
    assert "Refresh Massive Block Trade Feed" in str(lane["recommended_action"])


def test_lane_states_do_not_count_disabled_optional_lane_as_blocker() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_options_flow",
                    "label": "Massive Options Flow",
                    "state": "disabled",
                    "status_class": "neutral",
                    "required_now": False,
                    "blocks_execution": False,
                    "detail": "Options entitlement is not enabled for today's workflow.",
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[
            {
                "lane": "options_anomaly",
                "label": "Options Anomaly",
                "group": "context",
                "status": "blocked",
                "status_class": "block",
                "required_now": False,
                "analysis_state": "data_void",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    options = _lane(states, "massive_options_flow")
    anomaly = _lane(states, "options_anomaly")
    assert options["state"] == "disabled_optional"
    assert options["blocks_execution"] is False
    assert options["blocker"] is False
    assert anomaly["state"] == "disabled_optional"
    assert anomaly["blocker"] is False


def _lane(states: list[dict[str, object]], lane_id: str) -> dict[str, object]:
    for row in states:
        if row["lane_id"] == lane_id:
            return row
    raise AssertionError(f"missing lane state for {lane_id}")
