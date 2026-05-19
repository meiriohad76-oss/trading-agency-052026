from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agency.contracts import validate_contract

DIRECTION_EPSILON = 0.05


@dataclass(frozen=True)
class SignalActionabilityConfig:
    """Thresholds used to classify normalized signal scores."""

    actionable_score: float = 0.5
    context_score: float = 0.1
    min_confidence: float = 0.5


def build_signal_result(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    lane: str,
    score: float,
    provenance: Mapping[str, object],
    confidence: float = 1.0,
    reason_codes: Sequence[str] | None = None,
    actionability: str | None = None,
    suppression_reason: str | None = None,
    summary: str | None = None,
    config: SignalActionabilityConfig | None = None,
) -> dict[str, object]:
    """Build one schema-valid SignalResult from a normalized lane score."""
    normalized_config = config or SignalActionabilityConfig()
    normalized_ticker = ticker.upper()
    normalized_score = _finite_float(score, field="score")
    normalized_confidence = _clamp(confidence)
    normalized_provenance = dict(provenance)
    actionability_value = actionability or _actionability(
        score=normalized_score,
        confidence=normalized_confidence,
        freshness=str(normalized_provenance["freshness"]),
        config=normalized_config,
    )
    signal: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": cycle_id,
        "ticker": normalized_ticker,
        "as_of": as_of,
        "lane": lane,
        "score": normalized_score,
        "direction": _direction(normalized_score),
        "actionability": actionability_value,
        "source_tier": str(normalized_provenance["source_tier"]),
        "verification_level": str(normalized_provenance["verification_level"]),
        "freshness": str(normalized_provenance["freshness"]),
        "confidence": normalized_confidence,
        "provenance": normalized_provenance,
        "reason_codes": (
            list(reason_codes) if reason_codes is not None else _reason_codes(lane, score)
        ),
        "suppression_reason": _suppression_reason(
            actionability_value,
            suppression_reason,
            normalized_score,
            normalized_confidence,
        ),
    }
    if summary is not None:
        signal["summary"] = summary
    validate_contract("signal-result", signal)
    return signal


def build_signal_results_from_scores(
    *,
    cycle_id: str,
    as_of: str,
    lane: str,
    scores: Mapping[str, float],
    provenance_by_ticker: Mapping[str, Mapping[str, object]],
    confidence: float = 1.0,
    config: SignalActionabilityConfig | None = None,
) -> list[dict[str, object]]:
    """Adapt ticker scores into deterministic, schema-valid SignalResult payloads."""
    signals: list[dict[str, object]] = []
    for ticker in sorted(scores, key=str.upper):
        score = scores[ticker]
        normalized_ticker = ticker.upper()
        if normalized_ticker not in provenance_by_ticker:
            raise KeyError(f"missing provenance for {normalized_ticker}")
        signals.append(
            build_signal_result(
                cycle_id=cycle_id,
                ticker=normalized_ticker,
                as_of=as_of,
                lane=lane,
                score=score,
                provenance=provenance_by_ticker[normalized_ticker],
                confidence=confidence,
                config=config,
            )
        )
    return signals


def _actionability(
    *,
    score: float,
    confidence: float,
    freshness: str,
    config: SignalActionabilityConfig,
) -> str:
    if freshness == "UNAVAILABLE":
        return "SUPPRESSED"
    if abs(score) >= config.actionable_score and confidence >= config.min_confidence:
        return "ACTIONABLE"
    if abs(score) >= config.context_score:
        return "CONTEXT_ONLY"
    return "SUPPRESSED"


def _direction(score: float) -> str:
    if score > DIRECTION_EPSILON:
        return "BULLISH"
    if score < -DIRECTION_EPSILON:
        return "BEARISH"
    return "NEUTRAL"


def _reason_codes(lane: str, score: float) -> list[str]:
    return [f"{lane}_{_direction(score).lower()}"]


def _suppression_reason(
    actionability: str,
    explicit_reason: str | None,
    score: float,
    confidence: float,
) -> str | None:
    if actionability != "SUPPRESSED":
        return None
    if explicit_reason is not None:
        return explicit_reason
    if confidence <= 0.0:
        return "zero_confidence"
    return "below_actionability_threshold" if abs(score) < DIRECTION_EPSILON else "not_actionable"


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, _finite_float(value, field="confidence")))


def _finite_float(value: float, *, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result
