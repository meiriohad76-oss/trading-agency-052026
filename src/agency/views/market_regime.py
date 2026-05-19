"""View-model constructors for the market_regime page."""
from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
import asyncio

from agency.broker import AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot
from agency.runtime.market_regime import load_market_regime_snapshot

from agency.views._shared import (
    BROKER_STATUS_CONTEXT_CACHE_SECONDS,
    MARKET_REGIME_CONTEXT_CACHE_SECONDS,
    dashboard_data_health,
    _env_bool_text,
    _format_timestamp_label,
    live_dashboard_data_load_status,
)

_market_regime_context_cache: dict[str, tuple[float, dict[str, object]]] = {}
_broker_status_context_cache: dict[str, tuple[float, dict[str, object]]] = {}
DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS = 1.0


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
    try:
        config = AlpacaTradingConfig.from_env()
        config.require_paper(purpose="dashboard broker reads")
        broker_read = broker_snapshot(config=config)
        context = (
            await asyncio.wait_for(
                broker_read,
                timeout=DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS,
            )
            if use_cache
            else await broker_read
        )
    except TimeoutError:
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
    except AlpacaBrokerError as exc:
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


def _broker_status_cache_key() -> str:
    import os

    enabled = "enabled" if _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED") else "disabled"
    base_url = os.environ.get("ALPACA_TRADING_BASE_URL", "")
    return f"{enabled}|{base_url}"
