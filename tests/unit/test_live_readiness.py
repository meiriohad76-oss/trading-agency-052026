from __future__ import annotations

from agency.runtime import build_live_readiness


def test_live_readiness_ready_for_paper_validation() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
    )

    assert summary["ready"] is True
    assert summary["verdict"] == "ready_for_paper_validation"
    assert summary["cycle_id"] == "cycle-new"
    assert summary["reviewable_candidate_count"] == 1
    assert summary["open_risk_decision_count"] == 1
    assert summary["blockers"] == []


def test_live_readiness_marks_stale_sources_context_only() -> None:
    summary = build_live_readiness(
        source_health=[
            _source("daily-market-bars", status="UNAVAILABLE", freshness="UNAVAILABLE")
        ],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH", source="daily-market-bars")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
    )

    blockers = summary["blockers"]

    assert summary["ready"] is False
    assert summary["verdict"] == "context_only_source_health"
    assert isinstance(blockers, list)
    assert blockers[0]["kind"] == "source_health"
    assert summary["degraded_source_count"] == 1


def test_live_readiness_blocks_on_provider_unavailable_lane_state() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
        lane_states=[
            {
                "lane_id": "massive_live_trade_slices",
                "lane_kind": "raw_acquisition",
                "blocker": True,
                "status_class": "block",
                "state": "provider_unavailable",
                "operator_message": (
                    "Massive Live Trade Slices provider is unavailable."
                ),
            }
        ],
    )

    assert summary["ready"] is False
    assert summary["verdict"] == "context_only_lane_state"
    assert summary["blockers"][0]["kind"] == "raw_acquisition"
    assert "unavailable" in str(summary["detail"])


def test_live_readiness_treats_needs_refresh_lane_as_review_caution() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
        lane_states=[
            {
                "lane_id": "massive_live_trade_slices",
                "lane_kind": "raw_acquisition",
                "blocker": True,
                "status_class": "block",
                "state": "needs_refresh",
                "operator_message": (
                    "Massive Live Trade Slices analysis exists but needs refresh."
                ),
            }
        ],
    )

    assert summary["ready"] is True
    assert summary["verdict"] == "ready_for_paper_validation"
    assert summary["lane_state_blocker_count"] == 0
    assert summary["blockers"] == []


def test_live_readiness_does_not_block_on_context_lane_waiting_for_analysis() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
        lane_states=[
            {
                "lane_id": "sector_momentum",
                "lane_kind": "derived_signal",
                "blocker": False,
                "blocks_execution": False,
                "state": "loaded_unanalyzed",
                "operator_message": (
                    "Sector Momentum source data exists, but the agent has not produced current analysis."
                ),
            }
        ],
    )

    assert summary["ready"] is True
    assert summary["verdict"] == "ready_for_paper_validation"
    assert summary["lane_state_blocker_count"] == 0
    assert summary["blockers"] == []


def test_live_readiness_blocks_old_critical_source_health_even_if_marked_fresh() -> None:
    summary = build_live_readiness(
        source_health=[
            _source(
                "daily-market-bars",
                status="HEALTHY",
                freshness="FRESH",
                checked_at="2000-01-01T00:00:00Z",
            )
        ],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH", source="daily-market-bars")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
    )

    blockers = summary["blockers"]

    assert summary["ready"] is False
    assert summary["verdict"] == "context_only_source_health"
    assert isinstance(blockers, list)
    assert blockers[0]["kind"] == "source_health"
    assert "checked_at" in str(blockers[0]["reason"])


def test_live_readiness_accepts_old_critical_source_health_with_lane_proof() -> None:
    summary = build_live_readiness(
        source_health=[
            _source(
                "daily-market-bars",
                status="HEALTHY",
                freshness="FRESH",
                checked_at="2000-01-01T00:00:00Z",
            )
        ],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH", source="daily-market-bars")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
        lane_states=[
            {
                "lane_id": "massive_daily_bars",
                "lane_kind": "raw_acquisition",
                "state": "ready_for_review",
                "ready_for_review": True,
                "blocker": False,
            }
        ],
    )

    assert summary["ready"] is True
    assert summary["verdict"] == "ready_for_paper_validation"
    assert summary["blockers"] == []


def test_live_readiness_does_not_block_on_noncritical_source_staleness() -> None:
    summary = build_live_readiness(
        source_health=[_source("rss-news", status="STALE", freshness="STALE")],
        selection_reports=[_report("cycle-new", "AAPL", "WATCH", source="rss-news")],
        risk_decisions=[_risk("cycle-new", "AAPL", "WARN")],
    )

    assert summary["ready"] is True
    assert summary["verdict"] == "ready_for_paper_validation"
    assert summary["degraded_source_count"] == 1
    assert summary["blockers"] == []


def test_live_readiness_uses_latest_cycle_only() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[
            _report("cycle-new", "MSFT", "NO_TRADE"),
            _report("cycle-old", "AAPL", "WATCH"),
        ],
        risk_decisions=[
            _risk("cycle-new", "MSFT", "BLOCK"),
            _risk("cycle-old", "AAPL", "ALLOW"),
        ],
    )

    assert summary["cycle_id"] == "cycle-new"
    assert summary["verdict"] == "cycle_waiting_for_candidates"
    assert summary["reviewable_candidate_count"] == 0
    assert summary["open_risk_decision_count"] == 0


def test_live_readiness_prefers_live_pit_cycles() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[
            _report("manual-smoke-t74", "MSFT", "WATCH"),
            _report("live-pit-2025-12-31", "AAPL", "WATCH"),
        ],
        risk_decisions=[
            _risk("manual-smoke-t74", "MSFT", "WARN"),
            _risk("live-pit-2025-12-31", "AAPL", "ALLOW"),
        ],
    )

    assert summary["cycle_id"] == "live-pit-2025-12-31"
    assert summary["ready"] is True


def test_live_readiness_prefers_newer_full_active_cycle_over_old_live_pit() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[
            _report("live-pit-2026-05-19-20260519T124015Z", "MSFT", "WATCH"),
            _report("full-active-refresh-20260524T0625Z", "AAPL", "WATCH"),
        ],
        risk_decisions=[
            _risk("live-pit-2026-05-19-20260519T124015Z", "MSFT", "WARN"),
            _risk("full-active-refresh-20260524T0625Z", "AAPL", "WARN"),
        ],
    )

    assert summary["cycle_id"] == "full-active-refresh-20260524T0625Z"
    assert summary["ready"] is True


def test_live_readiness_prefers_operational_cycle_over_newer_manual_smoke() -> None:
    summary = build_live_readiness(
        source_health=[_source("sec-edgar", status="HEALTHY", freshness="FRESH")],
        selection_reports=[
            _report("manual-smoke-20260524T090000Z", "MSFT", "WATCH"),
            _report("live-pit-2026-05-23-20260523T210000Z", "AAPL", "WATCH"),
        ],
        risk_decisions=[
            _risk("manual-smoke-20260524T090000Z", "MSFT", "WARN"),
            _risk("live-pit-2026-05-23-20260523T210000Z", "AAPL", "WARN"),
        ],
    )

    assert summary["cycle_id"] == "live-pit-2026-05-23-20260523T210000Z"
    assert summary["ready"] is True


def test_live_readiness_ignores_sources_not_used_by_latest_cycle() -> None:
    summary = build_live_readiness(
        source_health=[
            _source("sec-edgar", status="HEALTHY", freshness="FRESH"),
            _source("activity-alerts", status="UNAVAILABLE", freshness="UNAVAILABLE"),
        ],
        selection_reports=[_report("live-pit-2025-12-31", "AAPL", "WATCH")],
        risk_decisions=[_risk("live-pit-2025-12-31", "AAPL", "WARN")],
    )

    assert summary["ready"] is True
    assert summary["source_count"] == 1
    assert summary["degraded_source_count"] == 0


def test_live_readiness_reports_missing_cycle() -> None:
    summary = build_live_readiness(
        source_health=[],
        selection_reports=[],
        risk_decisions=[],
    )

    assert summary["ready"] is False
    assert summary["verdict"] == "no_runtime_cycle"
    assert summary["cycle_id"] is None


def _source(
    source: str,
    *,
    status: str,
    freshness: str,
    checked_at: str = "2099-01-01T00:00:00Z",
) -> dict[str, object]:
    return {
        "source": source,
        "status": status,
        "freshness": freshness,
        "checked_at": checked_at,
        "notes": [f"{source} note"],
    }


def _report(
    cycle_id: str,
    ticker: str,
    action: str,
    *,
    source: str = "sec-edgar",
) -> dict[str, object]:
    return {
        "cycle_id": cycle_id,
        "ticker": ticker,
        "final_action": action,
        "evidence_pack": {
            "actionable_signals": [_signal(ticker, source)],
            "context_signals": [],
            "suppressed_signals": [],
        },
    }


def _risk(cycle_id: str, ticker: str, decision: str) -> dict[str, object]:
    return {"cycle_id": cycle_id, "ticker": ticker, "decision": decision}


def _signal(ticker: str, source: str) -> dict[str, object]:
    return {"ticker": ticker, "provenance": {"source": source}}
