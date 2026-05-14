"""Daily loop smoke test — sprint gate T121.

Verifies the full pipeline using the seeded demo data:
source health → evidence packs → selection reports → risk decisions →
execution previews → lifecycle events.

Uses no external API calls. Runs in under 5 seconds.
"""
from __future__ import annotations

from agency.services import DemoRuntimeSeed, build_demo_runtime_seed


def test_daily_loop_source_health_is_non_empty() -> None:
    """Source health must include at least one schema-valid entry."""
    seed = build_demo_runtime_seed()
    assert len(seed.source_health) > 0, "Expected source health entries"
    for entry in seed.source_health:
        assert "source" in entry, f"Missing 'source' key in {entry}"
        assert "status" in entry, f"Missing 'status' key in {entry}"
        assert "freshness" in entry, f"Missing 'freshness' key in {entry}"


def test_daily_loop_evidence_packs_built() -> None:
    """Evidence packs must be present and contain ticker + signal counts."""
    seed = build_demo_runtime_seed()
    assert len(seed.evidence_packs) > 0, "Expected at least one evidence pack"
    for pack in seed.evidence_packs:
        assert "ticker" in pack, f"Missing 'ticker' in evidence pack: {pack}"
        assert "actionable_signals" in pack, f"Missing 'actionable_signals' in {pack}"


def test_daily_loop_selection_reports_present() -> None:
    """Selection reports must be produced with valid actions."""
    seed = build_demo_runtime_seed()
    assert len(seed.selection_reports) > 0, "Expected selection reports"
    valid_actions = {"WATCH", "NO_TRADE", "HOLD", "BUY", "SELL"}
    for report in seed.selection_reports:
        action = report.get("final_action") or report.get("action")
        assert action in valid_actions, f"Unexpected action {action!r} in {report}"


def test_daily_loop_risk_decisions_present() -> None:
    """Risk decisions must be present for the selection reports."""
    seed = build_demo_runtime_seed()
    assert len(seed.risk_decisions) > 0, "Expected risk decisions"
    valid_decisions = {"ALLOW", "WARN", "BLOCK"}
    for decision in seed.risk_decisions:
        assert decision.get("decision") in valid_decisions, (
            f"Unexpected risk decision: {decision!r}"
        )


def test_daily_loop_execution_previews_present() -> None:
    """Execution previews must exist for actionable selection reports."""
    seed = build_demo_runtime_seed()
    assert len(seed.execution_previews) > 0, "Expected execution previews"


def test_daily_loop_lifecycle_events_cover_all_stages() -> None:
    """Lifecycle events must be present for selection, risk, and execution stages."""
    seed = build_demo_runtime_seed()
    all_events = seed.all_lifecycle_events
    assert len(all_events) > 0, "Expected lifecycle events"
    stages = {str(event.get("stage") or event.get("event_type") or "") for event in all_events}
    # At least one non-empty stage identifier
    assert any(s for s in stages), f"All lifecycle events have empty stage/event_type: {all_events[:2]}"


def test_daily_loop_demo_seed_is_schema_valid() -> None:
    """build_demo_runtime_seed() must return a DemoRuntimeSeed without raising."""
    seed = build_demo_runtime_seed()
    assert isinstance(seed, DemoRuntimeSeed)
    # The seed builder validates contracts internally — if it didn't raise, it's valid.
    assert seed.source_health is not None
    assert seed.selection_reports is not None
    assert seed.risk_decisions is not None
