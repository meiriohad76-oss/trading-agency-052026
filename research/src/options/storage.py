from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

OPTIONS_COLUMNS = [
    "ticker",
    "snapshot_date",
    "expiration",
    "option_type",
    "strike",
    "last_price",
    "bid",
    "ask",
    "volume",
    "open_interest",
    "implied_volatility",
    "in_the_money",
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


def write_options_frame(root: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    written = 0
    for ticker, group in frame.groupby("ticker"):
        path = root / f"ticker={str(ticker).upper()}" / "options.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        output = group[OPTIONS_COLUMNS].copy()
        if path.exists():
            output = pd.concat([pd.read_parquet(path), output], ignore_index=True)
        output = (
            output.drop_duplicates(
                subset=["ticker", "snapshot_date", "expiration", "option_type", "strike"],
                keep="last",
            )
            .sort_values(["ticker", "snapshot_date", "expiration", "option_type", "strike"])
            .reset_index(drop=True)
        )
        output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
        written += len(group)
    return written


def write_manifest(manifest_path: Path, data_root: Path, *, fetched_at: datetime) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _stats(data_root)
    manifest = {
        "dataset": "options_chains",
        "path": data_root.name,
        "schema_version": 1,
        "row_count": stats["row_count"],
        "checksum": _tree_checksum(data_root),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": (fetched_at + timedelta(days=3650)).isoformat(),
        "source_url": "https://finance.yahoo.com",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _stats(root: Path) -> dict[str, int | str]:
    frames: list[pd.DataFrame] = []
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["timestamp_as_of"])
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
