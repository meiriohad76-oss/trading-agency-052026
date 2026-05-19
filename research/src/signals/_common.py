from __future__ import annotations

import math
import warnings
from typing import Any, cast

import pandas as pd

MIN_CROSS_SECTION = 2


def payload_dict(value: object, label: str) -> dict[str, object]:
    payload = cast(Any, value).value if hasattr(value, "value") else value
    if not isinstance(payload, dict):
        raise TypeError(f"{label} payload must be a dict")
    return payload


def score_dict(frame: pd.DataFrame, score_column: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for row in frame[["ticker", score_column]].itertuples(index=False):
        score = float_or_none(getattr(row, score_column))
        if score is not None and pd.notna(score):
            scores[str(row.ticker)] = score
    return scores


def zscore(series: pd.Series) -> pd.Series:
    if len(series.dropna()) < MIN_CROSS_SECTION:
        warnings.warn(
            f"zscore: insufficient_cross_section (n={len(series.dropna())})",
            UserWarning,
            stacklevel=2,
        )
        return pd.Series([0.0 for _ in series], index=series.index)
    std = series.std(ddof=0)
    if std == 0.0 or pd.isna(std):
        return pd.Series([0.0 for _ in series], index=series.index)
    return (series - series.mean()) / std


def directional_rank_score(series: pd.Series) -> pd.Series:
    """Rank directional magnitudes without changing the raw pressure sign."""
    numeric = pd.to_numeric(series, errors="coerce")
    result = pd.Series([0.0 for _ in numeric], index=numeric.index)
    valid = numeric.dropna()
    valid = valid[valid.map(math.isfinite)]
    nonzero = valid[valid != 0.0]
    if len(nonzero) == 0:
        return result
    if len(nonzero) == 1:
        value = float(nonzero.iloc[0])
        result.loc[nonzero.index[0]] = 1.0 if value > 0 else -1.0
        return result
    magnitude_rank = nonzero.abs().rank(method="average", pct=True)
    signed = magnitude_rank * nonzero.apply(lambda value: 1.0 if value > 0 else -1.0)
    result.loc[signed.index] = signed
    return result


def float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def positive_float(value: object) -> float | None:
    parsed = float_or_none(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed
