from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import cast

from live_runtime.config import DATASET_CONFIGS, DEFAULT_RUNTIME_SIGNALS, LANE_CONFIGS
from live_runtime.signals import build_runtime_signals
from live_runtime.source_health import source_health_from_manifests, utc_now
from pit.loader import PITLoader
from pit.manifest import DatasetName, ManifestRegistry

from agency.services import (
    RuntimeCycleResult,
    build_runtime_cycle,
    build_runtime_cycle_from_evidence_packs,
)
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
    enable_llm_review: bool | None = None,
    news_consumption_ledger_path: Path | None = None,
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
    source_health = _with_lane_source_health(source_health, lanes)
    as_of_text = datetime.combine(as_of, time.min, tzinfo=UTC).isoformat()
    news_consumption_items: list[dict[str, object]] = []
    signals = build_runtime_signals(
        cycle_id=cycle_id,
        as_of=as_of,
        as_of_text=as_of_text,
        generated_at=checked_at,
        tickers=normalized_tickers,
        lanes=lanes,
        loader=loader,
        registry=registry,
        news_consumption_ledger_path=news_consumption_ledger_path,
        news_consumption_items=news_consumption_items,
    )
    cycle = build_runtime_cycle(
        cycle_id=cycle_id,
        as_of=as_of_text,
        generated_at=checked_at.isoformat(),
        source_health=source_health,
        signals=signals,
        tickers=sorted(normalized_tickers),
    )
    cycle = replace(cycle, news_consumption_items=news_consumption_items)

    _log_cycle_complete(cycle_id, as_of, normalized_tickers, cycle, checked_at)

    llm_enabled = _llm_review_enabled() if enable_llm_review is None else enable_llm_review
    if not llm_enabled:
        return cycle

    # LLM review is enabled — run it over WATCH-action evidence packs.
    provider = OpenAILlmReviewProvider.from_env(enabled=True)
    llm_batch = _run_async_review(
        review_evidence_packs(
            cast(list[Mapping[str, object]], cycle.evidence_packs),
            provider=provider,
        )
    )
    reviewed_cycle = build_runtime_cycle_from_evidence_packs(
        cycle_id=cycle.cycle_id,
        as_of=cycle.as_of,
        generated_at=cycle.generated_at,
        source_health=cycle.source_health,
        evidence_packs=cycle.evidence_packs,
        llm_reviews=llm_batch.reviews_by_ticker,
        llm_lifecycle_events=llm_batch.lifecycle_events,
        llm_prompt_audits=llm_batch.prompt_audits,
    )
    reviewed_cycle = replace(reviewed_cycle, news_consumption_items=news_consumption_items)
    return LlmEnhancedCycleResult(cycle=reviewed_cycle, llm_batch=llm_batch)


def _run_async_review(awaitable: object) -> LlmReviewBatchResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            cast(Coroutine[object, object, LlmReviewBatchResult], awaitable)
        )

    result: dict[str, object] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(
                cast(
                    Coroutine[object, object, LlmReviewBatchResult],
                    awaitable,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=runner, name="llm-review-sync-runner", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise cast(BaseException, result["error"])
    return cast(LlmReviewBatchResult, result["value"])


def _llm_review_enabled() -> bool:
    return os.environ.get(LLM_REVIEW_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def required_runtime_datasets(lanes: tuple[str, ...]) -> set[DatasetName]:
    _validate_lanes(lanes)
    return {LANE_CONFIGS[lane].dataset for lane in lanes}


def _with_lane_source_health(
    source_health: list[dict[str, object]],
    lanes: tuple[str, ...],
) -> list[dict[str, object]]:
    rows = list(source_health)
    present_sources = {str(row.get("source")) for row in rows}
    health_by_source = {str(row.get("source")): row for row in rows}
    for lane in lanes:
        lane_config = LANE_CONFIGS[lane]
        if lane_config.source in present_sources:
            continue
        dataset_source = DATASET_CONFIGS[lane_config.dataset].source
        base_health = health_by_source.get(dataset_source)
        if base_health is None:
            continue
        derived = dict(base_health)
        derived["source"] = lane_config.source
        derived["source_tier"] = lane_config.source_tier
        raw_notes = derived.get("notes")
        notes = [
            str(note)
            for note in (raw_notes if isinstance(raw_notes, list) else [])
            if isinstance(note, str) and note.strip()
        ]
        notes.append(f"{lane}: derived from {dataset_source}")
        derived["notes"] = notes
        rows.append(derived)
        present_sources.add(lane_config.source)
        health_by_source[lane_config.source] = derived
    return rows


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
