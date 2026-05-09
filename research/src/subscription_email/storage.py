from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

EVENT_COLUMNS = [
    "ticker",
    "service",
    "services",
    "event_type",
    "event_types",
    "direction",
    "title",
    "source_refs",
    "source_id",
    "source_url",
    "message_id_hash",
    "sender_domain",
    "received_at",
    "timestamp_observed",
    "timestamp_as_of",
    "confidence",
    "verification_level",
]


def write_event_frame(path: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame[EVENT_COLUMNS].copy()
    if path.exists():
        output = pd.concat([pd.read_parquet(path), output], ignore_index=True)
    output = (
        output.drop_duplicates(subset=["source_id"], keep="last")
        .sort_values(["timestamp_as_of", "ticker", "source_id"])
        .reset_index(drop=True)
    )
    output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
    return len(frame)


def write_manifest(
    manifest_path: Path,
    parquet_path: Path,
    *,
    fetched_at: datetime,
    issues: list[dict[str, object]] | None = None,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _stats(parquet_path)
    manifest = {
        "dataset": "subscription_emails",
        "path": parquet_path.name,
        "schema_version": 1,
        "row_count": stats["row_count"],
        "checksum": _checksum(parquet_path),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": (fetched_at + timedelta(days=3650)).isoformat(),
        "source_url": None,
        "issues": issues or [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def write_summary(
    output_root: Path,
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "subscription-email-ingest.json"
    md_path = output_root / "subscription-email-ingest.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(summary_to_markdown(summary), encoding="utf-8")
    return json_path, md_path


def summary_to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Subscription Email Ingest",
        "",
        f"Config: `{summary['config_path']}`",
        f"Mode: `{summary['mode']}`",
        f"Verdict: `{summary['verdict']}`",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Processed emails | {summary['processed_emails']} |",
        f"| News rows | {summary['news_rows']} |",
        f"| Activity rows | {summary['activity_rows']} |",
        f"| Deduped events | {summary['event_rows']} |",
        f"| Manual review | {summary['manual_review_count']} |",
        f"| Ignored | {summary['ignored_count']} |",
        "",
        "| Service | Events |",
        "| --- | ---: |",
    ]
    service_counts = summary.get("service_counts", {})
    if isinstance(service_counts, dict) and service_counts:
        for service, count in sorted(service_counts.items()):
            lines.append(f"| {service} | {count} |")
    else:
        lines.append("| none | 0 |")
    lines.append("")
    return "\n".join(lines)


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
