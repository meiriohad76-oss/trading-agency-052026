from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from agency.contracts import validate_contract

FRESHNESS_RANK = {
    "FRESH": 0,
    "AGING": 1,
    "STALE": 2,
    "UNAVAILABLE": 3,
}


def build_evidence_pack(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    generated_at: str,
    signals: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Assemble one schema-valid evidence pack from validated signal results."""
    normalized_signals = [_validated_signal(signal) for signal in signals]
    normalized_ticker = ticker.upper()
    for signal in normalized_signals:
        _assert_signal_identity(signal, cycle_id=cycle_id, ticker=normalized_ticker, as_of=as_of)

    pack: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": cycle_id,
        "ticker": normalized_ticker,
        "as_of": as_of,
        "generated_at": generated_at,
        "actionable_signals": _signals_by_actionability(normalized_signals, "ACTIONABLE"),
        "context_signals": _signals_by_actionability(normalized_signals, "CONTEXT_ONLY"),
        "suppressed_signals": _signals_by_actionability(normalized_signals, "SUPPRESSED"),
        "data_quality": _data_quality(normalized_signals),
    }
    validate_contract("evidence-pack", pack)
    return pack


def _validated_signal(signal: Mapping[str, object]) -> dict[str, object]:
    validate_contract("signal-result", signal)
    return dict(signal)


def _assert_signal_identity(
    signal: Mapping[str, object],
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> None:
    if str(signal["cycle_id"]) != cycle_id:
        raise ValueError("signal cycle_id does not match evidence pack")
    if str(signal["ticker"]) != ticker:
        raise ValueError("signal ticker does not match evidence pack")
    if str(signal["as_of"]) != as_of:
        raise ValueError("signal as_of does not match evidence pack")


def _signals_by_actionability(
    signals: list[dict[str, object]],
    actionability: str,
) -> list[dict[str, object]]:
    return [signal for signal in signals if signal["actionability"] == actionability]


def _data_quality(signals: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "freshness": _worst_freshness(signals),
        "source_count": len(_source_keys(signals)),
        "confirmed_signal_count": _verification_count(signals, "CONFIRMED"),
        "inferred_signal_count": _verification_count(signals, "INFERRED"),
        "blockers": _blockers(signals),
    }


def _worst_freshness(signals: Sequence[Mapping[str, object]]) -> str:
    if not signals:
        return "UNAVAILABLE"
    return max((str(signal["freshness"]) for signal in signals), key=_freshness_rank)


def _freshness_rank(freshness: str) -> int:
    return FRESHNESS_RANK.get(freshness, FRESHNESS_RANK["UNAVAILABLE"])


def _source_keys(signals: Sequence[Mapping[str, object]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for signal in signals:
        provenance = _mapping_field(signal, "provenance")
        keys.add((str(provenance["source"]), str(provenance["source_id"])))
    return keys


def _verification_count(signals: Sequence[Mapping[str, object]], verification_level: str) -> int:
    return sum(1 for signal in signals if signal["verification_level"] == verification_level)


def _blockers(signals: Sequence[Mapping[str, object]]) -> list[str]:
    if not signals:
        return ["no_signal_results"]
    if all(signal["freshness"] == "UNAVAILABLE" for signal in signals):
        return ["all_sources_unavailable"]
    return []


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)
