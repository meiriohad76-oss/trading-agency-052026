from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

BASIS_POINTS = 10_000
PositionSizingRule = Literal["equal_weight", "score_weighted", "volatility_targeted"]


@dataclass(frozen=True)
class CostModel:
    """Per-side trading costs used when target weights change."""

    bps_per_side: float = 5.0
    slippage_bps: float = 0.0

    @property
    def total_bps_per_side(self) -> float:
        return self.bps_per_side + self.slippage_bps


@dataclass(frozen=True)
class Portfolio:
    """Backtest output model with positions, equity curve, returns, and trade log."""

    positions: pd.DataFrame
    equity_curve: pd.Series
    period_returns: pd.Series
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)


def target_weights(
    scores: dict[str, float],
    *,
    max_positions: int,
    sizing_rule: PositionSizingRule,
    max_gross_exposure: float,
    volatilities: dict[str, float] | None = None,
) -> dict[str, float]:
    """Convert signed scores to deterministic target weights.

    Positive scores become long weights and negative scores become short
    weights. The selected names are the largest absolute scores, capped by
    `max_positions`; final absolute weights sum to `max_gross_exposure`.
    """
    if max_positions < 1:
        raise ValueError("max_positions must be >= 1")
    candidates = {ticker: score for ticker, score in scores.items() if score != 0.0}
    selected = sorted(candidates.items(), key=lambda item: (-abs(item[1]), item[0]))[:max_positions]
    if not selected:
        return {}
    gross_inputs = _gross_inputs(selected, sizing_rule=sizing_rule, volatilities=volatilities)
    total = sum(gross_inputs.values())
    if total <= 0.0:
        return {}
    return {
        ticker: _sign(score) * max_gross_exposure * gross_inputs[ticker] / total
        for ticker, score in selected
    }


def turnover_between(current: dict[str, float], target: dict[str, float]) -> float:
    """Return one-sided turnover, `sum(abs(target-current)) / 2`."""
    tickers = set(current) | set(target)
    return sum(abs(target.get(ticker, 0.0) - current.get(ticker, 0.0)) for ticker in tickers) / 2.0


def rebalance_cost_return(
    current: dict[str, float],
    target: dict[str, float],
    cost_model: CostModel,
) -> float:
    """Return the negative return drag from changing portfolio weights."""
    weight_delta = 2.0 * turnover_between(current, target)
    return weight_delta * cost_model.total_bps_per_side / BASIS_POINTS


def _gross_inputs(
    selected: list[tuple[str, float]],
    *,
    sizing_rule: PositionSizingRule,
    volatilities: dict[str, float] | None,
) -> dict[str, float]:
    if sizing_rule == "equal_weight":
        return {ticker: 1.0 for ticker, _score in selected}
    if sizing_rule == "score_weighted":
        return {ticker: abs(score) for ticker, score in selected}
    if volatilities is None:
        raise ValueError("volatilities are required for volatility_targeted sizing")
    return {
        ticker: abs(score) / volatilities[ticker]
        for ticker, score in selected
        if volatilities.get(ticker, 0.0) > 0.0
    }


def _sign(value: float) -> float:
    return 1.0 if value > 0.0 else -1.0
