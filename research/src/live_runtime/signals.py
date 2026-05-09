from __future__ import annotations

from datetime import date, datetime
from typing import Any

from evaluation.signal_registry import SIGNALS
from live_runtime.config import LANE_CONFIGS, RuntimeLaneConfig
from live_runtime.freshness import effective_freshness_timestamp
from pit.manifest import DataManifest, ManifestRegistry
from signals.subscription_thesis import subscription_thesis_contexts

from agency.provenance import compute_freshness
from agency.services import build_signal_result


def build_runtime_signals(
    *,
    cycle_id: str,
    as_of: date,
    as_of_text: str,
    generated_at: datetime,
    tickers: set[str],
    lanes: tuple[str, ...],
    loader: Any,
    registry: ManifestRegistry,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for lane in lanes:
        config = LANE_CONFIGS[lane]
        if lane == "subscription_thesis":
            results.extend(
                _subscription_thesis_signals(
                    cycle_id=cycle_id,
                    as_of=as_of,
                    as_of_text=as_of_text,
                    generated_at=generated_at,
                    tickers=tickers,
                    loader=loader,
                    registry=registry,
                    config=config,
                )
            )
            continue
        try:
            scores = SIGNALS[lane](as_of, tickers, loader)
            manifest = registry.require(config.dataset, as_of=as_of)
        except Exception:
            continue
        filtered_scores = {
            ticker.upper(): score for ticker, score in scores.items() if ticker.upper() in tickers
        }
        results.extend(
            build_signal_result(
                cycle_id=cycle_id,
                ticker=ticker,
                as_of=as_of_text,
                lane=lane,
                score=score,
                provenance=_provenance(config, manifest, generated_at=generated_at),
                confidence=config.confidence,
            )
            for ticker, score in sorted(filtered_scores.items())
        )
    return results


def _subscription_thesis_signals(
    *,
    cycle_id: str,
    as_of: date,
    as_of_text: str,
    generated_at: datetime,
    tickers: set[str],
    loader: Any,
    registry: ManifestRegistry,
    config: RuntimeLaneConfig,
) -> list[dict[str, object]]:
    try:
        contexts = subscription_thesis_contexts(as_of, tickers, loader)
        manifest = registry.require(config.dataset, as_of=as_of)
    except Exception:
        return []
    provenance = _provenance(config, manifest, generated_at=generated_at)
    return [
        build_signal_result(
            cycle_id=cycle_id,
            ticker=context.ticker,
            as_of=as_of_text,
            lane=config.lane,
            score=context.score,
            provenance=provenance,
            confidence=config.confidence,
            reason_codes=["subscription_thesis_context_only"],
            actionability="CONTEXT_ONLY",
            summary=context.summary,
        )
        for context in contexts
        if context.ticker in tickers
    ]


def _provenance(
    config: RuntimeLaneConfig,
    manifest: DataManifest,
    *,
    generated_at: datetime,
) -> dict[str, object]:
    freshness = compute_freshness(
        effective_freshness_timestamp(
            config.dataset,
            manifest.max_timestamp_as_of,
            generated_at,
        ),
        config.freshness_domain,
        now=generated_at,
    )
    return {
        "source": config.source,
        "source_tier": config.source_tier,
        "source_id": f"{config.dataset.value}:{manifest.checksum[:12]}",
        "source_url": manifest.source_url,
        "timestamp_observed": generated_at.isoformat(),
        "timestamp_as_of": manifest.max_timestamp_as_of.isoformat(),
        "freshness": freshness.value,
        "confidence": config.confidence,
        "verification_level": config.verification_level,
    }
