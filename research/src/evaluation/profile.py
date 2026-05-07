from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd
from backtests.metrics import PerformanceReport, compute_performance
from backtests.scoped_loader import LoaderLike, SignalFn
from backtests.walk_forward import WalkForward, WalkForwardConfig

WEEKLY_TARGET_RETURN = 0.03


@dataclass(frozen=True)
class StrategyProfile:
    name: str
    start: date
    end: date
    performance: PerformanceReport
    weekly_return: float
    weekly_target: float
    weekly_target_gap: float


def profile_strategy(
    *,
    name: str,
    config: WalkForwardConfig,
    loader: LoaderLike,
    signal_fn: SignalFn,
    start: date,
    end: date,
) -> StrategyProfile:
    """Run a walk-forward profile and compute H4 performance metrics."""
    portfolio = WalkForward(config, loader, signal_fn).run(start, end)
    performance = compute_performance(portfolio.equity_curve, portfolio.trades)
    weekly_return = _annual_to_weekly(performance.cagr)
    return StrategyProfile(
        name=name,
        start=start,
        end=end,
        performance=performance,
        weekly_return=weekly_return,
        weekly_target=WEEKLY_TARGET_RETURN,
        weekly_target_gap=weekly_return - WEEKLY_TARGET_RETURN,
    )


def profile_to_frame(profile: StrategyProfile) -> pd.DataFrame:
    row = {
        "name": profile.name,
        "start": profile.start,
        "end": profile.end,
        "weekly_return": profile.weekly_return,
        "weekly_target": profile.weekly_target,
        "weekly_target_gap": profile.weekly_target_gap,
        **asdict(profile.performance),
    }
    return pd.DataFrame([row])


def _annual_to_weekly(cagr: float) -> float:
    return float((1.0 + cagr) ** (1.0 / 52.0) - 1.0)
