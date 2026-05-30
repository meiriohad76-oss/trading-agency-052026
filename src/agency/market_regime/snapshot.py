from __future__ import annotations

# ruff: noqa: I001

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agency.market_regime.analyzer import (
    analyze_intraday_drift,
    classify_macro_tilt,
    classify_market_backdrop,
    classify_sector_state,
    classify_vol_regime,
    detect_regime_change,
    per_stock_context,
)
from agency.market_regime.fetcher import load_state_json, refresh_regime_state, write_state_json
from agency.market_regime.metrics import (
    build_macro_tiles as _build_macro_tiles,
    latest_date as _latest_date,
    mapping as _mapping,
    metrics_by_ticker as _metrics_by_ticker,
    number as _float,
    percent_label as _pct_label,
    rows as _rows,
    sector_spread as _sector_spread,
)
from agency.market_regime.policy import RegimePolicy

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATE_DIR = REPO_ROOT / "research" / "state" / "market_regime"
DEFAULT_TICKER_SECTOR_MAP = REPO_ROOT / "research" / "config" / "ticker-sector-map.json"
BENCHMARKS = ("SPY", "QQQ", "IWM", "DIA")
SECTOR_ETFS = ("XLK", "XLE", "XLF", "XLV", "XLI", "XLB", "XLY", "XLP", "XLU", "XLC", "XLRE")
MACRO_PROXIES = ("TLT", "GLD", "UUP")


def build_regime_snapshot(
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
    broker_positions: list[dict[str, object]] | None = None,
    policy: RegimePolicy | None = None,
    generated_at: str | None = None,
    refresh_mode: Literal["pre_market", "intraday", "post_market", "manual"] = "manual",
    force_fetch: bool = False,
) -> dict[str, object]:
    active_policy = policy or RegimePolicy.from_env()
    generated = generated_at or datetime.now(UTC).isoformat()
    if force_fetch:
        refresh_regime_state(state_dir, mode=refresh_mode, policy=active_policy)
    state = _load_state(state_dir)
    bars = _mapping(state["etf_bars"])
    metrics = _metrics_by_ticker(bars)
    latest_date = _latest_date(metrics)
    breadth = _breadth(_mapping(state["grouped_daily"]))
    macro = _macro(_mapping(state["macro_fred"]), metrics, active_policy)
    sector_map = _sector_map(metrics, active_policy)
    spread = _sector_spread(sector_map)
    market_backdrop = _market_backdrop(metrics, breadth, macro, spread, active_policy)
    market_backdrop.update(_mapping(macro["vol"]))
    market_backdrop.update(_mapping(macro["tilt"]))
    stock_context = per_stock_context(
        sorted(_ticker_sector_map().keys()),
        _ticker_sector_map(),
        sector_map,
    )
    intraday_drift = analyze_intraday_drift(
        _mapping(state["intraday_bars"]), morning_rank=list(sector_map)
    )
    snapshot: dict[str, object] = {
        "schema_version": "1.0.0",
        "generated_at": generated,
        "snapshot_type": refresh_mode,
        "data_as_of": latest_date or "not available",
        "bluf": _bluf(market_backdrop, latest_date),
        "market_backdrop": market_backdrop,
        "sector_map": sector_map,
        "per_stock_context": stock_context,
        "breadth": breadth,
        "macro": macro,
        "benchmarks": _benchmarks(metrics),
        "intraday_drift": intraday_drift,
        "portfolio_context": _portfolio_context(broker_positions or [], stock_context),
        "data_sources": _data_sources(bars, state, sector_map),
    }
    snapshot["change"] = detect_regime_change(_mapping(state["last_regime"]), snapshot)
    _persist_last_regime(state_dir, snapshot)
    return snapshot


def _load_state(state_dir: Path) -> dict[str, object]:
    names = (
        "etf_bars",
        "intraday_bars",
        "grouped_daily",
        "macro_fred",
        "macro_proxies",
        "last_regime",
    )
    return {name: load_state_json(state_dir / f"{name}.json") for name in names}


def _market_backdrop(
    metrics: Mapping[str, Mapping[str, object]],
    breadth: Mapping[str, object],
    macro: Mapping[str, object],
    spread: float | None,
    policy: RegimePolicy,
) -> dict[str, object]:
    spy = metrics.get("SPY", {})
    qqq = metrics.get("QQQ", {})
    tlt = metrics.get("TLT", {})
    if not spy:
        return classify_market_backdrop(
            spy_5d_pct=None,
            qqq_5d_pct=None,
            breadth_pct=None,
            spy_vol_10d=None,
            tlt_5d_pct=None,
            sector_zscore_spread=None,
            policy=policy,
        )
    return classify_market_backdrop(
        spy_5d_pct=_float(spy.get("return_5d_pct")),
        qqq_5d_pct=_float(qqq.get("return_5d_pct")),
        breadth_pct=_float(breadth.get("advancers_pct")),
        spy_vol_10d=_float(spy.get("realized_vol_10d")),
        tlt_5d_pct=_float(tlt.get("return_5d_pct")),
        sector_zscore_spread=spread,
        policy=policy,
    )


def _sector_map(
    metrics: Mapping[str, Mapping[str, object]],
    policy: RegimePolicy,
) -> dict[str, dict[str, object]]:
    spy_20d = _float(_mapping(metrics.get("SPY")).get("return_20d_pct")) or 0.0
    spy_20d_5d_ago = _float(_mapping(metrics.get("SPY")).get("return_20d_pct_5d_ago")) or 0.0
    result: dict[str, dict[str, object]] = {}
    for ticker in SECTOR_ETFS:
        metric = _mapping(metrics.get(ticker))
        if not metric:
            continue
        rs_ratio = (_float(metric.get("return_20d_pct")) or 0.0) - spy_20d
        rs_ratio_5d_ago = (_float(metric.get("return_20d_pct_5d_ago")) or 0.0) - spy_20d_5d_ago
        rs_momentum = rs_ratio - rs_ratio_5d_ago
        state = classify_sector_state(
            rs_ratio,
            rs_momentum,
            _float(metric.get("cmf_14")),
            str(metric.get("obv_trend", "UNKNOWN")),
            policy,
        )
        result[ticker] = {
            **state,
            "ticker": ticker,
            "score": round(rs_ratio, 2),
            "return_5d_pct": round(_float(metric.get("return_5d_pct")) or 0.0, 2),
            "return_20d_pct": round(_float(metric.get("return_20d_pct")) or 0.0, 2),
        }
    return result


def _macro(
    macro_fred: Mapping[str, object],
    metrics: Mapping[str, Mapping[str, object]],
    policy: RegimePolicy,
) -> dict[str, object]:
    series = _mapping(macro_fred.get("series"))
    vix = _latest_series_value(series, "VIXCLS")
    yield_curve = _latest_series_value(series, "T10Y2Y")
    credit_delta = _series_delta(series, "BAMLH0A0HYM2")
    tlt_5d = _float(_mapping(metrics.get("TLT")).get("return_5d_pct"))
    proxies = {
        ticker: _float(_mapping(metrics.get(ticker)).get("return_5d_pct"))
        for ticker in MACRO_PROXIES
    }
    return {
        "series": series,
        "tiles": _build_macro_tiles(series, proxies),
        "vol": classify_vol_regime(vix, policy),
        "tilt": classify_macro_tilt(yield_curve, credit_delta, tlt_5d, policy),
        "proxies": proxies,
    }


def _breadth(payload: Mapping[str, object]) -> dict[str, object]:
    total = int(_float(payload.get("total")) or 0)
    advancers_pct = _float(payload.get("advancers_pct"))
    return {
        "total": total,
        "advancers_pct": advancers_pct,
        "advancers_label": _pct_label(advancers_pct),
        "status_class": "pass" if total and advancers_pct is not None else "warn",
    }


def _benchmarks(metrics: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    return [_benchmark_row(ticker, _mapping(metrics.get(ticker))) for ticker in BENCHMARKS]


def _benchmark_row(ticker: str, metric: Mapping[str, object]) -> dict[str, object]:
    return {
        "ticker": ticker,
        "return_5d_pct": metric.get("return_5d_pct"),
        "return_20d_pct": metric.get("return_20d_pct"),
        "latest_price": metric.get("latest_price"),
    }


def _portfolio_context(
    positions: Sequence[Mapping[str, object]],
    stock_context: Mapping[str, Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    buckets: dict[str, list[dict[str, object]]] = {
        "headwind_positions": [],
        "topping_positions": [],
        "tailwind_positions": [],
    }
    for position in positions:
        ticker = str(position.get("ticker") or position.get("symbol") or "").upper()
        context = _mapping(stock_context.get(ticker))
        row = {"ticker": ticker, **context}
        if context.get("sector_bias") == "HEADWIND":
            buckets["headwind_positions"].append(row)
        elif context.get("sector_state") == "TOPPING":
            buckets["topping_positions"].append(row)
        elif context.get("sector_bias") == "TAILWIND":
            buckets["tailwind_positions"].append(row)
    return buckets


def _data_sources(
    bars: Mapping[str, object],
    state: Mapping[str, object],
    sector_map: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        _source("OHLCV", "PASS" if bars else "BLOCK", f"{len(bars)} ETF series loaded"),
        _source(
            "FRED", "PASS" if _mapping(state["macro_fred"]).get("series") else "WARN", "macro cache"
        ),
        _source("COMPUTE", "PASS" if sector_map else "WARN", f"{len(sector_map)} sectors analyzed"),
        _source("FLOW", "PASS" if sector_map else "WARN", "CMF/OBV sector flow"),
    ]


def _bluf(market_backdrop: Mapping[str, object], latest_date: str | None) -> dict[str, object]:
    regime = str(market_backdrop.get("regime", "DATA_LIMITED"))
    vol = str(market_backdrop.get("vol_regime", "UNKNOWN"))
    macro = str(market_backdrop.get("macro_tilt", "NEUTRAL"))
    return {
        "headline": f"{regime} / {vol} volatility / {macro} macro",
        "operator_message": f"Market regime context uses data through {latest_date or 'not available'}.",
        "status_class": str(market_backdrop.get("status_class", "warn")),
    }


def _persist_last_regime(state_dir: Path, snapshot: Mapping[str, object]) -> None:
    backdrop = _mapping(snapshot.get("market_backdrop"))
    if backdrop.get("regime") == "DATA_LIMITED":
        return
    write_state_json(
        state_dir / "last_regime.json",
        {
            "generated_at": snapshot.get("generated_at"),
            "market_backdrop": backdrop,
            "sector_map": snapshot.get("sector_map", {}),
        },
    )


def _ticker_sector_map() -> dict[str, str]:
    payload = load_state_json(DEFAULT_TICKER_SECTOR_MAP)
    return {str(ticker).upper(): str(sector).upper() for ticker, sector in payload.items()}


def _source(label: str, status: str, detail: str) -> dict[str, object]:
    return {"label": label, "status": status, "status_class": status.lower(), "detail": detail}


def _latest_series_value(series: Mapping[str, object], series_id: str) -> float | None:
    rows = _rows(series.get(series_id))
    return _float(rows[-1].get("value")) if rows else None


def _series_delta(series: Mapping[str, object], series_id: str) -> float | None:
    rows = _rows(series.get(series_id))
    if len(rows) < 2:
        return 0.0
    latest = _float(rows[-1].get("value"))
    prior = _float(rows[0].get("value"))
    return None if latest is None or prior is None else (latest - prior) * 100.0
