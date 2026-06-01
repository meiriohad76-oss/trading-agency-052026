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


def test_actionability_gate_excludes_stale_sources_from_lane_thresholds() -> None:
    gated = apply_actionability_gate(
        [
            _signal("news", "rss", "fresh"),
            _signal("news", "provider", "stale", freshness="STALE"),
        ]
    )

    assert gated[0]["actionability"] == "CONTEXT_ONLY"
    assert "insufficient_independent_sources" in _reason_codes(gated[0])
    assert gated[1]["actionability"] == "CONTEXT_ONLY"
    assert "stale_evidence" in _reason_codes(gated[1])


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


def test_actionability_gate_keeps_fresh_duplicate_regardless_of_input_order() -> None:
    stale = _signal(
        "fundamentals",
        "sec",
        "same",
        freshness="STALE",
        timestamp_as_of="2026-05-07T08:59:00Z",
    )
    fresh = _signal(
        "fundamentals",
        "sec",
        "same",
        freshness="FRESH",
        timestamp_as_of="2026-05-08T08:59:00Z",
    )

    stale_first = apply_actionability_gate([stale, fresh])
    fresh_first = apply_actionability_gate([fresh, stale])

    assert stale_first[0]["actionability"] == "SUPPRESSED"
    assert stale_first[1]["actionability"] == "ACTIONABLE"
    assert fresh_first[0]["actionability"] == "ACTIONABLE"
    assert fresh_first[1]["actionability"] == "SUPPRESSED"


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


def test_actionability_gate_demotes_all_inferred_lanes_when_no_confirmed_signal() -> None:
    """All inferred lanes must be CONTEXT_ONLY when no confirmed signal is present."""
    signals = [
        _signal("abnormal_volume", "alpaca", "src-1", verification_level="INFERRED"),
        _signal("buy_sell_pressure", "massive", "src-2", verification_level="INFERRED"),
        _signal("technical_analysis", "prices", "src-3", verification_level="INFERRED"),
    ]
    gated = apply_actionability_gate(signals)

    for result in gated:
        assert result["actionability"] == "CONTEXT_ONLY", (
            f"Lane {result['lane']} should be CONTEXT_ONLY without a confirmed signal, "
            f"got {result['actionability']}"
        )
        assert "requires_confirmed_corroboration" in _reason_codes(result)


def test_actionability_gate_allows_inferred_lane_when_confirmed_signal_present() -> None:
    """An inferred lane may be ACTIONABLE when a same-direction confirmed signal exists."""
    signals = [
        _signal("fundamentals", "sec", "sec-1"),  # CONFIRMED by default
        _signal("abnormal_volume", "alpaca", "src-1", verification_level="INFERRED"),
    ]
    gated = apply_actionability_gate(signals)

    fundamentals_result = next(r for r in gated if r["lane"] == "fundamentals")
    volume_result = next(r for r in gated if r["lane"] == "abnormal_volume")

    assert fundamentals_result["actionability"] == "ACTIONABLE"
    assert volume_result["actionability"] == "ACTIONABLE"
    assert "requires_confirmed_corroboration" not in _reason_codes(volume_result)


def test_actionability_gate_rejects_opposite_direction_confirmed_corroboration() -> None:
    signals = [
        _signal("fundamentals", "sec", "sec-1", score=-0.8),
        _signal("abnormal_volume", "alpaca", "src-1", verification_level="INFERRED"),
    ]

    gated = apply_actionability_gate(signals)
    volume_result = next(r for r in gated if r["lane"] == "abnormal_volume")

    assert volume_result["actionability"] == "CONTEXT_ONLY"
    assert "requires_confirmed_corroboration" in _reason_codes(volume_result)


def test_actionability_gate_rejects_suppressed_confirmed_corroboration() -> None:
    suppressed_confirmed = _signal("fundamentals", "sec", "blocked")
    suppressed_confirmed["actionability"] = "SUPPRESSED"
    inferred = _signal(
        "abnormal_volume",
        "alpaca",
        "src-1",
        verification_level="INFERRED",
    )

    gated = apply_actionability_gate([suppressed_confirmed, inferred])
    volume_result = next(r for r in gated if r["lane"] == "abnormal_volume")

    assert volume_result["actionability"] == "CONTEXT_ONLY"
    assert "requires_confirmed_corroboration" in _reason_codes(volume_result)


def test_actionability_gate_rejects_confirmed_signal_demoted_by_own_lane_gate() -> None:
    news = _signal("news", "rss", "single-news-source")
    inferred = _signal(
        "technical_analysis",
        "prices",
        "ta-src",
        verification_level="INFERRED",
    )

    gated = apply_actionability_gate([news, inferred])
    news_result = next(r for r in gated if r["lane"] == "news")
    technical_result = next(r for r in gated if r["lane"] == "technical_analysis")

    assert news_result["actionability"] == "CONTEXT_ONLY"
    assert "insufficient_independent_sources" in _reason_codes(news_result)
    assert technical_result["actionability"] == "CONTEXT_ONLY"
    assert "requires_confirmed_corroboration" in _reason_codes(technical_result)


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


def test_actionability_gate_caps_institutional_at_context_only() -> None:
    """Institutional signals must never reach ACTIONABLE because 13F data is 45+ days stale."""
    signal = build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of=AS_OF,
        lane="institutional",
        score=0.9,
        provenance=_provenance("sec", "13f-q1-2026", "FRESH", "CONFIRMED"),
        confidence=0.95,
    )
    # Signal would be ACTIONABLE without the lane cap
    assert signal["actionability"] == "ACTIONABLE"

    gated = apply_actionability_gate([signal])

    assert gated[0]["actionability"] == "CONTEXT_ONLY"
    assert "13f_data_delayed" in _reason_codes(gated[0])
    validate_contract("signal-result", gated[0])


def _reason_codes(signal: dict[str, object]) -> list[str]:
    return cast(list[str], signal["reason_codes"])


def _signal(
    lane: str,
    source: str,
    source_id: str,
    *,
    freshness: str = "FRESH",
    verification_level: str = "CONFIRMED",
    timestamp_as_of: str = "2026-05-08T08:59:00Z",
    score: float = 0.8,
) -> dict[str, object]:
    return build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of=AS_OF,
        lane=lane,
        score=score,
        provenance=_provenance(
            source,
            source_id,
            freshness,
            verification_level,
            timestamp_as_of=timestamp_as_of,
        ),
        confidence=0.9,
        actionability="ACTIONABLE",
    )


def _provenance(
    source: str,
    source_id: str,
    freshness: str,
    verification_level: str,
    *,
    timestamp_as_of: str = "2026-05-08T08:59:00Z",
) -> dict[str, object]:
    source_tier = "INFERRED_FROM_BARS" if verification_level == "INFERRED" else "OFFICIAL_FILING"
    return {
        "source": source,
        "source_tier": source_tier,
        "source_id": source_id,
        "source_url": None,
        "timestamp_observed": "2026-05-08T09:00:00Z",
        "timestamp_as_of": timestamp_as_of,
        "freshness": freshness,
        "confidence": 1.0,
        "verification_level": verification_level,
    }
