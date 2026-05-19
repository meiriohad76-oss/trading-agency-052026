from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


DEFAULT_LANE_MANIFEST_ROOT = Path("research/data/manifests/massive_lanes")


def manifest_path_for_lane(repo_root: Path, lane_id: str) -> Path:
    return repo_root / DEFAULT_LANE_MANIFEST_ROOT / f"{_safe_lane_id(lane_id)}.json"


def read_lane_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_lane_manifest(
    path: Path,
    *,
    lane_id: str,
    dataset: str,
    raw_source_dataset: str,
    fetched_at: datetime,
    requested_start: date | str | None,
    requested_end: date | str | None,
    tickers: Sequence[str],
    row_count: int,
    source_manifest: Path | str | None,
    status: str,
    issues: Sequence[Mapping[str, object]] = (),
    coverage: Sequence[Mapping[str, object]] = (),
    coverage_pct: int | None = None,
    request_budget_label: str | None = None,
) -> dict[str, Any]:
    normalized_tickers = sorted({str(ticker).upper() for ticker in tickers if str(ticker).strip()})
    resolved_coverage_pct = (
        max(0, min(100, coverage_pct))
        if coverage_pct is not None
        else _coverage_pct(coverage, normalized_tickers)
    )
    complete_coverage_pct = _coverage_pct(coverage, normalized_tickers)
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "lane_id": lane_id,
        "dataset": dataset,
        "raw_source_dataset": raw_source_dataset,
        "fetched_at": _utc(fetched_at).isoformat(),
        "window": {
            "start": _date_text(requested_start),
            "end": _date_text(requested_end),
        },
        "ticker_count": len(normalized_tickers),
        "tickers": normalized_tickers,
        "row_count": max(row_count, 0),
        "source_manifest": "" if source_manifest is None else str(source_manifest),
        "status": status,
        "coverage_pct": resolved_coverage_pct,
        "complete_coverage_pct": complete_coverage_pct,
        "usable_coverage_pct": resolved_coverage_pct,
        "coverage": [dict(row) for row in coverage],
        "issues": [dict(issue) for issue in issues],
        "issue_count": len(issues),
        "request_budget_label": request_budget_label or "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _coverage_pct(
    coverage: Sequence[Mapping[str, object]],
    tickers: Sequence[str],
) -> int:
    if not coverage:
        return 100 if not tickers else 0
    complete = sum(
        1
        for row in coverage
        if row.get("complete") is True
        or str(row.get("coverage_status") or row.get("status") or "").lower() == "complete"
    )
    return round(complete / max(len(coverage), 1) * 100)


def _date_text(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_lane_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return safe.strip("_") or "unknown"
