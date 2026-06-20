# src/agency/market_regime/massive.py
from __future__ import annotations

import math
import os
import ssl
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import import_module
from typing import cast

import httpx

DEFAULT_MASSIVE_BASE_URL = "https://api.polygon.io"
_ETF_DAILY_PATH = "/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
_SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
_GROUPED_PATH = "/v2/aggs/grouped/locale/us/market/stocks/{day}"


def massive_api_key() -> str | None:
    """Return the Massive/Polygon API key from env, or None if not configured."""
    return (
        os.environ.get("MASSIVE_API_KEY", "").strip()
        or os.environ.get("POLYGON_API_KEY", "").strip()
        or None
    )


def fetch_etf_daily_bars(
    tickers: Sequence[str],
    *,
    start_date: str,
    end_date: str,
    api_key: str,
    base_url: str = DEFAULT_MASSIVE_BASE_URL,
    _transport: httpx.BaseTransport | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Call /v2/aggs/ticker/{ticker}/range/1/day for each ticker.

    Returns {TICKER: [{date, open, high, low, close, volume}]}.
    Tickers that return no usable response are skipped so one transient
    ticker failure does not erase the whole ETF cache.
    """
    result: dict[str, list[dict[str, object]]] = {}
    params = {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key}
    with httpx.Client(verify=_ssl_context(), timeout=30.0, transport=_transport) as client:
        for ticker in tickers:
            path = _ETF_DAILY_PATH.format(ticker=ticker.upper(), start=start_date, end=end_date)
            url = f"{base_url.rstrip('/')}{path}"
            resp = client.get(url, params=params)
            if not resp.is_success:
                continue
            rows = _extract_records(resp.json(), "results")
            if rows:
                result[ticker.upper()] = [_normalize_bar(row) for row in rows]
    return result


def fetch_intraday_snapshot(
    tickers: Sequence[str],
    *,
    api_key: str,
    base_url: str = DEFAULT_MASSIVE_BASE_URL,
    _transport: httpx.BaseTransport | None = None,
) -> dict[str, dict[str, object]]:
    """Call /v2/snapshot/locale/us/markets/stocks/tickers for a batch.

    Returns {TICKER: {price: float, prior_close: float}}.
    """
    url = f"{base_url.rstrip('/')}{_SNAPSHOT_PATH}"
    params = {"tickers": ",".join(t.upper() for t in tickers), "apiKey": api_key}
    with httpx.Client(verify=_ssl_context(), timeout=30.0, transport=_transport) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    result: dict[str, dict[str, object]] = {}
    for item in _extract_records(resp.json(), "tickers", "results"):
        ticker = str(item.get("ticker", "")).upper()
        if not ticker:
            continue
        day = item.get("day") or {}
        prev_day = item.get("prevDay") or {}
        price = _num(day.get("c") if isinstance(day, dict) else None)
        prior_close = _num(prev_day.get("c") if isinstance(prev_day, dict) else None)
        if price is not None and prior_close is not None:
            result[ticker] = {"price": price, "prior_close": prior_close}
    return result


def fetch_grouped_daily_rows(
    day: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_MASSIVE_BASE_URL,
    _transport: httpx.BaseTransport | None = None,
) -> list[dict[str, object]]:
    """Call /v2/aggs/grouped/locale/us/market/stocks/{day}.

    Returns minimal rows [{open, close}] suitable for grouped_daily_breadth().
    """
    url = f"{base_url.rstrip('/')}{_GROUPED_PATH.format(day=day)}"
    params = {"adjusted": "true", "apiKey": api_key}
    with httpx.Client(verify=_ssl_context(), timeout=60.0, transport=_transport) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return [
        {"open": _num(row.get("o")), "close": _num(row.get("c"))}
        for row in _extract_records(resp.json(), "results")
        if _num(row.get("o")) is not None and _num(row.get("c")) is not None
    ]


# ── private helpers ──────────────────────────────────────────────────────────


def _normalize_bar(row: Mapping[str, object]) -> dict[str, object]:
    ts_ms = _num(row.get("t"))
    bar_date = (
        datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC).date().isoformat()
        if ts_ms is not None
        else None
    )
    return {
        "date": bar_date,
        "open": _num(row.get("o")),
        "high": _num(row.get("h")),
        "low": _num(row.get("l")),
        "close": _num(row.get("c")),
        "volume": _num(row.get("v")),
    }


def _extract_records(payload: object, *keys: str) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    value: object = []
    for key in keys:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            value = candidate
            break
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _num(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _ssl_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
