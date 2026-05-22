from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def load_consumed_news_ids(path: Path) -> set[str]:
    """Return RSS/news source IDs already used by a live decision cycle."""
    if not path.is_file():
        return set()
    payload = _read_ledger(path)
    items = payload.get("items")
    if not isinstance(items, Mapping):
        return set()
    return {str(source_id) for source_id in items if str(source_id).strip()}


def mark_news_consumed(
    path: Path,
    *,
    cycle_id: str,
    as_of: str,
    used_at: str,
    items: Iterable[Mapping[str, object]],
) -> int:
    """Persist a single-use ledger entry for each consumed RSS/news source ID."""
    normalized = _normalized_consumption_items(
        cycle_id=cycle_id,
        as_of=as_of,
        used_at=used_at,
        items=items,
    )
    if not normalized:
        return 0
    payload = _read_ledger(path) if path.is_file() else _empty_ledger()
    ledger_items = payload.setdefault("items", {})
    if not isinstance(ledger_items, dict):
        ledger_items = {}
        payload["items"] = ledger_items
    written = 0
    for source_id, entry in normalized.items():
        if source_id in ledger_items:
            continue
        ledger_items[source_id] = entry
        written += 1
    if written > 0:
        _write_ledger(path, payload)
    return written


def _normalized_consumption_items(
    *,
    cycle_id: str,
    as_of: str,
    used_at: str,
    items: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for item in items:
        ticker = str(item.get("ticker") or "").upper()
        source_ids = _string_list(item.get("source_ids"))
        raw_source_ids = _string_list(item.get("raw_source_ids"))
        raw_by_source = dict(zip(source_ids, raw_source_ids, strict=False))
        for source_id in source_ids:
            if source_id in output:
                continue
            entry: dict[str, object] = {
                "source_id": source_id,
                "cycle_id": cycle_id,
                "ticker": ticker,
                "as_of": as_of,
                "used_at": used_at,
                "lane": "news",
            }
            raw_source_id = raw_by_source.get(source_id)
            if raw_source_id:
                entry["raw_source_id"] = raw_source_id
            output[source_id] = entry
    return output


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, Iterable):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _read_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _empty_ledger()
    if not isinstance(payload, dict):
        return _empty_ledger()
    if payload.get("schema_version") != SCHEMA_VERSION:
        payload["schema_version"] = SCHEMA_VERSION
    return payload


def _write_ledger(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _empty_ledger() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "items": {},
    }
