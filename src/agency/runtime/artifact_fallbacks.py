from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_ARTIFACT_ROOT = (
    REPO_ROOT / "research" / "results" / "latest-live-runtime-cycle"
)
DEFAULT_LIFECYCLE_EVENTS_PATH = (
    REPO_ROOT / "research" / "results" / "local-candidate-lifecycle-events.jsonl"
)


def artifact_fallback_enabled() -> bool:
    value = os.environ.get("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "false")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def runtime_selection_report_artifacts(
    *,
    artifact_root: Path | None = None,
    ticker: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    return _runtime_rows(
        "selection-reports.json",
        artifact_root=artifact_root,
        ticker=ticker,
        limit=limit,
    )


def runtime_risk_decision_artifacts(
    *,
    artifact_root: Path | None = None,
    ticker: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    return _runtime_rows(
        "risk-decisions.json",
        artifact_root=artifact_root,
        ticker=ticker,
        limit=limit,
    )


def runtime_source_health_artifacts(
    *,
    artifact_root: Path | None = None,
) -> list[dict[str, object]]:
    rows = _read_json_rows(_artifact_path("source-health.json", artifact_root))
    return _sort_rows(rows)


def append_runtime_lifecycle_event_artifact(event: Mapping[str, object]) -> None:
    path = _lifecycle_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), sort_keys=True, default=str) + "\n")


def runtime_lifecycle_event_artifacts(
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    rows = _read_jsonl_rows(_lifecycle_events_path())
    if ticker is not None:
        wanted = ticker.upper()
        rows = [row for row in rows if str(row.get("ticker", "")).upper() == wanted]
    if cycle_id is not None:
        rows = [row for row in rows if row.get("cycle_id") == cycle_id]
    return _sort_rows(rows)[:limit]


def _runtime_rows(
    filename: str,
    *,
    artifact_root: Path | None,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    rows = _read_json_rows(_artifact_path(filename, artifact_root))
    if ticker is not None:
        wanted = ticker.upper()
        rows = [row for row in rows if str(row.get("ticker", "")).upper() == wanted]
    return _sort_rows(rows)[:limit]


def _artifact_path(filename: str, artifact_root: Path | None) -> Path:
    return (artifact_root or DEFAULT_RUNTIME_ARTIFACT_ROOT) / filename


def _read_json_rows(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(cast(Mapping[str, object], row)) for row in payload if isinstance(row, Mapping)]


def _read_jsonl_rows(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, object]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(cast(Mapping[str, object], payload)))
    return rows


def _lifecycle_events_path() -> Path:
    configured = os.environ.get("AGENCY_RUNTIME_LIFECYCLE_EVENTS_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_LIFECYCLE_EVENTS_PATH


def _sort_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(rows, key=_row_sort_key, reverse=True)


def _row_sort_key(row: Mapping[str, object]) -> tuple[datetime, str, str]:
    timestamp = (
        _parse_datetime(row.get("generated_at"))
        or _parse_datetime(row.get("checked_at"))
        or _parse_datetime(row.get("as_of"))
        or datetime.min.replace(tzinfo=UTC)
    )
    return (
        timestamp,
        str(row.get("cycle_id") or ""),
        str(row.get("ticker") or row.get("source") or ""),
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
