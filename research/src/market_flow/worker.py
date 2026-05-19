from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics.forward_returns import RETURN_PREFIX, compute_forward_returns
from statistics.ic import compute_ic
from typing import Any, Protocol

import pandas as pd
import polars as pl
from market_flow.features import (
    FEATURE_COLUMNS,
    MarketFlowFeatureConfig,
    market_flow_feature_frame,
)

DEFAULT_HORIZONS = (5, 20)
DEFAULT_THRESHOLDS = (0.0, 0.15, 0.30, 0.50)
DEFAULT_TEST_FRACTION = 0.30
MIN_PRECISION_FOR_WEIGHT = 0.55


class MarketFlowWorkerLoader(Protocol):
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...


@dataclass(frozen=True)
class MarketFlowWorkerConfig:
    start: date
    end: date
    tickers: tuple[str, ...]
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    step_size_days: int = 21
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS
    feature_config: MarketFlowFeatureConfig = MarketFlowFeatureConfig()
    test_fraction: float = DEFAULT_TEST_FRACTION
    min_train_observations: int = 20
    min_test_observations: int = 10


@dataclass(frozen=True)
class MarketFlowWorkerResult:
    config: MarketFlowWorkerConfig
    features: pd.DataFrame
    ic: pd.DataFrame
    threshold_sweep: pd.DataFrame
    calibration: dict[str, object]
    written_paths: tuple[str, ...]


def run_market_flow_worker(
    *,
    config: MarketFlowWorkerConfig,
    loader: MarketFlowWorkerLoader,
    output_root: Path,
) -> MarketFlowWorkerResult:
    """Run the market-flow analysis worker and write auditable artifacts."""
    _validate_config(config)
    features = build_feature_history(config, loader)
    forward_returns = _forward_returns(config, loader, features)
    ic = _ic_frame(features, forward_returns, config.horizons)
    threshold_sweep = _threshold_sweep(features, forward_returns, config)
    calibration = _calibration(config, features, ic, threshold_sweep)
    written_paths = _write_outputs(
        output_root,
        features=features,
        ic=ic,
        threshold_sweep=threshold_sweep,
        calibration=calibration,
    )
    return MarketFlowWorkerResult(config, features, ic, threshold_sweep, calibration, written_paths)


def build_feature_history(
    config: MarketFlowWorkerConfig,
    loader: MarketFlowWorkerLoader,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    universe = {ticker.upper() for ticker in config.tickers}
    for as_of in _evaluation_dates(config):
        frame = market_flow_feature_frame(as_of, universe, loader, config.feature_config)
        if frame.empty:
            continue
        frame.insert(0, "date", pd.Timestamp(as_of))
        rows.append(frame)
    if not rows:
        return _empty_features()
    return pd.concat(rows, ignore_index=True).sort_values(["date", "ticker"]).reset_index(
        drop=True
    )


def calibration_to_markdown(calibration: dict[str, object]) -> str:
    coverage = calibration.get("coverage_summary", {})
    if not isinstance(coverage, dict):
        coverage = {}
    lines = [
        "# T110-T115 Market-Flow Worker Calibration",
        "",
        f"Verdict: `{calibration['verdict']}`",
        f"Worker: `{calibration['worker']}`",
        "",
        "## Coverage",
        "",
        f"- Feature rows: {_fmt(coverage.get('feature_rows'))}",
        f"- Feature dates: {_fmt(coverage.get('feature_dates'))}",
        f"- Feature tickers: {_fmt(coverage.get('feature_tickers'))}",
        f"- IC observations: {_fmt(coverage.get('ic_observations'))}",
        f"- Max holdout selections: {_fmt(coverage.get('max_test_selected_count'))}",
        "",
        "## Runtime Guidance",
        "",
        "| Lane | Recommendation | Weight | Threshold | Horizon | "
        "Test precision | Test mean return |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    guidance = calibration["runtime_guidance"]
    if not isinstance(guidance, dict):
        raise TypeError("runtime_guidance must be an object")
    for lane, item in sorted(guidance.items()):
        if not isinstance(item, dict):
            raise TypeError("guidance rows must be objects")
        lines.append(
            "| "
            f"{lane} | {item['recommendation']} | {_fmt(item['suggested_weight'])} | "
            f"{_fmt(item['threshold'])} | {_fmt(item['horizon'])} | "
            f"{_fmt(item['test_precision_positive'])} | {_fmt(item['test_mean_return'])} |"
        )
    lines.extend(["", f"Rationale: {calibration['rationale']}", ""])
    return "\n".join(lines)


def _forward_returns(
    config: MarketFlowWorkerConfig,
    loader: MarketFlowWorkerLoader,
    features: pd.DataFrame,
) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame(columns=["date", "ticker"])
    tickers = sorted({str(ticker).upper() for ticker in features["ticker"].unique()})
    lookback_days = max((config.end - config.start).days + max(config.horizons) + 1, 1)
    prices = loader.prices(tickers, config.end, lookback_days).to_pandas()
    price_column = "adj_close" if "adj_close" in prices.columns else "close"
    prices = prices[["date", "ticker", price_column]].rename(columns={price_column: "adj_close"})
    return compute_forward_returns(prices, list(config.horizons))


def _ic_frame(
    features: pd.DataFrame,
    forward_returns: pd.DataFrame,
    horizons: tuple[int, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if features.empty or forward_returns.empty:
        return _empty_ic()
    merged = features.merge(forward_returns, on=["date", "ticker"], how="inner")
    for feature in FEATURE_COLUMNS:
        for horizon in horizons:
            returns_column = f"{RETURN_PREFIX}{horizon}"
            ic = compute_ic(_indexed(merged, feature), _indexed(merged, returns_column))
            rows.append(
                {
                    "feature": feature,
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


def _threshold_sweep(
    features: pd.DataFrame,
    forward_returns: pd.DataFrame,
    config: MarketFlowWorkerConfig,
) -> pd.DataFrame:
    if features.empty or forward_returns.empty:
        return _empty_threshold_sweep()
    merged = features.merge(forward_returns, on=["date", "ticker"], how="inner")
    split_date = _split_date(merged["date"], config.test_fraction)
    rows: list[dict[str, object]] = []
    for feature in FEATURE_COLUMNS:
        for horizon in config.horizons:
            for threshold in config.thresholds:
                selected = merged[merged[feature] >= threshold]
                for window, window_frame in (
                    ("train", selected[selected["date"] <= split_date]),
                    ("test", selected[selected["date"] > split_date]),
                    ("all", selected),
                ):
                    rows.append(_threshold_row(feature, horizon, threshold, window, window_frame))
    return pd.DataFrame(rows)


def _threshold_row(
    feature: str,
    horizon: int,
    threshold: float,
    window: str,
    frame: pd.DataFrame,
) -> dict[str, object]:
    returns_column = f"{RETURN_PREFIX}{horizon}"
    returns = pd.to_numeric(frame.get(returns_column, pd.Series(dtype="float64")), errors="coerce")
    returns = returns.dropna()
    selected_count = int(len(returns))
    precision = float((returns > 0.0).mean()) if selected_count else float("nan")
    return {
        "feature": feature,
        "horizon": horizon,
        "threshold": threshold,
        "window": window,
        "selected_count": selected_count,
        "precision_positive": precision,
        "mean_return": float(returns.mean()) if selected_count else float("nan"),
        "median_return": float(returns.median()) if selected_count else float("nan"),
    }


def _calibration(
    config: MarketFlowWorkerConfig,
    features: pd.DataFrame,
    ic: pd.DataFrame,
    threshold_sweep: pd.DataFrame,
) -> dict[str, object]:
    guidance = {
        feature: _feature_guidance(feature, config, threshold_sweep) for feature in FEATURE_COLUMNS
    }
    eligible = [item for item in guidance.values() if _is_runtime_weight_eligible(item)]
    verdict = "market_flow_weight_eligible" if eligible else "context_only_until_more_coverage"
    return {
        "schema_version": "0.1.0",
        "worker": "market_flow_analysis_worker",
        "config": _config_json(config),
        "coverage_summary": _coverage_summary(features, ic, threshold_sweep),
        "ic_summary": _best_ic_rows(ic),
        "runtime_guidance": guidance,
        "verdict": verdict,
        "rationale": _rationale(verdict),
    }


def _coverage_summary(
    features: pd.DataFrame,
    ic: pd.DataFrame,
    threshold_sweep: pd.DataFrame,
) -> dict[str, object]:
    feature_dates = 0
    feature_tickers = 0
    if not features.empty:
        feature_dates = int(pd.to_datetime(features["date"]).nunique())
        feature_tickers = int(features["ticker"].nunique())
    ic_observations = 0
    if not ic.empty and "n_observations" in ic.columns:
        ic_observations = int(pd.to_numeric(ic["n_observations"], errors="coerce").fillna(0).max())
    max_test_selected_count = 0
    if not threshold_sweep.empty:
        test = threshold_sweep[threshold_sweep["window"] == "test"]
        if not test.empty:
            max_test_selected_count = int(
                pd.to_numeric(test["selected_count"], errors="coerce").fillna(0).max()
            )
    return {
        "feature_rows": int(len(features)),
        "feature_dates": feature_dates,
        "feature_tickers": feature_tickers,
        "ic_observations": ic_observations,
        "max_test_selected_count": max_test_selected_count,
    }


def _feature_guidance(
    feature: str,
    config: MarketFlowWorkerConfig,
    sweep: pd.DataFrame,
) -> dict[str, object]:
    default = {
        "recommendation": "context_only_until_more_coverage",
        "suggested_weight": 0.0,
        "threshold": None,
        "horizon": None,
        "train_precision_positive": None,
        "train_mean_return": None,
        "train_selected_count": 0,
        "test_precision_positive": None,
        "test_mean_return": None,
        "test_selected_count": 0,
    }
    if sweep.empty:
        return default
    train = sweep[(sweep["feature"] == feature) & (sweep["window"] == "train")]
    train = train[train["selected_count"] >= config.min_train_observations]
    if train.empty:
        return default
    best = train.sort_values(
        ["precision_positive", "mean_return", "selected_count"],
        ascending=[False, False, False],
    ).iloc[0]
    test = _matching_test_row(sweep, best)
    if test is None:
        return default | _guidance_metrics(best, None)
    recommendation = _recommendation(config, test)
    return {
        **default,
        **_guidance_metrics(best, test),
        "recommendation": recommendation,
        "suggested_weight": (
            _suggested_weight(test) if recommendation == "eligible_for_runtime_weight" else 0.0
        ),
        "threshold": float(best["threshold"]),
        "horizon": int(best["horizon"]),
    }


def _matching_test_row(sweep: pd.DataFrame, train_row: pd.Series) -> pd.Series | None:
    matches = sweep[
        (sweep["feature"] == train_row["feature"])
        & (sweep["horizon"] == train_row["horizon"])
        & (sweep["threshold"] == train_row["threshold"])
        & (sweep["window"] == "test")
    ]
    return None if matches.empty else matches.iloc[0]


def _recommendation(config: MarketFlowWorkerConfig, test: pd.Series) -> str:
    if int(test["selected_count"]) < config.min_test_observations:
        return "context_only_until_more_coverage"
    if (
        float(test["precision_positive"]) >= MIN_PRECISION_FOR_WEIGHT
        and float(test["mean_return"]) > 0.0
    ):
        return "eligible_for_runtime_weight"
    return "context_only_until_retest"


def _suggested_weight(test: pd.Series) -> float:
    precision_edge = max(float(test["precision_positive"]) - 0.5, 0.0)
    return round(min(0.7, max(0.2, precision_edge * 4.0)), 3)


def _guidance_metrics(best: pd.Series, test: pd.Series | None) -> dict[str, object]:
    return {
        "train_precision_positive": _finite_or_none(best["precision_positive"]),
        "train_mean_return": _finite_or_none(best["mean_return"]),
        "train_selected_count": int(best["selected_count"]),
        "test_precision_positive": (
            None if test is None else _finite_or_none(test["precision_positive"])
        ),
        "test_mean_return": None if test is None else _finite_or_none(test["mean_return"]),
        "test_selected_count": 0 if test is None else int(test["selected_count"]),
    }


def _best_ic_rows(ic: pd.DataFrame) -> list[dict[str, object]]:
    if ic.empty:
        return []
    rows: list[dict[str, object]] = []
    for _feature, group in ic.groupby("feature", sort=True):
        ordered = group.assign(__abs_ic=group["mean_ic"].abs()).sort_values(
            ["__abs_ic", "n_observations"],
            ascending=[False, False],
        )
        rows.append(_series_json(ordered.iloc[0].drop(labels=["__abs_ic"])))
    return rows


def _write_outputs(
    output_root: Path,
    *,
    features: pd.DataFrame,
    ic: pd.DataFrame,
    threshold_sweep: pd.DataFrame,
    calibration: dict[str, object],
) -> tuple[str, ...]:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "market-flow-features.csv": features,
        "market-flow-ic.csv": ic,
        "market-flow-threshold-sweep.csv": threshold_sweep,
    }
    for name, frame in outputs.items():
        frame.to_csv(output_root / name, index=False)
    (output_root / "market-flow-calibration.json").write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "market-flow-calibration.md").write_text(
        calibration_to_markdown(calibration),
        encoding="utf-8",
    )
    return (*outputs.keys(), "market-flow-calibration.json", "market-flow-calibration.md")


def _indexed(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.set_index(["date", "ticker"])[column].sort_index()


def _evaluation_dates(config: MarketFlowWorkerConfig) -> list[date]:
    return [
        item.date()
        for item in pd.date_range(config.start, config.end, freq=f"{config.step_size_days}D")
    ]


def _split_date(series: pd.Series, test_fraction: float) -> pd.Timestamp:
    dates = sorted(pd.to_datetime(series).dropna().unique())
    if len(dates) <= 1:
        return pd.Timestamp.max
    split_index = max(1, int(len(dates) * (1.0 - test_fraction))) - 1
    split_index = min(split_index, len(dates) - 2)
    return pd.Timestamp(dates[split_index])


def _two_sided_p_value(t_stat: float, n_observations: int) -> float:
    if n_observations <= 1 or not math.isfinite(t_stat):
        return float("nan")
    from scipy import stats  # type: ignore[import-untyped]

    return float(2.0 * stats.t.sf(abs(t_stat), df=n_observations - 1))


def _config_json(config: MarketFlowWorkerConfig) -> dict[str, object]:
    data = asdict(config)
    data["start"] = config.start.isoformat()
    data["end"] = config.end.isoformat()
    return data


def _series_json(series: pd.Series) -> dict[str, object]:
    return {str(key): _json_value(value) for key, value in series.items()}


def _json_value(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return _finite_or_none(value)
    return value


def _is_runtime_weight_eligible(item: object) -> bool:
    return isinstance(item, dict) and item.get("recommendation") == "eligible_for_runtime_weight"


def _finite_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _rationale(verdict: str) -> str:
    if verdict == "market_flow_weight_eligible":
        return "At least one market-flow feature passed train selection and holdout checks."
    return (
        "Market-flow features are available for analysis, but the worker did not find "
        "enough holdout evidence to increase runtime weights yet."
    )


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _empty_features() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "ticker", *FEATURE_COLUMNS])


def _empty_ic() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "feature",
            "horizon",
            "mean_ic",
            "ic_std",
            "t_stat",
            "information_ratio",
            "n_observations",
            "p_value",
        ]
    )


def _empty_threshold_sweep() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "feature",
            "horizon",
            "threshold",
            "window",
            "selected_count",
            "precision_positive",
            "mean_return",
            "median_return",
        ]
    )


def _validate_config(config: MarketFlowWorkerConfig) -> None:
    if config.end < config.start:
        raise ValueError("end must be on or after start")
    if not config.tickers:
        raise ValueError("tickers must not be empty")
    if config.step_size_days < 1:
        raise ValueError("step_size_days must be >= 1")
    if not config.horizons or any(horizon < 1 for horizon in config.horizons):
        raise ValueError("horizons must be positive")
    if any(threshold < 0.0 for threshold in config.thresholds):
        raise ValueError("thresholds must be non-negative")
    if not 0.0 < config.test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")
