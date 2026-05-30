# Market Regime — Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three identified gaps in the market regime redesign: (1) Massive API fetching is unimplemented, (2) macro tiles are bare id/value structs, (3) sector cards expose bias instead of state and omit flow score, quadrant, and conviction boost.

**Architecture:** Gap 1 adds `src/agency/market_regime/massive.py` (sync httpx) and wires it into `fetcher.py`'s `refresh_regime_state()` per mode. Gap 2 adds `build_macro_tiles()` to `metrics.py` (keeping snapshot.py under 300 lines) and pushes enriched tile dicts through to the Jinja2 template. Gap 3 adds state/quadrant/flow/boost fields to the view's `_sector_row()` adapter and updates the template markup.

**Tech Stack:** Python 3.14, httpx 0.28 (sync client + MockTransport), pytest, Jinja2/htmx, existing CSS classes only (quality-card, metric-gauge, metric-cell, tag, muted-line).

**Baseline:** 26 tests pass. All files ≤ 300 lines. The spec is at `docs/superpowers/specs/2026-05-29-market-regime-redesign.md`.

---

## File Map

| Action | File | What changes |
|---|---|---|
| Create | `src/agency/market_regime/massive.py` | New sync-httpx HTTP layer for Massive API |
| Modify | `src/agency/market_regime/fetcher.py` | Add `refresh_etf_bars`, `refresh_intraday_bars`, `refresh_grouped_daily`; update `refresh_regime_state()` |
| Modify | `tests/integration/test_market_regime_fetcher.py` | Add 6 new integration tests for Massive refresh functions |
| Modify | `src/agency/market_regime/metrics.py` | Add `build_macro_tiles()` and private tile-classification helpers |
| Modify | `src/agency/market_regime/snapshot.py` | Import + call `build_macro_tiles`; delete old `_macro_tiles`; add `return_20d_pct_5d_ago` flow-through |
| Modify | `src/agency/views/market_regime.py` | Add `_TOOLTIPS` dict; enrich `_sector_row()`; remove dead `quality_rows` |
| Modify | `src/agency/templates/market_regime.html` | Update macro tiles section and sector card markup |
| Modify | `src/agency/market_regime/metrics.py` (again, bonus) | Add `return_20d_pct_5d_ago` to `_metric()` |
| Modify | `src/agency/market_regime/snapshot.py` (again, bonus) | Use `return_20d_pct_5d_ago` in `_sector_map()` for spec-correct RS-Momentum |

---

## Gap 1 — Massive API Fetching

### Task 1: Write failing tests for `massive.py`

**Files:**
- Create: `tests/unit/test_market_regime_massive.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_market_regime_massive.py
from __future__ import annotations

import json
import httpx
import pytest
from agency.market_regime.massive import (
    fetch_etf_daily_bars,
    fetch_grouped_daily_rows,
    fetch_intraday_snapshot,
)


def _bars_payload(ticker: str) -> dict:
    return {
        "results": [
            {"t": 1748390400000, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1_000_000}
        ],
        "status": "OK",
    }


def _snapshot_payload() -> dict:
    return {
        "results": [
            {
                "ticker": "SPY",
                "day": {"c": 456.0},
                "prevDay": {"c": 450.0},
            },
            {
                "ticker": "XLK",
                "day": {"c": 200.0},
                "prevDay": {"c": 195.0},
            },
        ]
    }


def _grouped_payload() -> dict:
    return {
        "results": [
            {"T": "AAPL", "o": 10.0, "c": 11.0},
            {"T": "BBB",  "o": 10.0, "c": 9.0},
        ]
    }


def _make_transport(routes: dict[str, dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        for pattern, payload in routes.items():
            if pattern in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"status": "NOT_FOUND"})
    return httpx.MockTransport(handler)


def test_fetch_etf_daily_bars_returns_ticker_keyed_bars() -> None:
    transport = _make_transport({
        "/v2/aggs/ticker/SPY": _bars_payload("SPY"),
        "/v2/aggs/ticker/QQQ": _bars_payload("QQQ"),
    })
    result = fetch_etf_daily_bars(
        ["SPY", "QQQ"],
        start_date="2026-05-01",
        end_date="2026-05-28",
        api_key="test",
        _transport=transport,
    )
    assert "SPY" in result
    assert "QQQ" in result
    assert result["SPY"][0]["close"] == 101.0
    assert result["SPY"][0]["date"] != ""


def test_fetch_etf_daily_bars_skips_404_tickers() -> None:
    transport = _make_transport({"/v2/aggs/ticker/SPY": _bars_payload("SPY")})
    result = fetch_etf_daily_bars(
        ["SPY", "MISSING"],
        start_date="2026-05-01",
        end_date="2026-05-28",
        api_key="test",
        _transport=transport,
    )
    assert "SPY" in result
    assert "MISSING" not in result


def test_fetch_intraday_snapshot_returns_price_and_prior_close() -> None:
    transport = _make_transport({"/v2/snapshot": _snapshot_payload()})
    result = fetch_intraday_snapshot(
        ["SPY", "XLK"], api_key="test", _transport=transport
    )
    assert result["SPY"]["price"] == 456.0
    assert result["SPY"]["prior_close"] == 450.0
    assert result["XLK"]["price"] == 200.0


def test_fetch_grouped_daily_rows_returns_open_close_rows() -> None:
    transport = _make_transport({"/v2/aggs/grouped": _grouped_payload()})
    result = fetch_grouped_daily_rows(
        "2026-05-28", api_key="test", _transport=transport
    )
    assert len(result) == 2
    assert result[0]["open"] == 10.0
    assert result[0]["close"] == 11.0
```

- [ ] **Step 2: Run the tests — verify they fail with ImportError**

```
python -m pytest tests/unit/test_market_regime_massive.py -v
```

Expected: `ImportError: cannot import name 'fetch_etf_daily_bars' from 'agency.market_regime.massive'` (module doesn't exist yet).

---

### Task 2: Create `src/agency/market_regime/massive.py`

**Files:**
- Create: `src/agency/market_regime/massive.py`

- [ ] **Step 1: Write the file**

```python
# src/agency/market_regime/massive.py
from __future__ import annotations

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
    Tickers that return HTTP 404 are silently skipped.
    Raises httpx.HTTPStatusError for non-404 failures.
    """
    result: dict[str, list[dict[str, object]]] = {}
    params = {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key}
    with httpx.Client(verify=_ssl_context(), timeout=30.0, transport=_transport) as client:
        for ticker in tickers:
            path = _ETF_DAILY_PATH.format(
                ticker=ticker.upper(), start=start_date, end=end_date
            )
            url = f"{base_url.rstrip('/')}{path}"
            resp = client.get(url, params=params)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            rows = _extract_results(resp.json())
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
    for item in _extract_results(resp.json()):
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
        for row in _extract_results(resp.json())
        if _num(row.get("o")) is not None and _num(row.get("c")) is not None
    ]


# ── private helpers ──────────────────────────────────────────────────────────

def _normalize_bar(row: Mapping[str, object]) -> dict[str, object]:
    ts_ms = row.get("t")
    bar_date = (
        datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC).date().isoformat()
        if ts_ms is not None
        else ""
    )
    return {
        "date": bar_date,
        "open": _num(row.get("o")),
        "high": _num(row.get("h")),
        "low": _num(row.get("l")),
        "close": _num(row.get("c")),
        "volume": _num(row.get("v")),
    }


def _extract_results(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    value = payload.get("results", [])
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _num(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ssl_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
```

- [ ] **Step 2: Run the tests — verify they pass**

```
python -m pytest tests/unit/test_market_regime_massive.py -v
```

Expected: 4 PASSED.

---

### Task 3: Write failing tests for the new `fetcher.py` refresh functions

**Files:**
- Modify: `tests/integration/test_market_regime_fetcher.py`

- [ ] **Step 1: Append 6 new tests to `tests/integration/test_market_regime_fetcher.py`**

```python
# append after the existing 4 tests

from datetime import timedelta
from agency.market_regime.fetcher import (
    refresh_etf_bars,
    refresh_intraday_bars,
    refresh_grouped_daily,
)


def test_refresh_etf_bars_writes_state_file(tmp_path) -> None:
    fake_bars = {
        "SPY": [{"date": "2026-05-28", "open": 100.0, "high": 102.0,
                 "low": 99.0, "close": 101.0, "volume": 1_000_000.0}],
    }

    def fake_client(tickers, start, end):
        return {t: fake_bars[t] for t in tickers if t in fake_bars}

    result = refresh_etf_bars(
        tmp_path / "etf_bars.json",
        policy=RegimePolicy(),
        now=datetime.now(UTC),
        etf_client=fake_client,
    )

    assert result.ok is True
    assert load_state_json(tmp_path / "etf_bars.json") == fake_bars


def test_refresh_etf_bars_client_failure_non_blocking(tmp_path) -> None:
    def broken_client(tickers, start, end):
        raise RuntimeError("network error")

    result = refresh_etf_bars(
        tmp_path / "etf_bars.json",
        policy=RegimePolicy(),
        now=datetime.now(UTC),
        etf_client=broken_client,
    )

    assert result.ok is False
    assert any("failed" in issue.lower() for issue in result.issues)
    assert not (tmp_path / "etf_bars.json").exists()


def test_refresh_intraday_bars_writes_state_file(tmp_path) -> None:
    fake = {"SPY": {"price": 456.0, "prior_close": 450.0}}

    result = refresh_intraday_bars(
        tmp_path / "intraday_bars.json",
        snapshot_client=lambda tickers: fake,
    )

    assert result.ok is True
    assert load_state_json(tmp_path / "intraday_bars.json") == fake


def test_refresh_intraday_bars_failure_non_blocking(tmp_path) -> None:
    def broken(_):
        raise RuntimeError("down")

    result = refresh_intraday_bars(
        tmp_path / "intraday_bars.json",
        snapshot_client=broken,
    )

    assert result.ok is False


def test_refresh_grouped_daily_writes_breadth(tmp_path) -> None:
    fake_rows = [
        {"open": 10.0, "close": 11.0},
        {"open": 10.0, "close": 9.0},
        {"open": 10.0, "close": 11.5},
    ]

    result = refresh_grouped_daily(
        tmp_path / "grouped_daily.json",
        now=datetime.now(UTC),
        grouped_client=lambda day: fake_rows,
    )

    assert result.ok is True
    breadth = load_state_json(tmp_path / "grouped_daily.json")
    assert breadth["total"] == 3
    assert breadth["advancers"] == 2
    assert breadth["decliners"] == 1
    assert breadth["advancers_pct"] == pytest.approx(66.67, rel=0.01)


def test_refresh_grouped_daily_failure_non_blocking(tmp_path) -> None:
    def broken(day):
        raise RuntimeError("down")

    result = refresh_grouped_daily(
        tmp_path / "grouped_daily.json",
        now=datetime.now(UTC),
        grouped_client=broken,
    )

    assert result.ok is False
```

Note: the import block at the top of the file already imports `datetime`, `UTC`, `timedelta`, `FetchSummary`, `load_state_json`, `write_state_json`, `RegimePolicy`. Add `refresh_etf_bars`, `refresh_intraday_bars`, `refresh_grouped_daily` to the existing `from agency.market_regime.fetcher import (...)` block. Add `import pytest` if not already present.

- [ ] **Step 2: Run the new tests — verify they fail**

```
python -m pytest tests/integration/test_market_regime_fetcher.py -v -k "refresh_etf or refresh_intraday or refresh_grouped"
```

Expected: `ImportError` or `AttributeError` — `refresh_etf_bars` not yet defined.

---

### Task 4: Add `refresh_etf_bars`, `refresh_intraday_bars`, `refresh_grouped_daily` to `fetcher.py`

**Files:**
- Modify: `src/agency/market_regime/fetcher.py`

- [ ] **Step 1: Add imports at the top of `fetcher.py`**

After the existing imports, add:
```python
from collections.abc import Callable, Sequence
from datetime import timedelta

from agency.market_regime.massive import (
    fetch_etf_daily_bars,
    fetch_grouped_daily_rows,
    fetch_intraday_snapshot,
    massive_api_key as _massive_api_key,
)
```

(Remove `Callable` and `Sequence` from the existing import line if present; the existing file already imports `Callable` — merge.)

Existing imports to keep exactly as-is:
```python
from collections.abc import Callable, Iterable, Mapping
```
Add `Sequence` to that line:
```python
from collections.abc import Callable, Iterable, Mapping, Sequence
```

And add the `timedelta` import to the existing datetime import line:
```python
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 2: Add three constants after the `FRED_SERIES` tuple**

```python
ALL_ETFS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA",
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLB", "XLY", "XLP", "XLU", "XLC", "XLRE",
    "TLT", "GLD", "UUP",
)
SECTOR_SNAPSHOT_TICKERS: tuple[str, ...] = (
    "SPY", "XLK", "XLE", "XLF", "XLV", "XLI", "XLB", "XLY", "XLP", "XLU", "XLC", "XLRE",
)
```

- [ ] **Step 3: Add the three refresh functions before `refresh_regime_state()`**

```python
def refresh_etf_bars(
    path: Path,
    *,
    policy: RegimePolicy,
    now: datetime,
    etfs: tuple[str, ...] = ALL_ETFS,
    etf_client: Callable[[Sequence[str], str, str], dict[str, list[dict]]] | None = None,
) -> FetchSummary:
    """Fetch daily OHLCV bars for all ETFs and write to ``path``."""
    api_key = _massive_api_key()
    if api_key is None and etf_client is None:
        return FetchSummary(ok=False, issues=["MASSIVE_API_KEY not configured; etf_bars not updated."])
    end_date = now.date().isoformat()
    start_date = (now.date() - timedelta(days=policy.etf_bars_lookback_days)).isoformat()
    client: Callable[[Sequence[str], str, str], dict[str, list[dict]]] = (
        etf_client if etf_client is not None
        else (lambda tickers, s, e: fetch_etf_daily_bars(tickers, start_date=s, end_date=e, api_key=api_key))  # type: ignore[arg-type]
    )
    try:
        bars = client(etfs, start_date, end_date)
    except Exception as exc:
        return FetchSummary(ok=False, issues=[f"ETF bars fetch failed: {exc}"])
    if not bars:
        return FetchSummary(ok=False, issues=["ETF bars returned no data."])
    write_state_json(path, bars)
    return FetchSummary(ok=True, updated_files=[str(path)])


def refresh_intraday_bars(
    path: Path,
    *,
    tickers: tuple[str, ...] = SECTOR_SNAPSHOT_TICKERS,
    snapshot_client: Callable[[Sequence[str]], dict[str, dict]] | None = None,
) -> FetchSummary:
    """Fetch live intraday snapshot and write to ``path``."""
    api_key = _massive_api_key()
    if api_key is None and snapshot_client is None:
        return FetchSummary(ok=False, issues=["MASSIVE_API_KEY not configured; intraday_bars not updated."])
    client: Callable[[Sequence[str]], dict[str, dict]] = (
        snapshot_client if snapshot_client is not None
        else (lambda t: fetch_intraday_snapshot(t, api_key=api_key))  # type: ignore[arg-type]
    )
    try:
        bars = client(tickers)
    except Exception as exc:
        return FetchSummary(ok=False, issues=[f"Intraday snapshot fetch failed: {exc}"])
    write_state_json(path, bars)
    return FetchSummary(ok=True, updated_files=[str(path)])


def refresh_grouped_daily(
    path: Path,
    *,
    now: datetime,
    grouped_client: Callable[[str], list[dict]] | None = None,
) -> FetchSummary:
    """Fetch grouped daily bars, compute breadth, and write to ``path``."""
    api_key = _massive_api_key()
    if api_key is None and grouped_client is None:
        return FetchSummary(ok=False, issues=["MASSIVE_API_KEY not configured; grouped_daily not updated."])
    day = now.date().isoformat()
    client: Callable[[str], list[dict]] = (
        grouped_client if grouped_client is not None
        else (lambda d: fetch_grouped_daily_rows(d, api_key=api_key))  # type: ignore[arg-type]
    )
    try:
        rows = client(day)
    except Exception as exc:
        return FetchSummary(ok=False, issues=[f"Grouped daily fetch failed: {exc}"])
    write_state_json(path, grouped_daily_breadth(rows))
    return FetchSummary(ok=True, updated_files=[str(path)])
```

- [ ] **Step 4: Update `refresh_regime_state()` to call the new functions based on `mode`**

Replace the entire body of `refresh_regime_state()` with:

```python
def refresh_regime_state(
    state_dir: Path,
    *,
    mode: str,
    policy: RegimePolicy | None = None,
    now: datetime | None = None,
) -> FetchSummary:
    active_policy = policy or RegimePolicy.from_env()
    timestamp = now or datetime.now(UTC)
    state_dir.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []
    updated_files: list[str] = []

    if mode in ("pre_market", "post_market", "manual"):
        etf = refresh_etf_bars(
            state_dir / "etf_bars.json", policy=active_policy, now=timestamp
        )
        issues.extend(etf.issues)
        updated_files.extend(etf.updated_files)

    if mode in ("intraday", "manual"):
        intra = refresh_intraday_bars(state_dir / "intraday_bars.json")
        issues.extend(intra.issues)
        updated_files.extend(intra.updated_files)

    if mode in ("post_market", "manual"):
        grouped = refresh_grouped_daily(state_dir / "grouped_daily.json", now=timestamp)
        issues.extend(grouped.issues)
        updated_files.extend(grouped.updated_files)

    fred = refresh_fred_series(
        state_dir / "macro_fred.json", policy=active_policy, now=timestamp
    )
    issues.extend(fred.issues)
    updated_files.extend(fred.updated_files)

    marker = state_dir / "last_fetch.json"
    write_state_json(
        marker,
        {"generated_at": timestamp.isoformat(), "mode": mode, "ok": not issues, "issues": issues},
    )
    updated_files.append(str(marker))
    return FetchSummary(ok=not issues, issues=issues, updated_files=updated_files)
```

- [ ] **Step 5: Verify line count stays ≤ 300**

```
python -c "print(len(open('src/agency/market_regime/fetcher.py').readlines()))"
```

Expected: ≤ 300.

- [ ] **Step 6: Run all market regime tests**

```
python -m pytest tests/unit/test_market_regime_massive.py tests/integration/test_market_regime_fetcher.py tests/unit/test_market_regime_analyzer.py -v
```

Expected: all pass (10 integration + 4 unit massive + 20 analyzer = 34).

- [ ] **Step 7: Commit Gap 1**

```
git add src/agency/market_regime/massive.py src/agency/market_regime/fetcher.py tests/unit/test_market_regime_massive.py tests/integration/test_market_regime_fetcher.py
git commit -m "feat(market-regime): implement Massive API ETF/intraday/grouped-daily fetching"
```

---

## Gap 2 — Macro Tile Enrichment

### Task 5: Write a failing test for enriched macro tiles

**Files:**
- Modify: `tests/unit/test_market_regime_analyzer.py`

- [ ] **Step 1: Append one test**

```python
# append to tests/unit/test_market_regime_analyzer.py
def test_macro_tiles_are_enriched() -> None:
    """build_macro_tiles() must return tiles with class, label, trend, delta, gauge_style, as_of."""
    from agency.market_regime.metrics import build_macro_tiles

    series = {
        "VIXCLS": [
            {"date": "2026-05-27", "value": 20.0},
            {"date": "2026-05-28", "value": 18.0},
        ],
        "T10Y2Y": [{"date": "2026-05-28", "value": -0.1}],
    }
    proxies = {"TLT": 1.8, "GLD": None, "UUP": -0.3}

    tiles = build_macro_tiles(series, proxies)

    required_keys = {"id", "label", "value", "class", "trend", "delta", "gauge_style", "as_of"}
    for tile in tiles:
        assert required_keys.issubset(tile.keys()), f"Tile {tile.get('id')} missing keys: {required_keys - tile.keys()}"

    vix_tile = next(t for t in tiles if t["id"] == "VIXCLS")
    assert vix_tile["class"] == "pass"           # VIX 18 < 20 → pass
    assert vix_tile["as_of"] == "2026-05-28"

    t10y2y_tile = next(t for t in tiles if t["id"] == "T10Y2Y")
    assert t10y2y_tile["class"] == "warn"        # T10Y2Y -0.1 < 0 → inverted → warn

    tlt_tile = next(t for t in tiles if t["id"] == "TLT")
    assert tlt_tile["class"] == "warn"           # TLT 5D +1.8% ≥ +1.5 → flight to safety → warn
    assert "5D" in tlt_tile["as_of"] or tlt_tile["as_of"] != ""
```

- [ ] **Step 2: Run — verify it fails**

```
python -m pytest tests/unit/test_market_regime_analyzer.py::test_macro_tiles_are_enriched -v
```

Expected: `ImportError: cannot import name 'build_macro_tiles'`.

---

### Task 6: Add `build_macro_tiles()` to `metrics.py`

**Files:**
- Modify: `src/agency/market_regime/metrics.py`

- [ ] **Step 1: Append tile helpers and `build_macro_tiles` to `metrics.py`**

Add after the last existing function (`_pct`):

```python
# ── Macro tile enrichment ────────────────────────────────────────────────────

_FRED_LABELS: dict[str, str] = {
    "VIXCLS":       "VIX",
    "T10Y2Y":       "2S10S",
    "DGS10":        "10Y YIELD",
    "BAMLH0A0HYM2": "HY OAS",
    "BAMLC0A0CM":   "CORP OAS",
    "STLFSI4":      "STRESS INDEX",
    "ICSA":         "CLAIMS",
}

_GAUGE_MAX: dict[str, float] = {
    "VIXCLS": 40.0, "T10Y2Y": 3.0, "DGS10": 6.0,
    "BAMLH0A0HYM2": 800.0, "BAMLC0A0CM": 300.0,
    "STLFSI4": 5.0, "ICSA": 400_000.0,
}


def build_macro_tiles(
    series: Mapping[str, object],
    proxies: Mapping[str, float | None],
) -> list[dict[str, object]]:
    """Return enriched tile dicts for all FRED series and proxy ETFs."""
    tiles: list[dict[str, object]] = []
    for series_id, label in _FRED_LABELS.items():
        tile_rows = rows(series.get(series_id))
        tiles.append(_fred_tile(series_id, label, tile_rows))
    for ticker, label in (("TLT", "TLT 5D"), ("GLD", "GLD 5D"), ("UUP", "UUP 5D")):
        tiles.append(_proxy_tile(ticker, label, number(proxies.get(ticker))))
    return tiles


def _fred_tile(
    series_id: str,
    label: str,
    tile_rows: list[dict[str, object]],
) -> dict[str, object]:
    latest_row = tile_rows[-1] if tile_rows else {}
    prior_row = tile_rows[-2] if len(tile_rows) >= 2 else {}
    value_raw = number(latest_row.get("value"))
    prior_raw = number(prior_row.get("value"))
    delta_raw = (value_raw - prior_raw) if value_raw is not None and prior_raw is not None else None
    as_of = str(latest_row.get("date", ""))
    trend = _trend_label(delta_raw)
    value_str = f"{value_raw:.2f}" if value_raw is not None else "n/a"
    delta_str = f"{delta_raw:+.2f}" if delta_raw is not None else "—"
    gauge_max = _GAUGE_MAX.get(series_id, 100.0)
    gauge_pct = min(100, round(abs(value_raw or 0.0) / gauge_max * 100)) if value_raw else 0
    return {
        "id": series_id,
        "label": label,
        "value": value_str,
        "value_raw": value_raw,
        "class": _tile_class(series_id, value_raw, delta_raw),
        "trend": trend,
        "delta": delta_str,
        "delta_raw": delta_raw,
        "gauge_style": f"width: {gauge_pct}%",
        "as_of": as_of,
    }


def _proxy_tile(ticker: str, label: str, return_5d: float | None) -> dict[str, object]:
    cls = "neutral"
    if ticker == "TLT" and return_5d is not None:
        cls = "warn" if return_5d >= 1.5 else ("pass" if return_5d < 0.0 else "neutral")
    elif ticker == "GLD" and return_5d is not None:
        cls = "warn" if return_5d >= 3.0 else "neutral"
    trend = _trend_label(return_5d)
    gauge_pct = min(100, round(abs(return_5d or 0.0) / 5.0 * 100)) if return_5d else 0
    return {
        "id": ticker,
        "label": label,
        "value": f"{return_5d:+.1f}%" if return_5d is not None else "n/a",
        "value_raw": return_5d,
        "class": cls,
        "trend": trend,
        "delta": "—",
        "delta_raw": None,
        "gauge_style": f"width: {gauge_pct}%",
        "as_of": "5D return",
    }


def _tile_class(series_id: str, value: float | None, delta: float | None) -> str:
    if value is None:
        return "neutral"
    d = delta or 0.0
    if series_id == "VIXCLS":
        return "block" if value > 35.0 else ("warn" if value > 20.0 else "pass")
    if series_id == "T10Y2Y":
        return "warn" if value < 0.0 else "pass"
    if series_id == "DGS10":
        return "warn" if d > 0.20 else "neutral"
    if series_id == "BAMLH0A0HYM2":
        return "warn" if d > 0.50 else ("pass" if d < -0.10 else "neutral")
    if series_id == "BAMLC0A0CM":
        return "warn" if d > 0.25 else "neutral"
    if series_id == "STLFSI4":
        return "warn" if value > 0.5 else ("pass" if value < 0.0 else "neutral")
    if series_id == "ICSA":
        return "warn" if value > 300_000 else "pass"
    return "neutral"


def _trend_label(delta: float | None) -> str:
    if delta is None:
        return "—"
    if delta > 0:
        return "↑ Rising"
    if delta < 0:
        return "↓ Falling"
    return "= Stable"
```

- [ ] **Step 2: Verify metrics.py line count**

```
python -c "print(len(open('src/agency/market_regime/metrics.py').readlines()))"
```

Expected: ≤ 300.

- [ ] **Step 3: Run the failing test — verify it now passes**

```
python -m pytest tests/unit/test_market_regime_analyzer.py::test_macro_tiles_are_enriched -v
```

Expected: PASSED.

---

### Task 7: Wire `build_macro_tiles` into `snapshot.py` and update `_macro()`

**Files:**
- Modify: `src/agency/market_regime/snapshot.py`

- [ ] **Step 1: Add `build_macro_tiles` to the metrics import block**

Find the existing import block:
```python
from agency.market_regime.metrics import (
    latest_date as _latest_date,
)
from agency.market_regime.metrics import (
    mapping as _mapping,
)
...
```

Consolidate into one import and add `build_macro_tiles`:
```python
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
```

- [ ] **Step 2: Update `_macro()` to use `_build_macro_tiles` and remove `_macro_tiles()`**

Replace the `_macro()` function body so the `"tiles"` line calls `_build_macro_tiles`:

```python
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
```

Then **delete** the old `_macro_tiles()` function (lines that define it; currently about 6 lines starting with `def _macro_tiles`).

- [ ] **Step 3: Run all tests to confirm nothing regressed**

```
python -m pytest tests/unit/test_market_regime_analyzer.py tests/unit/test_market_regime.py tests/unit/test_fastapi_app.py -q -k "market_regime"
```

Expected: all green.

---

### Task 8: Add `tooltips` to the view context and update the macro tile template

**Files:**
- Modify: `src/agency/views/market_regime.py`
- Modify: `src/agency/templates/market_regime.html`

- [ ] **Step 1: Add `_TOOLTIPS` constant to `views/market_regime.py`**

Add this constant near the top of the file, after the module-level imports:

```python
_TOOLTIPS: dict[str, str] = {
    # Regime states
    "RISK_ON":   "SPY 5D ≥ +1%, breadth ≥ 55%, vol < 20%. Standard approval path for candidates.",
    "RISK_OFF":  "Broad market is defensive. SPY 5D ≤ -1.5% or breadth ≤ 35% or bond flight detected. Raise the conviction bar.",
    "VOLATILE":  "High realized volatility (≥ 25% ann.) with a large price swing. Reduce position sizes; tighten stops.",
    "ROTATING":  "Sector leadership is split. Market index direction is less useful. Focus on sector alignment per candidate.",
    "NEUTRAL":   "No strong directional signal. Candidate-specific evidence dominates the decision.",
    "DATA_LIMITED": "Insufficient price data to classify the regime. Check data sources.",
    # Vol regimes
    "CALM":      "VIX below 20. Normal fear levels. Standard position sizing applies.",
    "ELEVATED":  "VIX 20–35. Elevated uncertainty. Reduce new position sizes to 75% of normal.",
    "HIGH":      "VIX above 35. High fear. Reduce position sizes to 50%. Prefer cash over new entries.",
    # Sector states
    "ADVANCING": "RS-Ratio positive and RS-Momentum positive. Sector is leading the market.",
    "TOPPING":   "RS-Ratio positive but RS-Momentum turning negative. Sector is still ahead but losing steam.",
    "BASING":    "RS-Ratio negative but RS-Momentum improving. Sector is lagging but showing early recovery.",
    "DECLINING": "RS-Ratio negative and RS-Momentum negative. Sector is underperforming and weakening.",
    # FRED series
    "VIXCLS":       "VIX below 20 is calm. Above 35 is fear. Rising fast signals deteriorating conditions.",
    "T10Y2Y":       "10-year minus 2-year Treasury yield spread. Below 0 (inverted) is historically a leading recession signal.",
    "DGS10":        "10-year Treasury constant maturity rate. A fast rise (>20 bps/week) pressures equity valuations.",
    "BAMLH0A0HYM2": "ICE BofA High Yield Option-Adjusted Spread. Widening spreads signal institutional risk-off.",
    "BAMLC0A0CM":   "Investment-grade corporate option-adjusted spread. Wider means tighter credit conditions.",
    "STLFSI4":      "St. Louis Fed Financial Stress Index. Negative = below-average stress. Rising rapidly = financial system tension.",
    "ICSA":         "Weekly initial jobless claims. Rising claims signal a weakening labor market. Watch the 5-week trend.",
    # Proxy ETFs
    "TLT":       "TLT 5-day return. Rising TLT (bonds up) may signal flight to safety and risk-off rotation.",
    "GLD":       "GLD 5-day return. Gold spikes often coincide with stress or USD weakness.",
    "UUP":       "UUP 5-day return. USD ETF direction used as a macro cross-asset signal.",
    # Sector card metrics
    "flow_confirmed": "CMF(14) positive and OBV trend rising. Institutional money is accumulating in this sector ETF.",
    "momentum_score": "Composite relative-strength score: 20% 5D, 50% 20D, 30% 60D excess return vs SPY. Positive = leadership.",
    "flow_score":     "Chaikin Money Flow (14-day). Positive = institutional accumulation. Negative = distribution.",
    "rs_ratio":       "Sector 20D return minus SPY 20D return. Positive means the sector is outperforming the broad market.",
    "rs_momentum":    "Change in RS-Ratio over 5 sessions. Positive = the sector's relative strength is improving.",
    "conviction_boost": "Added to or subtracted from a candidate's final conviction score based on sector tailwind or headwind.",
}
```

- [ ] **Step 2: Pass `_TOOLTIPS` into the adapted context in `_adapt_market_regime_context()`**

In the function `_adapt_market_regime_context()`, add to the return value before the `return adapted` statement (or at the point where `adapted["kpis"]` etc. are set):

```python
adapted["tooltips"] = _TOOLTIPS
```

Place this line after `adapted["active_nav"] = "market"` and before `adapted["summary"] = {...}`.

- [ ] **Step 3: Enrich `_sector_row()` with new fields**

In `_sector_row()`, add these keys to the returned dict (alongside the existing keys):

```python
"state": str(row.get("state", "UNKNOWN")),
"quadrant": str(row.get("quadrant", "")),
"flow_confirmed": bool(row.get("flow_confirmed", False)),
"cmf_14_label": (
    f"{_float(row.get('cmf_14')):+.3f}"
    if row.get("cmf_14") is not None
    else "n/a"
),
"conviction_boost_pct": f"{abs(_float(row.get('conviction_boost', 0)) * 100):.0f}",
"return_5d_class": _tone_class(_float(row.get("return_5d_pct"))),
```

Also update the existing `"stance"` key — it currently reads `_human_label(row.get("bias"))`. Keep it. The template will show both `state` (ADVANCING) and `stance` (Tailwind) as separate elements.

- [ ] **Step 4: Remove dead `quality_rows` code**

In `_adapt_market_regime_context()`, delete this line:
```python
adapted["quality_rows"] = list(_list(adapted.get("data_sources")))
```

- [ ] **Step 5: Update `market_regime.html` — macro tiles section**

Replace the entire `<section>` for Macro Context:

```html
  <section class="panel" aria-labelledby="macro-heading">
    <div class="section-heading">
      <div>
        <h2 id="macro-heading">Macro Context</h2>
        <p class="section-subtitle">FRED series and proxy ETFs used for volatility and macro tilt.</p>
      </div>
      <span class="tag tag-neutral" title="Macro tilt from yield curve, credit spreads, and TLT direction.">{{ market_backdrop.macro_tilt | default("NEUTRAL") }}</span>
    </div>
    <div class="sector-leadership-grid">
      {% for tile in macro.tiles %}
      <article class="quality-card quality-card-{{ tile.class }}"
               aria-label="{{ tile.label }}"
               title="{{ tooltips.get(tile.id, tile.label) }}">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
          <span class="metric-label">{{ tile.label }}</span>
          <span class="tag tag-neutral">{{ tile.id }}</span>
        </div>
        <strong>{{ tile.value }}</strong>
        <span class="tag tag-{{ tile.class }}" style="margin-top: 6px;">{{ tile.trend }}</span>
        <div class="metric-gauge metric-gauge-{{ tile.class }}" aria-hidden="true" style="margin-top: 8px;">
          <span style="{{ tile.gauge_style }}"></span>
        </div>
        <p class="muted-line" title="Change vs prior reading / data as of">
          {{ tile.delta }} &nbsp;·&nbsp; {{ tile.as_of }}
        </p>
      </article>
      {% else %}
      <p class="empty-block">No FRED macro tiles are available yet.</p>
      {% endfor %}
    </div>
  </section>
```

- [ ] **Step 6: Run tests to confirm no regressions**

```
python -m pytest tests/unit/test_fastapi_app.py -q -k "market_regime"
```

Expected: all pass. The `test_market_regime_page_renders_snapshot` test uses an empty `macro.tiles = []` fixture so the tile loop renders nothing — no breakage.

- [ ] **Step 7: Commit Gap 2**

```
git add src/agency/market_regime/metrics.py src/agency/market_regime/snapshot.py src/agency/views/market_regime.py src/agency/templates/market_regime.html tests/unit/test_market_regime_analyzer.py
git commit -m "feat(market-regime): enrich macro tiles with class/trend/delta/gauge/tooltip"
```

---

## Gap 3 — Sector Card Fix

### Task 9: Write a failing test for the enriched sector row

**Files:**
- Modify: `tests/unit/test_fastapi_app.py`

- [ ] **Step 1: Extend `test_market_regime_context_adapts_new_snapshot_contract`**

After line `assert context["sector_rows"][0]["ticker"] == "XLK"`, append:

```python
    sector_row = context["sector_rows"][0]
    assert sector_row["state"] == "ADVANCING"
    assert sector_row["quadrant"] == "Leading"
    assert sector_row["flow_confirmed"] is True
    assert "cmf_14_label" in sector_row
    assert "conviction_boost_pct" in sector_row
```

- [ ] **Step 2: Run — verify new assertions fail**

```
python -m pytest tests/unit/test_fastapi_app.py::test_market_regime_context_adapts_new_snapshot_contract -v
```

Expected: `AssertionError: assert 'state' in {...}` (key not yet in `_sector_row()` output).

---

### Task 10: Update the sector card template to show state, flow score, quadrant, and conviction boost

**Files:**
- Modify: `src/agency/templates/market_regime.html`

- [ ] **Step 1: Replace the sector card `<article>` block**

Find the existing article block (lines ≈ 88–118) starting with:
```html
      <article class="sector-card sector-card-{{ row.stance_class }}" aria-label="{{ row.ticker }} sector">
```

Replace the entire article through its closing `</article>` with:

```html
      <article class="sector-card sector-card-{{ row.stance_class }}" aria-label="{{ row.ticker }} sector">
        <div class="sector-card-head">
          <div>
            <span class="metric-label">#{{ row.rank }} / {{ row.ticker }}</span>
            <strong title="{{ tooltips.get(row.state, 'Sector state') }}">{{ row.state }}</strong>
          </div>
          <span class="tag tag-{{ row.stance_class }}"
                title="Sector bias inherited by stocks in this sector.">{{ row.stance }}</span>
        </div>
        <div class="sector-card-score">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span>
              <strong title="{{ tooltips.momentum_score }}">S {{ row.score_label }}</strong>
            </span>
            <span title="{{ tooltips.flow_score }}">
              F {{ row.cmf_14_label }}
              {% if row.flow_confirmed %}
                <span title="{{ tooltips.flow_confirmed }}" style="color: var(--green);">✓</span>
              {% endif %}
            </span>
          </div>
          <div class="metric-gauge metric-gauge-{{ row.stance_class }}" aria-hidden="true">
            <span style="{{ row.score_gauge_style }}"></span>
          </div>
        </div>
        <div class="market-mini-grid">
          <div class="metric-cell metric-cell-{{ row.return_5d_class }}"
               title="Sector ETF 5-day return.">
            <span class="metric-label">5D</span>
            <strong>{{ row.excess_5d }}</strong>
          </div>
          <div class="metric-cell metric-cell-{{ row.excess_20d_class }}"
               title="{{ tooltips.rs_ratio }}">
            <span class="metric-label">vs SPY</span>
            <strong>{{ row.excess_20d }}</strong>
          </div>
          <div title="{{ tooltips.rs_momentum }}">
            <span class="metric-label">RRG</span>
            <strong>{{ row.quadrant }}</strong>
          </div>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.82em; color: var(--text-dim);">
          <span title="{{ tooltips.conviction_boost }}">
            {% if row.conviction_boost > 0 %}
              <span style="color: var(--green);">+{{ row.conviction_boost_pct }}%</span>
            {% elif row.conviction_boost < 0 %}
              <span style="color: var(--red);">-{{ row.conviction_boost_pct }}%</span>
            {% else %}
              <span>0%</span>
            {% endif %}
          </span>
          <span class="muted-line">{{ row.latest_date }}</span>
        </div>
      </article>
```

Note: `row.conviction_boost` used for the conditional is the float from the view. The template needs to access it — verify the view returns `"conviction_boost": boost` (float). Looking at the existing `_sector_row()` code, `boost` is already defined and returned as `"guidance"` uses it. Confirm the key `"conviction_boost"` is in the returned dict. If it isn't, add it.

- [ ] **Step 2: Verify `_sector_row()` returns `conviction_boost` as a float key**

Open `src/agency/views/market_regime.py`, find `_sector_row()`. Confirm or add:
```python
"conviction_boost": boost,      # float, already computed above
```

The variable `boost` is already computed as `boost = _float(row.get("conviction_boost"))` at the start of the function. Confirm it's included in the dict (it may only appear in `"guidance"` text currently). If it's missing from the returned dict, add `"conviction_boost": boost,` alongside the other keys.

- [ ] **Step 3: Run all failing tests — verify they now pass**

```
python -m pytest tests/unit/test_fastapi_app.py::test_market_regime_context_adapts_new_snapshot_contract tests/unit/test_fastapi_app.py::test_market_regime_page_renders_snapshot -v
```

Expected: both PASS.

- [ ] **Step 4: Run full market regime suite**

```
python -m pytest tests/unit/test_market_regime_analyzer.py tests/unit/test_market_regime.py tests/integration/test_market_regime_fetcher.py tests/unit/test_market_regime_massive.py tests/unit/test_fastapi_app.py -q -k "market_regime or massive"
```

Expected: all pass.

- [ ] **Step 5: Commit Gap 3**

```
git add src/agency/views/market_regime.py src/agency/templates/market_regime.html tests/unit/test_fastapi_app.py
git commit -m "feat(market-regime): expose state/quadrant/flow/boost in sector card; fix template markup"
```

---

## Bonus — RS-Momentum Formula Fix

The current RS-Momentum uses `(5d_excess - 20d_excess)` as a proxy. The spec formula is `rs_ratio_today − rs_ratio_5d_ago`, which requires the 20D return ending 5 sessions ago.

### Task 11: Add `return_20d_pct_5d_ago` to `metrics.py` and `snapshot.py`

**Files:**
- Modify: `src/agency/market_regime/metrics.py`
- Modify: `src/agency/market_regime/snapshot.py`

- [ ] **Step 1: Add `_window_return_offset` helper to `metrics.py`**

Add after `_window_return`:

```python
def _window_return_offset(closes: Sequence[float], sessions: int, offset: int) -> float | None:
    """Return the ``sessions``-window return ending ``offset`` bars before the latest.

    Example: offset=5 → return ending 5 sessions ago (close[-6] / close[-26] - 1).
    """
    if len(closes) < sessions + offset + 1:
        return None
    tail = closes[: len(closes) - offset]
    return _window_return(tail, sessions, None)
```

- [ ] **Step 2: Add `return_20d_pct_5d_ago` to `_metric()`**

In `_metric()`, extend the returned dict:

```python
"return_20d_pct_5d_ago": _window_return_offset(usable_closes, 20, 5),
```

Place it after `"return_60d_pct": ...`.

- [ ] **Step 3: Update `_sector_map()` in `snapshot.py`**

Replace the existing `rs_momentum` computation:

```python
# Old (proxy formula):
rs_momentum = ((_float(metric.get("return_5d_pct")) or 0.0) - spy_5d) - rs_ratio

# New (spec formula):
spy_20d_5d_ago = _float(_mapping(metrics.get("SPY")).get("return_20d_pct_5d_ago")) or 0.0
rs_ratio_5d_ago = (_float(metric.get("return_20d_pct_5d_ago")) or 0.0) - spy_20d_5d_ago
rs_momentum = rs_ratio - rs_ratio_5d_ago
```

The `spy_20d_5d_ago` value only needs to be fetched once — move it outside the per-ticker loop (alongside `spy_20d` and `spy_5d`):

```python
def _sector_map(metrics, policy):
    spy = _mapping(metrics.get("SPY"))
    spy_20d = _float(spy.get("return_20d_pct")) or 0.0
    spy_20d_5d_ago = _float(spy.get("return_20d_pct_5d_ago")) or 0.0
    result = {}
    for ticker in SECTOR_ETFS:
        metric = _mapping(metrics.get(ticker))
        if not metric:
            continue
        rs_ratio = (_float(metric.get("return_20d_pct")) or 0.0) - spy_20d
        rs_ratio_5d_ago = (_float(metric.get("return_20d_pct_5d_ago")) or 0.0) - spy_20d_5d_ago
        rs_momentum = rs_ratio - rs_ratio_5d_ago
        ...
```

Remove the now-unused `spy_5d` variable from `_sector_map()` (previously `spy_5d = _float(_mapping(metrics.get("SPY")).get("return_5d_pct")) or 0.0`).

- [ ] **Step 4: Run the full suite**

```
python -m pytest tests/ -q --tb=short 2>&1 | tail -10
```

Expected: all tests still pass. If `test_snapshot_pre_market_with_state_files` fails because the fixture has < 26 bars, update the fixture to provide 30 bars for each ETF:

```python
# In tests/unit/test_market_regime_analyzer.py, find _make_bars() or similar fixture
# Ensure it generates at least 30 rows so return_20d_pct_5d_ago can be computed
```

If no such fixture exists and the test still passes, nothing to change.

- [ ] **Step 5: Commit bonus**

```
git add src/agency/market_regime/metrics.py src/agency/market_regime/snapshot.py
git commit -m "fix(market-regime): use spec RS-Momentum formula (20D return ending 5d ago)"
```

---

## Final Verification

- [ ] **Run the complete market regime test suite**

```
python -m pytest tests/unit/test_market_regime_analyzer.py tests/unit/test_market_regime.py tests/integration/test_market_regime_fetcher.py tests/unit/test_market_regime_massive.py tests/unit/test_fastapi_app.py -v --tb=short
```

Expected: all pass.

- [ ] **Verify line counts**

```
python -c "
import os
for root, dirs, files in os.walk('src/agency/market_regime'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            n = len(open(path).readlines())
            status = '✅' if n <= 300 else '❌'
            print(f'{status} {n:3d}  {path}')
"
```

Expected: all ✅.

- [ ] **Confirm AC 4 (all metrics have title tooltips) by checking rendered HTML**

```
python -m pytest tests/unit/test_fastapi_app.py::test_market_regime_page_renders_snapshot -v -s
```

Expected: PASS with `title="` appearing in response (existing assertion).

---

## Self-Review Against Spec §13 Acceptance Criteria

| AC | Plan coverage |
|---|---|
| AC 1: 25 unit tests | Task 5 adds `test_macro_tiles_are_enriched`; Tasks 1/3 add 10 new tests; all 26 original pass |
| AC 2: 4 integration tests | Existing 4 pass; 6 more added in Task 3 |
| AC 3: 13 keys for empty/pre/intraday | Unchanged by this plan — already met |
| AC 4: every metric has title tooltip | Task 8 (macro tiles) + Task 10 (sector card) add per-metric tooltips from `_TOOLTIPS` dict |
| AC 5: FRED failure → NEUTRAL + WARN | Unchanged — already met |
| AC 6: RegimePolicy env loading | Unchanged — already met |
| AC 7: no file > 300 lines | Final verification step confirms |
| AC 8: no HTTP in analyzer.py | `massive.py` is new; `analyzer.py` untouched |

**Gap 1 (Massive API):** Tasks 1–4 ✅  
**Gap 2 (Macro tiles):** Tasks 5–8 ✅  
**Gap 3 (Sector card):** Tasks 9–10 ✅  
**Bonus (RS-Momentum):** Task 11 ✅
