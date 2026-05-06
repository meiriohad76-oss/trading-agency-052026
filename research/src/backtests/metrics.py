from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

TRADING_DAYS = 252
CALENDAR_DAYS = 365.25
MIN_EQUITY_POINTS = 2


@dataclass(frozen=True)
class PerformanceReport:
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    recovery_time_days: int
    hit_rate: float
    average_win: float
    average_loss: float
    turnover: float
    time_in_market: float


def compute_performance(equity_curve: pd.Series, trades: pd.DataFrame) -> PerformanceReport:
    """Compute absolute performance metrics from an equity curve and trade log."""
    equity = equity_curve.sort_index().astype("float64")
    if len(equity) < MIN_EQUITY_POINTS:
        raise ValueError("equity_curve must contain at least two observations")
    returns = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    return PerformanceReport(
        total_return=total_return,
        cagr=_cagr(equity, total_return),
        sharpe=_sharpe(returns),
        max_drawdown=_max_drawdown(equity),
        recovery_time_days=_recovery_time_days(equity),
        hit_rate=_hit_rate(returns),
        average_win=_average(returns[returns > 0.0]),
        average_loss=_average(returns[returns < 0.0]),
        turnover=_trade_sum(trades, "turnover"),
        time_in_market=_time_in_market(trades),
    )


def _cagr(equity: pd.Series, total_return: float) -> float:
    days = max((equity.index[-1] - equity.index[0]).days, 1)
    return float((1.0 + total_return) ** (CALENDAR_DAYS / days) - 1.0)


def _sharpe(returns: pd.Series) -> float:
    std = float(returns.std(ddof=1))
    if std == 0.0 or np.isnan(std):
        return float("nan")
    return float(returns.mean() / std * sqrt(TRADING_DAYS))


def _max_drawdown(equity: pd.Series) -> float:
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _recovery_time_days(equity: pd.Series) -> int:
    high_water = equity.cummax()
    drawdown_start: pd.Timestamp | None = None
    max_days = 0
    for index, value in enumerate(equity.to_list()):
        timestamp = pd.Timestamp(equity.index[index])
        peak = float(high_water.iloc[index])
        if float(value) < peak and drawdown_start is None:
            drawdown_start = timestamp
        elif float(value) >= peak and drawdown_start is not None:
            max_days = max(max_days, (timestamp - drawdown_start).days)
            drawdown_start = None
    if drawdown_start is not None:
        max_days = max(max_days, (pd.Timestamp(equity.index[-1]) - drawdown_start).days)
    return int(max_days)


def _hit_rate(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    return float((returns > 0.0).mean())


def _average(values: pd.Series) -> float:
    return float(values.mean()) if not values.empty else float("nan")


def _trade_sum(trades: pd.DataFrame, column: str) -> float:
    return float(trades[column].sum()) if column in trades else float("nan")


def _time_in_market(trades: pd.DataFrame) -> float:
    if "gross_exposure" not in trades or trades.empty:
        return float("nan")
    return float((trades["gross_exposure"] > 0.0).mean())
