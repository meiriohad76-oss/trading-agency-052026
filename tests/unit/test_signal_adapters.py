from __future__ import annotations

import math

import pytest

from agency.contracts import validate_contract
from agency.services import (
    SignalActionabilityConfig,
    build_signal_result,
    build_signal_results_from_scores,
)


def test_build_signal_result_creates_actionable_contract_payload() -> None:
    signal = build_signal_result(
        cycle_id="cycle-1",
        ticker="aapl",
        as_of="2026-05-07T09:30:00Z",
        lane="fundamentals",
        score=0.7,
        provenance=_provenance(),
        confidence=0.9,
    )

    validate_contract("signal-result", signal)
    assert signal["ticker"] == "AAPL"
    assert signal["direction"] == "BULLISH"
    assert signal["actionability"] == "ACTIONABLE"
    assert signal["suppression_reason"] is None


def test_build_signal_result_can_carry_context_summary() -> None:
    signal = build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        lane="subscription_thesis",
        score=0.65,
        provenance=_provenance(source="subscription-email-thesis"),
        confidence=0.65,
        actionability="CONTEXT_ONLY",
        summary="Subscription article thesis: constructive context for AAPL.",
    )

    validate_contract("signal-result", signal)
    assert signal["summary"] == "Subscription article thesis: constructive context for AAPL."


def test_build_signal_result_suppresses_low_confidence_scores() -> None:
    signal = build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        lane="news",
        score=0.8,
        provenance=_provenance(source="rss"),
        confidence=0.1,
    )

    assert signal["actionability"] == "CONTEXT_ONLY"
    assert signal["suppression_reason"] is None


def test_build_signal_result_allows_custom_thresholds() -> None:
    signal = build_signal_result(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        lane="prepost",
        score=0.2,
        provenance=_provenance(),
        config=SignalActionabilityConfig(actionable_score=0.2),
    )

    assert signal["actionability"] == "ACTIONABLE"


def test_build_signal_results_from_scores_is_sorted_and_requires_provenance() -> None:
    signals = build_signal_results_from_scores(
        cycle_id="cycle-1",
        as_of="2026-05-07T09:30:00Z",
        lane="momentum",
        scores={"MSFT": -0.8, "aapl": 0.7},
        provenance_by_ticker={"AAPL": _provenance(), "MSFT": _provenance(source="prices")},
    )

    assert [signal["ticker"] for signal in signals] == ["AAPL", "MSFT"]
    assert signals[1]["direction"] == "BEARISH"

    with pytest.raises(KeyError, match="MSFT"):
        build_signal_results_from_scores(
            cycle_id="cycle-1",
            as_of="2026-05-07T09:30:00Z",
            lane="momentum",
            scores={"MSFT": -0.8},
            provenance_by_ticker={},
        )


@pytest.mark.parametrize("bad_score", [math.nan, math.inf, -math.inf])
def test_build_signal_result_rejects_non_finite_scores(bad_score: float) -> None:
    with pytest.raises(ValueError, match="score must be finite"):
        build_signal_result(
            cycle_id="cycle-1",
            ticker="AAPL",
            as_of="2026-05-07T09:30:00Z",
            lane="momentum",
            score=bad_score,
            provenance=_provenance(),
        )


def _provenance(source: str = "sec-edgar") -> dict[str, object]:
    return {
        "source": source,
        "source_tier": "OFFICIAL_FILING",
        "source_id": f"{source}-1",
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
