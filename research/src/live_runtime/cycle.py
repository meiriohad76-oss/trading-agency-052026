from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from live_runtime.config import DEFAULT_RUNTIME_SIGNALS, LANE_CONFIGS
from live_runtime.signals import build_runtime_signals
from live_runtime.source_health import source_health_from_manifests, utc_now
from pit.loader import PITLoader
from pit.manifest import DatasetName, ManifestRegistry

from agency.services import RuntimeCycleResult, build_runtime_cycle
from agency.services.llm_review import (
    LLM_REVIEW_ENABLED_ENV,
    LlmReviewBatchResult,
    OpenAILlmReviewProvider,
    review_evidence_packs,
)


@dataclass(frozen=True)
class LlmEnhancedCycleResult:
    """A paper cycle result with LLM review batch results attached."""

    cycle: RuntimeCycleResult
    llm_batch: LlmReviewBatchResult


def build_live_pit_runtime_cycle(
    *,
    cycle_id: str,
    as_of: date,
    tickers: set[str],
    manifest_root: Path,
    parquet_root: Path,
    lanes: tuple[str, ...] = DEFAULT_RUNTIME_SIGNALS,
    generated_at: datetime | None = None,
    freshness_checked_at: datetime | None = None,
) -> RuntimeCycleResult | LlmEnhancedCycleResult:
    """Build a paper runtime cycle from local PIT research data.

    When the ``AGENCY_ENABLE_LLM_REVIEW`` environment variable is set to
    ``"true"`` the function runs an optional LLM review pass over WATCH
    candidates and returns an :class:`LlmEnhancedCycleResult` that wraps both
    the base cycle and the :class:`LlmReviewBatchResult`.  When the flag is
    absent or false the function returns a plain :class:`RuntimeCycleResult`
    with no breaking change to existing callers.
    """
    _validate_lanes(lanes)
    normalized_tickers = {ticker.upper() for ticker in tickers}
    checked_at = utc_now() if generated_at is None else generated_at.astimezone(UTC)
    print(
        json.dumps(
            {
                "event": "cycle_start",
                "cycle_id": cycle_id,
                "as_of": str(as_of),
                "ticker_count": len(normalized_tickers),
                "lanes": list(lanes),
                "ts": checked_at.isoformat(),
            },
            default=str,
        ),
        flush=True,
    )
    source_checked_at = checked_at if freshness_checked_at is None else freshness_checked_at
    source_checked_at = source_checked_at.astimezone(UTC)
    registry = ManifestRegistry(manifest_root, parquet_root, clock=lambda: checked_at)
    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=checked_at.date,
        clock=lambda: checked_at,
    )
    datasets = {LANE_CONFIGS[lane].dataset for lane in lanes}
    source_health = source_health_from_manifests(
        datasets,
        registry=registry,
        as_of=as_of,
        checked_at=source_checked_at,
        cap_timestamp_at_checked_at=freshness_checked_at is not None,
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
    cycle = build_runtime_cycle(
        cycle_id=cycle_id,
        as_of=as_of_text,
        generated_at=checked_at.isoformat(),
        source_health=source_health,
        signals=signals,
        tickers=sorted(normalized_tickers),
    )

    _log_cycle_complete(cycle_id, as_of, normalized_tickers, cycle, checked_at)

    if os.environ.get(LLM_REVIEW_ENABLED_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return cycle

    # LLM review is enabled — run it over WATCH-action evidence packs.
    provider = OpenAILlmReviewProvider.from_env(enabled=True)
    llm_batch = asyncio.run(
        review_evidence_packs(
            cycle.evidence_packs,
            provider=provider,
        )
    )
    return LlmEnhancedCycleResult(cycle=cycle, llm_batch=llm_batch)


def required_runtime_datasets(lanes: tuple[str, ...]) -> set[DatasetName]:
    _validate_lanes(lanes)
    return {LANE_CONFIGS[lane].dataset for lane in lanes}


def _validate_lanes(lanes: tuple[str, ...]) -> None:
    unknown = sorted(set(lanes).difference(LANE_CONFIGS))
    if unknown:
        raise ValueError(f"unknown runtime signal lane(s): {unknown}")


def _log_cycle_complete(
    cycle_id: str,
    as_of: date,
    normalized_tickers: set[str],
    cycle: RuntimeCycleResult,
    checked_at: datetime,
) -> None:
    # candidate_count is the total number of tickers evaluated in this cycle.
    print(
        json.dumps(
            {
                "event": "cycle_complete",
                "cycle_id": cycle_id,
                "as_of": str(as_of),
                "ticker_count": len(normalized_tickers),
                "candidate_count": len(cycle.selection_reports),
                "ts": checked_at.isoformat(),
            },
            default=str,
        ),
        flush=True,
    )
