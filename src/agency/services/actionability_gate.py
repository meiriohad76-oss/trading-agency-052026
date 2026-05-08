from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from agency.contracts import validate_contract

FRESHNESS_ACTIONABILITY = {
    "FRESH": "PASS",
    "AGING": "PASS",
    "STALE": "CONTEXT_ONLY",
    "UNAVAILABLE": "SUPPRESSED",
}
INFERRED_VERIFICATION = "INFERRED"


@dataclass(frozen=True)
class LaneActionabilityRule:
    """Per-lane evidence thresholds for v1 actionability."""

    min_sources: int = 1
    min_confirmed_sources: int = 1
    inferred_needs_confirmed_corroboration: bool = True


@dataclass(frozen=True)
class ActionabilityGateConfig:
    """Configurable lane rules for the EvidencePack actionability gate."""

    default_rule: LaneActionabilityRule = LaneActionabilityRule()
    lane_rules: Mapping[str, LaneActionabilityRule] | None = None


DEFAULT_LANE_RULES: Mapping[str, LaneActionabilityRule] = {
    "fundamentals": LaneActionabilityRule(),
    "insider": LaneActionabilityRule(),
    "institutional": LaneActionabilityRule(),
    "sector_momentum": LaneActionabilityRule(),
    "news": LaneActionabilityRule(min_sources=2, min_confirmed_sources=1),
    "activity_alerts": LaneActionabilityRule(),
    "abnormal_volume": LaneActionabilityRule(min_confirmed_sources=0),
    "prepost": LaneActionabilityRule(min_confirmed_sources=0),
    "options_flow": LaneActionabilityRule(min_confirmed_sources=0),
}


def apply_actionability_gate(
    signals: Sequence[Mapping[str, object]],
    *,
    config: ActionabilityGateConfig | None = None,
) -> list[dict[str, object]]:
    """Demote or suppress signal results that do not pass actionability rules."""
    normalized = [_validated_signal(signal) for signal in signals]
    if not normalized:
        return []
    gate_config = config or ActionabilityGateConfig(lane_rules=DEFAULT_LANE_RULES)
    duplicate_indexes = _duplicate_indexes(normalized)
    stats = _lane_stats(normalized, duplicate_indexes)
    has_confirmed = any(_is_confirmed(signal) for signal in normalized)
    return [
        _gate_signal(
            signal,
            index=index,
            duplicate_indexes=duplicate_indexes,
            stats=stats,
            has_confirmed=has_confirmed,
            config=gate_config,
        )
        for index, signal in enumerate(normalized)
    ]


def _gate_signal(
    signal: Mapping[str, object],
    *,
    index: int,
    duplicate_indexes: set[int],
    stats: Mapping[str, _LaneStats],
    has_confirmed: bool,
    config: ActionabilityGateConfig,
) -> dict[str, object]:
    output = dict(signal)
    if index in duplicate_indexes:
        return _reclassify(output, "SUPPRESSED", "duplicate_signal_source")
    if signal["actionability"] == "SUPPRESSED":
        return output

    freshness_action = FRESHNESS_ACTIONABILITY.get(str(signal["freshness"]), "SUPPRESSED")
    if freshness_action != "PASS":
        freshness_reason = (
            "stale_evidence" if freshness_action == "CONTEXT_ONLY" else "source_unavailable"
        )
        return _reclassify(output, freshness_action, freshness_reason)
    if signal["actionability"] != "ACTIONABLE":
        return output

    rule = _rule_for(signal, config)
    lane_stats = stats[str(signal["lane"])]
    reason = _threshold_reason(signal, rule, lane_stats, has_confirmed)
    if reason is not None:
        return _reclassify(output, "CONTEXT_ONLY", reason)
    output["suppression_reason"] = None
    return output


def _threshold_reason(
    signal: Mapping[str, object],
    rule: LaneActionabilityRule,
    stats: _LaneStats,
    has_confirmed: bool,
) -> str | None:
    if stats.source_count < rule.min_sources:
        return "insufficient_independent_sources"
    if stats.confirmed_source_count < rule.min_confirmed_sources:
        return "insufficient_confirmed_sources"
    if (
        signal["verification_level"] == INFERRED_VERIFICATION
        and rule.inferred_needs_confirmed_corroboration
        and not has_confirmed
    ):
        return "requires_confirmed_corroboration"
    return None


def _reclassify(signal: dict[str, object], actionability: str, reason: str) -> dict[str, object]:
    signal["actionability"] = actionability
    signal["suppression_reason"] = reason if actionability == "SUPPRESSED" else None
    signal["reason_codes"] = [*_string_list(signal, "reason_codes"), reason]
    validate_contract("signal-result", signal)
    return signal


def _rule_for(
    signal: Mapping[str, object],
    config: ActionabilityGateConfig,
) -> LaneActionabilityRule:
    lane_rules = config.lane_rules or DEFAULT_LANE_RULES
    return lane_rules.get(str(signal["lane"]), config.default_rule)


@dataclass(frozen=True)
class _LaneStats:
    source_count: int
    confirmed_source_count: int


def _lane_stats(
    signals: Sequence[Mapping[str, object]],
    duplicate_indexes: set[int],
) -> dict[str, _LaneStats]:
    source_keys: dict[str, set[tuple[str, str]]] = {}
    confirmed_keys: dict[str, set[tuple[str, str]]] = {}
    for index, signal in enumerate(signals):
        if index in duplicate_indexes or signal["actionability"] == "SUPPRESSED":
            continue
        lane = str(signal["lane"])
        key = _source_key(signal)
        source_keys.setdefault(lane, set()).add(key)
        if _is_confirmed(signal):
            confirmed_keys.setdefault(lane, set()).add(key)
    return {
        lane: _LaneStats(
            source_count=len(keys),
            confirmed_source_count=len(confirmed_keys.get(lane, set())),
        )
        for lane, keys in source_keys.items()
    }


def _duplicate_indexes(signals: Sequence[Mapping[str, object]]) -> set[int]:
    seen: set[tuple[str, str, str, str]] = set()
    duplicates: set[int] = set()
    for index, signal in enumerate(signals):
        key = (str(signal["ticker"]), str(signal["lane"]), *_source_key(signal))
        if key in seen:
            duplicates.add(index)
        else:
            seen.add(key)
    return duplicates


def _source_key(signal: Mapping[str, object]) -> tuple[str, str]:
    provenance = _mapping_field(signal, "provenance")
    return (str(provenance["source"]), str(provenance["source_id"]))


def _is_confirmed(signal: Mapping[str, object]) -> bool:
    return signal["verification_level"] == "CONFIRMED"


def _validated_signal(signal: Mapping[str, object]) -> dict[str, object]:
    validate_contract("signal-result", signal)
    return dict(signal)


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return [str(item) for item in value]
