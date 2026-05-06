from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd


def write_manifest(
    manifest_path: Path,
    parquet_path: Path,
    frame: pd.DataFrame,
    metadata: Mapping[str, object],
    checksum: str,
    fetched_at: datetime,
    *,
    base_date: date,
    stale_after: str,
    coverage_end: date,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    source_urls = [
        str(source["url"]) for source in _metadata_sources(metadata) if "url" in source
    ]
    manifest = {
        "dataset": "universe_membership",
        "path": parquet_path.name,
        "schema_version": 1,
        "row_count": len(frame),
        "checksum": checksum,
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": _max_timestamp_as_of(frame).isoformat(),
        "stale_after": stale_after,
        "source_url": source_urls[0],
        "source_urls": source_urls,
        "coverage_start": base_date.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "columns": list(frame.columns),
    }
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")


def _max_timestamp_as_of(frame: pd.DataFrame) -> datetime:
    value = max(frame["timestamp_as_of"])
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _metadata_sources(metadata: Mapping[str, object]) -> list[Mapping[str, object]]:
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        raise ValueError("source metadata must include a sources list")
    return [source for source in sources if isinstance(source, Mapping)]
