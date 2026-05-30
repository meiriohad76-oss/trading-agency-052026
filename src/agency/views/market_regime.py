"""View-model constructors for the market_regime page."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from time import monotonic

from agency.broker import AlpacaBrokerError, AlpacaTradingConfig, broker_snapshot
from agency.market_regime.snapshot import DEFAULT_STATE_DIR, build_regime_snapshot
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

_TOOLTIPS: dict[str, str] = {
    "RISK_ON": "SPY 5D >= +1%, breadth >= 55%, and volatility below 20%. Normal candidate approval path.",
    "RISK_OFF": "Broad market is defensive. Require stronger ticker-specific evidence before approving trades.",
    "VOLATILE": "Realized volatility is high. Reduce sizing and prefer cleaner evidence.",
    "ROTATING": "Sector leadership is split. Sector alignment matters more than index direction.",
    "NEUTRAL": "No strong market regime. Candidate-specific evidence drives the decision.",
    "DATA_LIMITED": "Not enough market-regime data is loaded to classify the backdrop.",
    "CALM": "VIX below 20. Standard sizing can apply if candidate evidence is strong.",
    "ELEVATED": "VIX between 20 and 35. Use reduced sizing and stronger review discipline.",
    "HIGH": "VIX above 35. Prefer caution and smaller paper orders.",
    "ADVANCING": "Relative strength and relative momentum are both positive. Sector is leading.",
    "TOPPING": "Relative strength is positive, but momentum is weakening.",
    "BASING": "Relative strength is still negative, but momentum is improving.",
    "DECLINING": "Relative strength and momentum are both negative. Sector is underperforming.",
    "VIXCLS": "VIX fear gauge. Below 20 is calm; above 35 is high fear.",
    "T10Y2Y": "10-year minus 2-year Treasury yield spread. Negative means inverted curve.",
    "DGS10": "10-year Treasury yield. Fast rises can pressure equity valuations.",
    "BAMLH0A0HYM2": "High-yield credit spread. Widening is risk-off.",
    "BAMLC0A0CM": "Investment-grade credit spread. Widening means tighter credit conditions.",
    "STLFSI4": "St. Louis Fed financial stress index. Rising stress is defensive.",
    "ICSA": "Weekly initial jobless claims. Rising claims can signal labor-market weakening.",
    "TLT": "Long-bond ETF 5D return. A sharp bond bid can indicate flight to safety.",
    "GLD": "Gold ETF 5D return. A sharp rise may indicate stress or dollar weakness.",
    "UUP": "US dollar ETF 5D return. A sharp rise can pressure risk assets.",
    "flow_confirmed": "CMF is positive and OBV trend is rising. Sector flow confirms accumulation.",
    "momentum_score": "Composite sector relative-strength score versus SPY.",
    "flow_score": "Chaikin Money Flow. Positive means accumulation; negative means distribution.",
    "rs_ratio": "Sector 20D return minus SPY 20D return.",
    "rs_momentum": "Change in relative-strength ratio over the last five sessions.",
    "conviction_boost": "Sector tailwind/headwind adjustment applied to candidate conviction.",
}


def load_market_regime_snapshot() -> dict[str, object]:
    return build_regime_snapshot(state_dir=DEFAULT_STATE_DIR)


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
    context = _adapt_market_regime_context(await asyncio.to_thread(load_market_regime_snapshot))
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


async def refresh_market_regime_context() -> dict[str, object]:
    _market_regime_context_cache.clear()
    context = _adapt_market_regime_context(
        await asyncio.to_thread(
            build_regime_snapshot,
            state_dir=DEFAULT_STATE_DIR,
            refresh_mode="manual",
            force_fetch=True,
        )
    )
    _format_market_regime_timestamps(context)
    context["data_health"] = dashboard_data_health(
        "Market regime dashboard",
        data_load_status=await live_dashboard_data_load_status(),
        datasets=("prices_daily",),
        lanes=("sector_momentum", "technical_analysis"),
        provider_label=_market_regime_provider_label(context),
    )
    _store_market_regime_context(context)
    return context


def _format_market_regime_timestamps(context: dict[str, object]) -> None:
    summary = context.get("summary")
    if isinstance(summary, dict):
        summary["as_of_label"] = _format_timestamp_label(summary.get("as_of"))


def _adapt_market_regime_context(context: dict[str, object]) -> dict[str, object]:
    adapted = deepcopy(context)
    if isinstance(adapted.get("summary"), dict):
        adapted.setdefault("active_nav", "market")
        adapted.setdefault("tooltips", _TOOLTIPS)
        return adapted
    backdrop = _mapping(adapted.get("market_backdrop"))
    bluf = _mapping(adapted.get("bluf"))
    data_as_of = str(adapted.get("data_as_of") or "not available")
    regime_label = _human_label(backdrop.get("regime"), fallback="Data Limited")
    confidence_pct = round(_float(backdrop.get("confidence")) * 100)
    adapted["active_nav"] = "market"
    adapted["tooltips"] = _TOOLTIPS
    adapted["summary"] = {
        "topbar_label": f"{backdrop.get('regime', 'DATA_LIMITED')} / data through {data_as_of}",
        "status_class": str(backdrop.get("status_class") or bluf.get("status_class") or "warn"),
        "headline": str(bluf.get("headline") or "Market regime context is available."),
        "interpretation": str(bluf.get("operator_message") or "Review the market backdrop."),
        "decision_guidance": _decision_guidance(backdrop),
        "regime_label": regime_label,
        "as_of": data_as_of,
        "confidence_pct": confidence_pct,
    }
    adapted["kpis"] = _kpi_rows_from_snapshot(adapted)
    adapted["breadth"] = _breadth_from_snapshot(_mapping(adapted.get("breadth")))
    adapted["benchmark_rows"] = _benchmark_rows_from_snapshot(adapted.get("benchmarks"))
    adapted["sector_rows"] = _sector_rows_from_snapshot(adapted.get("sector_map"), data_as_of)
    adapted["universe"] = {
        "member_count": len(_mapping(adapted.get("per_stock_context"))),
        "priced_count": len(_mapping(adapted.get("per_stock_context"))),
        "coverage_label": "mapped",
        "state_class": "pass" if _mapping(adapted.get("per_stock_context")) else "warn",
    }
    adapted["data_source"] = {
        "provider_label": "Massive/FRED regime state",
        "row_count_label": f"{len(_mapping(adapted.get('sector_map')))} sectors",
        "detail": "Market regime state files normalized by the redesigned regime agent.",
    }
    return adapted


def _kpi_rows_from_snapshot(context: dict[str, object]) -> list[dict[str, object]]:
    backdrop = _mapping(context.get("market_backdrop"))
    breadth = _mapping(context.get("breadth"))
    spy = _first_benchmark(context.get("benchmarks"), "SPY")
    return [
        {
            "label": "Risk regime",
            "value": _human_label(backdrop.get("regime"), fallback="Data Limited"),
            "detail": _decision_guidance(backdrop),
            "class": str(backdrop.get("status_class", "warn")),
        },
        {
            "label": "Vol",
            "value": _human_label(backdrop.get("vol_regime"), fallback="Unknown"),
            "detail": "position sizing context",
            "class": str(backdrop.get("status_class", "warn")),
        },
        {
            "label": "SPY 5D",
            "value": _signed_pct(_mapping(spy).get("return_5d_pct")),
            "detail": "broad market direction",
            "class": _tone_class(_float(_mapping(spy).get("return_5d_pct"))),
        },
        {
            "label": "Breadth",
            "value": str(breadth.get("advancers_label", "n/a")),
            "detail": f"{breadth.get('total', 0)} grouped-daily rows",
            "class": str(breadth.get("status_class", "warn")),
        },
    ]


def _breadth_from_snapshot(breadth: dict[str, object]) -> dict[str, object]:
    return {
        **breadth,
        "state_class": str(breadth.get("status_class", "warn")),
        "breadth_score_label": str(breadth.get("advancers_label", "n/a")),
        "detail": f"{breadth.get('total', 0)} grouped-daily equities; {breadth.get('advancers_label', 'n/a')} advancers",
        "above_sma20_label": "n/a",
        "above_sma50_label": "n/a",
        "advancers_5d_label": str(breadth.get("advancers_label", "n/a")),
        "coverage_label": "full market" if breadth.get("total") else "not available",
    }


def _benchmark_rows_from_snapshot(benchmarks: object) -> list[dict[str, object]]:
    return [
        {
            "ticker": str(row.get("ticker", "")),
            "label": str(row.get("ticker", "")),
            "latest_price": _price_label(row.get("latest_price")),
            "return_5d": _signed_pct(row.get("return_5d_pct")),
            "return_20d": _signed_pct(row.get("return_20d_pct")),
            "return_60d": "n/a",
            "tone_class": _tone_class(_float(row.get("return_5d_pct"))),
            "observations": "state",
        }
        for row in _list(benchmarks)
    ]


def _sector_rows_from_snapshot(sector_map: object, data_as_of: str) -> list[dict[str, object]]:
    rows = sorted(
        [_mapping(row) for row in _mapping(sector_map).values()],
        key=lambda row: (-_float(row.get("score")), str(row.get("ticker", ""))),
    )
    return [_sector_row(index, row, data_as_of) for index, row in enumerate(rows, start=1)]


def _sector_row(index: int, row: dict[str, object], data_as_of: str) -> dict[str, object]:
    boost = _float(row.get("conviction_boost"))
    cmf = row.get("cmf_14")
    return {
        "rank": index,
        "ticker": str(row.get("ticker", "")),
        "label": str(row.get("ticker", "")),
        "state": str(row.get("state", "UNKNOWN")),
        "quadrant": str(row.get("quadrant", "")),
        "flow_confirmed": bool(row.get("flow_confirmed", False)),
        "cmf_14_label": f"{_float(cmf):+.3f}" if cmf is not None else "n/a",
        "conviction_boost": boost,
        "conviction_boost_pct": f"{abs(boost * 100):.0f}",
        "stance": _human_label(row.get("bias"), fallback="Neutral"),
        "stance_class": str(row.get("status_class", "neutral")),
        "score_label": f"{_float(row.get('score')):+.2f}",
        "score_gauge_style": _gauge_style(row.get("score"), 3.0),
        "return_5d_class": _tone_class(_float(row.get("return_5d_pct"))),
        "return_20d": _signed_pct(row.get("return_20d_pct")),
        "return_20d_class": _tone_class(_float(row.get("return_20d_pct"))),
        "return_20d_gauge_style": _gauge_style(row.get("return_20d_pct"), 15.0),
        "return_60d": "n/a",
        "return_60d_class": "neutral",
        "return_60d_gauge_style": "width: 0%",
        "excess_5d": _signed_pct(row.get("return_5d_pct")),
        "excess_20d": _signed_pct(row.get("score")),
        "excess_20d_class": _tone_class(_float(row.get("score"))),
        "excess_20d_gauge_style": _gauge_style(row.get("score"), 3.0),
        "excess_60d": "n/a",
        "observations": "state",
        "latest_date": data_as_of,
        "guidance": f"{row.get('state', 'UNKNOWN')} sector context; conviction modifier {boost:+.2f}.",
    }


def _decision_guidance(backdrop: dict[str, object]) -> str:
    regime = str(backdrop.get("regime", "DATA_LIMITED"))
    if regime == "RISK_ON":
        return "Normal approval path; sector tailwinds can corroborate candidates."
    if regime == "RISK_OFF":
        return "Use caution; require stronger stock-specific evidence before approvals."
    if regime == "VOLATILE":
        return "Reduce paper sizing and prefer cleaner evidence before new entries."
    if regime == "ROTATING":
        return "Focus on sector alignment; index direction is less informative."
    return "Use ticker-specific evidence as the primary decision input."


def _human_label(value: object, *, fallback: str) -> str:
    return fallback if value is None else str(value).replace("_", " ").title()


def _first_benchmark(benchmarks: object, ticker: str) -> dict[str, object]:
    for row in _list(benchmarks):
        if str(row.get("ticker", "")).upper() == ticker:
            return row
    return {}


def _list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _float(value: object) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        return float(value)
    except TypeError, ValueError:
        return 0.0


def _signed_pct(value: object) -> str:
    return f"{_float(value):+.1f}%" if value is not None else "n/a"


def _price_label(value: object) -> str:
    return f"${_float(value):,.2f}" if value is not None else "n/a"


def _tone_class(value: float) -> str:
    if value > 0:
        return "pass"
    if value < 0:
        return "block"
    return "neutral"


def _gauge_style(value: object, cap: float) -> str:
    if cap <= 0.0:
        return "width: 0%"
    return f"width: {min(100, round(abs(_float(value)) / cap * 100))}%"


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
