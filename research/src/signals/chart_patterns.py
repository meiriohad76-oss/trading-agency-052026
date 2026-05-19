from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from signals._common import float_or_none

PIVOT_WINDOW = 3
MAX_PIVOTS = 8
MIN_PATTERN_OBSERVATIONS = 40
MIN_DOUBLE_PIVOTS = 2
MIN_TRIPLE_PIVOTS = 3
MIN_SEPARATION_BARS = 5
DOUBLE_TOLERANCE = 0.04
DOUBLE_MIN_DEPTH = 0.06
SHOULDER_TOLERANCE = 0.08
HEAD_PROMINENCE = 0.03
NECKLINE_BREAK_BUFFER = 0.005
CUP_LOOKBACK = 80
CUP_MIN_DEPTH = 0.10
CUP_MAX_DEPTH = 0.45
CUP_RIM_TOLERANCE = 0.08
HANDLE_MAX_PULLBACK = 0.10
MIN_CONFIDENCE = 0.35
CONFIRMED_BONUS = 0.15
VOLUME_CONFIRMATION_BONUS = 0.10
MAX_SCORE_CONTRIBUTION = 1.0


@dataclass(frozen=True)
class Pivot:
    index: int
    value: float


@dataclass(frozen=True)
class ChartPattern:
    name: str
    direction: str
    confidence: float
    status: str
    breakout_level: float | None
    invalidation_level: float | None
    target_level: float | None
    reason: str


@dataclass(frozen=True)
class ChartPatternSummary:
    primary: ChartPattern | None
    patterns: tuple[ChartPattern, ...]
    score: float
    reason_codes: list[str]

    @property
    def summary_fragment(self) -> str:
        if self.primary is None:
            return "No high-confidence named chart pattern is active."
        pattern = self.primary
        return (
            f"Primary named pattern is {pattern.name.replace('_', ' ')} "
            f"({pattern.direction}, {pattern.status}, confidence {pattern.confidence:.2f}); "
            f"{pattern.reason}"
        )


def chart_pattern_summary(
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> ChartPatternSummary:
    """Detect named chart patterns from OHLCV structure without lookahead."""
    normalized_close = _numeric(close)
    normalized_high = _numeric(high).fillna(normalized_close)
    normalized_low = _numeric(low).fillna(normalized_close)
    normalized_volume = _numeric(volume).fillna(0.0)
    if len(normalized_close.dropna()) < MIN_PATTERN_OBSERVATIONS:
        return ChartPatternSummary(None, (), 0.0, [])
    highs = _pivots(normalized_high, mode="high")
    lows = _pivots(normalized_low, mode="low")
    candidates = [
        _double_bottom(normalized_close, lows, normalized_volume),
        _double_top(normalized_close, highs, normalized_volume),
        _head_and_shoulders(normalized_close, highs, lows),
        _inverse_head_and_shoulders(normalized_close, highs, lows),
        _cup_and_handle(normalized_close, normalized_high, normalized_low, normalized_volume),
    ]
    patterns = tuple(
        sorted(
            (pattern for pattern in candidates if pattern is not None),
            key=lambda pattern: pattern.confidence,
            reverse=True,
        )
    )
    primary = patterns[0] if patterns else None
    return ChartPatternSummary(
        primary=primary,
        patterns=patterns,
        score=_pattern_score(primary),
        reason_codes=_reason_codes(primary),
    )


def _double_bottom(
    close: pd.Series,
    lows: list[Pivot],
    volume: pd.Series,
) -> ChartPattern | None:
    if len(lows) < MIN_DOUBLE_PIVOTS:
        return None
    first, second = lows[-2], lows[-1]
    if second.index - first.index < MIN_SEPARATION_BARS:
        return None
    if _relative_gap(first.value, second.value) > DOUBLE_TOLERANCE:
        return None
    middle_high = _range_max(close, first.index, second.index)
    trough = min(first.value, second.value)
    depth = _safe_ratio(middle_high, trough) - 1.0
    if depth < DOUBLE_MIN_DEPTH:
        return None
    latest = _latest(close)
    confirmed = latest > middle_high * (1.0 + NECKLINE_BREAK_BUFFER)
    confidence = _bounded_confidence(0.45 + depth + _volume_bonus(volume, second.index))
    if confirmed:
        confidence = _bounded_confidence(confidence + CONFIRMED_BONUS)
    return ChartPattern(
        name="double_bottom",
        direction="bullish",
        confidence=confidence,
        status="confirmed" if confirmed else "forming",
        breakout_level=middle_high,
        invalidation_level=trough,
        target_level=middle_high + (middle_high - trough),
        reason="two similar lows formed with a neckline above the troughs.",
    )


def _double_top(
    close: pd.Series,
    highs: list[Pivot],
    volume: pd.Series,
) -> ChartPattern | None:
    if len(highs) < MIN_DOUBLE_PIVOTS:
        return None
    first, second = highs[-2], highs[-1]
    if second.index - first.index < MIN_SEPARATION_BARS:
        return None
    if _relative_gap(first.value, second.value) > DOUBLE_TOLERANCE:
        return None
    middle_low = _range_min(close, first.index, second.index)
    peak = max(first.value, second.value)
    depth = 1.0 - _safe_ratio(middle_low, peak)
    if depth < DOUBLE_MIN_DEPTH:
        return None
    latest = _latest(close)
    confirmed = latest < middle_low * (1.0 - NECKLINE_BREAK_BUFFER)
    confidence = _bounded_confidence(0.45 + depth + _volume_bonus(volume, second.index))
    if confirmed:
        confidence = _bounded_confidence(confidence + CONFIRMED_BONUS)
    return ChartPattern(
        name="double_top",
        direction="bearish",
        confidence=confidence,
        status="confirmed" if confirmed else "forming",
        breakout_level=middle_low,
        invalidation_level=peak,
        target_level=middle_low - (peak - middle_low),
        reason="two similar highs formed with a neckline below the peaks.",
    )


def _head_and_shoulders(
    close: pd.Series,
    highs: list[Pivot],
    lows: list[Pivot],
) -> ChartPattern | None:
    if len(highs) < MIN_TRIPLE_PIVOTS:
        return None
    left, head, right = highs[-3], highs[-2], highs[-1]
    if not _ordered(left, head, right):
        return None
    if head.value <= max(left.value, right.value) * (1.0 + HEAD_PROMINENCE):
        return None
    if _relative_gap(left.value, right.value) > SHOULDER_TOLERANCE:
        return None
    neckline = _neckline_between_lows(lows, left.index, right.index)
    if neckline is None:
        return None
    latest = _latest(close)
    confirmed = latest < neckline * (1.0 - NECKLINE_BREAK_BUFFER)
    confidence = _bounded_confidence(
        0.50 + min(_safe_ratio(head.value, max(left.value, right.value)) - 1.0, 0.20)
    )
    if confirmed:
        confidence = _bounded_confidence(confidence + CONFIRMED_BONUS)
    return ChartPattern(
        name="head_and_shoulders",
        direction="bearish",
        confidence=confidence,
        status="confirmed" if confirmed else "forming",
        breakout_level=neckline,
        invalidation_level=head.value,
        target_level=neckline - (head.value - neckline),
        reason="middle high stands above two similar shoulders.",
    )


def _inverse_head_and_shoulders(
    close: pd.Series,
    highs: list[Pivot],
    lows: list[Pivot],
) -> ChartPattern | None:
    if len(lows) < MIN_TRIPLE_PIVOTS:
        return None
    left, head, right = lows[-3], lows[-2], lows[-1]
    if not _ordered(left, head, right):
        return None
    shoulder_floor = min(left.value, right.value)
    if head.value >= shoulder_floor * (1.0 - HEAD_PROMINENCE):
        return None
    if _relative_gap(left.value, right.value) > SHOULDER_TOLERANCE:
        return None
    neckline = _neckline_between_highs(highs, left.index, right.index)
    if neckline is None:
        return None
    latest = _latest(close)
    confirmed = latest > neckline * (1.0 + NECKLINE_BREAK_BUFFER)
    confidence = _bounded_confidence(
        0.50 + min(1.0 - _safe_ratio(head.value, shoulder_floor), 0.20)
    )
    if confirmed:
        confidence = _bounded_confidence(confidence + CONFIRMED_BONUS)
    return ChartPattern(
        name="inverse_head_and_shoulders",
        direction="bullish",
        confidence=confidence,
        status="confirmed" if confirmed else "forming",
        breakout_level=neckline,
        invalidation_level=head.value,
        target_level=neckline + (neckline - head.value),
        reason="middle low undercuts two similar shoulders.",
    )


def _cup_and_handle(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> ChartPattern | None:
    if len(close) < CUP_LOOKBACK:
        return None
    window_close = close.tail(CUP_LOOKBACK).reset_index(drop=True)
    window_high = high.tail(CUP_LOOKBACK).reset_index(drop=True)
    window_low = low.tail(CUP_LOOKBACK).reset_index(drop=True)
    left_rim_index = int(window_high.iloc[: CUP_LOOKBACK // 2].idxmax())
    trough_index = int(window_low.iloc[left_rim_index:].idxmin())
    right_rim_index = int(window_high.iloc[trough_index:].idxmax())
    if not left_rim_index < trough_index < right_rim_index:
        return None
    left_rim = float(window_high.iloc[left_rim_index])
    right_rim = float(window_high.iloc[right_rim_index])
    trough = float(window_low.iloc[trough_index])
    rim = min(left_rim, right_rim)
    depth = 1.0 - _safe_ratio(trough, rim)
    if not CUP_MIN_DEPTH <= depth <= CUP_MAX_DEPTH:
        return None
    if _relative_gap(left_rim, right_rim) > CUP_RIM_TOLERANCE:
        return None
    handle_low = float(window_low.iloc[right_rim_index:].min())
    handle_pullback = 1.0 - _safe_ratio(handle_low, right_rim)
    if handle_pullback > HANDLE_MAX_PULLBACK:
        return None
    latest = _latest(window_close)
    confirmed = latest > rim * (1.0 + NECKLINE_BREAK_BUFFER)
    confidence = _bounded_confidence(
        0.45
        + min(depth, 0.25)
        + max(HANDLE_MAX_PULLBACK - handle_pullback, 0.0)
        + _recent_volume_bonus(volume)
    )
    if confirmed:
        confidence = _bounded_confidence(confidence + CONFIRMED_BONUS)
    return ChartPattern(
        name="cup_and_handle",
        direction="bullish",
        confidence=confidence,
        status="confirmed" if confirmed else "forming",
        breakout_level=rim,
        invalidation_level=handle_low,
        target_level=rim + (rim - trough),
        reason="rounded recovery returned near the prior rim with a shallow handle.",
    )


def _pivots(series: pd.Series, *, mode: str) -> list[Pivot]:
    values = _numeric(series).reset_index(drop=True)
    pivots: list[Pivot] = []
    for index in range(PIVOT_WINDOW, len(values) - PIVOT_WINDOW):
        center = float_or_none(values.iloc[index])
        if center is None:
            continue
        window = values.iloc[index - PIVOT_WINDOW : index + PIVOT_WINDOW + 1]
        if mode == "high" and center >= float(window.max()):
            pivots.append(Pivot(index, center))
        if mode == "low" and center <= float(window.min()):
            pivots.append(Pivot(index, center))
    return pivots[-MAX_PIVOTS:]


def _pattern_score(primary: ChartPattern | None) -> float:
    if primary is None or primary.confidence < MIN_CONFIDENCE:
        return 0.0
    sign = 1.0 if primary.direction == "bullish" else -1.0
    return sign * min(primary.confidence, MAX_SCORE_CONTRIBUTION)


def _reason_codes(primary: ChartPattern | None) -> list[str]:
    if primary is None or primary.confidence < MIN_CONFIDENCE:
        return []
    return [
        f"technical_pattern_{primary.direction}",
        f"technical_pattern_{primary.name}",
        f"technical_pattern_{primary.status}",
    ]


def _neckline_between_lows(lows: list[Pivot], start: int, end: int) -> float | None:
    candidates = [pivot.value for pivot in lows if start < pivot.index < end]
    return min(candidates) if candidates else None


def _neckline_between_highs(highs: list[Pivot], start: int, end: int) -> float | None:
    candidates = [pivot.value for pivot in highs if start < pivot.index < end]
    return max(candidates) if candidates else None


def _range_max(series: pd.Series, start: int, end: int) -> float:
    return float(series.iloc[start : end + 1].max())


def _range_min(series: pd.Series, start: int, end: int) -> float:
    return float(series.iloc[start : end + 1].min())


def _volume_bonus(volume: pd.Series, index: int) -> float:
    current = float_or_none(volume.iloc[index]) or 0.0
    baseline = float(volume.tail(21).median()) if len(volume.dropna()) else 0.0
    if baseline <= 0.0 or current <= baseline:
        return 0.0
    return VOLUME_CONFIRMATION_BONUS


def _recent_volume_bonus(volume: pd.Series) -> float:
    values = _numeric(volume).dropna()
    if len(values) < MIN_PATTERN_OBSERVATIONS:
        return 0.0
    recent = float(values.tail(PIVOT_WINDOW).mean())
    baseline = float(values.tail(21).median())
    return VOLUME_CONFIRMATION_BONUS if baseline > 0.0 and recent > baseline else 0.0


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _latest(series: pd.Series) -> float:
    values = _numeric(series).dropna()
    return 0.0 if values.empty else float(values.iloc[-1])


def _relative_gap(left: float, right: float) -> float:
    denominator = max(abs(left), abs(right), 1.0)
    return abs(left - right) / denominator


def _safe_ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator <= 0.0 else numerator / denominator


def _bounded_confidence(value: float) -> float:
    parsed = float_or_none(value)
    if parsed is None:
        return 0.0
    return max(0.0, min(1.0, parsed))


def _ordered(left: Pivot, middle: Pivot, right: Pivot) -> bool:
    return left.index < middle.index < right.index
