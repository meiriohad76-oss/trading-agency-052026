from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import cast

import pandas as pd
import polars as pl
from backtests.portfolio import (
    CostModel,
    Portfolio,
    PositionSizingRule,
    rebalance_cost_return,
    target_weights,
    turnover_between,
)
from backtests.scoped_loader import LoaderLike, ScopedPITLoader, SignalFn

INITIAL_EQUITY = 1.0


@dataclass(frozen=True)
class WalkForwardConfig:
    """Configuration for deterministic close-to-close walk-forward simulation.

    Signals are generated at each rebalance date using a loader scoped to that
    same date. The engine then applies target weights at that close, subtracts
    per-side trading costs/slippage on weight changes, and realizes returns
    from subsequent adjusted closes until the next rebalance.
    """

    in_sample_window_days: int = 504
    out_of_sample_window_days: int = 126
    step_size_days: int = 21
    rebalance_frequency: str = "D"
    max_positions: int = 10
    position_sizing: PositionSizingRule = "equal_weight"
    max_gross_exposure: float = 1.0
    cost_model: CostModel = field(default_factory=CostModel)
    static_universe: set[str] | None = None


@dataclass(frozen=True)
class WalkForward:
    config: WalkForwardConfig
    loader: LoaderLike
    signal_fn: SignalFn

    def run(self, start: date, end: date) -> Portfolio:
        if end <= start:
            raise ValueError("end must be after start")
        rebalance_dates = _rebalance_dates(start, end, self.config.step_size_days)
        current_weights: dict[str, float] = {}
        equity = INITIAL_EQUITY
        equity_points: list[tuple[pd.Timestamp, float]] = [(pd.Timestamp(start), equity)]
        return_points: list[tuple[pd.Timestamp, float]] = []
        position_rows: list[dict[str, object]] = []
        trade_rows: list[dict[str, object]] = []

        for index, rebalance_at in enumerate(rebalance_dates):
            next_rebalance = rebalance_dates[index + 1] if index + 1 < len(rebalance_dates) else end
            universe = self._universe(rebalance_at)
            target = self._target_weights(rebalance_at, universe)
            turnover = turnover_between(current_weights, target)
            cost_return = rebalance_cost_return(current_weights, target, self.config.cost_model)
            equity *= 1.0 - cost_return
            trade_rows.append(_trade_row(rebalance_at, turnover, cost_return, target))
            equity_points.append((pd.Timestamp(rebalance_at), equity))
            return_points.append((pd.Timestamp(rebalance_at), -cost_return))
            current_weights = target
            position_rows.append(_position_row(rebalance_at, current_weights))
            equity = self._simulate_period(
                current_weights,
                start=rebalance_at,
                end=next_rebalance,
                equity=equity,
                equity_points=equity_points,
                return_points=return_points,
            )

        return Portfolio(
            positions=(
                pd.DataFrame(position_rows).set_index("date")
                if position_rows
                else pd.DataFrame()
            ),
            equity_curve=_series(equity_points, "equity"),
            period_returns=_series(return_points, "return"),
            trades=pd.DataFrame(trade_rows),
        )

    def _universe(self, as_of: date) -> set[str]:
        if self.config.static_universe is not None:
            return set(self.config.static_universe)
        return self.loader.universe_members(as_of)

    def _target_weights(self, as_of: date, universe: set[str]) -> dict[str, float]:
        scoped_loader = ScopedPITLoader(self.loader, as_of)
        scores = self.signal_fn(as_of, universe, scoped_loader)
        filtered = {ticker: score for ticker, score in scores.items() if ticker in universe}
        return target_weights(
            filtered,
            max_positions=self.config.max_positions,
            sizing_rule=self.config.position_sizing,
            max_gross_exposure=self.config.max_gross_exposure,
        )

    def _simulate_period(
        self,
        weights: dict[str, float],
        *,
        start: date,
        end: date,
        equity: float,
        equity_points: list[tuple[pd.Timestamp, float]],
        return_points: list[tuple[pd.Timestamp, float]],
    ) -> float:
        if not weights or end <= start:
            return equity
        price_frame = _prices_to_pandas(
            self.loader.prices(
                sorted(weights),
                as_of=end,
                lookback_days=max((end - start).days + 1, 1),
            )
        )
        returns = _weighted_returns(price_frame, weights, start=start, end=end)
        for timestamp, period_return in returns.items():
            equity *= 1.0 + float(period_return)
            equity_points.append((cast(pd.Timestamp, timestamp), equity))
            return_points.append((cast(pd.Timestamp, timestamp), float(period_return)))
        return equity


def _rebalance_dates(start: date, end: date, step_size_days: int) -> list[date]:
    if step_size_days < 1:
        raise ValueError("step_size_days must be >= 1")
    values = [item.date() for item in pd.date_range(start, end, freq=f"{step_size_days}D")]
    if values[-1] != end:
        values.append(end)
    return values[:-1]


def _prices_to_pandas(frame: pl.DataFrame) -> pd.DataFrame:
    pandas = frame.to_pandas()
    pandas["date"] = pd.to_datetime(pandas["date"])
    price_column = "adj_close" if "adj_close" in pandas.columns else "close"
    return pandas[["date", "ticker", price_column]].rename(columns={price_column: "price"})


def _weighted_returns(
    prices: pd.DataFrame,
    weights: dict[str, float],
    *,
    start: date,
    end: date,
) -> pd.Series:
    pivot = prices.pivot_table(index="date", columns="ticker", values="price", aggfunc="last")
    pivot = pivot.sort_index().ffill()
    pivot = pivot[(pivot.index >= pd.Timestamp(start)) & (pivot.index <= pd.Timestamp(end))]
    returns = pivot.pct_change().dropna(how="all").fillna(0.0)
    weight_series = pd.Series(weights, dtype="float64")
    aligned_weights = weight_series.reindex(returns.columns).fillna(0.0)
    return returns.mul(aligned_weights, axis=1).sum(axis=1)


def _trade_row(
    rebalance_at: date,
    turnover: float,
    cost_return: float,
    target: dict[str, float],
) -> dict[str, object]:
    return {
        "date": rebalance_at,
        "turnover": turnover,
        "cost_return": cost_return,
        "gross_exposure": sum(abs(weight) for weight in target.values()),
    }


def _position_row(rebalance_at: date, weights: dict[str, float]) -> dict[str, object]:
    return {"date": rebalance_at, **weights}


def _series(points: list[tuple[pd.Timestamp, float]], name: str) -> pd.Series:
    series = pd.Series(dict(points), name=name).sort_index()
    return series[~series.index.duplicated(keep="last")]
