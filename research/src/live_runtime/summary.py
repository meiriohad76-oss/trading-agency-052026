from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from agency.services import RuntimeCycleResult


def build_live_runtime_summary(cycle: RuntimeCycleResult, *, persisted: bool) -> dict[str, Any]:
    return {
        "cycle_id": cycle.cycle_id,
        "as_of": cycle.as_of,
        "generated_at": cycle.generated_at,
        "persisted": persisted,
        "source_status_counts": _counts(cycle.source_health, "status"),
        "signal_count": sum(_pack_signal_count(pack) for pack in cycle.evidence_packs),
        "evidence_pack_count": len(cycle.evidence_packs),
        "selection_action_counts": _counts(cycle.selection_reports, "final_action"),
        "risk_decision_counts": _counts(cycle.risk_decisions, "decision"),
        "execution_state_counts": _counts(cycle.execution_previews, "preview_state"),
        "tickers": [str(report["ticker"]) for report in cycle.selection_reports],
        "verdict": _verdict(cycle),
    }


def write_live_runtime_summary(summary: dict[str, Any], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "live-runtime-cycle-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "live-runtime-cycle-summary.md").write_text(
        summary_to_markdown(summary),
        encoding="utf-8",
    )


def summary_to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# T83 Live Runtime Cycle Summary",
        "",
        f"Cycle: `{summary['cycle_id']}`",
        f"As-of: {summary['as_of']}",
        f"Verdict: `{summary['verdict']}`",
        f"Persisted: {summary['persisted']}",
        f"Evidence packs: {summary['evidence_pack_count']}",
        f"Signals: {summary['signal_count']}",
        "",
        "| Final action | Count |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _items(summary, "selection_action_counts")],
        "",
        "| Risk decision | Count |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _items(summary, "risk_decision_counts")],
        "",
        "| Source status | Count |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _items(summary, "source_status_counts")],
    ]
    return "\n".join(lines) + "\n"


def _counts(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def _pack_signal_count(pack: dict[str, object]) -> int:
    return sum(len(_list(pack, key)) for key in SIGNAL_BUCKETS)


def _verdict(cycle: RuntimeCycleResult) -> str:
    if any(report["final_action"] == "WATCH" for report in cycle.selection_reports):
        return "watch_candidates_available"
    if any(source["status"] in {"STALE", "UNAVAILABLE"} for source in cycle.source_health):
        return "blocked_or_context_only_due_to_source_health"
    return "ran_without_watch_candidates"


def _items(summary: dict[str, Any], key: str) -> list[tuple[str, int]]:
    value = summary.get(key, {})
    if not isinstance(value, dict):
        return []
    return [(str(item_key), int(item_value)) for item_key, item_value in value.items()]


def _list(payload: dict[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


SIGNAL_BUCKETS = ("actionable_signals", "context_signals", "suppressed_signals")
