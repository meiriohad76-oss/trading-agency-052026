from __future__ import annotations

import math


def bonferroni_adjust(p_values: list[float]) -> list[float]:
    """Return Bonferroni-adjusted p-values clipped to `[0, 1]`.

    This family-wise-error control is conservative: each p-value is multiplied
    by the number of tested hypotheses.
    """
    _validate_p_values(p_values)
    count = len(p_values)
    return [min(p_value * count, 1.0) for p_value in p_values]


def benjamini_hochberg_adjust(p_values: list[float]) -> list[float]:
    """Return Benjamini-Hochberg false-discovery-rate adjusted p-values.

    Adjusted values are computed on sorted p-values and then made monotonic
    from the largest p-value back to the smallest, matching statsmodels'
    `fdr_bh` convention.
    """
    _validate_p_values(p_values)
    count = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [0.0] * count
    running_min = 1.0
    for rank, (original_index, p_value) in reversed(list(enumerate(indexed, start=1))):
        raw_adjusted = p_value * count / rank
        running_min = min(running_min, raw_adjusted)
        adjusted[original_index] = min(running_min, 1.0)
    return adjusted


def _validate_p_values(p_values: list[float]) -> None:
    for p_value in p_values:
        if math.isnan(p_value) or p_value < 0.0 or p_value > 1.0:
            raise ValueError("p-values must be finite values in [0, 1]")
