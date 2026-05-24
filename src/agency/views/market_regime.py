"""View-model constructors for the market_regime page."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import monotonic

from agency.broker import AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot
from agency.runtime.market_regime import load_market_regime_snapshot
from agency.views._shared import (
    BROKER_STATUS_CONTEXT_CACHE_SECONDS,
    MARKET_REGIME_CONTEXT_CACHE_SECONDS,
    _env_bool_text,
    _format_timestamp_label,
    dashboard_data_health,
    live_dashboard_data_load_status,
)

_market_regime_context_cache: dict[str, tuple[float, dict[str, object]]] = {}
_broker_status_context_cache: dict[str, tuple[float, dict[str, object]]] = {}
_broker_status_inflight: dict[tuple[str, int], asyncio.Task[dict[str, object]]] = {}
DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS = 2.5


async def market_regime_context() -> dict[str, object]:
    cached = _cached_market_regime_context()
    if cached is not None:
        _format_market_regime_timestamps(cached)
        cached["data_health"] = dashboard_data_health(
            "Market regime dashboard",
            data_load_status=await live_dashboard_data_load_status(),
            datasets=("prices_daily",),
            lanes=("sector_momentum", "technical_analysis"),
            provider_label=_market_regime_provider_label(cached),
        )
        return cached
    context = await asyncio.to_thread(load_market_regime_snapshot)
    _format_market_regime_timestamps(context)
    data_source = context.get("data_source")
    context["data_health"] = dashboard_data_health(
        "Market regime dashboard",
        data_load_status=await live_dashboard_data_load_status(),
        datasets=("prices_daily",),
        lanes=("sector_momentum", "technical_analysis"),
        provider_label=(
            str(data_source.get("provider_label", "local runtime cache"))
            if isinstance(data_source, dict)
            else None
        ),
    )
    _store_market_regime_context(context)
    return context

def _format_market_regime_timestamps(context: dict[str, object]) -> None:
    summary = context.get("summary")
    if isinstance(summary, dict):
        summary["as_of_label"] = _format_timestamp_label(summary.get("as_of"))

async def broker_status_context(
    *,
    use_cache: bool = True,
    allow_live_read: bool = True,
) -> dict[str, object]:
    cache_key = _broker_status_cache_key()
    cached = _cached_broker_status_context(cache_key) if use_cache else None
    if cached is not None:
        return cached
    if not allow_live_read:
        return {
            "provider": "alpaca",
            "mode": "paper",
            "connected": False,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": None,
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Check Pending",
            "status_class": "warn",
            "detail": (
                "Dashboard did not block on a live broker read. Execution preview "
                "and paper submit still perform strict fresh Alpaca checks before "
                "any order can be submitted."
            ),
        }
    if not _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED"):
        context = {
            "provider": "alpaca",
            "mode": "paper",
            "connected": False,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": None,
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Disabled",
            "status_class": "neutral",
            "detail": "Set AGENCY_ALPACA_BROKER_ENABLED=true to read Alpaca paper account data.",
        }
        _store_broker_status_context(cache_key, context)
        return context
    cache_context = True
    broker_read: asyncio.Task[dict[str, object]] | None = None
    try:
        config = AlpacaTradingConfig.from_env()
        config.require_paper(purpose="dashboard broker reads")
        loop_key = _broker_status_inflight_key(cache_key)
        broker_read = _broker_status_inflight.get(loop_key) if use_cache else None
        if broker_read is None or broker_read.done():
            broker_read = asyncio.create_task(broker_snapshot(config=config))
            if use_cache:
                _broker_status_inflight[loop_key] = broker_read
        context = (
            await asyncio.wait_for(
                asyncio.shield(broker_read),
                timeout=DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS,
            )
            if use_cache
            else await broker_read
        )
        if use_cache and broker_read.done():
            _broker_status_inflight.pop(loop_key, None)
    except TimeoutError:
        cache_context = False
        if broker_read is not None:
            broker_read.add_done_callback(
                lambda task: _store_completed_broker_status_context(cache_key, loop_key, task),
            )
        context = {
            "provider": "alpaca",
            "mode": "paper",
            "connected": False,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": None,
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Check Delayed",
            "status_class": "warn",
            "detail": (
                "Dashboard broker read did not finish within "
                f"{DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS:.2f}s. Execution submit "
                "still performs a strict fresh broker check before any paper order."
            ),
        }
        _store_broker_status_context(cache_key, context)
    except AlpacaBrokerError as exc:
        _clear_broker_status_inflight(cache_key)
        context = {
            "provider": "alpaca",
            "mode": "paper",
            "connected": False,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": None,
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Offline",
            "status_class": "warn",
            "detail": str(exc),
        }
    if cache_context:
        _store_broker_status_context(cache_key, context)
    return context

def _cached_market_regime_context() -> dict[str, object] | None:
    cached = _market_regime_context_cache.get("latest")
    if cached is None:
        return None
    cached_at, context = cached
    if monotonic() - cached_at > MARKET_REGIME_CONTEXT_CACHE_SECONDS:
        _market_regime_context_cache.pop("latest", None)
        return None
    return dict(context)

def _store_market_regime_context(context: dict[str, object]) -> None:
    _market_regime_context_cache["latest"] = (monotonic(), dict(context))

def _market_regime_provider_label(context: dict[str, object]) -> str | None:
    data_source = context.get("data_source")
    if isinstance(data_source, dict):
        return str(data_source.get("provider_label", "local runtime cache"))
    return None


def _cached_broker_status_context(key: str) -> dict[str, object] | None:
    cached = _broker_status_context_cache.get(key)
    if cached is None:
        return None
    cached_at, context = cached
    if monotonic() - cached_at > BROKER_STATUS_CONTEXT_CACHE_SECONDS:
        _broker_status_context_cache.pop(key, None)
        return None
    return dict(context)


def _store_broker_status_context(key: str, context: dict[str, object]) -> None:
    _broker_status_context_cache[key] = (monotonic(), dict(context))


def _store_completed_broker_status_context(
    key: str,
    loop_key: tuple[str, int],
    task: asyncio.Task[dict[str, object]],
) -> None:
    try:
        context = task.result()
    except asyncio.CancelledError:
        _broker_status_inflight.pop(loop_key, None)
        return
    except Exception as exc:
        _broker_status_inflight.pop(loop_key, None)
        _store_broker_status_context(key, _broker_offline_context(exc))
        return
    _broker_status_inflight.pop(loop_key, None)
    if isinstance(context, dict):
        _store_broker_status_context(key, context)


def _broker_offline_context(exc: BaseException) -> dict[str, object]:
    return {
        "provider": "alpaca",
        "mode": "paper",
        "connected": False,
        "checked_at": datetime.now(UTC).isoformat(),
        "account": None,
        "positions": [],
        "orders": [],
        "gross_exposure_pct": 0.0,
        "status_label": "Broker Offline",
        "status_class": "warn",
        "detail": str(exc) or exc.__class__.__name__,
    }


def _broker_status_cache_key() -> str:
    import os

    enabled = "enabled" if _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED") else "disabled"
    base_url = os.environ.get("ALPACA_TRADING_BASE_URL", "")
    return f"{enabled}|{base_url}"


def _broker_status_inflight_key(
    cache_key: str,
    loop: asyncio.AbstractEventLoop | None = None,
) -> tuple[str, int]:
    current_loop = asyncio.get_running_loop() if loop is None else loop
    return (cache_key, id(current_loop))


def _clear_broker_status_inflight(cache_key: str) -> None:
    for key in list(_broker_status_inflight):
        if key[0] == cache_key:
            _broker_status_inflight.pop(key, None)
