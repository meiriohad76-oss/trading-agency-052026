from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

SUMMARY_COLUMNS = frozenset(
    {
        "ticker",
        "alert_type",
        "direction",
        "source",
        "source_tier",
        "timestamp_as_of",
        "verification_level",
    }
)
BLOCK_TYPES = frozenset({"block_trade", "dark_pool", "large_print", "trade_print"})


def build_activity_alert_summary(
    frame: pd.DataFrame,
    *,
    input_path: Path | None = None,
    parquet_path: Path | None = None,
    manifest_path: Path | None = None,
    rows_written: int | None = None,
) -> dict[str, Any]:
    """Summarize imported activity-alert coverage without exposing raw rows."""
    issues = _schema_issues(frame)
    timestamps = _timestamps(frame)
    alert_type_counts = _counts(frame, "alert_type")
    warnings = _warnings(frame, alert_type_counts)
    summary: dict[str, Any] = {
        "dataset": "unusual_activity_alerts",
        "verdict": _verdict(frame, issues),
        "row_count": int(len(frame)),
        "rows_written": rows_written,
        "ticker_count": int(frame["ticker"].nunique()) if "ticker" in frame.columns else 0,
        "tickers": _strings(frame, "ticker"),
        "source_count": int(frame["source"].nunique()) if "source" in frame.columns else 0,
        "alert_type_counts": alert_type_counts,
        "direction_counts": _counts(frame, "direction"),
        "source_tier_counts": _counts(frame, "source_tier"),
        "verification_counts": _counts(frame, "verification_level"),
        "total_notional": _sum(frame, "notional"),
        "total_premium": _sum(frame, "premium"),
        "min_timestamp_as_of": _timestamp_text(timestamps.min()),
        "max_timestamp_as_of": _timestamp_text(timestamps.max()),
        "issues": issues,
        "warnings": warnings,
        "paths": _paths(input_path, parquet_path, manifest_path),
    }
    return summary


def write_activity_alert_summary(summary: dict[str, Any], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "activity-alert-import-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "activity-alert-import-summary.md").write_text(
        summary_to_markdown(summary),
        encoding="utf-8",
    )


def summary_to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# T82 Activity Alert Import Summary",
        "",
        f"Verdict: `{summary['verdict']}`",
        f"Rows: {summary['row_count']}",
        f"Rows written: {summary['rows_written']}",
        f"Tickers: {summary['ticker_count']}",
        f"Sources: {summary['source_count']}",
        f"Window: {summary['min_timestamp_as_of']} to {summary['max_timestamp_as_of']}",
        f"Total notional: {summary['total_notional']}",
        f"Total premium: {summary['total_premium']}",
        "",
        "| Alert type | Rows |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _mapping_items(summary, "alert_type_counts")],
        "",
        "| Direction | Rows |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _mapping_items(summary, "direction_counts")],
        "",
        f"Issues: {', '.join(_list(summary, 'issues')) or 'none'}",
        f"Warnings: {', '.join(_list(summary, 'warnings')) or 'none'}",
    ]
    return "\n".join(lines) + "\n"


def _schema_issues(frame: pd.DataFrame) -> list[str]:
    missing = sorted(SUMMARY_COLUMNS.difference(frame.columns))
    issues = [f"missing column: {column}" for column in missing]
    if frame.empty:
        issues.append("no activity alert rows")
    return issues


def _warnings(frame: pd.DataFrame, alert_type_counts: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    if len(frame) > 0 and not any(key in BLOCK_TYPES for key in alert_type_counts):
        warnings.append("no block-trade or dark-pool alert types")
    if _counts(frame, "verification_level").get("CONFIRMED", 0) == 0:
        warnings.append("no confirmed alerts")
    if _counts(frame, "direction").get("BULLISH", 0) == 0:
        warnings.append("no bullish alerts")
    if _counts(frame, "direction").get("BEARISH", 0) == 0:
        warnings.append("no bearish alerts")
    return warnings


def _verdict(frame: pd.DataFrame, issues: list[str]) -> str:
    if issues:
        return "blocked"
    if _counts(frame, "verification_level").get("CONFIRMED", 0) == 0:
        return "needs_confirmed_alerts"
    return "ready_for_research_batch"


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in frame.columns or frame.empty:
        return {}
    counts = frame[column].fillna("UNKNOWN").astype(str).value_counts().sort_index()
    return {str(key): int(value) for key, value in counts.items()}


def _strings(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame.columns or frame.empty:
        return []
    return sorted({str(value) for value in frame[column].dropna().tolist()})


def _sum(frame: pd.DataFrame, column: str) -> float:
    if column not in frame.columns or frame.empty:
        return 0.0
    return round(float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum()), 2)


def _timestamps(frame: pd.DataFrame) -> pd.Series:
    if "timestamp_as_of" not in frame.columns:
        return pd.Series([], dtype="datetime64[ns, UTC]")
    return pd.to_datetime(frame["timestamp_as_of"], errors="coerce", utc=True).dropna()


def _timestamp_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if bool(pd.isna(timestamp)):
        return None
    return timestamp.isoformat()


def _paths(
    input_path: Path | None,
    parquet_path: Path | None,
    manifest_path: Path | None,
) -> dict[str, str | None]:
    return {
        "input": None if input_path is None else input_path.as_posix(),
        "parquet": None if parquet_path is None else parquet_path.as_posix(),
        "manifest": None if manifest_path is None else manifest_path.as_posix(),
    }


def _mapping_items(summary: dict[str, Any], key: str) -> list[tuple[str, int]]:
    value = summary.get(key, {})
    if not isinstance(value, dict):
        return []
    return [(str(item_key), int(item_value)) for item_key, item_value in value.items()]


def _list(summary: dict[str, Any], key: str) -> list[str]:
    value = summary.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
