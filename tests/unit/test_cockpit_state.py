from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_outage_scenario_exposes_blocked_engine_cards_and_retry_context() -> None:
    sources = _sample_sources()
    sources["dashboard"]["data_sources"] = [  # type: ignore[index]
        {
            "name": "Massive market data",
            "status_label": "Unavailable",
            "status_class": "block",
            "freshness_label": "access problem",
            "detail": "Provider token rejected the request.",
        }
    ]
    sources["dashboard"]["review_queue"] = []  # type: ignore[index]
    sources["execution"]["preview_rows"] = []  # type: ignore[index]
    sources["execution"]["orderable_rows"] = []  # type: ignore[index]

    context = cockpit_context_from_sources(sources)

    assert context["scenario"]["state"] == "outage"
    assert context["scenario"]["candidate_controls_enabled"] is False
    assert context["scenario"]["engine_cards"][0]["name"] == "Massive market data"
    assert context["scenario"]["retry_label"]
    assert "last good" in context["scenario"]["last_good_cycle_label"].lower()


def test_runtime_setup_gap_is_not_presented_as_quiet_no_trade_day() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["review_queue"] = []  # type: ignore[index]
    dashboard["candidates"] = []  # type: ignore[index]
    dashboard["live_config"] = {"active_universe_count": 0}  # type: ignore[index]
    dashboard["full_live_readiness"] = {"cycle_id": "None"}  # type: ignore[index]
    dashboard["data_load_status"] = {  # type: ignore[index]
        "cycle_id": "None",
        "as_of": "target 2026-06-17 (config end missing)",
        "status_label": "Blocked",
        "status_class": "block",
        "review_operational_ready": False,
        "tradable_ready": False,
        "expected_ticker_count": 0,
        "overall_percent": 70,
        "critical_lane_percent": 14,
        "lane_states": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Massive Daily Bars",
                "state": "provider_unavailable",
                "status_label": "Provider unavailable",
                "status_class": "block",
                "progress_label": "not tracked",
                "required_now": True,
                "blocks_execution": True,
                "blocker": True,
                "operator_message": "Daily bars lane manifest is missing.",
                "recommended_action": "Refresh Daily Bars, then reload the cockpit.",
                "refresh_action_url": "/scheduler/massive-lanes/massive_daily_bars/refresh",
                "refresh_action_label": "Refresh Daily Bars",
            }
        ],
    }
    sources["execution"]["preview_rows"] = []  # type: ignore[index]
    sources["execution"]["orderable_rows"] = []  # type: ignore[index]

    context = cockpit_context_from_sources(sources)

    assert context["cycle"]["id"] == "cycle not attached"
    assert context["scenario"]["state"] == "outage"
    assert context["scenario"]["runtime_setup_required"] is True
    assert "Agency startup needed" in context["scenario"]["headline"]
    assert "not a quiet trading day" in context["scenario"]["detail"]
    assert "Active universe shows 168 tickers" in context["scenario"]["setup_steps"][2]


def test_no_actionable_scenario_has_skip_and_closest_candidate_explanations() -> None:
    sources = _sample_sources()
    for row in sources["dashboard"]["review_queue"]:  # type: ignore[index]
        row["final_action"] = "WATCH"
        row["is_reviewable"] = False
    sources["execution"]["preview_rows"] = []  # type: ignore[index]
    sources["execution"]["orderable_rows"] = []  # type: ignore[index]

    context = cockpit_context_from_sources(sources)

    assert context["scenario"]["state"] == "no-actionable"
    assert context["scenario"]["skip_to_portfolio_label"] == "Skip to Portfolio"
    assert len(context["scenario"]["closest_candidates"]) == 3
    assert context["scenario"]["closest_candidates"][0]["ticker"] == "AAA"
    assert "filtered" in context["scenario"]["agent_note"].lower()


def test_submitted_scenario_exposes_order_cards_from_broker_acknowledgements() -> None:
    sources = _sample_sources()
    sources["execution"]["preview_rows"] = [  # type: ignore[index]
        {
            "ticker": "AAA",
            "side": "BUY",
            "qty": 3,
            "limit_price": 140.25,
            "notional_label": "$421",
            "execution_state": "SUBMITTED",
            "broker_order_id": "paper-aaa-001",
        }
    ]

    context = cockpit_context_from_sources(sources)

    assert context["scenario"]["state"] == "submitted"
    assert context["scenario"]["submitted_orders"][0]["ticker"] == "AAA"
    assert context["scenario"]["submitted_orders"][0]["broker_order_id"] == "paper-aaa-001"
    assert context["scenario"]["submitted_total_notional"] == 421.0


def test_scenario_template_has_dedicated_no_actionable_outage_and_submitted_layouts() -> None:
    html = _template()

    assert 'data-cockpit-scenario-panel="no-actionable"' in html
    assert 'data-cockpit-scenario-panel="outage"' in html
    assert 'data-cockpit-scenario-panel="submitted"' in html
    assert "scenario.closest_candidates" in html
    assert "scenario.engine_cards" in html
    assert "scenario.submitted_orders" in html


def test_primary_cockpit_flow_has_no_classic_dashboard_escape_hatches() -> None:
    html = _template()
    context = cockpit_context_from_sources(_sample_sources())

    assert "Open classic candidates" not in html
    assert "Classic brief" not in html
    assert "/final-selection" not in html
    assert "/execution-preview#orderable-heading" not in html
    assert all(row["order_action_url"] == "" for row in context["candidates"])
