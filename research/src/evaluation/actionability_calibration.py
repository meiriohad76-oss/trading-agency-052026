from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from agency.services.deterministic_rules import (
    DEFAULT_MINIMUM_CONFIRMED_SIGNALS,
    DEFAULT_MINIMUM_SOURCE_COUNT,
    DEFAULT_WATCH_THRESHOLD,
)


def write_actionability_calibration(
    *,
    h1_verdicts_path: Path,
    batch_status_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    calibration = build_actionability_calibration(
        h1_verdicts_path=h1_verdicts_path,
        batch_status_path=batch_status_path,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "actionability-calibration.json").write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "actionability-calibration.md").write_text(
        calibration_to_markdown(calibration),
        encoding="utf-8",
    )
    return calibration


def build_actionability_calibration(
    *,
    h1_verdicts_path: Path,
    batch_status_path: Path,
) -> dict[str, Any]:
    status = _json_object(batch_status_path)
    config = _dict_field(status, "config")
    requested_signals = _string_list(config, "signals")
    verdicts = {row["signal"]: row for row in _read_verdict_rows(h1_verdicts_path)}
    recommendations = [
        _recommendation(signal, verdicts.get(signal)) for signal in requested_signals
    ]
    surviving = [item["signal"] for item in recommendations if item["h1_verdict"] == "survive"]
    return {
        "source_artifacts": {
            "h1_verdicts": h1_verdicts_path.as_posix(),
            "batch_status": batch_status_path.as_posix(),
        },
        "window": {"start": config["start"], "end": config["end"]},
        "runtime_thresholds": {
            "minimum_source_count": DEFAULT_MINIMUM_SOURCE_COUNT,
            "minimum_confirmed_signals": DEFAULT_MINIMUM_CONFIRMED_SIGNALS,
            "watch_threshold": DEFAULT_WATCH_THRESHOLD,
            "inferred_requires_confirmed_corroboration": True,
            "news_min_sources": 2,
        },
        "h1_recommendations": recommendations,
        "surviving_lanes": surviving,
        "verdict": "keep_conservative_thresholds",
        "rationale": (
            "No requested H1 lane survived the Bonferroni-adjusted significance bar; "
            "the deterministic engine therefore requires at least two usable "
            "independent sources before emitting WATCH."
        ),
    }


def calibration_to_markdown(calibration: dict[str, Any]) -> str:
    window = _dict_field(calibration, "window")
    thresholds = _dict_field(calibration, "runtime_thresholds")
    lines = [
        "# T73 Actionability Calibration",
        "",
        f"Window: {window['start']} to {window['end']}",
        f"Verdict: `{calibration['verdict']}`",
        "",
        "## Runtime Thresholds",
        "",
        f"- Minimum usable independent sources before WATCH: {thresholds['minimum_source_count']}",
        f"- Minimum confirmed signals: {thresholds['minimum_confirmed_signals']}",
        f"- Deterministic WATCH threshold: {thresholds['watch_threshold']}",
        "- Inferred signals require confirmed corroboration: true",
        "- News lane requires independent source count: 2",
        "",
        "## H1 Recommendations",
        "",
        "| Signal | H1 verdict | Best horizon | Mean IC | T-stat | Bonferroni p | Recommendation |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in _list_field(calibration, "h1_recommendations"):
        row = _dict_value(item)
        lines.append(
            "| "
            f"{row['signal']} | {row['h1_verdict']} | {_format_value(row['best_horizon'])} | "
            f"{_format_value(row['mean_ic'])} | {_format_value(row['t_stat'])} | "
            f"{_format_value(row['p_value_bonferroni'])} | {row['recommendation']} |"
        )
    lines.extend(["", f"Rationale: {calibration['rationale']}", ""])
    return "\n".join(lines)


def _recommendation(signal: str, row: dict[str, str] | None) -> dict[str, Any]:
    if row is None:
        return {
            "signal": signal,
            "h1_verdict": "not_evaluated",
            "best_horizon": None,
            "mean_ic": None,
            "t_stat": None,
            "information_ratio": None,
            "p_value_bonferroni": None,
            "recommendation": "context_only_until_ticker_tagged_coverage",
        }
    verdict = row["verdict"]
    return {
        "signal": signal,
        "h1_verdict": verdict,
        "best_horizon": int(row["best_horizon"]),
        "mean_ic": float(row["mean_ic"]),
        "t_stat": float(row["t_stat"]),
        "information_ratio": float(row["information_ratio"]),
        "p_value_bonferroni": float(row["p_value_bonferroni"]),
        "recommendation": _recommendation_for_verdict(verdict),
    }


def _recommendation_for_verdict(verdict: str) -> str:
    if verdict == "survive":
        return "eligible_for_action_weight_after_h2"
    if verdict == "inverse_candidate":
        return "research_review_before_action_weight"
    if verdict == "drop":
        return "drop_or_context_only"
    return "context_only_until_retest"


def _read_verdict_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    required = {
        "signal",
        "best_horizon",
        "mean_ic",
        "t_stat",
        "information_ratio",
        "p_value_bonferroni",
        "verdict",
    }
    for row in rows:
        missing = required.difference(row)
        if missing:
            raise ValueError(f"missing verdict columns: {sorted(missing)}")
    return rows


def _format_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    return value


def _dict_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("calibration rows must be objects")
    return value


def _list_field(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload
