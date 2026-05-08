from __future__ import annotations

from agency.services import (
    DeterministicRuleConfig,
    build_evidence_pack,
    build_signal_result,
    evaluate_deterministic_rules,
)

EXPECTED_WEIGHTED_SCORE = 0.466667


def test_deterministic_rules_weight_actionable_signals() -> None:
    pack = build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[
            _signal("fundamentals", 0.8),
            _signal("insider", -0.2),
        ],
    )

    result = evaluate_deterministic_rules(
        pack,
        config=DeterministicRuleConfig(
            watch_threshold=0.45,
            lane_weights={"fundamentals": 2.0, "insider": 1.0},
        ),
    )

    assert result.decision["action"] == "WATCH"
    assert result.decision["score"] == EXPECTED_WEIGHTED_SCORE


def test_deterministic_rules_block_when_data_quality_blocks() -> None:
    pack = build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[],
    )

    result = evaluate_deterministic_rules(pack)

    assert result.decision["action"] == "NO_TRADE"
    assert result.decision["reason_codes"] == ["policy_gate_blocked"]
    assert "no_signal_results" in result.decision["blockers"]


def test_deterministic_rules_demote_stale_signal_before_selection() -> None:
    pack = build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[_signal("fundamentals", 0.8, freshness="STALE")],
    )

    result = evaluate_deterministic_rules(pack)

    assert result.decision["action"] == "NO_TRADE"
    assert result.decision["reason_codes"] == ["no_actionable_signals"]
    assert {"name": "freshness", "status": "WARN", "reason": "stale"} in result.policy_gates


def _signal(lane: str, score: float, freshness: str = "FRESH") -> dict[str, object]:
    return build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        lane=lane,
        score=score,
        provenance=_provenance(lane, freshness),
        confidence=0.9,
        actionability="ACTIONABLE",
    )


def _provenance(source: str, freshness: str) -> dict[str, object]:
    return {
        "source": source,
        "source_tier": "OFFICIAL_FILING",
        "source_id": f"{source}-1",
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": freshness,
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
