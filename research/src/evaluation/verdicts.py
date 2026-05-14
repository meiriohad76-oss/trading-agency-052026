from __future__ import annotations

import math
from statistics.multiple_comparisons import (
    benjamini_hochberg_adjust,
    bonferroni_adjust,
)

import pandas as pd

DEFAULT_ALPHA = 0.05
DEFAULT_MIN_OBSERVATIONS = 20
DEFAULT_MIN_ABS_IC = 0.01
SIGNAL_VERDICT_COLUMNS = [
    "signal",
    "best_horizon",
    "mean_ic",
    "t_stat",
    "information_ratio",
    "p_value_bonferroni",
    "verdict",
]


def synthesize_horizon_verdicts(
    ic_results: pd.DataFrame,
    *,
    alpha: float = DEFAULT_ALPHA,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    min_abs_ic: float = DEFAULT_MIN_ABS_IC,
) -> pd.DataFrame:
    """Add adjusted p-values and row-level H1 verdicts to IC results."""
    _require_columns(ic_results)
    output = ic_results.copy().reset_index(drop=True)
    p_values = [float(value) for value in output["p_value"].fillna(1.0)]
    output["p_value_bonferroni"] = bonferroni_adjust(p_values)
    output["p_value_bh"] = benjamini_hochberg_adjust(p_values)
    output["verdict"] = [
        _row_verdict(row, alpha=alpha, min_observations=min_observations, min_abs_ic=min_abs_ic)
        for _, row in output.iterrows()
    ]
    return output


def summarize_signal_verdicts(horizon_verdicts: pd.DataFrame) -> pd.DataFrame:
    """Collapse horizon-level verdicts to one verdict row per signal."""
    rows = []
    for signal, group in horizon_verdicts.groupby("signal", sort=True):
        best = _best_row(group)
        rows.append(
            {
                "signal": signal,
                "best_horizon": int(best["horizon"]),
                "mean_ic": float(best["mean_ic"]),
                "t_stat": float(best["t_stat"]),
                "information_ratio": float(best["information_ratio"]),
                "p_value_bonferroni": float(best["p_value_bonferroni"]),
                "verdict": _signal_verdict(group),
            }
        )
    return pd.DataFrame(rows, columns=SIGNAL_VERDICT_COLUMNS)


def verdicts_to_markdown(signal_verdicts: pd.DataFrame) -> str:
    """Render compact Markdown suitable for a findings document."""
    columns = SIGNAL_VERDICT_COLUMNS
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]
    for _, row in signal_verdicts[columns].iterrows():
        lines.append("| " + " | ".join(_format_cell(row[column]) for column in columns) + " |")
    return "\n".join(lines) + "\n"


def _row_verdict(
    row: pd.Series,
    *,
    alpha: float,
    min_observations: int,
    min_abs_ic: float,
) -> str:
    if int(row["n_observations"]) < min_observations:
        return "inconclusive"
    mean_ic = float(row["mean_ic"])
    adjusted = float(row["p_value_bonferroni"])
    if not math.isfinite(mean_ic) or not math.isfinite(adjusted):
        return "inconclusive"
    if adjusted <= alpha and mean_ic >= min_abs_ic:
        return "survive"
    if adjusted <= alpha and mean_ic <= -min_abs_ic:
        return "inverse_candidate"
    if abs(mean_ic) < min_abs_ic:
        return "drop"
    return "inconclusive"


def _signal_verdict(group: pd.DataFrame) -> str:
    verdicts = {str(value) for value in group["verdict"]}
    if "survive" in verdicts:
        return "survive"
    if "inverse_candidate" in verdicts:
        return "inverse_candidate"
    if verdicts == {"drop"}:
        return "drop"
    return "inconclusive"


def _best_row(group: pd.DataFrame) -> pd.Series:
    ranked = group.assign(
        __priority=group["verdict"].map(_verdict_priority),
        __rank=group["mean_ic"].abs(),
    ).sort_values(
        ["__priority", "__rank"], ascending=[False, False]
    )
    return ranked.iloc[0]


def _verdict_priority(value: object) -> int:
    return {
        "survive": 4,
        "inverse_candidate": 3,
        "inconclusive": 2,
        "drop": 1,
    }.get(str(value), 0)


def _format_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _require_columns(frame: pd.DataFrame) -> None:
    required = {
        "signal",
        "horizon",
        "mean_ic",
        "t_stat",
        "information_ratio",
        "n_observations",
        "p_value",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
