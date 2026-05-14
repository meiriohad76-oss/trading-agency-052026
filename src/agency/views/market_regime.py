"""View-model constructors for the market_regime page."""
from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
import asyncio

from agency.broker import AlpacaBrokerError, broker_snapshot
from agency.runtime.market_regime import load_market_regime_snapshot

from agency.views._shared import (
    MARKET_REGIME_CONTEXT_CACHE_SECONDS,
    _env_bool_text,
)

_market_regime_context_cache: dict[str, tuple[float, dict[str, object]]] = {}


async def market_regime_context() -> dict[str, object]:
    cached = _cached_market_regime_context()
    if cached is not None:
        return cached
    context = await asyncio.to_thread(load_market_regime_snapshot)
    _store_market_regime_context(context)
    return context

async def broker_status_context() -> dict[str, object]:
    if not _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED"):
        return {
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
    try:
        return await broker_snapshot()
    except AlpacaBrokerError as exc:
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
            "detail": str(exc),
        }

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
