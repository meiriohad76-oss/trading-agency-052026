from __future__ import annotations

from datetime import UTC, date, datetime

from live_runtime.config import DATASET_CONFIGS, RuntimeDatasetConfig
from live_runtime.freshness import effective_freshness_timestamp, next_quarterly_filing_date
from pit.exceptions import DataNotAvailableAt
from pit.manifest import DataManifest, DatasetName, ManifestRegistry

from agency.contracts import validate_contract
from agency.provenance import FreshnessStatus, compute_freshness


def source_health_from_manifests(
    datasets: set[DatasetName],
    *,
    registry: ManifestRegistry,
    as_of: date,
    checked_at: datetime,
    cap_timestamp_at_checked_at: bool = False,
) -> list[dict[str, object]]:
    return [
        _source_health(
            dataset,
            registry=registry,
            as_of=as_of,
            checked_at=checked_at,
            cap_timestamp_at_checked_at=cap_timestamp_at_checked_at,
        )
        for dataset in sorted(datasets, key=lambda item: item.value)
    ]


def _source_health(
    dataset: DatasetName,
    *,
    registry: ManifestRegistry,
    as_of: date,
    checked_at: datetime,
    cap_timestamp_at_checked_at: bool,
) -> dict[str, object]:
    config = DATASET_CONFIGS[dataset]
    try:
        manifest = registry.require(dataset, as_of=as_of)
    except DataNotAvailableAt as exc:
        payload = _unavailable(config, checked_at=checked_at, reason=exc.reason)
    else:
        payload = _available(
            config,
            manifest=manifest,
            checked_at=checked_at,
            cap_timestamp_at_checked_at=cap_timestamp_at_checked_at,
        )
    validate_contract("data-source-health", payload)
    return payload


def _available(
    config: RuntimeDatasetConfig,
    *,
    manifest: DataManifest,
    checked_at: datetime,
    cap_timestamp_at_checked_at: bool,
) -> dict[str, object]:
    timestamp_as_of = _timestamp_as_of(
        manifest,
        checked_at=checked_at,
        cap_timestamp_at_checked_at=cap_timestamp_at_checked_at,
    )
    freshness_timestamp = effective_freshness_timestamp(
        config.dataset,
        timestamp_as_of,
        checked_at,
    )
    freshness = compute_freshness(
        freshness_timestamp,
        config.freshness_domain,
        now=checked_at,
    )
    lag = max((checked_at - timestamp_as_of).total_seconds(), 0.0)
    notes = [f"{manifest.dataset.value}: {manifest.row_count} rows"]
    if config.dataset is DatasetName.SEC_13F:
        next_filing = next_quarterly_filing_date(timestamp_as_of.date())
        notes.append(f"lagged by design — next expected filing: {next_filing.isoformat()}")
    if config.dataset is DatasetName.PRICES_DAILY and manifest.provider == "yfinance":
        notes.append("provider_fallback_active: yfinance")
    return {
        "schema_version": "0.1.0",
        "source": config.source,
        "source_tier": config.source_tier,
        "status": _status(freshness),
        "checked_at": checked_at.isoformat(),
        "freshness": freshness.value,
        "last_success_at": timestamp_as_of.isoformat(),
        "observed_lag_seconds": round(lag, 3),
        "error_count": 0,
        "reliability_score": _reliability(freshness),
        "rate_limit_reset_at": None,
        "notes": notes,
    }


def _unavailable(
    config: RuntimeDatasetConfig,
    *,
    checked_at: datetime,
    reason: str,
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": config.source,
        "source_tier": config.source_tier,
        "status": "UNAVAILABLE",
        "checked_at": checked_at.isoformat(),
        "freshness": "UNAVAILABLE",
        "last_success_at": None,
        "observed_lag_seconds": None,
        "error_count": 1,
        "reliability_score": 0.0,
        "rate_limit_reset_at": None,
        "notes": [reason],
    }


def _status(freshness: FreshnessStatus) -> str:
    if freshness is FreshnessStatus.FRESH:
        return "HEALTHY"
    if freshness is FreshnessStatus.AGING:
        return "DEGRADED"
    return "STALE"


def _reliability(freshness: FreshnessStatus) -> float:
    if freshness is FreshnessStatus.FRESH:
        return 1.0
    if freshness is FreshnessStatus.AGING:
        return 0.75
    return 0.4


def _timestamp_as_of(
    manifest: DataManifest,
    *,
    checked_at: datetime,
    cap_timestamp_at_checked_at: bool,
) -> datetime:
    if cap_timestamp_at_checked_at and manifest.max_timestamp_as_of > checked_at:
        return checked_at
    return manifest.max_timestamp_as_of


def utc_now() -> datetime:
    return datetime.now(UTC)
