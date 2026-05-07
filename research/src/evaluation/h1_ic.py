from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from statistics.forward_returns import RETURN_PREFIX, compute_forward_returns
from statistics.ic import compute_ic

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
    results = _ic_results(signal_name, scores, forward_returns, config.horizons)
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
    horizons: tuple[int, ...],
) -> pd.DataFrame:
    rows = []
    if scores.empty or forward_returns.empty:
        return _empty_results()
    merged = scores.merge(forward_returns, on=["date", "ticker"], how="inner")
    for horizon in horizons:
        column = f"{RETURN_PREFIX}{horizon}"
        ic = compute_ic(_indexed(merged, "score"), _indexed(merged, column))
        rows.append(
            {
                "signal": signal_name,
                "horizon": horizon,
                "mean_ic": ic.mean_ic,
                "ic_std": ic.ic_std,
                "t_stat": ic.t_stat,
                "information_ratio": ic.information_ratio,
                "n_observations": ic.n_observations,
                "p_value": _two_sided_p_value(ic.t_stat, ic.n_observations),
            }
        )
    return pd.DataFrame(rows)


def _indexed(frame: pd.DataFrame, column: str) -> pd.Series:
    series = frame.set_index(["date", "ticker"])[column]
    return series.sort_index()


def _two_sided_p_value(t_stat: float, n_observations: int) -> float:
    if n_observations <= 1 or not math.isfinite(t_stat):
        return float("nan")
    return math.erfc(abs(t_stat) / math.sqrt(2.0))


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
            "p_value",
        ]
    )
