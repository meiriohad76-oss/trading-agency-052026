from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COCKPIT_TEMPLATE = PROJECT_ROOT / "src/agency/templates/cockpit.html"
PANELS_TEMPLATE = PROJECT_ROOT / "src/agency/templates/_cockpit_panels.html"
STYLES = PROJECT_ROOT / "src/agency/static/styles.css"


def _cockpit_template() -> str:
    return COCKPIT_TEMPLATE.read_text(encoding="utf-8")


def _panels_template() -> str:
    return PANELS_TEMPLATE.read_text(encoding="utf-8")


def _styles() -> str:
    return STYLES.read_text(encoding="utf-8")


def _sources_with_lane_states() -> dict[str, object]:
    sources = _sample_sources()
    data_load = sources["dashboard"]["data_load_status"]  # type: ignore[index]
    data_load.update(  # type: ignore[union-attr]
        {
            "status_label": "Loaded With Gaps",
            "status_class": "warn",
            "overall_percent": 84,
            "critical_lane_percent": 53,
            "expected_ticker_count": 168,
            "review_operational_ready": True,
            "tradable_ready": False,
            "blocker_count": 0,
            "warning_count": 3,
            "as_of": "2026-05-22",
            "lane_states": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "lane_kind": "raw_acquisition",
                    "label": "Massive Live Trade Slices",
                    "status_label": "Data is still loading",
                    "status_class": "warn",
                    "state": "loading",
                    "operator_message": "Massive Live Trade Slices data is still loading (36/50 ticker-days).",
                    "recommended_action": "Wait for Massive Live Trade Slices to finish, then refresh the dashboard.",
                    "progress_label": "36/50 ticker-days",
                    "latest_as_of": "2026-05-22T13:25:29+00:00",
                    "checked_at": "2026-05-22T13:26:00+00:00",
                    "required_now": True,
                    "blocks_execution": True,
                    "blocker": True,
                    "ready_for_review": False,
                    "ready_for_paper_execution": False,
                    "raw_lanes_required": [],
                    "source_dataset": "stock_trades",
                },
                {
                    "lane_id": "technical_analysis",
                    "lane_kind": "derived_signal",
                    "label": "Technical Analysis",
                    "status_label": "Ready for paper execution",
                    "status_class": "pass",
                    "state": "ready_for_paper_execution",
                    "operator_message": "Technical Analysis is ready for paper execution.",
                    "recommended_action": "No lane action required before paper execution.",
                    "progress_label": "168/168 row(s)",
                    "latest_as_of": "2026-05-22T03:31:05+00:00",
                    "checked_at": "2026-05-22T13:26:00+00:00",
                    "required_now": True,
                    "blocks_execution": True,
                    "blocker": False,
                    "ready_for_review": True,
                    "ready_for_paper_execution": True,
                    "raw_lanes_required": ["massive_daily_bars"],
                    "source_dataset": "prices_daily",
                },
                {
                    "lane_id": "subscription_thesis",
                    "lane_kind": "derived_signal",
                    "label": "Subscription Thesis",
                    "status_label": "Analysis exists but needs refresh",
                    "status_class": "warn",
                    "state": "needs_refresh",
                    "operator_message": "Subscription Thesis analysis exists but needs refresh.",
                    "recommended_action": "Refresh Subscription Thesis using the lane refresh action.",
                    "progress_label": "1/168 row(s)",
                    "latest_as_of": "2026-05-19T12:00:00+00:00",
                    "checked_at": "2026-05-22T13:26:00+00:00",
                    "required_now": True,
                    "blocks_execution": False,
                    "blocker": False,
                    "ready_for_review": False,
                    "ready_for_paper_execution": False,
                    "raw_lanes_required": [],
                    "source_dataset": "subscription_emails",
                },
                {
                    "lane_id": "massive_options_flow",
                    "lane_kind": "raw_acquisition",
                    "label": "Massive Options Flow",
                    "status_label": "Not required for current workflow",
                    "status_class": "neutral",
                    "state": "disabled_optional",
                    "operator_message": "Massive Options Flow is optional for the current workflow.",
                    "recommended_action": "No action required unless this lane becomes part of today's workflow.",
                    "progress_label": "not tracked",
                    "latest_as_of": "not recorded",
                    "checked_at": "2026-05-22T13:26:00+00:00",
                    "required_now": False,
                    "blocks_execution": False,
                    "blocker": False,
                    "ready_for_review": False,
                    "ready_for_paper_execution": False,
                    "raw_lanes_required": [],
                    "source_dataset": "options_flow",
                },
            ],
        }
    )
    return sources


def test_cockpit_context_promotes_lane_state_operationability() -> None:
    context = cockpit_context_from_sources(_sources_with_lane_states())
    data_state = context["data_state"]

    assert data_state["overall_percent"] == 84
    assert data_state["critical_lane_percent"] == 53
    assert data_state["active_universe_label"] == "168 active-universe tickers"
    assert data_state["review"]["label"] == "Review ready"
    assert data_state["paper"]["label"] == "Paper execution gated"
    assert data_state["loading_count"] == 1
    assert data_state["needs_refresh_count"] == 1
    assert data_state["ready_paper_count"] == 1
    assert data_state["optional_count"] == 1

    first_gap = data_state["top_gaps"][0]
    assert first_gap["lane"] == "Massive Live Trade Slices"
    assert first_gap["progress_label"] == "36/50 ticker-days"
    assert "still loading" in first_gap["detail"]
    assert data_state["lane_rows"][0]["progress_percent"] == 72


def test_cockpit_context_sanitizes_primary_data_state_language() -> None:
    sources = _sources_with_lane_states()
    lane = sources["dashboard"]["data_load_status"]["lane_states"][0]  # type: ignore[index]
    lane["status_label"] = "Lane Stale"  # type: ignore[index]
    lane["operator_message"] = "Lane stale because the manifest is stale."  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    rendered_text = str(context["data_state"])

    assert "stale" not in rendered_text.lower()
    assert "needs refresh" in rendered_text.lower()


def test_cockpit_lane_state_derives_actionable_next_step_when_lane_omits_one() -> None:
    sources = _sources_with_lane_states()
    lane = sources["dashboard"]["data_load_status"]["lane_states"][1]  # type: ignore[index]
    lane.pop("recommended_action")  # type: ignore[union-attr]

    context = cockpit_context_from_sources(sources)
    technical = [
        row
        for row in context["data_state"]["lane_rows"]
        if row["lane_id"] == "technical_analysis"
    ][0]

    assert technical["recommended_action"] == (
        "No action needed for Technical Analysis; it is ready for paper execution."
    )
    assert "No lane action recorded" not in technical["tooltip"]


def test_cockpit_lane_state_rows_expose_individual_refresh_actions() -> None:
    context = cockpit_context_from_sources(_sources_with_lane_states())
    rows = {
        row["lane_id"]: row
        for row in context["data_state"]["lane_rows"]
    }
    html = _panels_template()

    live = rows["massive_live_trade_slices"]
    technical = rows["technical_analysis"]
    subscription = rows["subscription_thesis"]
    options = rows["massive_options_flow"]

    assert live["refresh_action"]["url"] == (
        "/scheduler/massive-lanes/massive_live_trade_slices/refresh"
    )
    assert live["refresh_action"]["label"] == "Refresh Live Trade Slices"
    assert technical["refresh_action"]["url"] == (
        "/scheduler/massive-lanes/massive_daily_bars/refresh"
    )
    assert subscription["refresh_action"]["url"] == (
        "/scheduler/subscription-emails/login-refresh"
    )
    assert options["refresh_action"]["url"] == ""
    assert options["refresh_action"]["label"] == "Policy locked"
    assert "not exposed as a runnable scheduler refresh" in options["refresh_action"]["detail"]
    assert 'action="{{ lane.refresh_action.url }}"' in html
    assert "{{ lane.refresh_action.label }}" in html


def test_cockpit_template_has_top_level_data_state_strip() -> None:
    html = _cockpit_template()
    css = _styles()

    assert "cockpit-data-state-strip" in html
    assert "Data State" in html
    assert "data_review.label" in html
    assert "data_paper.label" in html
    assert "data_state.overall_percent" in html
    assert "data_state.critical_lane_percent" in html
    assert "data_state.top_gaps" in html
    assert "data-cockpit-panel-target=\"universe\"" in html
    assert ".cockpit-data-state-strip" in css


def test_cockpit_universe_panel_has_lane_state_board() -> None:
    html = _panels_template()
    css = _styles()

    assert "Lane State Board" in html
    assert "data_state.lane_rows" in html
    assert "lane.status_label" in html
    assert "lane.progress_label" in html
    assert "lane.latest_as_of_label" in html
    assert "lane.recommended_action" in html
    assert "lane.requirement_label" in html
    assert "Paper execution impact" in html
    assert ".cockpit-lane-board" in css
