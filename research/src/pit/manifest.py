from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from .exceptions import DataNotAvailableAt


class DatasetName(StrEnum):
    PRICES = "prices"
    PRICES_DAILY = "prices_daily"
    FUNDAMENTALS = "fundamentals"
    SEC_COMPANY_FACTS = "sec_company_facts"
    INSIDER_TRANSACTIONS = "insider_transactions"
    SEC_FORM4 = "sec_form4"
    INSTITUTIONAL_HOLDINGS = "institutional_holdings"
    SEC_13F = "sec_13f"
    UNIVERSE_MEMBERSHIP = "universe_membership"
    SECTOR_ETFS = "sector_etfs"
    NEWS_RSS = "news_rss"
    SUBSCRIPTION_EMAILS = "subscription_emails"
    STOCK_TRADES = "stock_trades"
    OPTIONS_CHAINS = "options_chains"
    UNUSUAL_ACTIVITY_ALERTS = "unusual_activity_alerts"


@dataclass(frozen=True)
class DataManifest:
    dataset: DatasetName
    path: Path
    schema_version: int
    row_count: int
    checksum: str
    fetched_at: datetime
    max_timestamp_as_of: datetime
    stale_after: datetime
    source_url: str | None


class ManifestRegistry:
    def __init__(
        self,
        manifest_root: Path,
        parquet_root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.manifest_root = manifest_root
        self.parquet_root = parquet_root
        self._clock = clock or (lambda: datetime.now(UTC))

    def require(self, dataset: DatasetName, *, as_of: date | None = None) -> DataManifest:
        manifest_path = self.manifest_root / f"{dataset.value}.json"
        if not manifest_path.is_file():
            raise DataNotAvailableAt(dataset.value, as_of, f"missing {manifest_path}")

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DataNotAvailableAt(dataset.value, as_of, str(exc)) from exc

        if not isinstance(payload, Mapping):
            raise DataNotAvailableAt(dataset.value, as_of, "manifest must be an object")

        manifest = _parse_manifest(payload, manifest_path, self.parquet_root)
        if manifest.dataset is not dataset:
            reason = f"expected dataset={dataset.value}, got {manifest.dataset.value}"
            raise DataNotAvailableAt(dataset.value, as_of, reason)
        if manifest.row_count <= 0:
            raise DataNotAvailableAt(dataset.value, as_of, "manifest has no rows")
        if manifest.stale_after <= self._clock():
            stale_at = manifest.stale_after.isoformat()
            raise DataNotAvailableAt(dataset.value, as_of, f"manifest stale after {stale_at}")
        if not manifest.path.exists():
            raise DataNotAvailableAt(dataset.value, as_of, f"missing {manifest.path}")
        return manifest


def _parse_manifest(
    payload: Mapping[str, object],
    manifest_path: Path,
    parquet_root: Path,
) -> DataManifest:
    dataset = DatasetName(_text(payload, "dataset", manifest_path))
    parquet_path = _resolve_parquet_path(_text(payload, "path", manifest_path), parquet_root)
    return DataManifest(
        dataset=dataset,
        path=parquet_path,
        schema_version=_integer(payload, "schema_version", manifest_path),
        row_count=_integer(payload, "row_count", manifest_path),
        checksum=_text(payload, "checksum", manifest_path),
        fetched_at=_datetime(payload, "fetched_at", manifest_path),
        max_timestamp_as_of=_datetime(payload, "max_timestamp_as_of", manifest_path),
        stale_after=_datetime(payload, "stale_after", manifest_path),
        source_url=_optional_text(payload, "source_url", manifest_path),
    )


def _resolve_parquet_path(value: str, parquet_root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = parquet_root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(parquet_root.resolve(strict=False))
    except ValueError as exc:
        raise DataNotAvailableAt("manifest", None, "parquet path escapes parquet root") from exc
    return resolved


def _text(payload: Mapping[str, object], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise DataNotAvailableAt(path.name, None, f"{key} must be a non-empty string")
    return value


def _optional_text(payload: Mapping[str, object], key: str, path: Path) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise DataNotAvailableAt(path.name, None, f"{key} must be a non-empty string")
    return value


def _integer(payload: Mapping[str, object], key: str, path: Path) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise DataNotAvailableAt(path.name, None, f"{key} must be an integer")
    return value


def _datetime(payload: Mapping[str, object], key: str, path: Path) -> datetime:
    raw = _text(payload, key, path).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataNotAvailableAt(path.name, None, f"{key} must include timezone")
    return parsed.astimezone(UTC)
