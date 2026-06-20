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
    max_actionability: str | None = None
    max_actionability_reason: str | None = None


@dataclass(frozen=True)
class ActionabilityGateConfig:
    """Configurable lane rules for the EvidencePack actionability gate."""

    default_rule: LaneActionabilityRule = LaneActionabilityRule()
    lane_rules: Mapping[str, LaneActionabilityRule] | None = None


DEFAULT_LANE_RULES: Mapping[str, LaneActionabilityRule] = {
    "fundamentals": LaneActionabilityRule(),
    "insider": LaneActionabilityRule(),
    "institutional": LaneActionabilityRule(
        max_actionability="CONTEXT_ONLY",
        max_actionability_reason="13f_data_delayed",
    ),
    "sector_momentum": LaneActionabilityRule(),
    "news": LaneActionabilityRule(min_sources=2, min_confirmed_sources=1),
    "activity_alerts": LaneActionabilityRule(),
    "abnormal_volume": LaneActionabilityRule(min_confirmed_sources=0),
    "technical_analysis": LaneActionabilityRule(min_confirmed_sources=0),
    "block_trade_pressure": LaneActionabilityRule(min_confirmed_sources=0),
    "buy_sell_pressure": LaneActionabilityRule(min_confirmed_sources=0),
    "market_flow_trend": LaneActionabilityRule(min_confirmed_sources=0),
    "pre_market_unusual_activity": LaneActionabilityRule(min_confirmed_sources=0),
    "unusual_trade_activity": LaneActionabilityRule(min_confirmed_sources=0),
    "prepost": LaneActionabilityRule(min_confirmed_sources=0),
    "options_flow": LaneActionabilityRule(min_confirmed_sources=0),
    "options_anomaly": LaneActionabilityRule(min_confirmed_sources=0),
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
    confirmed_directions = _eligible_confirmed_directions(
        normalized,
        duplicate_indexes=duplicate_indexes,
        stats=stats,
        config=gate_config,
    )
    return [
        _gate_signal(
            signal,
            index=index,
            duplicate_indexes=duplicate_indexes,
            stats=stats,
            confirmed_directions=confirmed_directions,
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
    confirmed_directions: set[str],
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
    reason = _threshold_reason(signal, rule, lane_stats, confirmed_directions)
    if reason is not None:
        return _reclassify(output, "CONTEXT_ONLY", reason)
    cap_reason = _max_actionability_reason(output, rule)
    if cap_reason is not None:
        return _reclassify(
            output,
            cast(str, rule.max_actionability),
            cap_reason,
        )
    output["suppression_reason"] = None
    return output


def _threshold_reason(
    signal: Mapping[str, object],
    rule: LaneActionabilityRule,
    stats: _LaneStats,
    confirmed_directions: set[str],
) -> str | None:
    if stats.source_count < rule.min_sources:
        return "insufficient_independent_sources"
    if stats.confirmed_source_count < rule.min_confirmed_sources:
        return "insufficient_confirmed_sources"
    if (
        signal["verification_level"] == INFERRED_VERIFICATION
        and rule.inferred_needs_confirmed_corroboration
        and not _has_directional_corroboration(signal, confirmed_directions)
    ):
        return "requires_confirmed_corroboration"
    return None


def _has_directional_corroboration(
    signal: Mapping[str, object],
    confirmed_directions: set[str],
) -> bool:
    direction = str(signal["direction"])
    if direction == "NEUTRAL":
        return bool(confirmed_directions)
    return direction in confirmed_directions


def _eligible_confirmed_directions(
    signals: Sequence[Mapping[str, object]],
    *,
    duplicate_indexes: set[int],
    stats: Mapping[str, _LaneStats],
    config: ActionabilityGateConfig,
) -> set[str]:
    directions: set[str] = set()
    for index, signal in enumerate(signals):
        if (
            index in duplicate_indexes
            or signal["actionability"] != "ACTIONABLE"
            or not _is_confirmed(signal)
            or not _freshness_passes(signal)
        ):
            continue
        lane_stats = stats.get(str(signal["lane"]))
        if lane_stats is None:
            continue
        rule = _rule_for(signal, config)
        if lane_stats.source_count < rule.min_sources:
            continue
        if lane_stats.confirmed_source_count < rule.min_confirmed_sources:
            continue
        if _max_actionability_reason(signal, rule) is not None:
            continue
        directions.add(str(signal["direction"]))
    return directions


def _max_actionability_reason(
    signal: Mapping[str, object],
    rule: LaneActionabilityRule,
) -> str | None:
    if rule.max_actionability is None:
        return None
    ceiling_order = {"ACTIONABLE": 0, "CONTEXT_ONLY": 1, "SUPPRESSED": 2}
    current = str(signal["actionability"])
    ceiling = rule.max_actionability
    if ceiling_order.get(current, 0) >= ceiling_order.get(ceiling, 0):
        return None
    return rule.max_actionability_reason or "lane_max_actionability"


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
        if (
            index in duplicate_indexes
            or signal["actionability"] == "SUPPRESSED"
            or not _freshness_passes(signal)
        ):
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
    grouped: dict[tuple[str, str, str, str], list[tuple[int, Mapping[str, object]]]] = {}
    for index, signal in enumerate(signals):
        key = (str(signal["ticker"]), str(signal["lane"]), *_source_key(signal))
        grouped.setdefault(key, []).append((index, signal))
    duplicates: set[int] = set()
    for values in grouped.values():
        if len(values) < 2:
            continue
        canonical_index, _signal = max(
            values,
            key=lambda item: _canonical_duplicate_sort_key(item[0], item[1]),
        )
        duplicates.update(index for index, _signal in values if index != canonical_index)
    return duplicates


def _canonical_duplicate_sort_key(
    index: int,
    signal: Mapping[str, object],
) -> tuple[int, int, int, str, float, float, int]:
    provenance = _mapping_field(signal, "provenance")
    return (
        1 if _freshness_passes(signal) else 0,
        1 if signal["actionability"] != "SUPPRESSED" else 0,
        1 if _is_confirmed(signal) else 0,
        str(provenance.get("timestamp_as_of") or ""),
        _float_field(provenance.get("confidence")),
        abs(_float_field(signal.get("score"))),
        -index,
    )


def _source_key(signal: Mapping[str, object]) -> tuple[str, str]:
    provenance = _mapping_field(signal, "provenance")
    return (str(provenance["source"]), str(provenance["source_id"]))


def _is_confirmed(signal: Mapping[str, object]) -> bool:
    return signal["verification_level"] == "CONFIRMED"


def _freshness_passes(signal: Mapping[str, object]) -> bool:
    return FRESHNESS_ACTIONABILITY.get(str(signal["freshness"]), "SUPPRESSED") == "PASS"


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


def _float_field(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0
