from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ACTIVITY_ALERT_COLUMNS = [
    "ticker",
    "alert_type",
    "direction",
    "event_time",
    "summary",
    "price",
    "volume",
    "notional",
    "premium",
    "source",
    "source_tier",
    "source_id",
    "source_url",
    "timestamp_observed",
    "timestamp_as_of",
    "freshness",
    "confidence",
    "verification_level",
]


def write_activity_alert_frame(path: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame[ACTIVITY_ALERT_COLUMNS].copy()
    if path.exists():
        output = pd.concat([pd.read_parquet(path), output], ignore_index=True)
    output = (
        output.drop_duplicates(subset=["source", "source_id"], keep="last")
        .sort_values(["timestamp_as_of", "ticker", "source", "source_id"])
        .reset_index(drop=True)
    )
    output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
    return len(frame)


def write_manifest(manifest_path: Path, parquet_path: Path, *, fetched_at: datetime) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _stats(parquet_path)
    manifest = {
        "dataset": "unusual_activity_alerts",
        "path": parquet_path.name,
        "schema_version": 1,
        "row_count": stats["row_count"],
        "checksum": _checksum(parquet_path),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": (fetched_at + timedelta(days=3650)).isoformat(),
        "source_url": None,
        "issues": [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _stats(path: Path) -> dict[str, int | str]:
    if not path.exists():
        now = datetime.now(UTC).isoformat()
        return {"row_count": 0, "max_timestamp_as_of": now}
    frame = pd.read_parquet(path, columns=["timestamp_as_of"])
    max_date = pd.to_datetime(frame["timestamp_as_of"]).max().to_pydatetime()
    if max_date.tzinfo is None or max_date.utcoffset() is None:
        max_date = max_date.replace(tzinfo=UTC)
    return {"row_count": len(frame), "max_timestamp_as_of": max_date.isoformat()}


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        digest.update(path.read_bytes())
    return digest.hexdigest()
