from __future__ import annotations

import json

from agency.views.cockpit import cockpit_context_from_sources


def _sample_sources() -> dict[str, object]:
    return {
        "dashboard": {
            "broker_status": {"status_label": "Connected", "status_class": "pass"},
            "data_load_status": {
                "cycle_id": "cycle-live-20260522-1530",
                "overall_percent": 96,
                "health_monitor": {
                    "status_label": "Live",
                    "status_class": "pass",
                    "latest_checked_at": "2026-05-22T15:29:00+00:00",
                },
            },
            "full_live_readiness": {
                "cycle_id": "cycle-live-20260522-1530",
                "ready": True,
                "tradable_ready": True,
                "source_count": 11,
                "fresh_source_count": 9,
                "blocker_count": 0,
                "warning_count": 2,
                "status_label": "Ready with cautions",
                "status_class": "warn",
            },
            "review_progress": {
                "total_count": 3,
                "pending_count": 2,
                "approve_count": 1,
                "reviewed_count": 1,
            },
            "review_queue": [
                {
                    "ticker": "BBB",
                    "company": "Beta Builders",
                    "sector": "Industrials",
                    "final_action": "BUY",
                    "final_score": 0.71,
                    "deterministic_score_label": "0.71",
                    "llm_status_label": "LLM agreed",
                    "llm_score_label": "0.68",
                    "risk_status_label": "WARN",
                    "risk_detail": "Gross exposure would be 78% against an 85% warning line.",
                    "top_reasons": [
                        "Abnormal volume 2.3x baseline with positive close.",
                    ],
                    "review_status_label": "Needs review",
                    "is_reviewable": True,
                    "cycle_id": "cycle-live-20260522-1530",
                    "as_of": "2026-05-22T15:28:00+00:00",
                },
                {
                    "ticker": "AAA",
                    "company": "Alpha Apps",
                    "sector": "Technology",
                    "final_action": "BUY",
                    "final_score": 0.82,
                    "deterministic_score_label": "0.80",
                    "llm_status_label": "LLM not run for this ticker",
                    "risk_status_label": "PASS",
                    "risk_detail": "No major risk flag in current pack.",
                    "top_reasons": [
                        "Daily bars show 4.1% breakout above the 20-day range.",
                    ],
                    "review_status_label": "Needs review",
                    "is_reviewable": True,
                    "cycle_id": "cycle-live-20260522-1530",
                    "as_of": "2026-05-22T15:28:30+00:00",
                },
                {
                    "ticker": "CCC",
                    "company": "Core Cloud",
                    "sector": "Software",
                    "final_action": "WATCH",
                    "final_score": 0.76,
                    "deterministic_score_label": "0.76",
                    "llm_status_label": "LLM demoted to watch",
                    "risk_status_label": "BLOCK",
                    "risk_detail": "Position cap would be exceeded by 4.0 percentage points.",
                    "top_reasons": [
                        "One bullish lane, but policy cap blocks an order.",
                    ],
                    "review_status_label": "Audit only",
                    "is_reviewable": False,
                    "cycle_id": "cycle-live-20260522-1530",
                    "as_of": "2026-05-22T15:29:00+00:00",
                },
            ],
            "data_sources": [
                {
                    "name": "Massive live trade slices",
                    "status_label": "Loaded",
                    "status_class": "pass",
                    "freshness_label": "checked 1m ago",
                    "coverage_label": "168/168",
                    "detail": "Live-slice lane is current for the active universe.",
                },
                {
                    "name": "Subscription article analysis",
                    "status_label": "Needs login",
                    "status_class": "warn",
                    "freshness_label": "analysis not run",
                    "coverage_label": "3 links pending",
                    "detail": "Seeking Alpha login is required before opening gated links.",
                },
            ],
            "scheduler": {
                "running_jobs": [],
                "next_jobs": [{"lane": "massive_daily_bars", "eta_label": "after close"}],
            },
            "policy_summary": {
                "max_gross_exposure_pct": 100,
                "cash_reserve_pct": 10,
                "largest_name_cap_pct": 25,
            },
        },
        "execution": {
            "orderable_rows": [
                {"ticker": "AAA", "preview_state": "READY", "notional_label": "$4,200"}
            ],
            "preview_rows": [
                {"ticker": "AAA", "preview_state": "READY", "notional_label": "$4,200"},
                {"ticker": "BBB", "preview_state": "DISABLED", "notional_label": "No paper order"},
            ],
            "summary": {
                "orderable_count": 1,
                "status_label": "One paper preview ready",
                "status_class": "pass",
            },
        },
        "portfolio": {
            "positions": [
                {
                    "ticker": "XYZ",
                    "qty": 4,
                    "current_price": 42.5,
                    "market_value": 170.0,
                    "unrealized_pl_pct": 2.4,
                    "status_label": "Hold",
                    "thesis": "Holding above stop with positive weekly performance.",
                }
            ],
            "summary": {
                "position_count": 1,
                "gross_exposure_pct": 32.5,
                "cash_reserve_pct": 41.0,
            },
        },
        "market": {
            "summary": {
                "headline": "Market balanced; risk-on tilt",
                "status_label": "Balanced",
            },
            "broker": {
                "account": {"buying_power": 25000, "cash": 41000, "equity": 100000},
                "gross_exposure_pct": 32.5,
                "status_label": "Connected",
            },
        },
        "signals": {
            "lanes": [
                {
                    "lane": "technical_analysis",
                    "status_label": "Loaded",
                    "status_class": "pass",
                    "detail": "168/168 tickers scored from daily bars.",
                }
            ]
        },
    }


def test_cockpit_context_has_required_top_level_sections() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert set(context) >= {
        "cycle",
        "market",
        "engines",
        "funnel",
        "candidates",
        "positions",
        "account",
        "sectors",
        "sources",
        "universe_blocked",
        "signals",
        "audit_lifecycle",
        "policy",
        "monitor_events",
        "scenario",
    }


def test_cockpit_context_uses_real_dashboard_sources_not_prototype_data() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    payload = json.dumps(context, sort_keys=True)

    assert context["cycle"]["id"] == "cycle-live-20260522-1530"
    assert "window.COCKPIT_DATA" not in payload
    assert "C-14:32" not in payload
    assert "grossPostTrade" not in payload
    assert "NVDA" not in payload
    assert "Home Depot" not in payload


def test_cockpit_source_rows_use_live_checked_at_as_health_proof() -> None:
    sources = _sample_sources()
    sources["dashboard"]["data_sources"] = [  # type: ignore[index]
        {
            "name": "daily-market-bars",
            "status_label": "HEALTHY",
            "status_class": "pass",
            "freshness": "FRESH",
            "checked_at": "2026-05-22T13:19:42+00:00",
            "coverage_label": "168/168 tickers",
            "detail": "Daily bars are current through the latest completed market session.",
        }
    ]

    context = cockpit_context_from_sources(sources)
    source = context["sources"][0]

    assert source["state"] == "ready"
    assert source["state_label"] == "Usable with proof timestamp"
    assert source["last_pull"] == "2026-05-22T13:19:42+00:00"
    assert source["proof_timestamp"] == "2026-05-22T13:19:42+00:00"
    assert source["coverage"] == "168/168 tickers"


def test_cockpit_candidates_are_sorted_by_final_conviction() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    scores = [row["final_conviction"] for row in context["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert [row["ticker"] for row in context["candidates"]] == ["AAA", "CCC", "BBB"]


def test_cockpit_only_agent_approved_candidates_are_actionable() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    rows = {row["ticker"]: row for row in context["candidates"]}

    assert rows["AAA"]["status"] == "approved"
    assert rows["AAA"]["actionable"] is True
    assert rows["BBB"]["status"] == "demoted"
    assert rows["BBB"]["actionable"] is False
    assert rows["CCC"]["status"] == "blocked"
    assert rows["CCC"]["actionable"] is False
    assert rows["CCC"]["action_label"] == "Open audit"


def test_cockpit_derived_values_are_not_hardcoded() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["funnel"]["final"] == 3
    assert context["funnel"]["actionable"] == 1
    assert context["cycle"]["sources_total"] == 11
    assert context["cycle"]["sources_degraded"] == 2
    assert context["account"]["buying_power"] == 25000.0
    assert context["account"]["ready_to_trade"] == "1/3"


def test_cockpit_account_panel_does_not_invent_missing_broker_or_policy_values() -> None:
    sources = _sample_sources()
    sources["market"]["broker"] = {}  # type: ignore[index]
    sources["dashboard"]["broker_status"] = {}  # type: ignore[index]
    sources["dashboard"]["policy_summary"] = {}  # type: ignore[index]
    sources["portfolio"]["summary"] = {}  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    account = context["account"]

    assert account["equity_reported"] is False
    assert account["policy_reported"] is False
    assert account["buying_power_label"] == "not reported"
    assert account["gross_cap_label"] == "not reported"
    assert account["cash_cap_label"] == "not reported"
    assert account["largest_name_cap_label"] == "not reported"


def test_cockpit_source_counts_are_internally_consistent() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["full_live_readiness"]["warning_count"] = 99

    context = cockpit_context_from_sources(sources)

    assert context["cycle"]["sources_degraded"] <= context["cycle"]["sources_total"]


def test_cockpit_missing_source_proof_never_reads_as_ready() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["data_load_status"] = {
        "status_label": "Source proof unavailable",
        "status_class": "block",
        "source_proof_missing": True,
        "overall_percent": 0,
        "critical_lane_percent": 0,
        "blocker_count": 1,
    }

    context = cockpit_context_from_sources(sources)
    data_state = context["data_state"]

    assert data_state["review"]["ready"] is False
    assert data_state["paper"]["ready"] is False
    assert data_state["overall_percent"] == 0
    assert data_state["top_gaps"][0]["lane"] == "Source proof"
    assert context["scenario"]["state"] == "outage"
    assert "needs attention before review can continue" in context["scenario"]["headline"]
    assert context["scenario"]["primary_action"]["label"] == "Open Diagnostics for Source proof"
    assert context["scenario"]["primary_action"]["url"] == "/command"
    assert context["scenario"]["primary_action"]["method"] == "get"


def test_cockpit_blocker_gap_exposes_concrete_refresh_action() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["data_load_status"] = {
        "status_label": "Blocked",
        "status_class": "block",
        "review_operational_ready": False,
        "tradable_ready": False,
        "overall_percent": 66,
        "critical_lane_percent": 55,
        "blocker_count": 1,
        "blockers": [
            {
                "kind": "dataset",
                "item": "stock_trades",
                "reason": "Massive trade prints source needs refresh for the active universe.",
            }
        ],
    }

    context = cockpit_context_from_sources(sources)
    gap = context["data_state"]["top_gaps"][0]

    assert gap["lane"] == "Live Trade Slices"
    assert gap["refresh_action"]["url"] == "/scheduler/massive-lanes/massive_live_trade_slices/refresh"
    assert gap["refresh_action"]["label"] == "Refresh Live Trade Slices"
    assert context["scenario"]["primary_action"] == gap["refresh_action"]
    assert context["scenario"]["state"] == "status-delayed"
    assert "needs refresh before review can continue" in context["scenario"]["headline"]
    assert "outage" not in context["scenario"]["state"]


def test_cockpit_loading_data_gap_is_not_presented_as_outage() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["data_load_status"] = {
        "status_label": "Loaded With Gaps",
        "status_class": "warn",
        "review_operational_ready": False,
        "tradable_ready": False,
        "overall_percent": 90,
        "critical_lane_percent": 71,
        "blocker_count": 0,
        "warning_count": 1,
        "lane_states": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Massive Live Trade Slices",
                "state": "loading",
                "status_label": "Data is still loading",
                "status_class": "warn",
                "progress_label": "67/78 ticker-days",
                "eta_label": "6m",
                "required_now": True,
                "blocks_execution": True,
                "blocker": True,
                "operator_message": (
                    "Massive Live Trade Slices data is still loading "
                    "(67/78 ticker-days)."
                ),
                "recommended_action": (
                    "Wait for Massive Live Trade Slices to finish, then refresh the dashboard."
                ),
            }
        ],
    }

    context = cockpit_context_from_sources(sources)

    assert context["scenario"]["state"] == "status-delayed"
    assert "data is still loading" in context["scenario"]["headline"]
    assert "outage" not in context["scenario"]["state"]


def test_cockpit_review_queue_is_not_hidden_by_noncritical_engine_warning() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["data_load_status"] = {
        "status_label": "Review ready",
        "status_class": "warn",
        "review_operational_ready": True,
        "tradable_ready": False,
        "overall_percent": 66,
        "critical_lane_percent": 55,
        "lane_states": [
            {
                "lane_id": "massive_block_trade_feed",
                "name": "Massive Block Trade Feed",
                "state": "needs_refresh",
                "status_label": "Lane proof needs refresh",
                "status_class": "block",
                "progress_label": "100% manifest coverage",
                "required_now": True,
                "blocks_execution": True,
                "blocker": True,
                "operator_message": "Block-trade proof needs refresh before paper execution.",
                "refresh_action_url": "/scheduler/massive-lanes/massive_block_trade_feed/refresh",
                "refresh_action_label": "Refresh Block Trade Feed",
            }
        ],
    }
    dashboard["data_sources"] = [
        {
            "name": "activity-alerts",
            "status_label": "UNAVAILABLE",
            "status_class": "block",
            "freshness_label": "UNAVAILABLE",
            "checked_at": "2026-05-08T10:31:58+00:00",
            "detail": "Activity-alerts has not reported today.",
        }
    ]

    context = cockpit_context_from_sources(sources)

    assert context["data_state"]["review"]["ready"] is True
    assert context["scenario"]["state"] == "normal"
    assert "Selection is paused" not in context["scenario"]["headline"]
    assert context["scenario"]["primary_nav_action"]["label"] == "Review 1 ready trade"
    assert context["scenario"]["primary_nav_action"]["phase"] == "candidates"
