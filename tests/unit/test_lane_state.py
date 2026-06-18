from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agency.runtime import lane_state as lane_state_module
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
                    "percent_complete": 21,
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
    assert lane["progress_percent"] == 21
    assert "still loading" in str(lane["operator_message"])
    assert lane["refresh_action_available"] is True
    assert lane["refresh_action_url"] == (
        "/scheduler/massive-lanes/massive_live_trade_slices/refresh"
    )
    assert "Provider UNKNOWN" in str(lane["source_proof_label"])


def test_lane_states_use_lane_proof_timestamp_not_request_time() -> None:
    proof_time = "2026-05-22T13:26:00+00:00"
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
                    "fetched_at": proof_time,
                    "latest_as_of": "2026-05-22 13:25:00 UTC",
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "massive_live_trade_slices")
    assert lane["checked_at"] == proof_time
    assert lane["checked_at"] != NOW.isoformat()


def test_lane_states_include_window_and_manifest_proof_for_raw_lanes() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "ready",
                    "status_class": "pass",
                    "required_now": True,
                    "blocks_execution": True,
                    "latest_as_of": "2026-05-22 13:25:00 UTC",
                    "window_label": "2026-05-22",
                    "manifest_path": "research/data/manifests/massive_lanes/massive_live_trade_slices.json",
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "massive_live_trade_slices")
    assert lane["window_label"] == "2026-05-22"
    assert str(lane["manifest_path"]).endswith("massive_live_trade_slices.json")
    assert lane["refresh_action_label"] == "Refresh Live Trade Slices"
    assert "massive_live_trade_slices.json" in str(lane["source_proof_label"])


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
    assert lane["refresh_action_available"] is True
    assert lane["refresh_action_url"] == "/scheduler/massive-lanes/massive_daily_bars/refresh"


def test_abnormal_volume_depends_on_daily_bars_not_live_trade_slices() -> None:
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
                    "latest_as_of": NOW.isoformat(),
                },
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "running",
                    "status_class": "warn",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "1/2 ticker-days",
                },
            ]
        },
        dataset_rows=[
            {
                "dataset": "prices_daily",
                "status": "ready",
                "status_class": "pass",
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        lane_rows=[
            {
                "lane": "abnormal_volume",
                "label": "Abnormal Volume",
                "group": "critical",
                "source_dataset": "prices_daily",
                "status": "ready",
                "status_class": "pass",
                "analysis_state": "analyzed_current",
                "produced_count": 2,
                "expected_count": 2,
                "required_now": True,
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "abnormal_volume")
    assert lane["raw_lanes_required"] == ["massive_daily_bars"]
    assert lane["state"] == "ready_for_paper_execution"
    assert "live trade" not in str(lane["operator_message"]).lower()


def test_derived_lane_waits_on_running_raw_lane_when_no_analysis_exists() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "running",
                    "status_class": "warn",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "1/2 ticker-days",
                    "eta_label": "3m",
                    "percent_complete": 50,
                }
            ]
        },
        dataset_rows=[
            {
                "dataset": "stock_trades",
                "status": "warning",
                "status_class": "warn",
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        lane_rows=[
            {
                "lane": "market_flow_trend",
                "label": "Market Flow Trend",
                "group": "critical",
                "source_dataset": "stock_trades",
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

    lane = _lane(states, "market_flow_trend")
    assert lane["state"] == "loading"
    assert lane["status_label"] == "Data is still loading"
    assert lane["status_class"] == "warn"
    assert lane["blocker"] is True
    assert "1/2 ticker-days" in str(lane["operator_message"])


def test_derived_loading_lane_provider_unavailable_overrides_loading() -> None:
    states = build_lane_states(
        data_refresh={"massive_lanes": []},
        dataset_rows=[
            {
                "dataset": "stock_trades",
                "status": "blocked",
                "status_class": "block",
                "source_status": "UNAVAILABLE",
                "source_freshness": "UNAVAILABLE",
            }
        ],
        lane_rows=[
            {
                "lane": "market_flow_trend",
                "label": "Market Flow Trend",
                "group": "critical",
                "source_dataset": "stock_trades",
                "status": "loading",
                "status_class": "warn",
                "analysis_state": "loading",
                "produced_count": 0,
                "expected_count": 2,
                "required_now": True,
                "source_status": "UNAVAILABLE",
                "source_freshness": "UNAVAILABLE",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "market_flow_trend")
    assert lane["state"] == "provider_unavailable"
    assert lane["status_label"] == "Provider unavailable"
    assert "still loading" not in str(lane["operator_message"]).lower()
    assert lane["blocker"] is True


def test_missing_required_raw_proof_blocks_derived_execution_lane() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "missing_manifest",
                    "status_class": "block",
                    "required_now": True,
                    "blocks_execution": True,
                    "reason_code": "missing_manifest",
                    "detail": "No current live trade proof is recorded.",
                }
            ]
        },
        dataset_rows=[
            {
                "dataset": "stock_trades",
                "status": "ready",
                "status_class": "pass",
                "source_status": "HEALTHY",
                "source_freshness": "UNKNOWN",
            }
        ],
        lane_rows=[
            {
                "lane": "market_flow_trend",
                "label": "Market Flow Trend",
                "group": "critical",
                "source_dataset": "stock_trades",
                "status": "ready",
                "status_class": "pass",
                "analysis_state": "analyzed_current",
                "produced_count": 2,
                "expected_count": 2,
                "required_now": True,
                "source_status": "HEALTHY",
                "source_freshness": "UNKNOWN",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "market_flow_trend")
    assert lane["state"] == "provider_unavailable"
    assert lane["ready_for_paper_execution"] is False
    assert lane["blocker"] is True
    assert lane["blocking_raw_lane_id"] == "massive_live_trade_slices"
    assert "Required data source Massive Live Trade Slices" in str(lane["operator_message"])


def test_raw_lane_override_exposes_blocking_raw_progress_and_eta() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "running",
                    "status_class": "warn",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "37/168 ticker-days",
                    "eta_label": "12m",
                    "eta_seconds": 720,
                    "percent_complete": 22,
                }
            ]
        },
        dataset_rows=[
            {
                "dataset": "stock_trades",
                "status": "ready",
                "status_class": "pass",
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        lane_rows=[
            {
                "lane": "buy_sell_pressure",
                "label": "Buy Sell Pressure",
                "group": "critical",
                "source_dataset": "stock_trades",
                "status": "ready",
                "status_class": "pass",
                "analysis_state": "analyzed_current",
                "produced_count": 168,
                "expected_count": 168,
                "required_now": True,
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "buy_sell_pressure")
    assert lane["state"] == "needs_refresh"
    assert lane["blocking_raw_lane_id"] == "massive_live_trade_slices"
    assert lane["progress_label"] == "37/168 ticker-days"
    assert lane["progress_percent"] == 22
    assert lane["eta_label"] == "12m"
    assert lane["eta_seconds"] == 720


def test_lane_states_keep_partial_derived_subset_reviewable_not_execution_ready() -> None:
    states = build_lane_states(
        data_refresh={},
        dataset_rows=[
            {
                "dataset": "prices_daily",
                "status": "ready",
                "status_class": "pass",
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
                "status": "warning",
                "status_class": "warn",
                "analysis_state": "analyzed_current",
                "produced_count": 1,
                "expected_count": 168,
                "required_now": True,
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "technical_analysis")
    assert lane["state"] == "ready_for_review"
    assert lane["ready_for_review"] is True
    assert lane["ready_for_paper_execution"] is False
    assert lane["blocker"] is False
    assert lane["produced_count"] == 1
    assert lane["expected_count"] == 168


def test_lane_states_cover_massive_orchestrator_derived_requirements() -> None:
    states = build_lane_states(
        data_refresh={"massive_lanes": []},
        dataset_rows=[],
        lane_rows=[
            {
                "lane": "backtest_feature_builder",
                "source_dataset": "stock_trades",
                "analysis_state": "analyzed_current",
                "produced_count": 1,
                "expected_count": 1,
            },
            {
                "lane": "options_flow",
                "source_dataset": "options_chains",
                "analysis_state": "analyzed_current",
                "produced_count": 1,
                "expected_count": 1,
            },
        ],
        source_health_rows=[],
        now=NOW,
    )

    assert _lane(states, "backtest_feature_builder")["raw_lanes_required"] == [
        "massive_daily_bars",
        "massive_backtest_trade_tape",
    ]
    assert _lane(states, "options_flow")["raw_lanes_required"] == [
        "massive_options_flow"
    ]


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
    assert lane["status_label"] == "Lane proof needs refresh"
    assert "lane proof needs refresh" in str(lane["operator_message"]).lower()
    assert lane["blocks_execution"] is True
    assert lane["ready_for_review"] is False
    assert lane["ready_for_paper_execution"] is False
    assert "Refresh Massive Block Trade Feed" in str(lane["recommended_action"])


def test_lane_state_source_proof_translates_raw_stale_status() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "stale",
                    "status_class": "block",
                    "required_now": True,
                    "blocks_execution": True,
                    "latest_as_of": (NOW - timedelta(minutes=45)).isoformat(),
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[
            {
                "source": "massive-stock-trades",
                "lane_id": "massive_live_trade_slices",
                "status": "STALE",
                "freshness": "STALE",
                "checked_at": NOW.isoformat(),
            }
        ],
        now=NOW,
    )

    lane = _lane(states, "massive_live_trade_slices")

    assert "STALE" not in str(lane["source_proof_label"])
    assert "Needs refresh" in str(lane["source_proof_label"])


def test_raw_lane_provider_unavailable_overrides_refresh_age() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_premarket_trade_slices",
                    "label": "Massive Pre-Market Trade Slices",
                    "state": "stale",
                    "status_class": "block",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "0% manifest coverage",
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[
            {
                "source": "massive-stock-trades",
                "status": "UNAVAILABLE",
                "freshness": "UNAVAILABLE",
                "detail": (
                    "Provider returned 403 Forbidden for AAPL; check Massive/Polygon "
                    "trade endpoint entitlement."
                ),
            }
        ],
        now=NOW,
    )

    lane = _lane(states, "massive_premarket_trade_slices")
    assert lane["state"] == "provider_unavailable"
    assert lane["status_label"] == "Provider unavailable"
    assert "403 Forbidden" in str(lane["operator_message"])
    assert "provider credentials" in str(lane["recommended_action"])


def test_raw_lane_running_provider_error_is_provider_unavailable() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "running",
                    "status_class": "warn",
                    "required_now": True,
                    "blocks_execution": True,
                    "progress_label": "12/168 ticker-days",
                    "detail": (
                        "Provider returned 403 Forbidden; account plan does not include "
                        "trade endpoint entitlement."
                    ),
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "massive_live_trade_slices")
    assert lane["state"] == "provider_unavailable"
    assert lane["status_label"] == "Provider unavailable"
    assert "403 Forbidden" in str(lane["operator_message"])
    assert "provider credentials" in str(lane["recommended_action"])


def test_partial_derived_analyzed_needs_refresh_keeps_refresh_state() -> None:
    states = build_lane_states(
        data_refresh={},
        dataset_rows=[
            {
                "dataset": "prices_daily",
                "status": "ready",
                "status_class": "pass",
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
                "status": "warning",
                "status_class": "warn",
                "analysis_state": "analyzed_needs_refresh",
                "produced_count": 84,
                "expected_count": 168,
                "required_now": True,
                "source_status": "HEALTHY",
                "source_freshness": "FRESH",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "technical_analysis")
    assert lane["state"] == "needs_refresh"
    assert lane["ready_for_review"] is False
    assert lane["status_label"] == "Analysis exists but needs refresh"


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
    assert options["refresh_action_available"] is False
    assert "not enabled" in str(options["refresh_action_disabled_reason"])
    assert anomaly["state"] == "disabled_optional"
    assert anomaly["blocker"] is False


def test_optional_derived_premarket_lane_is_not_effectively_blocking() -> None:
    states = build_lane_states(
        data_refresh={"massive_lanes": []},
        dataset_rows=[],
        lane_rows=[
            {
                "lane": "pre_market_unusual_activity",
                "label": "Pre-Market Unusual Activity",
                "group": "critical",
                "status": "blocked",
                "status_class": "block",
                "required_now": False,
                "blocks_execution": True,
                "analysis_state": "data_void",
            }
        ],
        source_health_rows=[],
        now=NOW,
    )

    lane = _lane(states, "pre_market_unusual_activity")
    assert lane["state"] == "disabled_optional"
    assert lane["blocks_execution"] is True
    assert lane["effective_blocks_execution"] is False
    assert lane["blocker"] is False


def test_lane_state_unknown_status_gets_operator_label() -> None:
    assert lane_state_module._status_label_for_lane("planned", "raw_acquisition") == "Planned"


def test_options_raw_lane_uses_options_source_health() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_options_flow",
                    "label": "Massive Options Flow",
                    "state": "complete",
                    "required_now": True,
                    "blocks_execution": False,
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[
            {
                "source": "massive-options-flow",
                "status": "UNAVAILABLE",
                "freshness": "UNAVAILABLE",
            }
        ],
        now=NOW,
    )

    lane = _lane(states, "massive_options_flow")
    assert lane["source_status"] == "UNAVAILABLE"


def _lane(states: list[dict[str, object]], lane_id: str) -> dict[str, object]:
    for row in states:
        if row["lane_id"] == lane_id:
            return row
    raise AssertionError(f"missing lane state for {lane_id}")
