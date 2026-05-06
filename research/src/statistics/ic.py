from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import cast

import numpy as np
import pandas as pd

MIN_CORRELATION_PAIRS = 2


@dataclass(frozen=True)
class ICResult:
    """Summary of a cross-sectional information coefficient series.

    `ic_series` contains one Spearman rank correlation per date or one value
    for a single cross-section. `n_observations` is the number of usable IC
    observations, so the t-stat treats daily IC values as iid:
    `mean_ic / (sample_std / sqrt(n_observations))`.

    For autocorrelated IC series, replace this simple standard error with a
    Newey-West estimate in downstream analysis.
    """

    ic_series: pd.Series
    mean_ic: float
    ic_std: float
    t_stat: float
    information_ratio: float
    n_observations: int


def compute_ic(scores: pd.Series, forward_returns: pd.Series) -> ICResult:
    """Compute Spearman IC for one cross-section or a MultiIndex panel.

    Missing score/return pairs are removed within each cross-section. A date
    only contributes an IC observation when at least two valid pairs remain.
    Spearman is implemented as Pearson correlation on average ranks, matching
    the usual non-parametric monotonic signal test.
    """
    aligned = _aligned_frame(scores, forward_returns)
    if isinstance(aligned.index, pd.MultiIndex):
        date_level = "date" if "date" in aligned.index.names else aligned.index.names[0]
        ic_series = aligned.groupby(level=date_level, sort=True).apply(_spearman_frame)
        ic_series = ic_series.dropna().astype("float64")
    else:
        value = _spearman_frame(aligned)
        ic_series = pd.Series([value], index=pd.Index([0], name="cross_section")).dropna()
    return _summarize(ic_series)


def compute_ic_panel(scores: pd.DataFrame, forward_returns: pd.DataFrame) -> ICResult:
    """Compute cross-sectional IC for wide date-by-ticker panels.

    Both frames must use dates as the index and tickers as columns. The frames
    are stacked to `(date, ticker)` series and delegated to `compute_ic`, so
    missing values are omitted pair-by-pair within each date.
    """
    score_panel, return_panel = scores.align(forward_returns, join="inner", axis=None)
    score_series = cast(pd.Series, score_panel.stack(future_stack=True))
    return_series = cast(pd.Series, return_panel.stack(future_stack=True))
    score_series.index = score_series.index.set_names(["date", "ticker"])
    return_series.index = return_series.index.set_names(["date", "ticker"])
    return compute_ic(score_series, return_series)


def _aligned_frame(scores: pd.Series, forward_returns: pd.Series) -> pd.DataFrame:
    frame = pd.concat(
        [
            scores.rename("score"),
            forward_returns.rename("forward_return"),
        ],
        axis=1,
        join="inner",
    )
    return frame.dropna(subset=["score", "forward_return"])


def _spearman_frame(frame: pd.DataFrame) -> float:
    if len(frame) < MIN_CORRELATION_PAIRS:
        return float("nan")
    ranked = frame[["score", "forward_return"]].rank(method="average")
    if (
        ranked["score"].nunique() < MIN_CORRELATION_PAIRS
        or ranked["forward_return"].nunique() < MIN_CORRELATION_PAIRS
    ):
        return float("nan")
    return float(ranked["score"].corr(ranked["forward_return"]))


def _summarize(ic_series: pd.Series) -> ICResult:
    clean = ic_series.dropna().astype("float64")
    n_observations = int(len(clean))
    if n_observations == 0:
        return ICResult(clean, float("nan"), float("nan"), float("nan"), float("nan"), 0)
    mean_ic = float(clean.mean())
    ic_std = float(clean.std(ddof=1)) if n_observations > 1 else 0.0
    standard_error = ic_std / sqrt(n_observations) if ic_std > 0 else float("nan")
    t_stat = mean_ic / standard_error if np.isfinite(standard_error) else float("nan")
    information_ratio = mean_ic / ic_std if ic_std > 0 else float("nan")
    return ICResult(clean, mean_ic, ic_std, t_stat, information_ratio, n_observations)
