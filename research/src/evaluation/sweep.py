from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import date

import pandas as pd
from backtests.portfolio import CostModel, PositionSizingRule
from backtests.scoped_loader import LoaderLike, SignalFn
from backtests.walk_forward import WalkForwardConfig
from evaluation.profile import profile_strategy, profile_to_frame


@dataclass(frozen=True)
class SweepPoint:
    step_size_days: int
    max_positions: int
    score_threshold: float
    position_sizing: PositionSizingRule = "equal_weight"
    max_gross_exposure: float = 1.0
    bps_per_side: float = 5.0
    slippage_bps: float = 0.0


def threshold_signal(signal_fn: SignalFn, threshold: float) -> SignalFn:
    """Wrap a signal so low-conviction absolute scores are removed."""
    if threshold < 0.0:
        raise ValueError("threshold must be non-negative")

    def wrapped(as_of: date, universe: set[str], loader: LoaderLike) -> dict[str, float]:
        scores = signal_fn(as_of, universe, loader)
        return {ticker: score for ticker, score in scores.items() if abs(score) >= threshold}

    return wrapped


def run_parameter_sweep(
    *,
    name: str,
    base_config: WalkForwardConfig,
    points: Iterable[SweepPoint],
    loader: LoaderLike,
    signal_fn: SignalFn,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Run a deterministic H5 parameter sweep and return one row per point."""
    rows: list[pd.DataFrame] = []
    for index, point in enumerate(points):
        config = _config_for_point(base_config, point)
        profile = profile_strategy(
            name=f"{name}:{index}",
            config=config,
            loader=loader,
            signal_fn=threshold_signal(signal_fn, point.score_threshold),
            start=start,
            end=end,
        )
        frame = profile_to_frame(profile)
        for key, value in asdict(point).items():
            frame[key] = value
        rows.append(frame)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values(
        ["sharpe", "cagr"], ascending=[False, False]
    )


def best_by_sharpe(
    sweep: pd.DataFrame,
    *,
    max_drawdown_floor: float | None = None,
) -> pd.Series:
    """Select the best Sharpe row, optionally enforcing a drawdown floor."""
    candidates = sweep
    if max_drawdown_floor is not None:
        candidates = candidates[candidates["max_drawdown"] >= max_drawdown_floor]
    if candidates.empty:
        raise ValueError("no sweep rows match constraints")
    return candidates.sort_values(["sharpe", "cagr"], ascending=[False, False]).iloc[0]


def _config_for_point(base_config: WalkForwardConfig, point: SweepPoint) -> WalkForwardConfig:
    return replace(
        base_config,
        step_size_days=point.step_size_days,
        max_positions=point.max_positions,
        position_sizing=point.position_sizing,
        max_gross_exposure=point.max_gross_exposure,
        cost_model=CostModel(
            bps_per_side=point.bps_per_side,
            slippage_bps=point.slippage_bps,
        ),
    )
