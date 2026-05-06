from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from pit.loader import PITLoader
from pit.manifest import DatasetName

from agency.provenance import SourceTier

TODAY = date(2026, 5, 6)
OBSERVED = datetime(2026, 5, 6, tzinfo=UTC)
FY22_REVENUE = 394_328
Q3_MARKET_VALUE = 200
Q3_HOLDER_COUNT = 2
Q3_SHARES_A = 120
Q3_TOTAL_CHANGE = 50


def loader_with(tmp_path: Path, frames: dict[DatasetName, pl.DataFrame]) -> PITLoader:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    for dataset, frame in frames.items():
        parquet_path = parquet_root / f"{dataset.value}.parquet"
        frame.write_parquet(parquet_path)
        write_manifest(manifest_root, dataset, parquet_path.name, frame.height)
    return PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)


def write_manifest(
    manifest_root: Path,
    dataset: DatasetName,
    parquet_name: str,
    row_count: int,
    *,
    stale_after: str = "2099-01-01T00:00:00+00:00",
) -> None:
    payload = {
        "dataset": dataset.value,
        "path": parquet_name,
        "schema_version": 1,
        "row_count": row_count,
        "checksum": "fixture",
        "fetched_at": "2026-05-06T00:00:00+00:00",
        "max_timestamp_as_of": "2026-05-06T00:00:00+00:00",
        "stale_after": stale_after,
        "source_url": "fixture://pit",
    }
    (manifest_root / f"{dataset.value}.json").write_text(json.dumps(payload), encoding="utf-8")


def price(
    ticker: str,
    record_date: date,
    close: float,
    timestamp_as_of: date,
    source_id: str,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": record_date,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 1000,
        **provenance(SourceTier.MARKET_DATA, timestamp_as_of, source_id=source_id),
    }


def filing_row(ticker: str, filed_at: date, source_id: str, **extra: Any) -> dict[str, object]:
    return {
        "ticker": ticker,
        "filing_date": filed_at,
        "source_id": source_id,
        **extra,
        **provenance(SourceTier.OFFICIAL_FILING, filed_at, source_id=source_id),
    }


def member(ticker: str, start_date: date, end_date: date | None) -> dict[str, object]:
    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        **provenance(SourceTier.OFFICIAL_FILING, start_date, source_id=f"universe-{ticker}"),
    }


def provenance(
    source_tier: SourceTier,
    timestamp_as_of: date,
    *,
    source_id: str,
) -> dict[str, object]:
    return {
        "source": "fixture",
        "source_tier": source_tier.value,
        "source_id": source_id,
        "source_url": None,
        "timestamp_observed": OBSERVED,
        "timestamp_as_of": timestamp_as_of,
        "freshness": "STALE",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
