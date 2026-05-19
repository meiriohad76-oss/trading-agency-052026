from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


def write_partitioned_frame(
    root: Path,
    frame: pd.DataFrame,
    *,
    partition_column: str,
    filename: str,
    unique_columns: list[str],
) -> int:
    if frame.empty:
        return 0
    written = 0
    for partition_value, group in frame.groupby(partition_column):
        partition = str(partition_value).upper()
        path = root / f"{partition_column}={partition}" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        output = group.copy()
        if path.exists():
            existing = _read_parquet_or_quarantine(path)
            if existing is not None:
                output = pd.concat([existing, output], ignore_index=True)
        output = (
            output.drop_duplicates(subset=unique_columns, keep="last")
            .sort_values(unique_columns)
            .reset_index(drop=True)
        )
        output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
        written += len(group)
    return written


def write_raw_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(
    manifest_path: Path,
    data_root: Path,
    *,
    dataset: str,
    fetched_at: datetime,
    source_url: str,
    issues: list[dict[str, str]],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _dataset_stats(data_root)
    manifest = {
        "dataset": dataset,
        "path": data_root.name,
        "schema_version": 1,
        "row_count": stats["row_count"],
        "checksum": _tree_checksum(data_root),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": "2099-01-01T00:00:00+00:00",
        "source_url": source_url,
        "issues": issues,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dataset_stats(data_root: Path) -> dict[str, str | int]:
    frames: list[pd.DataFrame] = []
    for path in sorted(data_root.rglob("*.parquet")):
        frame = _read_parquet_or_quarantine(path, columns=["timestamp_as_of"])
        if frame is None:
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        now = datetime.now(UTC).isoformat()
        return {"row_count": 0, "max_timestamp_as_of": now}
    combined = pd.concat(frames, ignore_index=True)
    max_date = pd.to_datetime(combined["timestamp_as_of"]).max().to_pydatetime()
    if max_date.tzinfo is None or max_date.utcoffset() is None:
        max_date = max_date.replace(tzinfo=UTC)
    return {"row_count": len(combined), "max_timestamp_as_of": max_date.isoformat()}


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.parquet")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_parquet_or_quarantine(
    path: Path,
    *,
    columns: list[str] | None = None,
) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(path, columns=columns)
    except Exception as exc:  # noqa: BLE001
        quarantine_path = _quarantine_path(path)
        path.replace(quarantine_path)
        print(
            (
                "warning: quarantined unreadable SEC parquet "
                f"{path} -> {quarantine_path}: {type(exc).__name__}: {exc}"
            ),
            file=sys.stderr,
        )
        return None


def _quarantine_path(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.corrupt-{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}-{counter}")
        counter += 1
    return candidate
