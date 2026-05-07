from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import pandas as pd
from backtests.scoped_loader import LoaderLike, SignalFn
from signals._common import zscore


@dataclass(frozen=True)
class SignalWeight:
    name: str
    signal_fn: SignalFn
    weight: float


def combined_signal_fn(components: Iterable[SignalWeight]) -> SignalFn:
    """Return a signal function that combines z-scored component lanes."""
    component_list = list(components)
    if not component_list:
        raise ValueError("components must not be empty")

    def signal(as_of: date, universe: set[str], loader: LoaderLike) -> dict[str, float]:
        component_scores = {
            component.name: component.signal_fn(as_of, universe, loader)
            for component in component_list
        }
        weights = {component.name: component.weight for component in component_list}
        return combine_signal_scores(component_scores, weights)

    return signal


def combine_signal_scores(
    component_scores: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> dict[str, float]:
    """Combine lane score dictionaries using per-lane z-scores."""
    frames = []
    for name, scores in sorted(component_scores.items()):
        weight = float(weights.get(name, 0.0))
        if weight == 0.0 or not scores:
            continue
        frame = pd.DataFrame(
            {"ticker": list(scores), "score": list(scores.values())}
        ).sort_values("ticker")
        frame["component"] = name
        frame["weighted_score"] = zscore(frame["score"]) * weight
        frame["weight"] = abs(weight)
        frames.append(frame[["ticker", "weighted_score", "weight"]])
    if not frames:
        return {}
    combined = pd.concat(frames, ignore_index=True)
    grouped = combined.groupby("ticker", sort=True)[["weighted_score", "weight"]].sum()
    output = grouped["weighted_score"] / grouped["weight"]
    return {str(ticker): float(score) for ticker, score in output.items() if score != 0.0}


def weights_from_ic(
    ic_results: pd.DataFrame,
    *,
    signal_column: str = "signal",
    weight_column: str = "information_ratio",
) -> dict[str, float]:
    """Create normalized positive weights from an IC result table."""
    required = {signal_column, weight_column}
    missing = required.difference(ic_results.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    values = (
        ic_results[[signal_column, weight_column]]
        .dropna()
        .groupby(signal_column, sort=True)[weight_column]
        .max()
    )
    positive = values[values > 0.0]
    total = float(positive.sum())
    if total <= 0.0:
        return {}
    return {str(signal): float(value / total) for signal, value in positive.items()}
