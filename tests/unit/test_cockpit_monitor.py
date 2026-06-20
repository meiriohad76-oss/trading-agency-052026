from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agency.runtime.cockpit_monitor import source_state
from agency.views.cockpit import cockpit_context_from_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")
PANELS = Path("src/agency/templates/_cockpit_panels.html")


def _sources(*, monitor_updated_at: str | None = None) -> dict[str, object]:
    return {
        "dashboard": {
            "data_load_status": {
                "cycle_id": "cycle-monitor-test",
                "latest_checked_at": "2026-05-22T14:01:00+00:00",
            },
            "review_queue": [],
            "data_sources": [
                {
                    "name": "Massive live trade slices",
                    "lane_id": "massive_live_trade_slices",
                    "status_label": "Loaded",
                    "status_class": "pass",
                    "freshness_label": "source updated 2026-05-22 14:00 UTC",
                    "last_update": "2026-05-22T14:00:00+00:00",
                    "analysis_timestamp": "2026-05-22T14:00:30+00:00",
                    "coverage_label": "168/168 active universe",
                    "detail": "Live lane has current trade slices.",
                },
                {
                    "name": "SEC filings",
                    "status_label": "STALE",
                    "status_class": "warn",
                    "last_update": "2026-05-20T00:00:00+00:00",
                    "detail": "Latest filing exists but the agent has not rechecked publication status.",
                },
            ],
            "scheduler": {
                "latest_event_at": monitor_updated_at,
                "running_jobs": [
                    {
                        "lane": "massive_live_trade_slices",
                        "label": "Refreshing live trades",
                        "started_at": "2026-05-22T14:02:00+00:00",
                        "action_url": "/scheduler/massive-lanes/massive_live_trade_slices/refresh",
                    }
                ],
                "next_jobs": [
                    {
                        "lane": "massive_daily_bars",
                        "label": "Daily bars after close",
                        "eta_label": "after close",
                    }
                ],
            },
        },
        "execution": {},
        "portfolio": {},
        "market": {},
        "signals": {},
    }


def test_monitor_event_rows_include_timestamp_topic_and_action() -> None:
    context = cockpit_context_from_sources(_sources())

    event = context["monitor_events"][0]
    assert event["timestamp"] == "2026-05-22T14:02:00+00:00"
    assert event["topic"] == "massive_live_trade_slices"
    assert event["action"] == "Open lane refresh"
    assert event["action_url"] == "/scheduler/massive-lanes/massive_live_trade_slices/refresh"


def test_health_rows_include_proof_timestamp() -> None:
    context = cockpit_context_from_sources(_sources())

    source = context["sources"][0]
    assert source["proof_timestamp"] == "2026-05-22T14:01:00+00:00"
    assert source["source_timestamp"] == "2026-05-22T14:00:00+00:00"
    assert source["analysis_timestamp"] == "2026-05-22T14:00:30+00:00"


def test_cockpit_does_not_display_fresh_without_timestamp() -> None:
    panels = PANELS.read_text(encoding="utf-8")

    assert "{{ source.state }}" not in panels
    assert "{{ source.state_label }}" in panels
    assert "Proof timestamp" in panels


def test_cockpit_replaces_stale_with_actionable_state_copy() -> None:
    context = cockpit_context_from_sources(_sources())
    source = context["sources"][1]

    assert source["state_label"] == "Analyzed result needs refresh"
    assert "stale" not in source["state_label"].lower()
    assert source["next_action"] == "Refresh this lane, then rerun the agent analysis."


def test_source_state_treats_degraded_freshness_as_needs_refresh_even_with_timestamp() -> None:
    state = source_state(
        {
            "status": "HEALTHY",
            "freshness": "AGING",
            "status_label": "Loaded",
            "last_update": "2026-05-22T14:00:00+00:00",
        }
    )

    assert state["state"] == "needs_refresh"
    assert state["label"] == "Analyzed result needs refresh"


def test_source_state_does_not_treat_generic_needs_text_as_refresh() -> None:
    state = source_state(
        {
            "status": "HEALTHY",
            "status_label": "Loaded",
            "freshness": "fresh",
            "last_update": "2026-05-22T14:00:00+00:00",
            "detail": "Operator needs to review the visible proof before approval.",
        }
    )

    assert state["state"] == "ready"
    assert state["label"] == "Usable with proof timestamp"


def test_source_state_does_not_treat_generic_access_text_as_unavailable() -> None:
    state = source_state(
        {
            "status": "HEALTHY",
            "status_label": "Loaded",
            "freshness": "fresh",
            "last_update": "2026-05-22T14:00:00+00:00",
            "detail": "Data access exists and the latest proof is visible.",
        }
    )

    assert state["state"] == "ready"
    assert state["label"] == "Usable with proof timestamp"


def test_source_state_unknown_with_timestamp_needs_verification() -> None:
    state = source_state(
        {
            "status": "UNKNOWN",
            "status_label": "UNKNOWN",
            "freshness": "UNKNOWN",
            "last_update": "2026-05-22T14:00:00+00:00",
        }
    )

    assert state["state"] == "needs_refresh"
    assert state["label"] == "Source status needs verification"
    assert "confirm the health status" in state["next_action"]


def test_refreshable_lane_has_refresh_action() -> None:
    context = cockpit_context_from_sources(_sources())
    html = PANELS.read_text(encoding="utf-8")

    source = context["sources"][0]
    assert source["refresh_action"]["label"] == "Refresh lane"
    assert source["refresh_action"]["url"] == "/scheduler/massive-lanes/massive_live_trade_slices/refresh"
    assert 'method="post" action="{{ source.refresh_action.url }}"' in html


def test_live_indicator_requires_recent_monitor_update() -> None:
    recent = datetime.now(UTC).replace(microsecond=0).isoformat()
    old = (datetime.now(UTC) - timedelta(minutes=20)).replace(microsecond=0).isoformat()

    live_context = cockpit_context_from_sources(_sources(monitor_updated_at=recent))
    old_context = cockpit_context_from_sources(_sources(monitor_updated_at=old))
    html = TEMPLATE.read_text(encoding="utf-8")

    assert live_context["monitor"]["live"] is True
    assert old_context["monitor"]["live"] is False
    assert "data-cockpit-monitor-live" in html
    assert "Receiving current monitor updates" in html
