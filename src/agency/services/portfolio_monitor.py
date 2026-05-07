from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from agency.contracts import validate_contract


def build_portfolio_monitor(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    positions: Sequence[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Build a read-only position review snapshot from current selection reports."""
    reports_by_ticker = {
        str(report["ticker"]): report
        for report in selection_reports
    }
    position_rows = [
        _position_review(ticker.upper(), reports_by_ticker.get(ticker.upper()))
        for ticker in positions or []
    ]
    snapshot: dict[str, object] = {
        "schema_version": "0.1.0",
        "generated_at": generated_at or _now_utc(),
        "mode": "READ_ONLY",
        "positions": position_rows,
        "summary": _summary(position_rows),
    }
    validate_contract("portfolio-monitor", snapshot)
    return snapshot


def _position_review(
    ticker: str,
    report: Mapping[str, object] | None,
) -> dict[str, object]:
    if report is None:
        return {
            "ticker": ticker,
            "classification": "NO_CURRENT_SETUP",
            "reason": "no current selection report",
            "current_action": None,
            "conviction": None,
        }
    action = str(report["final_action"])
    risk_flags = _string_list(report, "risk_flags")
    if action in {"NO_TRADE", "CLOSE_REVIEW"}:
        classification = "CLOSE_CANDIDATE"
        reason = "current setup is no-trade or close-review"
    elif risk_flags or _gate_status(report) == "WARN":
        classification = "REVIEW"
        reason = "current setup carries warnings"
    else:
        classification = "HOLD"
        reason = "current setup remains aligned"
    return {
        "ticker": ticker,
        "classification": classification,
        "reason": reason,
        "current_action": action,
        "conviction": _float_field(report, "final_conviction"),
    }


def _summary(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        "position_count": len(rows),
        "hold_count": _count(rows, "HOLD"),
        "review_count": _count(rows, "REVIEW"),
        "close_candidate_count": _count(rows, "CLOSE_CANDIDATE"),
    }


def _count(rows: Sequence[Mapping[str, object]], classification: str) -> int:
    return sum(1 for row in rows if row["classification"] == classification)


def _gate_status(report: Mapping[str, object]) -> str:
    statuses = [
        str(gate["status"])
        for gate in _mapping_list(report, "policy_gates")
    ]
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARN" in statuses:
        return "WARN"
    if "PASS" in statuses:
        return "PASS"
    return "UNKNOWN"


def _mapping_list(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [
        item
        for item in _list_field(payload, key)
        if isinstance(item, Mapping)
    ]


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
