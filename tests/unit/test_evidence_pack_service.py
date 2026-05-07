from __future__ import annotations

import copy

import pytest

from agency.contracts import ContractValidationError, validate_contract
from agency.services import build_evidence_pack


def test_build_evidence_pack_partitions_signals_and_validates_contract() -> None:
    actionable = _signal_result("fundamentals", "ACTIONABLE", "CONFIRMED", "FRESH")
    context = _signal_result("news", "CONTEXT_ONLY", "INFERRED", "AGING")
    suppressed = _signal_result("prepost", "SUPPRESSED", "INFERRED", "STALE")

    pack = build_evidence_pack(
        cycle_id="cycle-1",
        ticker="aapl",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[actionable, context, suppressed],
    )

    validate_contract("evidence-pack", pack)
    assert pack["ticker"] == "AAPL"
    assert len(pack["actionable_signals"]) == 1
    assert len(pack["context_signals"]) == 1
    assert len(pack["suppressed_signals"]) == 1
    assert pack["data_quality"] == {
        "freshness": "STALE",
        "source_count": 3,
        "confirmed_signal_count": 1,
        "inferred_signal_count": 2,
        "blockers": [],
    }


def test_build_evidence_pack_adds_blocker_when_no_signals_exist() -> None:
    pack = build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[],
    )

    assert pack["data_quality"] == {
        "freshness": "UNAVAILABLE",
        "source_count": 0,
        "confirmed_signal_count": 0,
        "inferred_signal_count": 0,
        "blockers": ["no_signal_results"],
    }


def test_build_evidence_pack_rejects_invalid_signal_result() -> None:
    signal = _signal_result("fundamentals", "ACTIONABLE", "CONFIRMED", "FRESH")
    signal["ticker"] = "bad ticker"

    with pytest.raises(ContractValidationError):
        build_evidence_pack(
            cycle_id="cycle-1",
            ticker="AAPL",
            as_of="2026-05-07T09:30:00Z",
            generated_at="2026-05-07T09:31:00Z",
            signals=[signal],
        )


def test_build_evidence_pack_rejects_identity_mismatch() -> None:
    signal = _signal_result("fundamentals", "ACTIONABLE", "CONFIRMED", "FRESH")
    signal["ticker"] = "MSFT"

    with pytest.raises(ValueError, match="ticker"):
        build_evidence_pack(
            cycle_id="cycle-1",
            ticker="AAPL",
            as_of="2026-05-07T09:30:00Z",
            generated_at="2026-05-07T09:31:00Z",
            signals=[signal],
        )


def _signal_result(
    lane: str,
    actionability: str,
    verification_level: str,
    freshness: str,
) -> dict[str, object]:
    signal = {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "lane": lane,
        "score": 0.7,
        "direction": "BULLISH",
        "actionability": actionability,
        "source_tier": "OFFICIAL_FILING",
        "verification_level": verification_level,
        "freshness": freshness,
        "confidence": 0.9,
        "provenance": _provenance(lane, freshness, verification_level),
        "reason_codes": [f"{lane}_positive"],
        "suppression_reason": None,
    }
    if actionability == "SUPPRESSED":
        signal["suppression_reason"] = "below actionability threshold"
    return signal


def _provenance(source: str, freshness: str, verification_level: str) -> dict[str, object]:
    provenance = {
        "source": source,
        "source_tier": "OFFICIAL_FILING",
        "source_id": f"{source}-1",
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": freshness,
        "confidence": 1.0,
        "verification_level": verification_level,
    }
    return copy.deepcopy(provenance)
