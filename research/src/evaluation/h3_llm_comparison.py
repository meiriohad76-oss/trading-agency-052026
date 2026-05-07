from __future__ import annotations

import math

import pandas as pd

DEFAULT_MIN_SHARPE_DELTA = 0.05
DEFAULT_MIN_CAGR_DELTA = 0.0
DEFAULT_MAX_DRAWDOWN_TOLERANCE = 0.02


def summarize_llm_ab(
    ab_results: pd.DataFrame,
    *,
    min_sharpe_delta: float = DEFAULT_MIN_SHARPE_DELTA,
    min_cagr_delta: float = DEFAULT_MIN_CAGR_DELTA,
    max_drawdown_tolerance: float = DEFAULT_MAX_DRAWDOWN_TOLERANCE,
) -> pd.DataFrame:
    """Summarize deterministic-vs-reviewed H3 A/B rows into one verdict row."""
    _require_columns(ab_results)
    deterministic = ab_results[ab_results["variant"] == "deterministic"]
    reviewed = ab_results[ab_results["variant"] == "reviewed"]
    if len(deterministic) != 1:
        raise ValueError("expected exactly one deterministic row")
    if reviewed.empty:
        raise ValueError("expected at least one reviewed row")

    det = deterministic.iloc[0]
    deterministic_sharpe = _row_float(det, "sharpe")
    reviewed_mean_sharpe = _mean(reviewed, "sharpe")
    deterministic_cagr = _row_float(det, "cagr")
    reviewed_mean_cagr = _mean(reviewed, "cagr")
    deterministic_max_drawdown = _row_float(det, "max_drawdown")
    reviewed_mean_max_drawdown = _mean(reviewed, "max_drawdown")
    deterministic_turnover = _row_float(det, "turnover")
    reviewed_mean_turnover = _mean(reviewed, "turnover")
    sharpe_delta = reviewed_mean_sharpe - deterministic_sharpe
    cagr_delta = reviewed_mean_cagr - deterministic_cagr
    max_drawdown_delta = reviewed_mean_max_drawdown - deterministic_max_drawdown
    turnover_delta = reviewed_mean_turnover - deterministic_turnover
    verdict = _verdict(
        sharpe_delta=sharpe_delta,
        cagr_delta=cagr_delta,
        max_drawdown_delta=max_drawdown_delta,
        min_sharpe_delta=min_sharpe_delta,
        min_cagr_delta=min_cagr_delta,
        max_drawdown_tolerance=max_drawdown_tolerance,
    )
    row: dict[str, object] = {
        "deterministic_sharpe": deterministic_sharpe,
        "reviewed_mean_sharpe": reviewed_mean_sharpe,
        "reviewed_std_sharpe": _std(reviewed, "sharpe"),
        "deterministic_cagr": deterministic_cagr,
        "reviewed_mean_cagr": reviewed_mean_cagr,
        "reviewed_std_cagr": _std(reviewed, "cagr"),
        "deterministic_max_drawdown": deterministic_max_drawdown,
        "reviewed_mean_max_drawdown": reviewed_mean_max_drawdown,
        "deterministic_turnover": deterministic_turnover,
        "reviewed_mean_turnover": reviewed_mean_turnover,
        "reviewed_repeats": int(reviewed["repeat"].nunique()),
        "sharpe_delta": sharpe_delta,
        "cagr_delta": cagr_delta,
        "max_drawdown_delta": max_drawdown_delta,
        "turnover_delta": turnover_delta,
        "verdict": verdict,
    }
    return pd.DataFrame([row])


def llm_ab_summary_to_markdown(summary: pd.DataFrame) -> str:
    """Render the H3 summary for docs/findings.md."""
    _require_summary_columns(summary)
    row = summary.iloc[0]
    lines = [
        "| Metric | Deterministic | Reviewed mean | Delta |",
        "| --- | --- | --- | --- |",
        _metric_line(row, "Sharpe", "deterministic_sharpe", "reviewed_mean_sharpe", "sharpe_delta"),
        _metric_line(row, "CAGR", "deterministic_cagr", "reviewed_mean_cagr", "cagr_delta"),
        _metric_line(
            row,
            "Max drawdown",
            "deterministic_max_drawdown",
            "reviewed_mean_max_drawdown",
            "max_drawdown_delta",
        ),
        _metric_line(
            row,
            "Turnover",
            "deterministic_turnover",
            "reviewed_mean_turnover",
            "turnover_delta",
        ),
        "",
        f"Verdict: `{row['verdict']}` across {int(row['reviewed_repeats'])} reviewed repeat(s).",
    ]
    return "\n".join(lines) + "\n"


def _verdict(
    *,
    sharpe_delta: float,
    cagr_delta: float,
    max_drawdown_delta: float,
    min_sharpe_delta: float,
    min_cagr_delta: float,
    max_drawdown_tolerance: float,
) -> str:
    values = [sharpe_delta, cagr_delta, max_drawdown_delta]
    if not all(math.isfinite(value) for value in values):
        return "inconclusive"
    drawdown_ok = max_drawdown_delta >= -max_drawdown_tolerance
    if sharpe_delta >= min_sharpe_delta and cagr_delta >= min_cagr_delta and drawdown_ok:
        return "llm_survives"
    if sharpe_delta < 0.0 or cagr_delta < 0.0:
        return "deterministic_only"
    return "inconclusive"


def _metric_line(
    row: pd.Series,
    label: str,
    deterministic_column: str,
    reviewed_column: str,
    delta_column: str,
) -> str:
    values = [
        label,
        _format_float(_row_float(row, deterministic_column)),
        _format_float(_row_float(row, reviewed_column)),
        _format_float(_row_float(row, delta_column)),
    ]
    return "| " + " | ".join(values) + " |"


def _format_float(value: float) -> str:
    return f"{value:.4f}" if math.isfinite(value) else "nan"


def _row_float(row: pd.Series, column: str) -> float:
    return float(row[column])


def _mean(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].mean())


def _std(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].std(ddof=0))


def _require_columns(frame: pd.DataFrame) -> None:
    required = {"variant", "repeat", "sharpe", "cagr", "max_drawdown", "turnover"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")


def _require_summary_columns(frame: pd.DataFrame) -> None:
    required = {
        "deterministic_sharpe",
        "reviewed_mean_sharpe",
        "sharpe_delta",
        "deterministic_cagr",
        "reviewed_mean_cagr",
        "cagr_delta",
        "deterministic_max_drawdown",
        "reviewed_mean_max_drawdown",
        "max_drawdown_delta",
        "deterministic_turnover",
        "reviewed_mean_turnover",
        "turnover_delta",
        "reviewed_repeats",
        "verdict",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
