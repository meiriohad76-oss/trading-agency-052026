from __future__ import annotations

from typing import cast

from agency.contracts import validate_contract
from agency.services import (
    ActionabilityGateConfig,
    LaneActionabilityRule,
    apply_actionability_gate,
    build_signal_result,
)

AS_OF = "2026-05-08T09:30:00Z"


def test_actionability_gate_allows_official_single_source_lane() -> None:
    gated = apply_actionability_gate([_signal("fundamentals", "sec", "sec-1")])

    assert gated[0]["actionability"] == "ACTIONABLE"
    assert gated[0]["suppression_reason"] is None
    validate_contract("signal-result", gated[0])


def test_actionability_gate_requires_two_independent_news_sources() -> None:
    one_source = apply_actionability_gate([_signal("news", "rss", "one")])
    two_sources = apply_actionability_gate(
        [
            _signal("news", "rss", "one"),
            _signal("news", "provider", "two"),
        ]
    )

    assert one_source[0]["actionability"] == "CONTEXT_ONLY"
    assert "insufficient_independent_sources" in _reason_codes(one_source[0])
    assert [signal["actionability"] for signal in two_sources] == ["ACTIONABLE", "ACTIONABLE"]


def test_actionability_gate_suppresses_duplicate_source_for_same_lane() -> None:
    gated = apply_actionability_gate(
        [
            _signal("fundamentals", "sec", "same"),
            _signal("fundamentals", "sec", "same"),
        ]
    )

    assert gated[0]["actionability"] == "ACTIONABLE"
    assert gated[1]["actionability"] == "SUPPRESSED"
    assert gated[1]["suppression_reason"] == "duplicate_signal_source"


def test_actionability_gate_demotes_stale_and_unavailable_sources() -> None:
    gated = apply_actionability_gate(
        [
            _signal("fundamentals", "sec", "stale", freshness="STALE"),
            _signal("insider", "sec", "missing", freshness="UNAVAILABLE"),
        ]
    )

    assert gated[0]["actionability"] == "CONTEXT_ONLY"
    assert gated[0]["suppression_reason"] is None
    assert gated[1]["actionability"] == "SUPPRESSED"
    assert gated[1]["suppression_reason"] == "source_unavailable"


def test_actionability_gate_requires_confirmed_corroboration_for_inferred_signal() -> None:
    inferred_only = apply_actionability_gate(
        [_signal("abnormal_volume", "bars", "one", verification_level="INFERRED")]
    )
    corroborated = apply_actionability_gate(
        [
            _signal("abnormal_volume", "bars", "one", verification_level="INFERRED"),
            _signal("fundamentals", "sec", "confirmed"),
        ]
    )

    assert inferred_only[0]["actionability"] == "CONTEXT_ONLY"
    assert "requires_confirmed_corroboration" in _reason_codes(inferred_only[0])
    assert corroborated[0]["actionability"] == "ACTIONABLE"


def test_actionability_gate_treats_market_flow_as_inferred_corroborating_lane() -> None:
    gated = apply_actionability_gate(
        [
            _signal("buy_sell_pressure", "massive", "flow", verification_level="INFERRED"),
            _signal("fundamentals", "sec", "confirmed"),
        ]
    )

    assert gated[0]["actionability"] == "ACTIONABLE"


def test_actionability_gate_accepts_custom_lane_thresholds() -> None:
    config = ActionabilityGateConfig(
        lane_rules={"custom": LaneActionabilityRule(min_sources=2, min_confirmed_sources=1)}
    )

    gated = apply_actionability_gate([_signal("custom", "one", "one")], config=config)

    assert gated[0]["actionability"] == "CONTEXT_ONLY"
    assert "insufficient_independent_sources" in _reason_codes(gated[0])


def _reason_codes(signal: dict[str, object]) -> list[str]:
    return cast(list[str], signal["reason_codes"])


def _signal(
    lane: str,
    source: str,
    source_id: str,
    *,
    freshness: str = "FRESH",
    verification_level: str = "CONFIRMED",
) -> dict[str, object]:
    return build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of=AS_OF,
        lane=lane,
        score=0.8,
        provenance=_provenance(source, source_id, freshness, verification_level),
        confidence=0.9,
        actionability="ACTIONABLE",
    )


def _provenance(
    source: str,
    source_id: str,
    freshness: str,
    verification_level: str,
) -> dict[str, object]:
    source_tier = "INFERRED_FROM_BARS" if verification_level == "INFERRED" else "OFFICIAL_FILING"
    return {
        "source": source,
        "source_tier": source_tier,
        "source_id": source_id,
        "source_url": None,
        "timestamp_observed": "2026-05-08T09:00:00Z",
        "timestamp_as_of": "2026-05-08T08:59:00Z",
        "freshness": freshness,
        "confidence": 1.0,
        "verification_level": verification_level,
    }
