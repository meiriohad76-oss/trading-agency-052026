from __future__ import annotations

import pandas as pd

BASIS_POINTS = 10_000


def apply_costs(returns: pd.Series, turnover: pd.Series, bps: float) -> pd.Series:
    """Subtract transaction costs from returns.

    Turnover is one-sided turnover, conventionally
    `sum(abs(w_t - w_t-1)) / 2`. `bps` is per-side cost in basis points, so a
    period with 100% turnover and 5 bps per side pays 10 bps total:
    `1.0 * 2 * 5 / 10_000`.
    """
    if bps < 0:
        raise ValueError("bps must be non-negative")
    aligned_returns, aligned_turnover = returns.align(turnover, join="inner")
    cost = aligned_turnover.astype("float64") * (2.0 * bps / BASIS_POINTS)
    adjusted = aligned_returns.astype("float64") - cost
    adjusted.name = returns.name
    return adjusted
