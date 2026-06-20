# Market Regime Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved Market Regime Agent redesign as a tested top-down context layer with regime, volatility, macro, sector, per-stock, portfolio, and dashboard outputs.

**Architecture:** Add a new `src/agency/market_regime/` module and keep `src/agency/runtime/market_regime.py` unchanged while the new implementation is introduced. The fetcher writes provider state files and never raises; the analyzer is pure computation with no I/O or HTTP; the snapshot layer normalizes state into the new 13-key dashboard/consumer contract.

**Tech Stack:** Python 3.12, FastAPI/Jinja2, Massive/Polygon-compatible HTTP state fetches, `fredapi>=0.5.1`, pytest, Ruff, existing agency view/shared dashboard helpers.

---

## File Map

- Create `src/agency/market_regime/__init__.py`: public exports for `RegimePolicy`, `build_regime_snapshot`, `refresh_regime_state`, and scheduler helpers.
- Create `src/agency/market_regime/policy.py`: frozen `RegimePolicy` dataclass, env loading, optional local JSON override loading.
- Create `src/agency/market_regime/analyzer.py`: pure regime, volatility, macro, sector, flow, per-stock, transition, drift, and schema assembly helpers. No file I/O, no HTTP imports.
- Create `src/agency/market_regime/fetcher.py`: state-file I/O and provider fetch wrappers for Massive/FRED/yfinance fallback. Failures return `FetchSummary.issues`.
- Create `src/agency/market_regime/snapshot.py`: `build_regime_snapshot()` orchestration, prior-regime persistence, portfolio mapping, data-source quality rows.
- Create `src/agency/market_regime/scheduler.py`: APScheduler hook registration and refresh mode selection.
- Create `research/config/ticker-sector-map.json`: initial committed ticker-to-sector map for the agency universe starter set.
- Modify `pyproject.toml`: add only `fredapi>=0.5.1`.
- Modify `src/agency/views/market_regime.py`: use the new snapshot builder while preserving broker status helper contracts used by existing tests/views.
- Modify `src/agency/templates/market_regime.html`: replace the old read-only page with the approved V3 BLUF, KPI, portfolio, sector, market, macro, drift, and collapsible source-quality layout.
- Modify `docs/TOOLTIP_REGISTRY.md`: add every new Market Regime tooltip from the spec.
- Create `tests/unit/test_market_regime_analyzer.py`: pure analyzer and snapshot schema tests.
- Create `tests/integration/test_market_regime_fetcher.py`: state roundtrip, cache, failure, and grouped breadth tests.

## Contract Guardrails

- Do not modify `src/agency/runtime/market_regime.py`.
- Do not import `requests`, `urllib`, `httpx`, `fredapi`, `yfinance`, or agency provider clients inside `src/agency/market_regime/analyzer.py`.
- Use `datetime.now(UTC)`, never `datetime.utcnow()`.
- Use `from __future__ import annotations` at the top of every new Python file.
- Keep each `src/agency/market_regime/*.py` file at or under 300 lines.
- Fetchers never raise to callers; every external/provider failure becomes an issue row.
- Intraday drift is advisory only and must not change the full-day regime or conviction modifiers.

---

### Task 1: Policy Contract

**Files:**
- Create: `src/agency/market_regime/__init__.py`
- Create: `src/agency/market_regime/policy.py`
- Test: `tests/unit/test_market_regime_analyzer.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing policy tests**

Add these tests to `tests/unit/test_market_regime_analyzer.py`:

```python
from __future__ import annotations

import json

from agency.market_regime.policy import RegimePolicy


def test_policy_defaults_match_spec() -> None:
    policy = RegimePolicy()

    assert policy.risk_off_spy_5d_pct == -1.5
    assert policy.risk_off_breadth_pct == 35.0
    assert policy.risk_off_tlt_5d_pct == 1.5
    assert policy.risk_on_spy_5d_pct == 1.0
    assert policy.risk_on_qqq_5d_pct == 0.0
    assert policy.risk_on_breadth_pct == 55.0
    assert policy.risk_on_vol_cap == 20.0
    assert policy.volatile_vol_threshold == 25.0
    assert policy.volatile_abs_move_pct == 2.0
    assert policy.rotating_sector_spread == 1.5
    assert policy.vix_calm == 20.0
    assert policy.vix_high == 35.0
    assert policy.cmf_period == 14
    assert policy.risk_on_modifier == 0.03
    assert policy.risk_off_modifier == -0.08
    assert policy.elevated_vol_size_multiplier == 0.75
    assert policy.high_vol_size_multiplier == 0.50


def test_policy_loads_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("AGENCY_RISK_OFF_SPY_5D_PCT", "-2.25")
    monkeypatch.setenv("AGENCY_INTRADAY_REFRESH_INTERVAL_MINUTES", "30")

    policy = RegimePolicy.from_env()

    assert policy.risk_off_spy_5d_pct == -2.25
    assert policy.intraday_refresh_interval_minutes == 30


def test_policy_env_overrides_local_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "portfolio-policy.local.json"
    path.write_text(
        json.dumps({"market_regime": {"risk_off_spy_5d_pct": -2.0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENCY_RISK_OFF_SPY_5D_PCT", "-3.0")

    policy = RegimePolicy.from_env(config_path=path)

    assert policy.risk_off_spy_5d_pct == -3.0
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py::test_policy_defaults_match_spec tests\unit\test_market_regime_analyzer.py::test_policy_loads_env_overrides tests\unit\test_market_regime_analyzer.py::test_policy_env_overrides_local_json -q
```

Expected: fail because `agency.market_regime.policy` does not exist yet.

- [ ] **Step 3: Implement `RegimePolicy`**

Create `src/agency/market_regime/policy.py` with:

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Self


@dataclass(frozen=True)
class RegimePolicy:
    risk_off_spy_5d_pct: float = -1.5
    risk_off_breadth_pct: float = 35.0
    risk_off_tlt_5d_pct: float = 1.5
    risk_on_spy_5d_pct: float = 1.0
    risk_on_qqq_5d_pct: float = 0.0
    risk_on_breadth_pct: float = 55.0
    risk_on_vol_cap: float = 20.0
    volatile_vol_threshold: float = 25.0
    volatile_abs_move_pct: float = 2.0
    rotating_sector_spread: float = 1.5
    rotating_breadth_min: float = 40.0
    rotating_breadth_max: float = 65.0
    vix_calm: float = 20.0
    vix_elevated: float = 25.0
    vix_high: float = 35.0
    yield_curve_inverted: float = 0.0
    credit_spread_stress_delta_bps: float = 50.0
    rate_spike_delta_bps: float = 20.0
    macro_risk_appetite_curve: float = 1.0
    cmf_positive: float = 0.0
    cmf_negative: float = 0.0
    cmf_period: int = 14
    risk_on_modifier: float = 0.03
    risk_off_modifier: float = -0.08
    volatile_modifier: float = -0.05
    neutral_modifier: float = 0.0
    rotating_modifier: float = 0.0
    advancing_confirmed_boost: float = 0.03
    advancing_unconfirmed_boost: float = 0.01
    declining_confirmed_penalty: float = -0.05
    declining_unconfirmed_penalty: float = -0.02
    calm_size_multiplier: float = 1.0
    elevated_vol_size_multiplier: float = 0.75
    high_vol_size_multiplier: float = 0.50
    intraday_refresh_interval_minutes: int = 60
    fred_cache_hours: int = 24
    etf_bars_lookback_days: int = 65

    @classmethod
    def from_env(cls, *, config_path: Path | None = None) -> Self:
        policy = cls()
        local = _read_local_policy(config_path)
        if local:
            policy = replace(policy, **_coerce_overrides(policy, local))
        env_overrides = {
            field.name: os.environ[env_name]
            for field in fields(policy)
            if (env_name := f"AGENCY_{field.name.upper()}") in os.environ
        }
        if env_overrides:
            policy = replace(policy, **_coerce_overrides(policy, env_overrides))
        return policy


def _read_local_policy(path: Path | None) -> dict[str, object]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("market_regime", payload)
    return nested if isinstance(nested, dict) else {}


def _coerce_overrides(policy: RegimePolicy, raw: dict[str, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    fields_by_name = {field.name: field for field in fields(policy)}
    for name, value in raw.items():
        field = fields_by_name.get(str(name))
        if field is None:
            continue
        current = getattr(policy, field.name)
        result[field.name] = int(value) if isinstance(current, int) else float(value)
    return result
```

Create `src/agency/market_regime/__init__.py` with:

```python
from __future__ import annotations

from agency.market_regime.policy import RegimePolicy

__all__ = ["RegimePolicy"]
```

Add `fredapi>=0.5.1` to `pyproject.toml` dependencies and no other dependency.

- [ ] **Step 4: Run policy tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py::test_policy_defaults_match_spec tests\unit\test_market_regime_analyzer.py::test_policy_loads_env_overrides tests\unit\test_market_regime_analyzer.py::test_policy_env_overrides_local_json -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml src/agency/market_regime/__init__.py src/agency/market_regime/policy.py tests/unit/test_market_regime_analyzer.py
git commit -m "feat(market-regime): add policy contract"
```

### Task 2: Pure Analyzer

**Files:**
- Create: `src/agency/market_regime/analyzer.py`
- Test: `tests/unit/test_market_regime_analyzer.py`

- [ ] **Step 1: Add analyzer tests**

Append tests that call pure functions only:

```python
from agency.market_regime.analyzer import (
    analyze_intraday_drift,
    classify_macro_tilt,
    classify_market_backdrop,
    classify_sector_state,
    classify_vol_regime,
    detect_regime_change,
    per_stock_context,
)


def test_risk_off_on_negative_spy() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=-1.6,
        qqq_5d_pct=0.2,
        breadth_pct=70.0,
        spy_vol_10d=15.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.2,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_OFF"
    assert result["conviction_modifier"] == -0.08


def test_risk_off_on_low_breadth() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=0.1,
        qqq_5d_pct=0.1,
        breadth_pct=34.0,
        spy_vol_10d=12.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_OFF"


def test_risk_off_on_bond_flight() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=0.0,
        qqq_5d_pct=0.0,
        breadth_pct=60.0,
        spy_vol_10d=12.0,
        tlt_5d_pct=1.6,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_OFF"


def test_volatile_regime() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=2.1,
        qqq_5d_pct=2.0,
        breadth_pct=50.0,
        spy_vol_10d=26.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "VOLATILE"
    assert result["conviction_modifier"] == -0.05


def test_risk_on_all_conditions() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=1.2,
        qqq_5d_pct=0.1,
        breadth_pct=56.0,
        spy_vol_10d=19.0,
        tlt_5d_pct=-0.2,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_ON"


def test_neutral_fallthrough() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=0.2,
        qqq_5d_pct=-0.1,
        breadth_pct=50.0,
        spy_vol_10d=18.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.2,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "NEUTRAL"


def test_vol_regime_calm_and_high() -> None:
    assert classify_vol_regime(19.9, RegimePolicy())["vol_regime"] == "CALM"
    assert classify_vol_regime(35.1, RegimePolicy())["vol_regime"] == "HIGH"


def test_macro_tilt_defensive_and_risk_appetite() -> None:
    policy = RegimePolicy()
    assert classify_macro_tilt(-0.1, 10.0, -0.5, policy)["macro_tilt"] == "DEFENSIVE"
    assert classify_macro_tilt(1.2, -11.0, -0.5, policy)["macro_tilt"] == "RISK_APPETITE"


def test_sector_quadrants_and_boosts() -> None:
    policy = RegimePolicy()
    assert classify_sector_state(1.0, 0.2, 0.1, "UP", policy)["state"] == "ADVANCING"
    assert classify_sector_state(1.0, -0.2, 0.1, "DOWN", policy)["state"] == "TOPPING"
    assert classify_sector_state(-1.0, -0.2, -0.1, "DOWN", policy)["state"] == "DECLINING"
    assert classify_sector_state(-1.0, 0.2, 0.1, "UP", policy)["state"] == "BASING"
    assert classify_sector_state(1.0, 0.2, 0.1, "UP", policy)["conviction_boost"] == 0.03
    assert classify_sector_state(-1.0, -0.2, -0.1, "DOWN", policy)["conviction_boost"] == -0.05


def test_per_stock_context_lookup() -> None:
    sector_map = {"XLK": {"state": "ADVANCING", "bias": "TAILWIND", "conviction_boost": 0.03}}
    result = per_stock_context(["AAPL", "MSFT"], {"AAPL": "XLK"}, sector_map)
    assert result["AAPL"]["sector"] == "XLK"
    assert result["AAPL"]["conviction_boost"] == 0.03
    assert result["MSFT"]["sector"] == "UNKNOWN"


def test_regime_change_detected() -> None:
    result = detect_regime_change(
        {"market_backdrop": {"regime": "NEUTRAL"}, "sector_map": {"XLK": {"state": "TOPPING"}}},
        {"market_backdrop": {"regime": "RISK_OFF"}, "sector_map": {"XLK": {"state": "DECLINING"}}},
    )
    assert result["regime_changed"] is True
    assert result["prior_regime"] == "NEUTRAL"
    assert result["sector_transitions"] == [{"sector": "XLK", "from_state": "TOPPING", "to_state": "DECLINING"}]


def test_no_regime_change() -> None:
    result = detect_regime_change(
        {"market_backdrop": {"regime": "RISK_ON"}, "sector_map": {"XLK": {"state": "ADVANCING"}}},
        {"market_backdrop": {"regime": "RISK_ON"}, "sector_map": {"XLK": {"state": "ADVANCING"}}},
    )
    assert result["regime_changed"] is False


def test_intraday_drift_computed() -> None:
    result = analyze_intraday_drift(
        {"SPY": {"price": 101.0, "prior_close": 100.0}, "XLK": {"price": 103.0, "prior_close": 100.0}},
        morning_rank=["XLK", "SPY"],
    )
    assert result["spy_session_return_pct"] == 1.0
    assert result["sectors"]["XLK"]["vs_spy_pct"] == 2.0
```

- [ ] **Step 2: Run failing analyzer tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py -q
```

Expected: fail because analyzer functions do not exist yet.

- [ ] **Step 3: Implement pure analyzer**

Create `src/agency/market_regime/analyzer.py` with functions matching the tests. Use small helpers:

```python
def classify_market_backdrop(...): ...
def classify_vol_regime(vix_value: float | None, policy: RegimePolicy) -> dict[str, object]: ...
def classify_macro_tilt(...): ...
def classify_sector_state(...): ...
def per_stock_context(...): ...
def detect_regime_change(...): ...
def analyze_intraday_drift(...): ...
```

Implementation details:
- Convert thresholds in policy from percentage points to direct percent comparisons; inputs are percentage points, not fractions.
- Regime rule order is `DATA_LIMITED`, `RISK_OFF`, `VOLATILE`, `ROTATING`, `RISK_ON`, `NEUTRAL`.
- `classify_sector_state()` returns `state`, `quadrant`, `bias`, `flow_confirmed`, `flow_bearish`, and `conviction_boost`.
- `analyze_intraday_drift()` returns `None` when fewer than SPY plus one sector are available.

- [ ] **Step 4: Run analyzer tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py -q
```

Expected: all analyzer and policy tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/market_regime/analyzer.py tests/unit/test_market_regime_analyzer.py
git commit -m "feat(market-regime): add pure analyzer"
```

### Task 3: Fetcher State Layer

**Files:**
- Create: `src/agency/market_regime/fetcher.py`
- Test: `tests/integration/test_market_regime_fetcher.py`

- [ ] **Step 1: Write fetcher integration tests**

Create `tests/integration/test_market_regime_fetcher.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agency.market_regime.fetcher import (
    FetchSummary,
    grouped_daily_breadth,
    load_state_json,
    refresh_fred_series,
    write_state_json,
)
from agency.market_regime.policy import RegimePolicy


def test_etf_bars_roundtrip(tmp_path) -> None:
    path = tmp_path / "etf_bars.json"
    payload = {"SPY": [{"date": "2026-05-28", "close": 100.0}]}

    write_state_json(path, payload)

    assert load_state_json(path) == payload


def test_fred_cache_hit(tmp_path) -> None:
    cache = tmp_path / "macro_fred.json"
    now = datetime.now(UTC)
    write_state_json(cache, {"generated_at": now.isoformat(), "series": {"VIXCLS": [{"value": 18.0}]}})

    result = refresh_fred_series(cache, policy=RegimePolicy(), now=now + timedelta(hours=1))

    assert result.used_cache is True
    assert result.issues == []


def test_fred_failure_non_blocking(tmp_path) -> None:
    def broken_client(_: str):
        raise RuntimeError("fred down")

    result = refresh_fred_series(
        tmp_path / "macro_fred.json",
        policy=RegimePolicy(),
        now=datetime.now(UTC),
        series_client=broken_client,
    )

    assert isinstance(result, FetchSummary)
    assert result.ok is False
    assert result.issues


def test_grouped_daily_breadth_coverage() -> None:
    result = grouped_daily_breadth(
        [
            {"ticker": "AAA", "open": 10.0, "close": 11.0},
            {"ticker": "BBB", "open": 10.0, "close": 9.0},
            {"ticker": "CCC", "open": 10.0, "close": 12.0},
        ]
    )

    assert result["total"] == 3
    assert result["advancers"] == 2
    assert result["decliners"] == 1
    assert result["advancers_pct"] == 66.67
```

- [ ] **Step 2: Run failing fetcher tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\integration\test_market_regime_fetcher.py -q
```

Expected: fail because fetcher functions do not exist.

- [ ] **Step 3: Implement fetcher**

Create `src/agency/market_regime/fetcher.py`:
- `FetchSummary(ok: bool, issues: list[str], used_cache: bool = False, updated_files: list[str] = None)`
- `load_state_json(path: Path) -> dict[str, object]`
- `write_state_json(path: Path, payload: Mapping[str, object]) -> None`
- `refresh_fred_series(path, policy, now, series_client=None) -> FetchSummary`
- `grouped_daily_breadth(rows) -> dict[str, object]`
- `refresh_regime_state(state_dir, mode, policy=None) -> FetchSummary`

Provider wrapper behavior:
- If FRED cache is younger than `policy.fred_cache_hours`, return cache hit and do not call the client.
- If FRED client fails, return `ok=False` and write no broken cache.
- `refresh_regime_state()` creates `state_dir` and returns a summary even when provider keys are missing.

- [ ] **Step 4: Run fetcher tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\integration\test_market_regime_fetcher.py -q
```

Expected: all 4 integration tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/market_regime/fetcher.py tests/integration/test_market_regime_fetcher.py
git commit -m "feat(market-regime): add state fetcher shell"
```

### Task 4: Snapshot Builder and Sector Map

**Files:**
- Create: `src/agency/market_regime/snapshot.py`
- Modify: `src/agency/market_regime/__init__.py`
- Create: `research/config/ticker-sector-map.json`
- Test: `tests/unit/test_market_regime_analyzer.py`

- [ ] **Step 1: Add snapshot tests**

Append tests:

```python
from datetime import UTC, datetime
from pathlib import Path

from agency.market_regime.snapshot import build_regime_snapshot


REQUIRED_KEYS = {
    "schema_version",
    "generated_at",
    "snapshot_type",
    "data_as_of",
    "bluf",
    "market_backdrop",
    "sector_map",
    "per_stock_context",
    "breadth",
    "macro",
    "benchmarks",
    "intraday_drift",
    "portfolio_context",
    "data_sources",
}


def test_snapshot_schema_has_required_keys(tmp_path: Path) -> None:
    snapshot = build_regime_snapshot(
        state_dir=tmp_path,
        generated_at="2026-05-29T12:00:00+00:00",
        refresh_mode="manual",
    )

    assert REQUIRED_KEYS <= set(snapshot)


def test_data_limited_on_empty_inputs(tmp_path: Path) -> None:
    snapshot = build_regime_snapshot(state_dir=tmp_path, generated_at="2026-05-29T12:00:00+00:00")

    assert snapshot["market_backdrop"]["regime"] == "DATA_LIMITED"
    assert snapshot["market_backdrop"]["confidence"] == 0.0
    assert snapshot["data_sources"][0]["status"] in {"WARN", "BLOCK"}


def test_snapshot_pre_market_with_state_files(tmp_path: Path) -> None:
    etf_bars = {
        "SPY": [{"date": "2026-05-28", "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0, "volume": 1000}],
        "QQQ": [{"date": "2026-05-28", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000}],
        "XLK": [{"date": "2026-05-28", "open": 100.0, "high": 108.0, "low": 99.0, "close": 107.0, "volume": 1000}],
    }
    (tmp_path / "etf_bars.json").write_text(json.dumps(etf_bars), encoding="utf-8")
    (tmp_path / "grouped_daily.json").write_text(json.dumps({"advancers_pct": 60.0, "total": 8000}), encoding="utf-8")
    (tmp_path / "macro_fred.json").write_text(json.dumps({"series": {"VIXCLS": [{"value": 18.0}]}}), encoding="utf-8")

    snapshot = build_regime_snapshot(
        state_dir=tmp_path,
        generated_at="2026-05-29T12:00:00+00:00",
        refresh_mode="pre_market",
    )

    assert snapshot["snapshot_type"] == "pre_market"
    assert snapshot["data_as_of"] == "2026-05-28"
    assert "XLK" in snapshot["sector_map"]
```

- [ ] **Step 2: Run failing snapshot tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py::test_snapshot_schema_has_required_keys tests\unit\test_market_regime_analyzer.py::test_data_limited_on_empty_inputs tests\unit\test_market_regime_analyzer.py::test_snapshot_pre_market_with_state_files -q
```

Expected: fail because `snapshot.py` does not exist.

- [ ] **Step 3: Implement snapshot builder**

Create `src/agency/market_regime/snapshot.py`:
- Read `etf_bars.json`, `intraday_bars.json`, `grouped_daily.json`, `macro_fred.json`, `macro_proxies.json`, and `last_regime.json`.
- Return the 14 top-level keys listed in this plan; the spec says 13 but lists 14 including `data_sources`, so implement the listed contract.
- Empty/missing state returns `DATA_LIMITED` and never raises.
- For full snapshots, compute benchmark rows, breadth, macro, sector map, per-stock context, BLUF, portfolio context, data source rows.
- For intraday snapshots, preserve prior regime/sector state where possible and compute `intraday_drift` as advisory.
- Persist `last_regime.json` only for `pre_market`, `post_market`, or `manual` when state has enough data; do not persist empty `DATA_LIMITED` over a usable prior state.

Create `research/config/ticker-sector-map.json` with the excerpt in the spec plus enough common agency tickers to avoid "sector not reported" for mega-cap candidates.

Update `src/agency/market_regime/__init__.py`:

```python
from __future__ import annotations

from agency.market_regime.policy import RegimePolicy
from agency.market_regime.snapshot import build_regime_snapshot

__all__ = ["RegimePolicy", "build_regime_snapshot"]
```

- [ ] **Step 4: Run snapshot tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py -q
```

Expected: all unit tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/market_regime/__init__.py src/agency/market_regime/snapshot.py research/config/ticker-sector-map.json tests/unit/test_market_regime_analyzer.py
git commit -m "feat(market-regime): build snapshot contract"
```

### Task 5: Scheduler Hook

**Files:**
- Create: `src/agency/market_regime/scheduler.py`
- Test: `tests/unit/test_market_regime_analyzer.py`

- [ ] **Step 1: Add scheduler test**

Append:

```python
from agency.market_regime.scheduler import schedule_regime_refresh


class RecordingScheduler:
    def __init__(self) -> None:
        self.jobs = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_schedule_regime_refresh_registers_three_jobs(tmp_path: Path) -> None:
    scheduler = RecordingScheduler()

    schedule_regime_refresh(scheduler, tmp_path, RegimePolicy())

    assert [job["kwargs"]["mode"] for job in scheduler.jobs] == ["pre_market", "intraday", "post_market"]
    assert all(job["trigger"] == "cron" for job in scheduler.jobs)
```

- [ ] **Step 2: Run failing scheduler test**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py::test_schedule_regime_refresh_registers_three_jobs -q
```

Expected: fail because scheduler module does not exist.

- [ ] **Step 3: Implement scheduler**

Create `src/agency/market_regime/scheduler.py`:
- `schedule_regime_refresh(scheduler, state_dir, policy)` registers pre-market 07:00 ET, hourly 09:00-16:00 ET, and post-market 16:30 ET jobs.
- Job functions call `refresh_regime_state()` then `build_regime_snapshot()`.
- Use the policy interval for intraday only when APScheduler supports interval triggers; keep cron hourly as the spec baseline for this task.

- [ ] **Step 4: Run scheduler test**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py::test_schedule_regime_refresh_registers_three_jobs -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/market_regime/scheduler.py tests/unit/test_market_regime_analyzer.py
git commit -m "feat(market-regime): add refresh scheduler hooks"
```

### Task 6: View Wiring

**Files:**
- Modify: `src/agency/views/market_regime.py`
- Test: existing route tests that import or monkeypatch `agency.views.market_regime.load_market_regime_snapshot`

- [ ] **Step 1: Add/adjust view contract tests**

Find view tests:

```powershell
rg -n "market_regime_context|load_market_regime_snapshot|/market-regime" tests\unit
```

Ensure tests verify:
- `market_regime_context()` returns the new snapshot keys.
- `summary.as_of_label` is still formatted for the topbar.
- Existing `broker_status_context()` tests still pass unchanged.
- Monkeypatching `agency.views.market_regime.load_market_regime_snapshot` still works, so route tests do not need to import the new module directly.

- [ ] **Step 2: Run current market-regime view tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime.py tests\unit\test_fastapi_app.py -q
```

Expected: failures are allowed before wiring if tests expect old shape.

- [ ] **Step 3: Wire new snapshot**

Modify `src/agency/views/market_regime.py`:
- Import `load_market_regime_snapshot` from `agency.market_regime.snapshot` or define a compatibility alias that calls `build_regime_snapshot(state_dir=Path("research/state/market_regime"))`.
- Preserve `_market_regime_context_cache`, `broker_status_context()`, and helper names.
- Add compatibility summary fields for the base template: `active_nav`, `summary.topbar_label`, `summary.as_of_label`, and `data_health`.
- Do not remove broker status helpers; other routes use them.

- [ ] **Step 4: Run view tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime.py tests\unit\test_fastapi_app.py -q
```

Expected: pass or only fail on template assertions that Task 7 owns.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/market_regime.py tests/unit/test_market_regime.py tests/unit/test_fastapi_app.py
git commit -m "feat(market-regime): wire redesigned snapshot to view"
```

### Task 7: Dashboard and Tooltips

**Files:**
- Modify: `src/agency/templates/market_regime.html`
- Modify: `docs/TOOLTIP_REGISTRY.md`
- Test: route/template tests and static grep checks

- [ ] **Step 1: Add dashboard assertions**

Add tests asserting rendered HTML contains:
- `BLUF`
- `Risk regime`
- `Vol`
- `Portfolio Context`
- `Sector Leadership`
- `Macro Context`
- `Data Sources`
- `title=` on KPI, sector, macro, and data-source metric elements.

- [ ] **Step 2: Run failing dashboard tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime.py tests\unit\test_fastapi_app.py -q
```

Expected: fail until template is updated.

- [ ] **Step 3: Replace template with V3 layout**

Modify `src/agency/templates/market_regime.html`:
- Remove old unrelated navigation buttons.
- Use BLUF banner, 4 KPI cards, portfolio context columns, sector cards, benchmark row, macro tiles, intraday drift, and collapsible data sources.
- Add `title` tooltips for every metric listed in the spec.
- Keep Jinja2 only; no frontend framework.

Update `docs/TOOLTIP_REGISTRY.md` with a `Market Regime` section containing every tooltip in the spec, using the exact UI label and exact tooltip text.

- [ ] **Step 4: Run dashboard tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime.py tests\unit\test_fastapi_app.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/templates/market_regime.html docs/TOOLTIP_REGISTRY.md tests/unit/test_market_regime.py tests/unit/test_fastapi_app.py
git commit -m "feat(market-regime): redesign dashboard"
```

### Task 8: Final Verification and Cleanup

**Files:**
- All files changed above.

- [ ] **Step 1: Run targeted tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_market_regime_analyzer.py tests\integration\test_market_regime_fetcher.py tests\unit\test_market_regime.py tests\unit\test_fastapi_app.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full unit safety pass**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\ -x --tb=short -q
```

Expected: all unit tests pass.

- [ ] **Step 3: Run Ruff on touched files**

Run:

```powershell
.\.venv\Scripts\python -m ruff check src/agency/market_regime src/agency/views/market_regime.py tests/unit/test_market_regime_analyzer.py tests/integration/test_market_regime_fetcher.py
```

Expected: no Ruff violations.

- [ ] **Step 4: Run guardrail scans**

Run:

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; bad=[p for p in Path('src/agency/market_regime').glob('*.py') if len(p.read_text(encoding='utf-8').splitlines())>300]; raise SystemExit(f'Files over 300 lines: {bad}' if bad else 'line cap ok')"
```

Expected: `line cap ok`.

Run:

```powershell
rg -n "requests|urllib|httpx|fredapi|yfinance|datetime\.utcnow" src\agency\market_regime\analyzer.py
```

Expected: no output.

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Optional browser QA when server is running**

If the local server is running, open `/market-regime` and verify:
- BLUF reads first.
- Data source state is visible but collapsed.
- Each metric has an actual browser tooltip.
- No old "read-only cached data only" wording remains when the new state source is active.
- No overlapping text at desktop width.

- [ ] **Step 6: Final commit**

If Task 8 produced fixes:

```powershell
git add src/agency/market_regime src/agency/views/market_regime.py src/agency/templates/market_regime.html tests docs research/config pyproject.toml
git commit -m "test(market-regime): verify redesigned agent"
```

## Self-Review

- Spec coverage: Tasks 1-7 cover policy, fetcher, analyzer, snapshot, scheduler, ticker-sector map, view, template, tooltips, and tests. Portfolio manager, selection pipeline, and circuit-breaker wiring remain intentionally out of scope because the spec marks them as separate tickets.
- Placeholder scan: The plan avoids `TBD`, generic "add tests" wording, and undefined future work in task steps. The only intentionally abstract implementation step is the pure analyzer internals, bounded by exact tests and exact function names.
- Type consistency: `RegimePolicy`, `build_regime_snapshot`, `refresh_regime_state`, `FetchSummary`, `classify_*`, `per_stock_context`, `detect_regime_change`, and `analyze_intraday_drift` are named consistently across tasks.
