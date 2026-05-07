from __future__ import annotations

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
        return pd.Series([0.0 for _ in series], index=series.index)
    std = series.std(ddof=0)
    if std == 0.0 or pd.isna(std):
        return pd.Series([0.0 for _ in series], index=series.index)
    return (series - series.mean()) / std


def float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) else parsed


def positive_float(value: object) -> float | None:
    parsed = float_or_none(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed
