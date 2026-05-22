from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, time, timedelta
from inspect import signature
from typing import Any, cast

from evaluation.signal_registry import SIGNALS
from live_runtime.config import LANE_CONFIGS, RuntimeLaneConfig
from live_runtime.freshness import effective_freshness_timestamp
from pit.exceptions import DataNotAvailableAt
from pit.manifest import DataManifest, DatasetName, ManifestRegistry
from signals.options_anomaly import options_anomaly_frame
from signals.options_flow import options_flow_frame
from signals.subscription_thesis import subscription_thesis_contexts
from signals.technical_analysis import technical_analysis_contexts

from agency.provenance import compute_freshness
from agency.services import build_signal_result

LOGGER = logging.getLogger(__name__)
LATEST_STOCK_TRADE_SLICE_FALLBACK_DAYS = 7


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
        if lane in {"options_anomaly", "options_flow"}:
            results.extend(
                _options_frame_signals(
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
        if lane == "technical_analysis":
            results.extend(
                _technical_analysis_signals(
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
            scores = SIGNALS[lane](
                as_of,
                tickers,
                _live_signal_loader(config, loader),
            )
            manifest = registry.require(config.dataset, as_of=as_of)
        except DataNotAvailableAt as exc:
            _log_unavailable_lane(lane, exc, tickers=tickers, as_of=as_of)
            continue
        filtered_scores = {
            ticker.upper(): parsed
            for ticker, score in scores.items()
            for parsed in [_float_or_none(score)]
            if ticker.upper() in tickers and parsed is not None
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


def _live_signal_loader(config: RuntimeLaneConfig, loader: Any) -> Any:
    if config.dataset != DatasetName.STOCK_TRADES:
        return loader
    return _LiveStockTradeLoader(loader)


class _LiveStockTradeLoader:
    """Live wrapper that accepts complete coverage or verified descending latest slices."""

    def __init__(self, loader: Any) -> None:
        self._loader = loader

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)

    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> tuple[Any, Any]:
        requested_tickers = sorted({ticker.upper() for ticker in tickers})
        effective_as_of = as_of
        complete_tickers = _complete_stock_trade_tickers(
            self._loader,
            requested_tickers,
            as_of,
            lookback_days,
            allow_partial_coverage=True,
        )
        effective_lookback_days = lookback_days
        if lookback_days > 1 or not complete_tickers or as_of.weekday() >= 5:
            latest_slice_as_of, latest_slice_tickers = _latest_stock_trade_slice_tickers(
                self._loader,
                requested_tickers,
                as_of,
            )
            if latest_slice_tickers and (
                as_of.weekday() >= 5 or len(latest_slice_tickers) > len(complete_tickers)
            ):
                effective_as_of = latest_slice_as_of
                complete_tickers = latest_slice_tickers
                effective_lookback_days = 1
        if not complete_tickers:
            raise DataNotAvailableAt(
                DatasetName.STOCK_TRADES.value,
                as_of,
                "no requested ticker has complete stock-trade coverage for live market-flow lanes",
            )
        window_method = getattr(self._loader, "stock_trade_activity_frames_for_trade_window", None)
        if callable(window_method) and effective_as_of != as_of:
            if "allow_partial_coverage" in signature(window_method).parameters:
                return cast(
                    tuple[Any, Any],
                    window_method(
                        complete_tickers,
                        trade_end=effective_as_of,
                        knowledge_as_of=as_of,
                        lookback_days=effective_lookback_days,
                        allow_partial_coverage=True,
                    ),
                )
            return cast(
                tuple[Any, Any],
                window_method(
                    complete_tickers,
                    trade_end=effective_as_of,
                    knowledge_as_of=as_of,
                    lookback_days=effective_lookback_days,
                ),
            )
        method = self._loader.stock_trade_activity_frames
        if "allow_partial_coverage" in signature(method).parameters:
            return cast(
                tuple[Any, Any],
                method(
                    complete_tickers,
                    effective_as_of,
                    effective_lookback_days,
                    allow_partial_coverage=True,
                ),
            )
        return cast(
            tuple[Any, Any],
            method(complete_tickers, effective_as_of, effective_lookback_days),
        )

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> Any:
        raise DataNotAvailableAt(
            DatasetName.STOCK_TRADES.value,
            as_of,
            "live market-flow lanes require complete stock-trade coverage metadata",
        )


def _complete_stock_trade_tickers(
    loader: Any,
    tickers: list[str],
    as_of: date,
    lookback_days: int,
    *,
    allow_partial_coverage: bool = False,
) -> list[str]:
    normalized = sorted({ticker.upper() for ticker in tickers})
    if not normalized:
        return []
    method = getattr(loader, "complete_stock_trade_tickers", None)
    if callable(method):
        try:
            if "allow_partial_coverage" in signature(method).parameters:
                return list(
                    method(
                        normalized,
                        as_of,
                        lookback_days,
                        allow_partial_coverage=allow_partial_coverage,
                    )
                )
            return list(method(normalized, as_of, lookback_days))
        except DataNotAvailableAt:
            return []
    activity_method = getattr(loader, "stock_trade_activity_frames", None)
    if not callable(activity_method):
        return []
    complete: list[str] = []
    for ticker in normalized:
        try:
            if "allow_partial_coverage" in signature(activity_method).parameters:
                activity_method(
                    [ticker],
                    as_of,
                    lookback_days,
                    allow_partial_coverage=allow_partial_coverage,
                )
            else:
                activity_method([ticker], as_of, lookback_days)
        except DataNotAvailableAt:
            continue
        complete.append(ticker)
    return complete


def _latest_stock_trade_slice_tickers(
    loader: Any,
    tickers: list[str],
    as_of: date,
) -> tuple[date, list[str]]:
    for days_back in range(LATEST_STOCK_TRADE_SLICE_FALLBACK_DAYS + 1):
        candidate = as_of - timedelta(days=days_back)
        if candidate.weekday() >= 5:
            continue
        complete = _complete_stock_trade_tickers(
            loader,
            tickers,
            candidate,
            1,
            allow_partial_coverage=True,
        )
        if complete:
            return candidate, complete
    return as_of, []


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
        manifest = registry.require(config.dataset, as_of=as_of, allow_stale=True)
    except DataNotAvailableAt as exc:
        _log_unavailable_lane(config.lane, exc, tickers=tickers, as_of=as_of)
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


def _technical_analysis_signals(
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
        contexts = technical_analysis_contexts(as_of, tickers, loader)
        manifest = registry.require(config.dataset, as_of=as_of)
    except DataNotAvailableAt as exc:
        _log_unavailable_lane(config.lane, exc, tickers=tickers, as_of=as_of)
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
            reason_codes=context.reason_codes,
            summary=context.summary,
        )
        for context in contexts
        if context.ticker in tickers
    ]


def _options_frame_signals(
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
    score_column = (
        "options_anomaly_score"
        if config.lane == "options_anomaly"
        else "options_flow_score"
    )
    frame_builder = (
        options_anomaly_frame if config.lane == "options_anomaly" else options_flow_frame
    )
    try:
        frame = frame_builder(as_of, tickers, loader)
        manifest = registry.require(config.dataset, as_of=as_of)
    except DataNotAvailableAt as exc:
        _log_unavailable_lane(config.lane, exc, tickers=tickers, as_of=as_of)
        return []
    if frame.empty:
        return []
    results: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        ticker = str(row.get("ticker", "")).upper()
        if ticker not in tickers:
            continue
        score = _float_or_none(row.get(score_column))
        if score is None:
            continue
        timestamp_as_of = _timestamp_from_row(row.get("timestamp_as_of"), manifest)
        results.append(
            build_signal_result(
                cycle_id=cycle_id,
                ticker=ticker,
                as_of=as_of_text,
                lane=config.lane,
                score=score,
                provenance=_provenance(
                    config,
                    manifest,
                    generated_at=generated_at,
                    timestamp_as_of=timestamp_as_of,
                ),
                confidence=config.confidence,
            )
        )
    return results


def _provenance(
    config: RuntimeLaneConfig,
    manifest: DataManifest,
    *,
    generated_at: datetime,
    timestamp_as_of: datetime | None = None,
) -> dict[str, object]:
    as_of_timestamp = timestamp_as_of or manifest.max_timestamp_as_of
    freshness = compute_freshness(
        effective_freshness_timestamp(
            config.dataset,
            as_of_timestamp,
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
        "timestamp_as_of": as_of_timestamp.isoformat(),
        "freshness": freshness.value,
        "confidence": config.confidence,
        "verification_level": config.verification_level,
    }


def _log_unavailable_lane(
    lane: str,
    exc: DataNotAvailableAt,
    *,
    tickers: set[str],
    as_of: date,
) -> None:
    LOGGER.warning(
        "runtime signal lane unavailable",
        extra={
            "lane": lane,
            "as_of": as_of.isoformat(),
            "ticker_count": len(tickers),
            "dataset": getattr(exc, "dataset", ""),
            "reason": getattr(exc, "reason", str(exc)),
        },
    )


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp_from_row(value: object, manifest: DataManifest) -> datetime:
    if value is None:
        return manifest.max_timestamp_as_of
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return manifest.max_timestamp_as_of
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(text), time.min, tzinfo=UTC)
            except ValueError:
                return manifest.max_timestamp_as_of
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return manifest.max_timestamp_as_of
