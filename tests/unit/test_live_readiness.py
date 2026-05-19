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
