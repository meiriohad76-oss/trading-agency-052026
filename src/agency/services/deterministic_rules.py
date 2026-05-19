from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from agency.contracts import validate_contract

DEFAULT_LANE_WEIGHTS: Mapping[str, float] = {
    "fundamentals": 1.2,
    "institutional": 1.0,
    "insider": 0.9,
    "activity_alerts": 0.9,
    "sector_momentum": 0.8,
    "abnormal_volume": 0.7,
    "technical_analysis": 0.65,
    "options_flow": 0.7,
    "buy_sell_pressure": 0.5,
    "block_trade_pressure": 0.4,
    "unusual_trade_activity": 0.45,
    "pre_market_unusual_activity": 0.45,
    "market_flow_trend": 0.4,
    "options_anomaly": 0.4,
    "news": 0.6,
    "prepost": 0.5,
    "subscription_thesis": 0.0,
}
DEFAULT_WATCH_THRESHOLD = 0.5
DEFAULT_MINIMUM_SOURCE_COUNT = 2
DEFAULT_MINIMUM_CONFIRMED_SIGNALS = 1


@dataclass(frozen=True)
class DeterministicRuleConfig:
    """Configurable thresholds for deterministic selection v0."""

    watch_threshold: float = DEFAULT_WATCH_THRESHOLD
    minimum_source_count: int = DEFAULT_MINIMUM_SOURCE_COUNT
    minimum_confirmed_signals: int = DEFAULT_MINIMUM_CONFIRMED_SIGNALS
    lane_weights: Mapping[str, float] | None = None


@dataclass(frozen=True)
class DeterministicRuleResult:
    """Decision and policy gates produced by deterministic rules."""

    decision: dict[str, object]
    policy_gates: list[dict[str, object]]


def evaluate_deterministic_rules(
    evidence_pack: Mapping[str, object],
    *,
    config: DeterministicRuleConfig | None = None,
) -> DeterministicRuleResult:
    """Apply deterministic selection rules to one schema-valid evidence pack."""
    validate_contract("evidence-pack", evidence_pack)
    normalized_config = config or DeterministicRuleConfig()
    policy_gates = _policy_gates(evidence_pack, normalized_config)
    decision = _engine_decision(evidence_pack, policy_gates, normalized_config)
    return DeterministicRuleResult(decision=decision, policy_gates=policy_gates)


def _engine_decision(
    evidence_pack: Mapping[str, object],
    policy_gates: list[dict[str, object]],
    config: DeterministicRuleConfig,
) -> dict[str, object]:
    blockers = _blocking_reasons(policy_gates)
    signals = _actionable_signals(evidence_pack)
    if blockers:
        return _decision("NO_TRADE", 0.0, 0.0, ["policy_gate_blocked"], blockers)
    if not signals:
        return _decision("NO_TRADE", 0.0, 0.0, ["no_actionable_signals"], [])

    score = _weighted_score(signals, config.lane_weights or DEFAULT_LANE_WEIGHTS)
    conviction = _clamp(abs(score))
    if score >= config.watch_threshold:
        return _decision("WATCH", score, conviction, _reason_codes(signals), [])
    if score <= -config.watch_threshold:
        return _decision("NO_TRADE", score, conviction, ["bearish_action_not_enabled"], [])
    return _decision("NO_TRADE", score, conviction, ["signal_strength_below_threshold"], [])


def _policy_gates(
    evidence_pack: Mapping[str, object],
    config: DeterministicRuleConfig,
) -> list[dict[str, object]]:
    data_quality = _data_quality(evidence_pack)
    return [
        _evidence_breadth_gate(data_quality, config),
        _freshness_gate(str(data_quality["freshness"])),
    ]


def _evidence_breadth_gate(
    data_quality: Mapping[str, object],
    config: DeterministicRuleConfig,
) -> dict[str, object]:
    blockers = _string_list(data_quality, "blockers")
    source_count = _int_field(data_quality, "source_count")
    confirmed_count = _int_field(data_quality, "confirmed_signal_count")
    if blockers:
        return {"name": "evidence_breadth", "status": "BLOCK", "reason": blockers[0]}
    if source_count < config.minimum_source_count:
        reason = "no sources" if source_count == 0 else "insufficient independent sources"
        return {"name": "evidence_breadth", "status": "BLOCK", "reason": reason}
    if confirmed_count < config.minimum_confirmed_signals:
        return {
            "name": "evidence_breadth",
            "status": "WARN",
            "reason": "insufficient confirmed evidence",
        }
    return {"name": "evidence_breadth", "status": "PASS", "reason": "confirmed evidence present"}


def _freshness_gate(freshness: str) -> dict[str, object]:
    if freshness == "UNAVAILABLE":
        return {"name": "freshness", "status": "BLOCK", "reason": "sources unavailable"}
    if freshness in {"AGING", "STALE"}:
        return {"name": "freshness", "status": "WARN", "reason": freshness.lower()}
    return {"name": "freshness", "status": "PASS", "reason": "fresh evidence"}


def _decision(
    action: str,
    score: float,
    conviction: float,
    reason_codes: list[str],
    blockers: list[str],
) -> dict[str, object]:
    return {
        "action": action,
        "score": round(score, 6),
        "conviction": round(conviction, 6),
        "reason_codes": reason_codes,
        "blockers": blockers,
    }


def _weighted_score(
    signals: list[Mapping[str, object]],
    lane_weights: Mapping[str, float],
) -> float:
    numerator = 0.0
    denominator = 0.0
    for signal in signals:
        weight = abs(float(lane_weights.get(str(signal["lane"]), 1.0)))
        numerator += _float_field(signal, "score") * weight
        denominator += weight
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _blocking_reasons(policy_gates: list[dict[str, object]]) -> list[str]:
    return [str(gate["reason"]) for gate in policy_gates if gate["status"] == "BLOCK"]


def _data_quality(evidence_pack: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping_field(evidence_pack, "data_quality")


def _actionable_signals(evidence_pack: Mapping[str, object]) -> list[Mapping[str, object]]:
    items = _list_field(evidence_pack, "actionable_signals")
    return [cast(Mapping[str, object], item) for item in items]


def _reason_codes(signals: list[Mapping[str, object]]) -> list[str]:
    codes: list[str] = []
    for signal in signals:
        for code in _string_list(signal, "reason_codes"):
            if code not in codes:
                codes.append(code)
    return codes or ["actionable_signal_present"]


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
