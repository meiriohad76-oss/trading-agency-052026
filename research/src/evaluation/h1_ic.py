from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from statistics.forward_returns import RETURN_PREFIX, compute_forward_returns
from statistics.ic import compute_ic

import numpy as np
import pandas as pd
from backtests.scoped_loader import LoaderLike, ScopedPITLoader

SignalFn = Callable[[date, set[str], LoaderLike], dict[str, float]]


@dataclass(frozen=True)
class H1ICConfig:
    start: date
    end: date
    horizons: tuple[int, ...] = (5, 20)
    step_size_days: int = 1
    static_universe: set[str] | None = None
    bootstrap_iterations: int = 1000
    bootstrap_seed: int = 1729


@dataclass(frozen=True)
class H1ICReport:
    signal_name: str
    scores: pd.DataFrame
    forward_returns: pd.DataFrame
    results: pd.DataFrame


def evaluate_signal_ic(
    *,
    signal_name: str,
    signal_fn: SignalFn,
    loader: LoaderLike,
    config: H1ICConfig,
) -> H1ICReport:
    """Evaluate a signal with PIT-scoped scores and future-return labels."""
    _validate_config(config)
    scores = _score_frame(signal_fn, loader, config)
    prices = _price_frame(loader, config, scores)
    forward_returns = (
        pd.DataFrame()
        if prices.empty
        else compute_forward_returns(prices, list(config.horizons))
    )
    results = _ic_results(signal_name, scores, forward_returns, config)
    return H1ICReport(signal_name, scores, forward_returns, results)


def _score_frame(signal_fn: SignalFn, loader: LoaderLike, config: H1ICConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for as_of in _evaluation_dates(config):
        universe = set(config.static_universe or loader.universe_members(as_of))
        scoped = ScopedPITLoader(loader, as_of)
        scores = signal_fn(as_of, universe, scoped)
        rows.extend(
            {"date": pd.Timestamp(as_of), "ticker": ticker.upper(), "score": score}
            for ticker, score in sorted(scores.items())
        )
    return pd.DataFrame(rows, columns=["date", "ticker", "score"])


def _price_frame(loader: LoaderLike, config: H1ICConfig, scores: pd.DataFrame) -> pd.DataFrame:
    tickers = sorted(set(config.static_universe or []) | set(scores.get("ticker", [])))
    if not tickers:
        return pd.DataFrame(columns=["date", "ticker", "adj_close"])
    lookback_days = (config.end - config.start).days + 1
    frame = loader.prices(tickers, config.end, lookback_days)
    pandas = frame.to_pandas()
    price_column = "adj_close" if "adj_close" in pandas.columns else "close"
    return pandas[["date", "ticker", price_column]].rename(columns={price_column: "adj_close"})


def _ic_results(
    signal_name: str,
    scores: pd.DataFrame,
    forward_returns: pd.DataFrame,
    config: H1ICConfig,
) -> pd.DataFrame:
    rows = []
    if scores.empty or forward_returns.empty:
        return _empty_results()
    merged = scores.merge(forward_returns, on=["date", "ticker"], how="inner")
    for horizon in config.horizons:
        column = f"{RETURN_PREFIX}{horizon}"
        ic = compute_ic(_indexed(merged, "score"), _indexed(merged, column))
        lag = _hac_lag(horizon, config.step_size_days)
        hac_t_stat = _hac_t_stat(ic.ic_series, lag)
        p_value_hac = _two_sided_p_value(hac_t_stat, ic.n_observations)
        p_value_bootstrap = _moving_block_bootstrap_p_value(
            ic.ic_series,
            block_size=max(lag + 1, 1),
            iterations=config.bootstrap_iterations,
            seed=config.bootstrap_seed + horizon,
        )
        if lag > 0:
            p_values = [
                value
                for value in (p_value_hac, p_value_bootstrap)
                if math.isfinite(value)
            ]
            p_value = max(p_values) if p_values else float("nan")
            p_value_method = "hac_max_moving_block_bootstrap"
        else:
            p_value = _two_sided_p_value(ic.t_stat, ic.n_observations)
            p_value_method = "student_t"
        rows.append(
            {
                "signal": signal_name,
                "horizon": horizon,
                "mean_ic": ic.mean_ic,
                "ic_std": ic.ic_std,
                "t_stat": hac_t_stat if lag > 0 and math.isfinite(hac_t_stat) else ic.t_stat,
                "t_stat_iid": ic.t_stat,
                "t_stat_hac": hac_t_stat,
                "information_ratio": ic.information_ratio,
                "n_observations": ic.n_observations,
                "hac_lag": lag,
                "p_value": p_value,
                "p_value_iid": _two_sided_p_value(ic.t_stat, ic.n_observations),
                "p_value_hac": p_value_hac,
                "p_value_bootstrap": p_value_bootstrap,
                "p_value_method": p_value_method,
            }
        )
    return pd.DataFrame(rows)


def _indexed(frame: pd.DataFrame, column: str) -> pd.Series:
    series = frame.set_index(["date", "ticker"])[column]
    return series.sort_index()


def _two_sided_p_value(t_stat: float, n_observations: int) -> float:
    if n_observations <= 1 or not math.isfinite(t_stat):
        return float("nan")
    from scipy import stats  # type: ignore[import-untyped]

    return float(2.0 * stats.t.sf(abs(t_stat), df=n_observations - 1))


def _hac_lag(horizon: int, step_size_days: int) -> int:
    if horizon <= step_size_days:
        return 0
    return max(0, math.ceil(horizon / step_size_days) - 1)


def _hac_t_stat(ic_series: pd.Series, lag: int) -> float:
    clean = ic_series.dropna().astype("float64")
    n_observations = len(clean)
    if n_observations <= 1:
        return float("nan")
    if lag <= 0:
        std = float(clean.std(ddof=1))
        if std <= 0.0 or not math.isfinite(std):
            return float("nan")
        return float(clean.mean()) / (std / math.sqrt(n_observations))
    lag = min(lag, n_observations - 1)
    values = clean.to_numpy(dtype="float64")
    mean_value = float(values.mean())
    centered = values - mean_value
    long_run_variance = float(np.dot(centered, centered) / n_observations)
    for item_lag in range(1, lag + 1):
        covariance = float(np.dot(centered[item_lag:], centered[:-item_lag]) / n_observations)
        weight = 1.0 - item_lag / (lag + 1.0)
        long_run_variance += 2.0 * weight * covariance
    if long_run_variance <= 0.0 or not math.isfinite(long_run_variance):
        return float("nan")
    standard_error = math.sqrt(long_run_variance / n_observations)
    return mean_value / standard_error if standard_error > 0 else float("nan")


def _moving_block_bootstrap_p_value(
    ic_series: pd.Series,
    *,
    block_size: int,
    iterations: int,
    seed: int,
) -> float:
    clean = ic_series.dropna().astype("float64")
    n_observations = len(clean)
    if n_observations <= 1:
        return float("nan")
    if iterations < 1:
        return float("nan")
    values = clean.to_numpy(dtype="float64")
    observed = abs(float(values.mean()))
    centered = values - float(values.mean())
    block_size = max(1, min(block_size, n_observations))
    starts = np.arange(0, n_observations - block_size + 1)
    rng = np.random.default_rng(seed)
    exceedances = 0
    for _index in range(iterations):
        sampled: list[np.ndarray] = []
        while sum(len(block) for block in sampled) < n_observations:
            start = int(rng.choice(starts))
            sampled.append(centered[start : start + block_size])
        bootstrap_values = np.concatenate(sampled)[:n_observations]
        if abs(float(bootstrap_values.mean())) >= observed:
            exceedances += 1
    return float((exceedances + 1) / (iterations + 1))


def _evaluation_dates(config: H1ICConfig) -> list[date]:
    return [
        item.date()
        for item in pd.date_range(config.start, config.end, freq=f"{config.step_size_days}D")
    ]


def _validate_config(config: H1ICConfig) -> None:
    if config.end <= config.start:
        raise ValueError("end must be after start")
    if config.step_size_days < 1:
        raise ValueError("step_size_days must be >= 1")
    if not config.horizons or any(horizon < 1 for horizon in config.horizons):
        raise ValueError("horizons must be positive")
    if len(config.horizons) != len(set(config.horizons)):
        raise ValueError("horizons must be unique")
    if config.bootstrap_iterations < 0:
        raise ValueError("bootstrap_iterations must be >= 0")


def _empty_results() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "signal",
            "horizon",
            "mean_ic",
            "ic_std",
            "t_stat",
            "information_ratio",
            "n_observations",
            "t_stat_iid",
            "t_stat_hac",
            "hac_lag",
            "p_value",
            "p_value_iid",
            "p_value_hac",
            "p_value_bootstrap",
            "p_value_method",
        ]
    )
