from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from live_runtime.source_health import source_health_from_manifests
from pit.manifest import DatasetName, ManifestRegistry

CHECKED_AT = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
AS_OF = date(2026, 5, 6)


def _write_prices_daily_manifest(
    manifest_root: Path,
    parquet_root: Path,
    *,
    provider: str | None = None,
) -> None:
    parquet_path = parquet_root / "prices_daily.parquet"
    # Write a minimal valid parquet so path.exists() passes
    import pandas as pd

    pd.DataFrame({"ticker": ["AAPL"], "close": [100.0]}).to_parquet(
        parquet_path, engine="pyarrow", index=False
    )
    payload: dict[str, object] = {
        "dataset": "prices_daily",
        "path": "prices_daily.parquet",
        "schema_version": 1,
        "row_count": 1,
        "checksum": "fixture",
        "fetched_at": "2026-05-06T21:00:00+00:00",
        "max_timestamp_as_of": "2026-05-06T21:00:00+00:00",
        "stale_after": "2099-01-01T00:00:00+00:00",
        "source_url": "https://finance.yahoo.com",
    }
    if provider is not None:
        payload["source"] = provider
    (manifest_root / "prices_daily.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_prices_daily_notes_yfinance_fallback_when_active(tmp_path: Path) -> None:
    """When the prices_daily manifest records provider=yfinance, source health notes
    must contain the 'provider_fallback_active' warning."""
    manifest_root = tmp_path / "manifests"
    parquet_root = tmp_path / "parquet"
    manifest_root.mkdir()
    parquet_root.mkdir()

    _write_prices_daily_manifest(
        manifest_root, parquet_root, provider="yfinance"
    )

    registry = ManifestRegistry(manifest_root, parquet_root)
    results = source_health_from_manifests(
        {DatasetName.PRICES_DAILY},
        registry=registry,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
    )

    assert len(results) == 1
    notes = results[0]["notes"]
    assert isinstance(notes, list)
    fallback_notes = [n for n in notes if "provider_fallback_active" in str(n)]
    assert fallback_notes, (
        f"Expected a 'provider_fallback_active' note in notes, got: {notes}"
    )


def test_prices_daily_no_fallback_note_when_massive_active(tmp_path: Path) -> None:
    """When the prices_daily manifest records provider=massive, no fallback note
    should appear in source health notes."""
    manifest_root = tmp_path / "manifests"
    parquet_root = tmp_path / "parquet"
    manifest_root.mkdir()
    parquet_root.mkdir()

    _write_prices_daily_manifest(
        manifest_root, parquet_root, provider="massive"
    )

    registry = ManifestRegistry(manifest_root, parquet_root)
    results = source_health_from_manifests(
        {DatasetName.PRICES_DAILY},
        registry=registry,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
    )

    assert len(results) == 1
    notes = results[0]["notes"]
    assert isinstance(notes, list)
    fallback_notes = [n for n in notes if "provider_fallback_active" in str(n)]
    assert not fallback_notes, (
        f"Unexpected 'provider_fallback_active' note when provider=massive: {notes}"
    )


def test_prices_daily_no_fallback_note_when_provider_absent(tmp_path: Path) -> None:
    """When the prices_daily manifest has no provider field, no fallback note
    should appear (existing manifests without this field are not penalised)."""
    manifest_root = tmp_path / "manifests"
    parquet_root = tmp_path / "parquet"
    manifest_root.mkdir()
    parquet_root.mkdir()

    _write_prices_daily_manifest(
        manifest_root, parquet_root, provider=None
    )

    registry = ManifestRegistry(manifest_root, parquet_root)
    results = source_health_from_manifests(
        {DatasetName.PRICES_DAILY},
        registry=registry,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
    )

    assert len(results) == 1
    notes = results[0]["notes"]
    assert isinstance(notes, list)
    fallback_notes = [n for n in notes if "provider_fallback_active" in str(n)]
    assert not fallback_notes, (
        f"Unexpected 'provider_fallback_active' note when provider field is absent: {notes}"
    )
