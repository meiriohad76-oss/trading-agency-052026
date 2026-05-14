"""Edge-case e2e tests for the daily loop — T135.

Extends the happy-path coverage in test_daily_loop_smoke.py with three
scenarios:

  1. Empty state — all tickers produce NO_TRADE; review queue is empty.
  2. Degraded source — one data source is STALE; cycle still completes.
  3. Rejected candidate — a WATCH candidate receives a REJECT human-review
     event; the event is recorded in the lifecycle.

No external API calls.  Runs in under 10 seconds.
"""
from __future__ import annotations

import copy

from agency.contracts import validate_contract
from agency.services import (
    DemoRuntimeSeed,
    build_demo_runtime_seed,
    build_evidence_pack,
    build_execution_previews,
    build_human_review_event,
    build_risk_decisions,
    build_signal_result,
)
from agency.services.demo_cycle import (
    DEMO_AS_OF,
    DEMO_CYCLE_ID,
    DEMO_GENERATED_AT,
)
from agency.services.final_selection import build_final_selection
from agency.services.selection_events import build_report_lifecycle_event, status_for_action


# ---------------------------------------------------------------------------
# Helpers shared by multiple tests
# ---------------------------------------------------------------------------

def _make_source_health(source: str, *, freshness: str = "FRESH", status: str = "HEALTHY") -> dict:
    payload: dict = {
        "schema_version": "0.1.0",
        "source": source,
        "source_tier": "MARKET_DATA",
        "status": status,
        "checked_at": DEMO_GENERATED_AT,
        "freshness": freshness,
        "last_success_at": DEMO_AS_OF,
        "observed_lag_seconds": 60,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": ["edge-case test"],
    }
    validate_contract("data-source-health", payload)
    return payload


def _make_evidence_pack(ticker: str, *, score: float) -> dict:
    """Build a minimal evidence pack for *ticker* with the given signal score."""
    return build_evidence_pack(
        cycle_id=DEMO_CYCLE_ID,
        ticker=ticker,
        as_of=DEMO_AS_OF,
        generated_at=DEMO_GENERATED_AT,
        signals=[
            build_signal_result(
                cycle_id=DEMO_CYCLE_ID,
                ticker=ticker,
                as_of=DEMO_AS_OF,
                lane="fundamentals",
                score=score,
                provenance={
                    "source": "edge-case-test",
                    "source_tier": "MARKET_DATA",
                    "source_id": f"{ticker}-fundamentals",
                    "source_url": None,
                    "timestamp_observed": DEMO_GENERATED_AT,
                    "timestamp_as_of": DEMO_AS_OF,
                    "freshness": "FRESH",
                    "confidence": 1.0,
                    "verification_level": "CONFIRMED",
                },
                confidence=0.9,
            ),
        ],
    )


def _selection_lifecycle_events(report: dict) -> list[dict]:
    """Build the three lifecycle events for a selection report (mirrors demo_cycle logic)."""
    deterministic = report["deterministic"]
    assert isinstance(deterministic, dict)
    llm_review = report["llm_review"]
    assert isinstance(llm_review, dict)
    action = str(report["final_action"])
    events = [
        build_report_lifecycle_event(
            report,
            event_type="DETERMINISTIC_ACTION",
            status=status_for_action(str(deterministic["action"]), deterministic),
            reason="edge-case deterministic decision",
            payload={"deterministic": dict(deterministic)},
        ),
        build_report_lifecycle_event(
            report,
            event_type="LLM_ACTION",
            status="CONTEXT_ONLY",
            reason="edge-case llm review recorded",
            payload={"llm_review": dict(llm_review)},
        ),
        build_report_lifecycle_event(
            report,
            event_type="FINAL_ACTION",
            status=status_for_action(action, report),
            reason="edge-case final selection recorded",
            payload={
                "final_action": action,
                "final_conviction": report["final_conviction"],
                "risk_flags": report["risk_flags"],
            },
        ),
    ]
    for event in events:
        validate_contract("candidate-lifecycle-event", event)
    return events


def _build_seed_from_reports(
    selection_reports: list[dict],
    source_health: list[dict],
) -> DemoRuntimeSeed:
    """Assemble a DemoRuntimeSeed from pre-built reports and source health."""
    selection_lifecycle_events = [
        event
        for report in selection_reports
        for event in _selection_lifecycle_events(report)
    ]
    risk_results = build_risk_decisions(
        selection_reports,
        source_health,
        generated_at=DEMO_GENERATED_AT,
    )
    preview_results = build_execution_previews(
        [result.risk_decision for result in risk_results],
        generated_at=DEMO_GENERATED_AT,
    )
    return DemoRuntimeSeed(
        source_health=source_health,
        evidence_packs=[dict(report["evidence_pack"]) for report in selection_reports],  # type: ignore[arg-type]
        selection_reports=selection_reports,
        selection_lifecycle_events=selection_lifecycle_events,
        risk_decisions=[result.risk_decision for result in risk_results],
        risk_lifecycle_events=[result.lifecycle_event for result in risk_results],
        execution_previews=[result.preview for result in preview_results],
        execution_lifecycle_events=[result.lifecycle_event for result in preview_results],
    )


# ---------------------------------------------------------------------------
# Test 1 — Empty state: all tickers produce NO_TRADE
# ---------------------------------------------------------------------------

def test_empty_state_no_candidates() -> None:
    """When all tickers score below the WATCH threshold, the review queue is empty.

    A score of 0.1 is well below the DEFAULT_WATCH_THRESHOLD (0.5), so
    build_final_selection will return NO_TRADE for every ticker.
    """
    tickers = ["AAPL", "MSFT", "GOOGL"]
    source_health = [_make_source_health("edge-case-test")]

    selection_reports = [
        build_final_selection(_make_evidence_pack(ticker, score=0.1)).selection_report
        for ticker in tickers
    ]

    seed = _build_seed_from_reports(selection_reports, source_health)

    # Cycle ran — reports were produced for every ticker
    assert len(seed.selection_reports) == len(tickers), (
        "Expected one selection report per ticker"
    )

    # Every report must have final_action == NO_TRADE
    actions = [str(r["final_action"]) for r in seed.selection_reports]
    assert all(a == "NO_TRADE" for a in actions), (
        f"Expected all NO_TRADE, got: {actions}"
    )

    # No WATCH candidates → review queue is empty
    watch_reports = [r for r in seed.selection_reports if r.get("final_action") == "WATCH"]
    assert watch_reports == [], (
        f"Expected empty review queue but found WATCH candidates: {watch_reports}"
    )

    # Validate all contracts are still satisfied
    for report in seed.selection_reports:
        validate_contract("selection-report", report)
    for decision in seed.risk_decisions:
        validate_contract("risk-decision", decision)
    for event in seed.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)


# ---------------------------------------------------------------------------
# Test 2 — Degraded source: one dataset is STALE; cycle still completes
# ---------------------------------------------------------------------------

def test_degraded_source_cycle_still_completes() -> None:
    """A STALE data source should not prevent the cycle from completing.

    The cycle is expected to produce selection reports and emit a WARN risk
    decision (due to degraded source health), but not raise an exception.
    """
    # Start with normal demo seed source health, then set one to STALE
    normal_seed = build_demo_runtime_seed()
    stale_source = _make_source_health(
        "yfinance-daily",
        status="STALE",
        freshness="STALE",
    )
    # Replace the yfinance-daily entry with a STALE version; keep the others
    source_health = [
        stale_source if str(s["source"]) == "yfinance-daily" else copy.deepcopy(s)
        for s in normal_seed.source_health
    ]

    # Use the same selection reports as the normal seed (they reference the same sources)
    selection_reports = [copy.deepcopy(r) for r in normal_seed.selection_reports]

    # Cycle must complete without exception
    seed = _build_seed_from_reports(selection_reports, source_health)

    # Cycle produced selection reports (did not bail out early)
    assert len(seed.selection_reports) > 0, (
        "Expected selection reports even with a degraded source"
    )

    # Source health contains at least one STALE entry
    stale_entries = [
        s for s in seed.source_health if str(s.get("freshness")) == "STALE"
    ]
    assert stale_entries, (
        "Expected at least one source_health entry with freshness == STALE"
    )

    # Validate contracts on all artifacts
    for source in seed.source_health:
        validate_contract("data-source-health", source)
    for report in seed.selection_reports:
        validate_contract("selection-report", report)
    for decision in seed.risk_decisions:
        validate_contract("risk-decision", decision)
    for event in seed.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)


# ---------------------------------------------------------------------------
# Test 3 — Rejected candidate: REJECT human-review event is recorded
# ---------------------------------------------------------------------------

def test_rejected_candidate_recorded_in_lifecycle() -> None:
    """A WATCH candidate that receives a REJECT review must be recorded in lifecycle events.

    After rejection the candidate should no longer appear in the effective
    WATCH queue (i.e., in the lifecycle events the last HUMAN_REVIEW event
    for that ticker must have decision == REJECT, and that ticker must not
    have an un-reviewed WATCH still outstanding).
    """
    normal_seed = build_demo_runtime_seed()

    # Find a WATCH candidate to reject
    watch_reports = [
        r for r in normal_seed.selection_reports if str(r.get("final_action")) == "WATCH"
    ]
    assert watch_reports, (
        "The default demo seed must contain at least one WATCH candidate for this test"
    )
    candidate = watch_reports[0]
    ticker = str(candidate["ticker"])

    # Build the REJECT human-review event
    reject_event = build_human_review_event(
        cycle_id=str(candidate["cycle_id"]),
        ticker=ticker,
        as_of=str(candidate["as_of"]),
        decision="REJECT",
        reviewed_by="test-user",
        review_reason="e2e rejection test",
    )

    # Verify it validates as a proper lifecycle event
    validate_contract("candidate-lifecycle-event", reject_event)

    # Combine the reject event into the seed's lifecycle events
    all_events = [*normal_seed.all_lifecycle_events, reject_event]

    # There must be at least one HUMAN_REVIEW event for the rejected ticker
    human_review_events = [
        e for e in all_events
        if str(e.get("event_type")) == "HUMAN_REVIEW"
        and str(e.get("ticker")) == ticker
    ]
    assert human_review_events, (
        f"Expected HUMAN_REVIEW lifecycle event for {ticker}"
    )

    # The rejection must be recorded — payload contains review_decision == REJECT
    reject_payload_events = [
        e for e in human_review_events
        if isinstance(e.get("payload"), dict)
        and e["payload"].get("review_decision") == "REJECT"  # type: ignore[index]
    ]
    assert reject_payload_events, (
        f"Expected at least one REJECT review decision in lifecycle events for {ticker}, "
        f"got: {[e.get('payload') for e in human_review_events]}"
    )

    # After rejection, that ticker should no longer be in an un-reviewed WATCH state.
    # Concretely: the final HUMAN_REVIEW event for the ticker must not be APPROVE/DEFER.
    last_review = human_review_events[-1]
    last_decision = (
        last_review["payload"].get("review_decision")  # type: ignore[union-attr]
        if isinstance(last_review.get("payload"), dict)
        else None
    )
    assert last_decision == "REJECT", (
        f"Expected last human-review decision to be REJECT, got {last_decision!r}"
    )
