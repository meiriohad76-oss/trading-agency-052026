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
    assert rows["BBB"]["status"] == "approved"
    assert rows["BBB"]["actionable"] is True
    assert rows["CCC"]["status"] == "blocked"
    assert rows["CCC"]["actionable"] is False
    assert rows["CCC"]["action_label"] == "Open audit"


def test_cockpit_derived_values_are_not_hardcoded() -> None:
    context = cockpit_context_from_sources(_sample_sources())

    assert context["funnel"]["final"] == 3
    assert context["funnel"]["actionable"] == 2
    assert context["cycle"]["sources_total"] == 11
    assert context["cycle"]["sources_degraded"] == 2
    assert context["account"]["buying_power"] == 25000.0
    assert context["account"]["ready_to_trade"] == "1/3"


def test_cockpit_source_counts_are_internally_consistent() -> None:
    sources = _sample_sources()
    dashboard = sources["dashboard"]
    dashboard["full_live_readiness"]["warning_count"] = 99

    context = cockpit_context_from_sources(sources)

    assert context["cycle"]["sources_degraded"] <= context["cycle"]["sources_total"]
