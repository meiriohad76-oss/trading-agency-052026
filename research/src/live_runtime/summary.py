from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
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
        "lane_counts": _lane_counts(cycle),
        "evidence_pack_count": len(cycle.evidence_packs),
        "selection_action_counts": _counts(cycle.selection_reports, "final_action"),
        "llm_review_counts": _llm_review_counts(cycle),
        "prompt_audit_count": len(cycle.prompt_audits),
        "llm_prompt_status_counts": _prompt_payload_counts(cycle, "response_status"),
        "llm_prompt_action_counts": _prompt_payload_counts(cycle, "llm_action"),
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
        "# Live Runtime Cycle Summary",
        "",
        f"Cycle: `{summary['cycle_id']}`",
        f"As-of: {summary['as_of']}",
        f"Verdict: `{summary['verdict']}`",
        f"Persisted: {summary['persisted']}",
        *(
            [f"Persistence error: `{summary['persistence_error']}`"]
            if summary.get("persistence_error")
            else []
        ),
        f"Evidence packs: {summary['evidence_pack_count']}",
        f"Signals: {summary['signal_count']}",
        f"Prompt audits: {summary['prompt_audit_count']}",
        "",
        "| Signal lane | Count |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _items(summary, "lane_counts")],
        "",
        "| Final action | Count |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _items(summary, "selection_action_counts")],
        "",
        "| LLM review | Count |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in _items(summary, "llm_review_counts")],
        "",
        "| LLM prompt status | Count |",
        "| --- | ---: |",
        *[
            f"| {key} | {value} |"
            for key, value in _items(summary, "llm_prompt_status_counts")
        ],
        "",
        "| LLM prompt action | Count |",
        "| --- | ---: |",
        *[
            f"| {key} | {value} |"
            for key, value in _items(summary, "llm_prompt_action_counts")
        ],
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


def _lane_counts(cycle: RuntimeCycleResult) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for pack in cycle.evidence_packs:
        for bucket in SIGNAL_BUCKETS:
            for signal in _list(pack, bucket):
                if isinstance(signal, dict):
                    counts[str(signal.get("lane", "unknown"))] += 1
    return dict(sorted(counts.items()))


def _llm_review_counts(cycle: RuntimeCycleResult) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for report in cycle.selection_reports:
        review = report["llm_review"]
        if not isinstance(review, dict):
            raise TypeError("llm_review must be a mapping")
        counts[str(review.get("action") or "UNKNOWN")] += 1
    return dict(sorted(counts.items()))


def _prompt_payload_counts(cycle: RuntimeCycleResult, key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for prompt_audit in cycle.prompt_audits:
        payload = prompt_audit.get("payload")
        if not isinstance(payload, dict):
            continue
        value = payload.get(key)
        if value is not None:
            counts[str(value)] += 1
    return dict(sorted(counts.items()))


def _verdict(cycle: RuntimeCycleResult) -> str:
    if any(_blocking_source(source) for source in cycle.source_health):
        return "blocked_or_context_only_due_to_source_health"
    source_warning = any(_non_healthy_source(source) for source in cycle.source_health)
    current_risk_decisions = _current_risk_decisions(cycle)
    if current_risk_decisions and not any(
        str(decision.get("decision")) != "BLOCK" for decision in current_risk_decisions
    ):
        return (
            "cycle_blocked_by_risk_with_source_warnings"
            if source_warning
            else "cycle_blocked_by_risk"
        )
    has_orderable_action = any(
        str(report.get("final_action")) in TRADE_ACTIONS for report in cycle.selection_reports
    )
    if has_orderable_action and cycle.execution_previews and not any(
        str(preview.get("preview_state")) == "READY" for preview in cycle.execution_previews
    ):
        return (
            "cycle_has_no_ready_orders_with_source_warnings"
            if source_warning
            else "cycle_has_no_ready_orders"
        )
    if any(report["final_action"] == "WATCH" for report in cycle.selection_reports):
        return (
            "watch_candidates_available_with_source_warnings"
            if source_warning
            else "watch_candidates_available"
        )
    return (
        "ran_without_watch_candidates_with_source_warnings"
        if source_warning
        else "ran_without_watch_candidates"
    )


def _blocking_source(source: Mapping[str, object]) -> bool:
    if str(source.get("source") or "") not in CRITICAL_SOURCE_NAMES:
        return False
    status = str(source.get("status", "UNKNOWN")).upper()
    freshness = str(source.get("freshness", "UNKNOWN")).upper()
    return status in BLOCKING_SOURCE_STATUSES or freshness in BLOCKING_FRESHNESS


def _non_healthy_source(source: Mapping[str, object]) -> bool:
    status = str(source.get("status", "UNKNOWN")).upper()
    return status not in {"HEALTHY", "PASS", "READY"}


def _current_risk_decisions(cycle: RuntimeCycleResult) -> list[dict[str, object]]:
    current_keys = {
        (str(report.get("ticker")), str(report.get("final_action")))
        for report in cycle.selection_reports
    }
    return [
        decision
        for decision in cycle.risk_decisions
        if (str(decision.get("ticker")), str(decision.get("final_action"))) in current_keys
    ]


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
TRADE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}
CRITICAL_SOURCE_NAMES = {"daily-market-bars", "massive-stock-trades"}
BLOCKING_SOURCE_STATUSES = {"STALE", "UNAVAILABLE", "RATE_LIMITED"}
BLOCKING_FRESHNESS = {"STALE", "UNAVAILABLE"}
