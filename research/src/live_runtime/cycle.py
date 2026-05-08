from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

from live_runtime.config import DEFAULT_RUNTIME_SIGNALS, LANE_CONFIGS
from live_runtime.signals import build_runtime_signals
from live_runtime.source_health import source_health_from_manifests, utc_now
from pit.loader import PITLoader
from pit.manifest import DatasetName, ManifestRegistry

from agency.services import RuntimeCycleResult, build_runtime_cycle


def build_live_pit_runtime_cycle(
    *,
    cycle_id: str,
    as_of: date,
    tickers: set[str],
    manifest_root: Path,
    parquet_root: Path,
    lanes: tuple[str, ...] = DEFAULT_RUNTIME_SIGNALS,
    generated_at: datetime | None = None,
) -> RuntimeCycleResult:
    """Build a paper runtime cycle from local PIT research data."""
    _validate_lanes(lanes)
    normalized_tickers = {ticker.upper() for ticker in tickers}
    checked_at = utc_now() if generated_at is None else generated_at.astimezone(UTC)
    registry = ManifestRegistry(manifest_root, parquet_root, clock=lambda: checked_at)
    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=checked_at.date,
    )
    datasets = {LANE_CONFIGS[lane].dataset for lane in lanes}
    source_health = source_health_from_manifests(
        datasets,
        registry=registry,
        as_of=as_of,
        checked_at=checked_at,
    )
    as_of_text = datetime.combine(as_of, time.min, tzinfo=UTC).isoformat()
    signals = build_runtime_signals(
        cycle_id=cycle_id,
        as_of=as_of,
        as_of_text=as_of_text,
        generated_at=checked_at,
        tickers=normalized_tickers,
        lanes=lanes,
        loader=loader,
        registry=registry,
    )
    return build_runtime_cycle(
        cycle_id=cycle_id,
        as_of=as_of_text,
        generated_at=checked_at.isoformat(),
        source_health=source_health,
        signals=signals,
        tickers=sorted(normalized_tickers),
    )


def required_runtime_datasets(lanes: tuple[str, ...]) -> set[DatasetName]:
    _validate_lanes(lanes)
    return {LANE_CONFIGS[lane].dataset for lane in lanes}


def _validate_lanes(lanes: tuple[str, ...]) -> None:
    unknown = sorted(set(lanes).difference(LANE_CONFIGS))
    if unknown:
        raise ValueError(f"unknown runtime signal lane(s): {unknown}")
