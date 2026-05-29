# Portfolio Manager Redesign — Implementation Plan

---

## ⚡ Codex Initialization Prompt

> Copy this block verbatim as your first message to start a Codex session for this plan.

---

```
You are implementing the Portfolio Manager module for a supervised short-term equity
trading agency (1–3% weekly target, 2–5 day holds, paper trading only).

Read both of these files before writing a single line of code:
  - Spec:  docs/superpowers/specs/2026-05-29-portfolio-manager-redesign.md
  - Plan:  docs/superpowers/plans/2026-05-29-portfolio-manager-redesign.md

Your job is to implement exactly ONE task per session.
Start with the lowest-numbered task that has unchecked steps ([ ]).
When you finish a task, show me the full pytest output confirming all tests pass,
then stop and wait for me to confirm before moving to the next task.

HARD RULES — breaking any of these is a failure:
1. TDD only. Write the failing test first. Run it. Confirm it fails. Then implement.
   Never write implementation code before the test exists and is confirmed failing.
2. Use `python -m pytest <test_path> -v` for all test runs. Show the output.
3. Use exact file paths from the plan. Do not create files anywhere else.
4. Every new .py file must start with: `from __future__ import annotations`
5. Use `datetime.now(UTC)` everywhere. Never use `datetime.utcnow()`.
6. Do NOT modify:
     src/agency/services/portfolio_monitor.py
     src/agency/services/risk.py
7. Do NOT add imports from fastapi, alpaca, agency.broker, agency.views,
   or agency.app inside src/agency/portfolio/.
8. No file in src/agency/portfolio/ may exceed 250 lines.
9. Commit after each completed task using the exact commit message shown in the plan.
10. If a test fails unexpectedly, stop and explain the failure before trying to fix it.

Tech stack: Python 3.14, dataclasses, json, pathlib.Path. No new pip dependencies.
All tests use pytest with tmp_path for file I/O. No mocking frameworks.

Now: tell me which task number you are starting, then begin with Step 1 of that task.
```

---

## Overview

**Goal:** Build `src/agency/portfolio/` — a clean, self-contained portfolio manager module for a short-term investing system (1–3% weekly target, 2–5 day holds) with tiered exits, circuit breakers, and human-supervised execution.

**Architecture:** Pure functional core (`exit_rules.py`, `circuit_breaker.py`, `performance.py`) that takes plain dicts and returns plain dicts — no I/O, no DB, no broker calls inside those files. The `state.py` module owns all JSON file I/O. `snapshot.py` is the single public entry point that wires them together.

**Tech Stack:** Python 3.14, `dataclasses`, `json`, `pathlib.Path`, `datetime` (UTC-aware). No new dependencies beyond what is already in `pyproject.toml`. All tests use `pytest` with `tmp_path` for file I/O — no mocking.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/agency/portfolio/__init__.py` | Create | Re-exports public API (populated in Task 10) |
| `src/agency/portfolio/policy.py` | Create | `PortfolioPolicy` dataclass + `from_env()` loader |
| `src/agency/portfolio/state.py` | Create | Load/save all 6 JSON state files |
| `src/agency/portfolio/performance.py` | Create | Weekly + daily P&L calculation |
| `src/agency/portfolio/circuit_breaker.py` | Create | `evaluate_circuit_breakers()` |
| `src/agency/portfolio/exit_rules.py` | Create | `evaluate_exit_signal()` — all 8 signal types |
| `src/agency/portfolio/snapshot.py` | Create | `build_portfolio_snapshot()` — public entry point |
| `tests/unit/test_portfolio_manager.py` | Create | 23 unit tests (built up across Tasks 1–8) |
| `tests/integration/test_portfolio_state.py` | Create | 4 integration tests (Task 9) |

**Do NOT modify:**
- `src/agency/services/portfolio_monitor.py`
- `src/agency/services/risk.py`

---

## Task 1: PortfolioPolicy

**Files:**
- Create: `src/agency/portfolio/__init__.py`
- Create: `src/agency/portfolio/policy.py`
- Create: `tests/unit/test_portfolio_manager.py`

- [ ] **Step 1: Create the package**

```python
# src/agency/portfolio/__init__.py
# Public API — exports added in Task 10 after all submodules exist.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_portfolio_manager.py
from __future__ import annotations

from agency.portfolio.policy import PortfolioPolicy


def test_policy_defaults_match_spec() -> None:
    p = PortfolioPolicy()
    assert p.stop_loss_pct == 2.0
    assert p.take_profit_stage1_pct == 2.0
    assert p.take_profit_stage2_pct == 4.0
    assert p.trailing_stop_pct == 1.5
    assert p.trailing_stop_activates_at_pct == 1.5
    assert p.suggested_stage1_trim_pct == 0.50
    assert p.minimum_hold_days == 2
    assert p.time_stop_days == 4
    assert p.time_stop_flat_threshold_pct == 0.5
    assert p.reentry_cooldown_hours == 24
    assert p.weekly_target_pct == 3.0
    assert p.weekly_target_approach_pct == 2.5
    assert p.weekly_drawdown_limit_pct == 6.0
    assert p.daily_circuit_breaker_pct == 3.0
    assert p.max_positions == 8
    assert p.cash_reserve_pct == 20.0
    assert p.max_gross_exposure_pct == 80.0
    assert p.thesis_broken_conviction_floor == 0.40
    assert p.live_trading_enabled is False
    assert p.broker_submit_enabled is False
    assert p.allow_short_trades is False
```

- [ ] **Step 3: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py::test_policy_defaults_match_spec -v
```
Expected: `ModuleNotFoundError: No module named 'agency.portfolio'`

- [ ] **Step 4: Create `policy.py`**

```python
# src/agency/portfolio/policy.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

POLICY_PATH_ENV = "AGENCY_PORTFOLIO_POLICY_PATH"
DEFAULT_POLICY_PATH = Path("research/config/portfolio-policy.local.json")


@dataclass(frozen=True)
class PortfolioPolicy:
    # Target and drawdown
    weekly_target_pct: float = 3.0
    weekly_target_approach_pct: float = 2.5
    weekly_drawdown_limit_pct: float = 6.0
    daily_circuit_breaker_pct: float = 3.0

    # Position sizing
    max_positions: int = 8
    max_new_positions_per_day: int = 2
    default_position_pct: float = 10.0
    reduced_position_pct: float = 5.0
    max_single_name_pct: float = 20.0
    max_sector_exposure_pct: float = 30.0
    cash_reserve_pct: float = 20.0
    max_gross_exposure_pct: float = 80.0

    # Exit rules — per position
    stop_loss_pct: float = 2.0
    take_profit_stage1_pct: float = 2.0
    take_profit_stage2_pct: float = 4.0
    trailing_stop_pct: float = 1.5
    trailing_stop_activates_at_pct: float = 1.5
    suggested_stage1_trim_pct: float = 0.50

    # Thesis quality floor
    thesis_broken_conviction_floor: float = 0.40
    min_final_conviction: float = 0.65

    # Hold rules
    minimum_hold_days: int = 2
    time_stop_days: int = 4
    time_stop_flat_threshold_pct: float = 0.5
    reentry_cooldown_hours: int = 24

    # Broker / execution gates (env/file only — DB cannot override)
    live_trading_enabled: bool = False
    broker_submit_enabled: bool = False
    allow_short_trades: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PortfolioPolicy:
        if env is None:
            load_dotenv()
        values: Mapping[str, str] = os.environ if env is None else env
        d = cls()
        return cls(
            weekly_target_pct=_ef(values.get("AGENCY_WEEKLY_TARGET_PCT"), d.weekly_target_pct),
            weekly_target_approach_pct=_ef(values.get("AGENCY_WEEKLY_TARGET_APPROACH_PCT"), d.weekly_target_approach_pct),
            weekly_drawdown_limit_pct=_ef(values.get("AGENCY_WEEKLY_DRAWDOWN_LIMIT_PCT"), d.weekly_drawdown_limit_pct),
            daily_circuit_breaker_pct=_ef(values.get("AGENCY_DAILY_CIRCUIT_BREAKER_PCT"), d.daily_circuit_breaker_pct),
            max_positions=_ei(values.get("AGENCY_MAX_POSITIONS"), d.max_positions),
            max_new_positions_per_day=_ei(values.get("AGENCY_MAX_NEW_POSITIONS_PER_DAY"), d.max_new_positions_per_day),
            default_position_pct=_ef(values.get("AGENCY_DEFAULT_POSITION_PCT"), d.default_position_pct),
            reduced_position_pct=_ef(values.get("AGENCY_REDUCED_POSITION_PCT"), d.reduced_position_pct),
            max_single_name_pct=_ef(values.get("AGENCY_MAX_SINGLE_NAME_PCT"), d.max_single_name_pct),
            max_sector_exposure_pct=_ef(values.get("AGENCY_MAX_SECTOR_EXPOSURE_PCT"), d.max_sector_exposure_pct),
            cash_reserve_pct=_ef(values.get("AGENCY_CASH_RESERVE_PCT"), d.cash_reserve_pct),
            max_gross_exposure_pct=_ef(values.get("AGENCY_MAX_GROSS_EXPOSURE_PCT"), d.max_gross_exposure_pct),
            stop_loss_pct=_ef(values.get("AGENCY_STOP_LOSS_PCT"), d.stop_loss_pct),
            take_profit_stage1_pct=_ef(values.get("AGENCY_TAKE_PROFIT_STAGE1_PCT"), d.take_profit_stage1_pct),
            take_profit_stage2_pct=_ef(values.get("AGENCY_TAKE_PROFIT_STAGE2_PCT"), d.take_profit_stage2_pct),
            trailing_stop_pct=_ef(values.get("AGENCY_TRAILING_STOP_PCT"), d.trailing_stop_pct),
            trailing_stop_activates_at_pct=_ef(values.get("AGENCY_TRAILING_STOP_ACTIVATES_AT_PCT"), d.trailing_stop_activates_at_pct),
            suggested_stage1_trim_pct=_ef(values.get("AGENCY_SUGGESTED_STAGE1_TRIM_PCT"), d.suggested_stage1_trim_pct),
            thesis_broken_conviction_floor=_ef(values.get("AGENCY_THESIS_BROKEN_CONVICTION_FLOOR"), d.thesis_broken_conviction_floor),
            min_final_conviction=_ef(values.get("AGENCY_MIN_FINAL_CONVICTION"), d.min_final_conviction),
            minimum_hold_days=_ei(values.get("AGENCY_MINIMUM_HOLD_DAYS"), d.minimum_hold_days),
            time_stop_days=_ei(values.get("AGENCY_TIME_STOP_DAYS"), d.time_stop_days),
            time_stop_flat_threshold_pct=_ef(values.get("AGENCY_TIME_STOP_FLAT_THRESHOLD_PCT"), d.time_stop_flat_threshold_pct),
            reentry_cooldown_hours=_ei(values.get("AGENCY_REENTRY_COOLDOWN_HOURS"), d.reentry_cooldown_hours),
            live_trading_enabled=_eb(values.get("AGENCY_LIVE_TRADING_ENABLED"), d.live_trading_enabled),
            broker_submit_enabled=_eb(values.get("AGENCY_BROKER_SUBMIT_ENABLED"), d.broker_submit_enabled),
            allow_short_trades=_eb(values.get("AGENCY_ALLOW_SHORT_TRADES"), d.allow_short_trades),
        )

    def as_dict(self) -> dict[str, object]:
        from dataclasses import asdict
        return asdict(self)


def _ef(v: str | None, default: float) -> float:
    return float(v) if v and v.strip() else default


def _ei(v: str | None, default: int) -> int:
    return int(v) if v and v.strip() else default


def _eb(v: str | None, default: bool) -> bool:
    if v is None or not v.strip():
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 5: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py::test_policy_defaults_match_spec -v
```
Expected: `PASSED`

- [ ] **Step 6: Commit**

```
git add src/agency/portfolio/__init__.py src/agency/portfolio/policy.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): PortfolioPolicy dataclass with spec-aligned defaults"
```

---

## Task 2: State Management

**Files:**
- Create: `src/agency/portfolio/state.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add 1 test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
import json
from pathlib import Path


def test_high_water_marks_missing_file_returns_empty(tmp_path: Path) -> None:
    from agency.portfolio.state import load_high_water_marks
    marks = load_high_water_marks(tmp_path)
    assert marks == {}


def test_high_water_marks_roundtrip(tmp_path: Path) -> None:
    from agency.portfolio.state import load_high_water_marks, save_high_water_marks
    data = {"AAPL": 3.45, "MSFT": 1.20}
    save_high_water_marks(tmp_path, data)
    loaded = load_high_water_marks(tmp_path)
    assert loaded == {"AAPL": 3.45, "MSFT": 1.20}
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py::test_high_water_marks_missing_file_returns_empty tests/unit/test_portfolio_manager.py::test_high_water_marks_roundtrip -v
```
Expected: `ImportError: cannot import name 'load_high_water_marks'`

- [ ] **Step 3: Create `state.py`**

```python
# src/agency/portfolio/state.py
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


# ── File names ───────────────────────────────────────────────────────────────

_HWM_FILE = "high_water_marks.json"
_STAGE1_FILE = "stage1_executed.json"
_ENTRY_FILE = "entry_timestamps.json"
_WEEKLY_FILE = "weekly_baseline.json"
_DAILY_FILE = "daily_baseline.json"
_COOLDOWN_FILE = "reentry_cooldowns.json"


# ── High-water marks ─────────────────────────────────────────────────────────

def load_high_water_marks(state_dir: Path) -> dict[str, float]:
    """Peak unrealized P&L % per ticker. Returns {} if file missing or corrupt."""
    return _load_float_dict(state_dir / _HWM_FILE)


def save_high_water_marks(state_dir: Path, marks: dict[str, float]) -> None:
    _write_json(state_dir / _HWM_FILE, marks)


def update_high_water_marks(
    current: dict[str, float],
    broker_positions: list[dict[str, Any]],
) -> dict[str, float]:
    """Return updated marks — never mutates `current`."""
    result = dict(current)
    for pos in broker_positions:
        ticker = _ticker(pos)
        if not ticker:
            continue
        raw = pos.get("unrealized_plpc")
        if raw is None:
            continue
        pct = float(raw) * 100.0  # Alpaca returns fraction e.g. 0.023
        result[ticker] = max(result.get(ticker, pct), pct)
    return result


# ── Stage 1 trim tracking ────────────────────────────────────────────────────

def load_stage1_executed(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Returns {ticker: {executed: bool, executed_at: str}}."""
    raw = _load_json(state_dir / _STAGE1_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def save_stage1_executed(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    _write_json(state_dir / _STAGE1_FILE, data)


def is_stage1_executed(state_dir: Path, ticker: str) -> bool:
    data = load_stage1_executed(state_dir)
    return bool(data.get(ticker.upper(), {}).get("executed", False))


def mark_stage1_executed(state_dir: Path, ticker: str, executed_at: str) -> None:
    data = load_stage1_executed(state_dir)
    data[ticker.upper()] = {"executed": True, "executed_at": executed_at}
    save_stage1_executed(state_dir, data)


# ── Entry timestamps ─────────────────────────────────────────────────────────

def load_entry_timestamps(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Returns {ticker: {opened_at: str, trading_days_held: int}}."""
    raw = _load_json(state_dir / _ENTRY_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def save_entry_timestamps(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    _write_json(state_dir / _ENTRY_FILE, data)


def get_trading_days_held(state_dir: Path, ticker: str) -> int:
    data = load_entry_timestamps(state_dir)
    return int(data.get(ticker.upper(), {}).get("trading_days_held", 0))


# ── Weekly baseline ──────────────────────────────────────────────────────────

def load_weekly_baseline(state_dir: Path) -> dict[str, Any] | None:
    """Returns {week_start: str, equity: float} or None if not yet set."""
    raw = _load_json(state_dir / _WEEKLY_FILE)
    if isinstance(raw, dict) and "equity" in raw:
        return raw
    return None


def save_weekly_baseline(state_dir: Path, baseline: dict[str, Any]) -> None:
    _write_json(state_dir / _WEEKLY_FILE, baseline)


# ── Daily baseline ───────────────────────────────────────────────────────────

def load_daily_baseline(state_dir: Path) -> dict[str, Any] | None:
    """Returns {date: str, equity: float} or None if not yet set."""
    raw = _load_json(state_dir / _DAILY_FILE)
    if isinstance(raw, dict) and "equity" in raw:
        return raw
    return None


def save_daily_baseline(state_dir: Path, baseline: dict[str, Any]) -> None:
    _write_json(state_dir / _DAILY_FILE, baseline)


# ── Re-entry cooldowns ───────────────────────────────────────────────────────

def load_reentry_cooldowns(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Returns {ticker: {blocked_until: str, reason: str}}."""
    raw = _load_json(state_dir / _COOLDOWN_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def save_reentry_cooldowns(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    _write_json(state_dir / _COOLDOWN_FILE, data)


def cooldown_is_active(state_dir: Path, ticker: str, now_utc: str) -> bool:
    """Return True if a re-entry cooldown is still active for `ticker`."""
    cooldowns = load_reentry_cooldowns(state_dir)
    entry = cooldowns.get(ticker.upper())
    if not entry:
        return False
    blocked_until_str = entry.get("blocked_until", "")
    if not blocked_until_str:
        return False
    try:
        blocked_until = datetime.fromisoformat(
            blocked_until_str.replace("Z", "+00:00")
        ).astimezone(UTC)
        now = datetime.fromisoformat(now_utc.replace("Z", "+00:00")).astimezone(UTC)
        return now < blocked_until
    except ValueError:
        return False


def record_stop_loss_exit(
    state_dir: Path,
    ticker: str,
    exit_time_utc: str,
    cooldown_hours: int,
) -> None:
    """Write a re-entry cooldown for `ticker` starting at `exit_time_utc`."""
    exit_dt = datetime.fromisoformat(exit_time_utc.replace("Z", "+00:00")).astimezone(UTC)
    blocked_until = (exit_dt + timedelta(hours=cooldown_hours)).isoformat().replace("+00:00", "Z")
    cooldowns = load_reentry_cooldowns(state_dir)
    cooldowns[ticker.upper()] = {
        "blocked_until": blocked_until,
        "reason": f"Stop-loss exit recorded {exit_time_utc}",
    }
    save_reentry_cooldowns(state_dir, cooldowns)


# ── Private helpers ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_float_dict(path: Path) -> dict[str, float]:
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            result[str(k).upper()] = float(v)
    return result


def _ticker(pos: dict[str, Any]) -> str:
    return str(pos.get("symbol") or pos.get("ticker") or "").upper()
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py::test_high_water_marks_missing_file_returns_empty tests/unit/test_portfolio_manager.py::test_high_water_marks_roundtrip -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```
git add src/agency/portfolio/state.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): state.py — JSON persistence for all portfolio state files"
```

---

## Task 3: Performance Calculation

**Files:**
- Create: `src/agency/portfolio/performance.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
def test_weekly_performance_no_baseline() -> None:
    from agency.portfolio.performance import compute_weekly_performance
    from agency.portfolio.policy import PortfolioPolicy
    result = compute_weekly_performance(
        account={"equity": 100000.0},
        weekly_baseline=None,
        policy=PortfolioPolicy(),
    )
    assert result["weekly_return_pct"] is None
    assert result["baseline_equity"] is None


def test_weekly_performance_gain() -> None:
    from agency.portfolio.performance import compute_weekly_performance
    from agency.portfolio.policy import PortfolioPolicy
    result = compute_weekly_performance(
        account={"equity": 103000.0},
        weekly_baseline={"week_start": "2026-05-26", "equity": 100000.0},
        policy=PortfolioPolicy(),
    )
    assert result["weekly_return_pct"] == pytest.approx(3.0, abs=0.01)
    assert result["weekly_pl"] == pytest.approx(3000.0, abs=0.01)
    assert result["pct_of_target_reached"] == pytest.approx(100.0, abs=0.1)


def test_daily_performance_loss() -> None:
    from agency.portfolio.performance import compute_daily_performance
    result = compute_daily_performance(
        account={"equity": 97000.0},
        daily_baseline={"date": "2026-05-29", "equity": 100000.0},
    )
    assert result["daily_return_pct"] == pytest.approx(-3.0, abs=0.01)
    assert result["daily_pl"] == pytest.approx(-3000.0, abs=0.01)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "performance" -v
```
Expected: `ImportError: cannot import name 'compute_weekly_performance'`

- [ ] **Step 3: Create `performance.py`**

```python
# src/agency/portfolio/performance.py
from __future__ import annotations

from typing import Any

from agency.portfolio.policy import PortfolioPolicy


def compute_weekly_performance(
    account: dict[str, Any],
    weekly_baseline: dict[str, Any] | None,
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    """Return weekly P&L dict. All monetary values are floats; pcts are percentage points."""
    current_equity = _equity(account)
    if weekly_baseline is None or current_equity is None:
        return {
            "week_start": None,
            "baseline_equity": None,
            "current_equity": current_equity,
            "weekly_pl": None,
            "weekly_return_pct": None,
            "target_pct": policy.weekly_target_pct,
            "pct_of_target_reached": None,
        }
    baseline_equity = float(weekly_baseline.get("equity", 0.0))
    if baseline_equity <= 0:
        return {
            "week_start": weekly_baseline.get("week_start"),
            "baseline_equity": baseline_equity,
            "current_equity": current_equity,
            "weekly_pl": None,
            "weekly_return_pct": None,
            "target_pct": policy.weekly_target_pct,
            "pct_of_target_reached": None,
        }
    weekly_pl = round(current_equity - baseline_equity, 2)
    weekly_return_pct = round((current_equity / baseline_equity - 1.0) * 100.0, 4)
    pct_of_target = round(weekly_return_pct / policy.weekly_target_pct * 100.0, 2) if policy.weekly_target_pct else None
    return {
        "week_start": weekly_baseline.get("week_start"),
        "baseline_equity": baseline_equity,
        "current_equity": round(current_equity, 2),
        "weekly_pl": weekly_pl,
        "weekly_return_pct": weekly_return_pct,
        "target_pct": policy.weekly_target_pct,
        "pct_of_target_reached": pct_of_target,
    }


def compute_daily_performance(
    account: dict[str, Any],
    daily_baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return daily P&L dict."""
    current_equity = _equity(account)
    if daily_baseline is None or current_equity is None:
        return {
            "date": None,
            "baseline_equity": None,
            "current_equity": current_equity,
            "daily_pl": None,
            "daily_return_pct": None,
        }
    baseline_equity = float(daily_baseline.get("equity", 0.0))
    if baseline_equity <= 0:
        return {
            "date": daily_baseline.get("date"),
            "baseline_equity": baseline_equity,
            "current_equity": current_equity,
            "daily_pl": None,
            "daily_return_pct": None,
        }
    daily_pl = round(current_equity - baseline_equity, 2)
    daily_return_pct = round((current_equity / baseline_equity - 1.0) * 100.0, 4)
    return {
        "date": daily_baseline.get("date"),
        "baseline_equity": baseline_equity,
        "current_equity": round(current_equity, 2),
        "daily_pl": daily_pl,
        "daily_return_pct": daily_return_pct,
    }


def _equity(account: dict[str, Any]) -> float | None:
    for key in ("portfolio_value", "equity"):
        v = account.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v)
    return None
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "performance" -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```
git add src/agency/portfolio/performance.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): performance.py — weekly and daily P&L calculation"
```

---

## Task 4: Circuit Breakers

**Files:**
- Create: `src/agency/portfolio/circuit_breaker.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add 4 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
def _weekly_perf(return_pct: float) -> dict:
    return {
        "weekly_return_pct": return_pct,
        "target_pct": 3.0,
        "pct_of_target_reached": return_pct / 3.0 * 100,
    }


def _daily_perf(return_pct: float) -> dict:
    return {"daily_return_pct": return_pct}


def test_circuit_breaker_weekly_target_reached() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
    result = evaluate_circuit_breakers(
        _weekly_perf(3.0), _daily_perf(0.5), PortfolioPolicy()
    )
    assert result["new_entries_blocked"] is True
    assert "WEEKLY_TARGET_REACHED" in result["signals"]


def test_circuit_breaker_weekly_target_approach() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
    result = evaluate_circuit_breakers(
        _weekly_perf(2.6), _daily_perf(0.5), PortfolioPolicy()
    )
    assert result["new_entries_blocked"] is False
    assert result["reduced_sizing_active"] is True
    assert "WEEKLY_TARGET_APPROACH" in result["signals"]
    assert result["recommended_position_pct"] == PortfolioPolicy().reduced_position_pct


def test_circuit_breaker_daily_loss() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
    result = evaluate_circuit_breakers(
        _weekly_perf(0.5), _daily_perf(-3.0), PortfolioPolicy()
    )
    assert result["new_entries_blocked"] is True
    assert "DAILY_CIRCUIT_BREAKER" in result["signals"]


def test_circuit_breaker_weekly_drawdown_limit() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
    result = evaluate_circuit_breakers(
        _weekly_perf(-6.0), _daily_perf(-1.0), PortfolioPolicy()
    )
    assert result["new_entries_blocked"] is True
    assert "WEEKLY_DRAWDOWN_LIMIT" in result["signals"]


def test_circuit_breaker_all_clear() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
    result = evaluate_circuit_breakers(
        _weekly_perf(1.0), _daily_perf(0.5), PortfolioPolicy()
    )
    assert result["new_entries_blocked"] is False
    assert result["reduced_sizing_active"] is False
    assert result["signals"] == []
    assert result["recommended_position_pct"] == PortfolioPolicy().default_position_pct
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "circuit_breaker" -v
```
Expected: `ImportError: cannot import name 'evaluate_circuit_breakers'`

- [ ] **Step 3: Create `circuit_breaker.py`**

```python
# src/agency/portfolio/circuit_breaker.py
from __future__ import annotations

from typing import Any

from agency.portfolio.policy import PortfolioPolicy


def evaluate_circuit_breakers(
    weekly_perf: dict[str, Any],
    daily_perf: dict[str, Any],
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    """Return circuit-breaker state dict. Never raises — missing perf data is treated as 0."""
    weekly_return = _pct(weekly_perf, "weekly_return_pct")
    daily_return = _pct(daily_perf, "daily_return_pct")

    signals: list[str] = []
    new_entries_blocked = False
    reduced_sizing_active = False

    # Weekly target reached — block new entries
    if weekly_return is not None and weekly_return >= policy.weekly_target_pct:
        signals.append("WEEKLY_TARGET_REACHED")
        new_entries_blocked = True

    # Weekly drawdown limit — block new entries
    if weekly_return is not None and weekly_return <= -policy.weekly_drawdown_limit_pct:
        signals.append("WEEKLY_DRAWDOWN_LIMIT")
        new_entries_blocked = True

    # Daily circuit breaker — block new entries
    if daily_return is not None and daily_return <= -policy.daily_circuit_breaker_pct:
        signals.append("DAILY_CIRCUIT_BREAKER")
        new_entries_blocked = True

    # Weekly target approach — reduce sizing (only if not already blocked)
    if (
        not new_entries_blocked
        and weekly_return is not None
        and weekly_return >= policy.weekly_target_approach_pct
    ):
        signals.append("WEEKLY_TARGET_APPROACH")
        reduced_sizing_active = True

    recommended_pct = (
        policy.default_position_pct
        if new_entries_blocked
        else policy.reduced_position_pct
        if reduced_sizing_active
        else policy.default_position_pct
    )

    return {
        "active": len(signals) > 0,
        "signals": signals,
        "new_entries_blocked": new_entries_blocked,
        "reduced_sizing_active": reduced_sizing_active,
        "recommended_position_pct": recommended_pct,
    }


def _pct(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "circuit_breaker" -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```
git add src/agency/portfolio/circuit_breaker.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): circuit_breaker.py — weekly target, drawdown, daily loss gates"
```

---

## Task 5: Exit Rules — STOP_LOSS and THESIS_BROKEN

**Files:**
- Create: `src/agency/portfolio/exit_rules.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add 2 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
def test_stop_loss_fires_on_day_1() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=-2.0,
        quantity=10.0,
        trading_days_held=0,
        high_water_mark_pct=0.0,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "STOP_LOSS"
    assert result["exit_priority"] == "URGENT"
    assert result["recommendation"]["action"] == "CLOSE"


def test_thesis_broken_fires_on_day_1() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    report = {"final_action": "NO_TRADE", "final_conviction": 0.80, "risk_flags": [], "policy_gates": []}
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.0,
        quantity=10.0,
        trading_days_held=0,
        high_water_mark_pct=1.0,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "THESIS_BROKEN"
    assert result["exit_priority"] == "HIGH"
    assert result["recommendation"]["action"] == "CLOSE"


def test_thesis_broken_fires_on_low_conviction() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    report = {"final_action": "WATCH", "final_conviction": 0.35, "risk_flags": [], "policy_gates": []}
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "THESIS_BROKEN"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "stop_loss or thesis_broken" -v
```
Expected: `ImportError: cannot import name 'evaluate_exit_signal'`

- [ ] **Step 3: Create `exit_rules.py`** (initial — only covers priorities 1 and 2)

```python
# src/agency/portfolio/exit_rules.py
from __future__ import annotations

from typing import Any

from agency.portfolio.policy import PortfolioPolicy


def evaluate_exit_signal(
    *,
    ticker: str,
    unrealized_pct: float,
    quantity: float,
    trading_days_held: int,
    high_water_mark_pct: float,
    stage1_executed: bool,
    selection_report: dict[str, Any] | None,
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    """Evaluate all exit signals for one position. Returns the highest-priority signal dict.

    unrealized_pct  — percentage points, e.g. 2.38 means +2.38%
    high_water_mark_pct — peak unrealized %, same scale
    quantity        — current number of shares/units held
    """

    # ── Priority 1: STOP_LOSS ─────────────────────────────────────────────
    if unrealized_pct <= -policy.stop_loss_pct:
        return _signal(
            "STOP_LOSS", "URGENT",
            f"{ticker} unrealized loss {unrealized_pct:.2f}% hit the "
            f"-{policy.stop_loss_pct:.1f}% stop-loss.",
            {"action": "CLOSE", "rationale": "Hard stop reached. Close full position."},
        )

    # ── Priority 2: THESIS_BROKEN ─────────────────────────────────────────
    if selection_report is not None:
        action = str(selection_report.get("final_action", ""))
        conviction = float(selection_report.get("final_conviction", 1.0))
        if action == "NO_TRADE" or conviction < policy.thesis_broken_conviction_floor:
            return _signal(
                "THESIS_BROKEN", "HIGH",
                f"{ticker} thesis broken: action={action}, conviction={conviction:.2f}.",
                {"action": "CLOSE",
                 "rationale": "Research thesis no longer supports holding this position."},
            )

    # ── Remaining priorities implemented in later tasks ───────────────────
    return _hold(ticker)


def _signal(
    signal_type: str,
    priority: str,
    reason: str,
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "exit_signal": signal_type,
        "exit_priority": priority,
        "exit_reason": reason,
        "recommendation": recommendation,
    }


def _hold(ticker: str) -> dict[str, Any]:
    return _signal(
        "HOLD", "NONE",
        f"{ticker} is on track. No exit rule triggered.",
        {"action": "HOLD", "rationale": "Position is within all guardrails."},
    )


def _has_policy_gate_warn(report: dict[str, Any]) -> bool:
    return any(
        str(gate.get("status")) == "WARN"
        for gate in report.get("policy_gates", [])
        if isinstance(gate, dict)
    )
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "stop_loss or thesis_broken" -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```
git add src/agency/portfolio/exit_rules.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): exit_rules.py — STOP_LOSS and THESIS_BROKEN signals"
```

---

## Task 6: Exit Rules — TRAILING_STOP and TAKE_PROFIT_STAGE_2

**Files:**
- Modify: `src/agency/portfolio/exit_rules.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add 4 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
def test_trailing_stop_dormant_below_activation_gate() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    # Peak was only 0.8% — trailing stop should NOT activate
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.2,
        quantity=10.0,
        trading_days_held=3,
        high_water_mark_pct=0.8,  # below 1.5% activation gate
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "HOLD"


def test_trailing_stop_activates_after_gate() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    # Peak was 2.5%, now at 0.9% — drawback of 1.6% exceeds 1.5% trailing stop
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.9,
        quantity=10.0,
        trading_days_held=3,
        high_water_mark_pct=2.5,  # above 1.5% activation gate
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "TRAILING_STOP"
    assert result["exit_priority"] == "NORMAL"
    assert result["recommendation"]["action"] == "CLOSE"


def test_trailing_stop_does_not_fire_below_drawback_threshold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    # Peak 2.5%, now at 1.2% — drawback of 1.3% is below 1.5% trailing stop
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.2,
        quantity=10.0,
        trading_days_held=3,
        high_water_mark_pct=2.5,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "HOLD"


def test_take_profit_stage2_fires_after_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=4.1,
        quantity=10.0,
        trading_days_held=2,
        high_water_mark_pct=4.1,
        stage1_executed=True,  # stage1 already done
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "TAKE_PROFIT_STAGE_2"
    assert result["recommendation"]["action"] == "CLOSE"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "trailing_stop or stage2" -v
```
Expected: `4 failed` (HOLD returned for all, no TRAILING_STOP or TAKE_PROFIT_STAGE_2 logic yet)

- [ ] **Step 3: Extend `exit_rules.py` — add priorities 3 and 4**

Replace the section between `# Priority 2` and `# Remaining priorities` in `evaluate_exit_signal`:

```python
    # ── Priority 2: THESIS_BROKEN ─────────────────────────────────────────
    if selection_report is not None:
        action = str(selection_report.get("final_action", ""))
        conviction = float(selection_report.get("final_conviction", 1.0))
        if action == "NO_TRADE" or conviction < policy.thesis_broken_conviction_floor:
            return _signal(
                "THESIS_BROKEN", "HIGH",
                f"{ticker} thesis broken: action={action}, conviction={conviction:.2f}.",
                {"action": "CLOSE",
                 "rationale": "Research thesis no longer supports holding this position."},
            )

    # ── Priority 3: TAKE_PROFIT_STAGE_2 ──────────────────────────────────
    if (
        trading_days_held >= policy.minimum_hold_days
        and unrealized_pct >= policy.take_profit_stage2_pct
    ):
        return _signal(
            "TAKE_PROFIT_STAGE_2", "NORMAL",
            f"{ticker} gain {unrealized_pct:.2f}% reached the "
            f"+{policy.take_profit_stage2_pct:.1f}% Stage 2 target.",
            {"action": "CLOSE",
             "rationale": "Stage 2 profit target reached. Close remaining position."},
        )

    # ── Priority 4: TRAILING_STOP ─────────────────────────────────────────
    trailing_active = high_water_mark_pct >= policy.trailing_stop_activates_at_pct
    if trading_days_held >= policy.minimum_hold_days and trailing_active:
        drawback = high_water_mark_pct - unrealized_pct
        if drawback >= policy.trailing_stop_pct:
            return _signal(
                "TRAILING_STOP", "NORMAL",
                f"{ticker} drew back {drawback:.2f}% from peak "
                f"{high_water_mark_pct:.2f}%.",
                {"action": "CLOSE",
                 "rationale": "Trailing stop triggered. Protect remaining gains."},
            )
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "trailing_stop or stage2" -v
```
Expected: `4 passed`

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest tests/unit/test_portfolio_manager.py -v
```
Expected: all previously passing tests still pass

- [ ] **Step 6: Commit**

```
git add src/agency/portfolio/exit_rules.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): exit_rules — TRAILING_STOP and TAKE_PROFIT_STAGE_2"
```

---

## Task 7: Exit Rules — TAKE_PROFIT_STAGE_1, TIME_STOP, SETUP_WARNING, HOLD

**Files:**
- Modify: `src/agency/portfolio/exit_rules.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add 7 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
def test_take_profit_stage1_requires_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    # +2.5% gain but only held 1 day — must NOT fire
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.5,
        quantity=10.0,
        trading_days_held=1,  # below minimum_hold_days=2
        high_water_mark_pct=2.5,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "HOLD"


def test_take_profit_stage1_fires_after_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.3,
        quantity=10.0,
        trading_days_held=2,
        high_water_mark_pct=2.3,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "TAKE_PROFIT_STAGE_1"
    assert result["exit_priority"] == "NORMAL"
    assert result["recommendation"]["action"] == "TRIM"
    assert result["recommendation"]["suggested_trim_pct"] == 0.50
    assert result["recommendation"]["suggested_trim_qty"] == 5  # 50% of 10
    assert result["recommendation"]["breakeven_stop_recommendation"] is True


def test_stage1_suppressed_when_already_executed() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.5,
        quantity=5.0,  # already trimmed
        trading_days_held=2,
        high_water_mark_pct=2.5,
        stage1_executed=True,  # already done
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "HOLD"


def test_time_stop_fires_after_flat_days() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.3,   # flat: < 0.5%
        quantity=10.0,
        trading_days_held=5,  # > time_stop_days=4
        high_water_mark_pct=0.4,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "TIME_STOP"
    assert result["exit_priority"] == "LOW"
    assert result["recommendation"]["action"] == "REVIEW"


def test_time_stop_does_not_fire_if_moving() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.2,   # moved more than 0.5%
        quantity=10.0,
        trading_days_held=5,
        high_water_mark_pct=1.2,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "HOLD"


def test_setup_warning_fires_on_risk_flags() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    report = {
        "final_action": "WATCH",
        "final_conviction": 0.70,
        "risk_flags": ["low_volume"],
        "policy_gates": [],
    }
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "SETUP_WARNING"
    assert result["exit_priority"] == "INFO"


def test_hold_when_no_rules_triggered() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal
    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.0,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=1.0,
        stage1_executed=False,
        selection_report={"final_action": "WATCH", "final_conviction": 0.75,
                          "risk_flags": [], "policy_gates": []},
        policy=PortfolioPolicy(),
    )
    assert result["exit_signal"] == "HOLD"
    assert result["exit_priority"] == "NONE"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "stage1 or time_stop or setup_warning or hold_when" -v
```
Expected: `7 failed`

- [ ] **Step 3: Complete `exit_rules.py` — add priorities 5–8**

Add after the trailing stop block and before `return _hold(ticker)`:

```python
    # ── Priority 5: TAKE_PROFIT_STAGE_1 ──────────────────────────────────
    if (
        trading_days_held >= policy.minimum_hold_days
        and not stage1_executed
        and unrealized_pct >= policy.take_profit_stage1_pct
    ):
        suggested_qty = max(1, round(quantity * policy.suggested_stage1_trim_pct))
        return _signal(
            "TAKE_PROFIT_STAGE_1", "NORMAL",
            f"{ticker} gain {unrealized_pct:.2f}% reached the "
            f"+{policy.take_profit_stage1_pct:.1f}% Stage 1 target "
            f"after {trading_days_held} trading days.",
            {
                "action": "TRIM",
                "suggested_trim_pct": policy.suggested_stage1_trim_pct,
                "suggested_trim_qty": suggested_qty,
                "breakeven_stop_recommendation": True,
                "rationale": (
                    f"Secure {policy.suggested_stage1_trim_pct * 100:.0f}% of the position "
                    "at target. Move stop to break-even on the remainder."
                ),
            },
        )

    # ── Priority 6: TIME_STOP ─────────────────────────────────────────────
    if (
        trading_days_held > policy.time_stop_days
        and abs(unrealized_pct) < policy.time_stop_flat_threshold_pct
    ):
        return _signal(
            "TIME_STOP", "LOW",
            f"{ticker} held {trading_days_held} trading days with only "
            f"{unrealized_pct:.2f}% move — possible dead capital.",
            {"action": "REVIEW",
             "rationale": "Position has not moved after maximum hold window. Consider redeployment."},
        )

    # ── Priority 7: SETUP_WARNING ─────────────────────────────────────────
    if selection_report is not None:
        risk_flags = selection_report.get("risk_flags", [])
        if risk_flags or _has_policy_gate_warn(selection_report):
            return _signal(
                "SETUP_WARNING", "INFO",
                f"{ticker} current setup has warnings or risk flags.",
                {"action": "REVIEW",
                 "rationale": "Review warnings before adding more exposure to this ticker."},
            )

    # ── Priority 8: HOLD (no signal) ──────────────────────────────────────
    return _hold(ticker)
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py -v
```
Expected: all tests pass (target ≥ 20 passing)

- [ ] **Step 5: Commit**

```
git add src/agency/portfolio/exit_rules.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): exit_rules — TAKE_PROFIT_STAGE_1, TIME_STOP, SETUP_WARNING, HOLD"
```

---

## Task 8: Snapshot Builder

**Files:**
- Create: `src/agency/portfolio/snapshot.py`
- Modify: `tests/unit/test_portfolio_manager.py` (add 3 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_portfolio_manager.py`:

```python
def test_snapshot_schema_valid(tmp_path: Path) -> None:
    from agency.portfolio.snapshot import build_portfolio_snapshot
    positions = [{
        "symbol": "AAPL",
        "unrealized_plpc": "0.005",
        "unrealized_pl": "10.00",
        "market_value": "2000.00",
        "qty": "10",
        "side": "long",
    }]
    account = {"equity": 100000.0, "cash": 80000.0, "portfolio_value": 100000.0}
    result = build_portfolio_snapshot(
        broker_positions=positions,
        account=account,
        selection_reports=[],
        state_dir=tmp_path,
        policy=PortfolioPolicy(),
    )
    assert result["schema_version"] == "1.0.0"
    assert "circuit_breaker" in result
    assert "weekly_performance" in result
    assert "daily_performance" in result
    assert "summary" in result
    assert "positions" in result
    assert "reentry_blocks" in result
    assert len(result["positions"]) == 1
    assert result["positions"][0]["ticker"] == "AAPL"


def test_snapshot_empty_portfolio(tmp_path: Path) -> None:
    from agency.portfolio.snapshot import build_portfolio_snapshot
    result = build_portfolio_snapshot(
        broker_positions=[],
        account={"equity": 100000.0},
        selection_reports=[],
        state_dir=tmp_path,
        policy=PortfolioPolicy(),
    )
    assert result["positions"] == []
    assert result["summary"]["position_count"] == 0


def test_reentry_cooldown_active_in_snapshot(tmp_path: Path) -> None:
    from agency.portfolio.snapshot import build_portfolio_snapshot
    from agency.portfolio.state import record_stop_loss_exit
    record_stop_loss_exit(tmp_path, "TSLA", "2026-05-29T10:00:00Z", cooldown_hours=24)
    result = build_portfolio_snapshot(
        broker_positions=[],
        account={"equity": 100000.0},
        selection_reports=[],
        state_dir=tmp_path,
        policy=PortfolioPolicy(),
        generated_at="2026-05-29T18:00:00Z",  # 8h after exit — still in cooldown
    )
    assert "TSLA" in result["reentry_blocks"]
    assert result["reentry_blocks"]["TSLA"]["blocked_until"] is not None
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/unit/test_portfolio_manager.py -k "snapshot or reentry_cooldown_active" -v
```
Expected: `ImportError: cannot import name 'build_portfolio_snapshot'`

- [ ] **Step 3: Create `snapshot.py`**

```python
# src/agency/portfolio/snapshot.py
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
from agency.portfolio.exit_rules import evaluate_exit_signal
from agency.portfolio.performance import compute_daily_performance, compute_weekly_performance
from agency.portfolio.policy import PortfolioPolicy
from agency.portfolio.state import (
    load_daily_baseline,
    load_entry_timestamps,
    load_high_water_marks,
    load_reentry_cooldowns,
    load_stage1_executed,
    load_weekly_baseline,
    save_high_water_marks,
    update_high_water_marks,
)


def build_portfolio_snapshot(
    *,
    broker_positions: list[dict[str, Any]],
    account: dict[str, Any],
    selection_reports: list[dict[str, Any]],
    state_dir: Path,
    policy: PortfolioPolicy | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a complete portfolio snapshot. Updates high-water marks in state_dir.

    Does NOT write stage1_executed or reentry_cooldowns — those are written only
    when the human confirms an action via the UI.
    """
    p = policy or PortfolioPolicy()
    now = generated_at or _utc_now()

    # Load state
    hwm = load_high_water_marks(state_dir)
    stage1 = load_stage1_executed(state_dir)
    entry_ts = load_entry_timestamps(state_dir)
    weekly_baseline = load_weekly_baseline(state_dir)
    daily_baseline = load_daily_baseline(state_dir)
    cooldowns = load_reentry_cooldowns(state_dir)

    # Build selection report lookup by ticker
    reports: dict[str, dict[str, Any]] = {
        str(r.get("ticker", "")).upper(): r for r in selection_reports
    }

    # Compute performance
    weekly_perf = compute_weekly_performance(account, weekly_baseline, p)
    daily_perf = compute_daily_performance(account, daily_baseline)

    # Evaluate circuit breakers
    circuit = evaluate_circuit_breakers(weekly_perf, daily_perf, p)

    # Build position rows
    positions: list[dict[str, Any]] = []
    for pos in broker_positions:
        ticker = _ticker(pos)
        if not ticker:
            continue
        unrealized_pct = float(pos.get("unrealized_plpc") or 0.0) * 100.0
        quantity = float(pos.get("qty") or 0.0)
        hw = hwm.get(ticker, 0.0)
        s1_done = bool(stage1.get(ticker, {}).get("executed", False))
        days_held = int(entry_ts.get(ticker, {}).get("trading_days_held", 0))
        # Use already-loaded dict — do NOT call cooldown_is_active(state_dir, ...) in loop
        cd_active = _check_cooldown_active(cooldowns.get(ticker), now)

        signal = evaluate_exit_signal(
            ticker=ticker,
            unrealized_pct=unrealized_pct,
            quantity=quantity,
            trading_days_held=days_held,
            high_water_mark_pct=hw,
            stage1_executed=s1_done,
            selection_report=reports.get(ticker),
            policy=p,
        )

        positions.append(_build_position_row(pos, ticker, unrealized_pct, hw, s1_done, days_held, cd_active, signal, p))

    # Update and persist high-water marks
    updated_hwm = update_high_water_marks(hwm, broker_positions)
    save_high_water_marks(state_dir, updated_hwm)

    # Reentry blocks output
    reentry_blocks = _reentry_blocks(cooldowns, now)

    return {
        "schema_version": "1.0.0",
        "generated_at": now,
        "mode": "PAPER" if broker_positions else "READ_ONLY",
        "circuit_breaker": circuit,
        "weekly_performance": weekly_perf,
        "daily_performance": daily_perf,
        "summary": _summary(positions, account, circuit, p),
        "positions": positions,
        "reentry_blocks": reentry_blocks,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_position_row(
    pos: dict[str, Any],
    ticker: str,
    unrealized_pct: float,
    high_water_mark_pct: float,
    stage1_executed: bool,
    trading_days_held: int,
    reentry_cooldown_active: bool,
    signal: dict[str, Any],
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    unrealized_pl = float(pos.get("unrealized_pl") or 0.0)
    market_value = float(pos.get("market_value") or 0.0)
    quantity = float(pos.get("qty") or 0.0)
    trailing_active = high_water_mark_pct >= policy.trailing_stop_activates_at_pct
    drawback = round(high_water_mark_pct - unrealized_pct, 4) if trailing_active else None

    exit_signal = signal["exit_signal"]
    classification = (
        "URGENT" if signal["exit_priority"] == "URGENT"
        else "ACTION_NEEDED" if exit_signal not in {"HOLD", "SETUP_WARNING"}
        else "WARNING" if exit_signal == "SETUP_WARNING"
        else "HOLD"
    )

    return {
        "ticker": ticker,
        "side": str(pos.get("side") or "long").upper(),
        "quantity": quantity,
        "market_value": market_value,
        "unrealized_pl": unrealized_pl,
        "unrealized_plpc": float(pos.get("unrealized_plpc") or 0.0),
        "trading_days_held": trading_days_held,
        "stage1_executed": stage1_executed,
        "high_water_mark_pct": high_water_mark_pct,
        "trailing_stop_active": trailing_active,
        "trailing_stop_drawback_pct": drawback,
        "exit_signal": exit_signal,
        "exit_priority": signal["exit_priority"],
        "exit_reason": signal["exit_reason"],
        "recommendation": signal["recommendation"],
        "reentry_cooldown_active": reentry_cooldown_active,
        "classification": classification,
        "urgency": signal["exit_priority"],
        "pnl_label": f"${unrealized_pl:+.2f} / {unrealized_pct:+.2f}%",
    }


def _summary(
    positions: list[dict[str, Any]],
    account: dict[str, Any],
    circuit: dict[str, Any],
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    equity = float(account.get("equity") or account.get("portfolio_value") or 0.0)
    total_market_value = sum(float(p.get("market_value") or 0.0) for p in positions)
    gross_exposure_pct = round(total_market_value / equity * 100.0, 4) if equity > 0 else 0.0
    available = round(max(policy.max_gross_exposure_pct - gross_exposure_pct, 0.0), 4)

    urgent = sum(1 for p in positions if p["classification"] == "URGENT")
    action = sum(1 for p in positions if p["classification"] == "ACTION_NEEDED")
    hold = sum(1 for p in positions if p["classification"] == "HOLD")

    return {
        "position_count": len(positions),
        "urgent_count": urgent,
        "action_needed_count": action,
        "hold_count": hold,
        "gross_exposure_pct": gross_exposure_pct,
        "available_capacity_pct": available,
        "cash_pct": round(100.0 - gross_exposure_pct, 4),
        "equity": equity,
        "new_entries_blocked": circuit["new_entries_blocked"],
        "reduced_sizing_active": circuit["reduced_sizing_active"],
    }


def _reentry_blocks(
    cooldowns: dict[str, dict[str, Any]],
    now_utc: str,
) -> dict[str, dict[str, Any]]:
    """Return only cooldowns that are currently active."""
    result: dict[str, dict[str, Any]] = {}
    try:
        now = datetime.fromisoformat(now_utc.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return result
    for ticker, entry in cooldowns.items():
        blocked_until_str = str(entry.get("blocked_until") or "")
        if not blocked_until_str:
            continue
        try:
            blocked_until = datetime.fromisoformat(
                blocked_until_str.replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError:
            continue
        if now < blocked_until:
            result[ticker] = {
                "blocked_until": blocked_until_str,
                "reason": str(entry.get("reason") or ""),
            }
    return result


def _check_cooldown_active(entry: dict[str, Any] | None, now_utc: str) -> bool:
    """Check an already-loaded cooldown entry — no disk I/O."""
    if not entry:
        return False
    blocked_str = str(entry.get("blocked_until") or "")
    if not blocked_str:
        return False
    try:
        blocked = datetime.fromisoformat(blocked_str.replace("Z", "+00:00")).astimezone(UTC)
        now = datetime.fromisoformat(now_utc.replace("Z", "+00:00")).astimezone(UTC)
        return now < blocked
    except ValueError:
        return False


def _ticker(pos: dict[str, Any]) -> str:
    return str(pos.get("symbol") or pos.get("ticker") or "").upper()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/unit/test_portfolio_manager.py -v
```
Expected: all 23 tests pass

- [ ] **Step 5: Commit**

```
git add src/agency/portfolio/snapshot.py tests/unit/test_portfolio_manager.py
git commit -m "feat(portfolio): snapshot.py — build_portfolio_snapshot() public entry point"
```

---

## Task 9: Integration Tests

**Files:**
- Create: `tests/integration/test_portfolio_state.py`

- [ ] **Step 1: Write all 4 integration tests**

```python
# tests/integration/test_portfolio_state.py
from __future__ import annotations

from pathlib import Path

import pytest

from agency.portfolio.state import (
    load_high_water_marks,
    load_weekly_baseline,
    load_daily_baseline,
    save_high_water_marks,
    save_weekly_baseline,
    save_daily_baseline,
    update_high_water_marks,
)


def test_high_water_marks_persist_and_load(tmp_path: Path) -> None:
    """Write marks to disk and read them back — exact round-trip."""
    marks = {"AAPL": 3.45, "MSFT": 1.20, "NVDA": 0.0}
    save_high_water_marks(tmp_path, marks)
    loaded = load_high_water_marks(tmp_path)
    assert loaded["AAPL"] == pytest.approx(3.45)
    assert loaded["MSFT"] == pytest.approx(1.20)
    assert loaded["NVDA"] == pytest.approx(0.0)


def test_update_high_water_marks_only_goes_up(tmp_path: Path) -> None:
    """update_high_water_marks never decreases a mark."""
    current = {"AAPL": 3.45}
    # Position has unrealized_plpc 0.02 (2%), which is below current 3.45%
    positions = [{"symbol": "AAPL", "unrealized_plpc": "0.020"}]
    updated = update_high_water_marks(current, positions)
    assert updated["AAPL"] == pytest.approx(3.45)  # unchanged

    # Position now at 4%, above current mark
    positions2 = [{"symbol": "AAPL", "unrealized_plpc": "0.040"}]
    updated2 = update_high_water_marks(updated, positions2)
    assert updated2["AAPL"] == pytest.approx(4.0)  # updated


def test_weekly_baseline_roundtrip(tmp_path: Path) -> None:
    """Weekly baseline writes and reads correctly."""
    baseline = {"week_start": "2026-05-26", "equity": 98500.00}
    save_weekly_baseline(tmp_path, baseline)
    loaded = load_weekly_baseline(tmp_path)
    assert loaded is not None
    assert loaded["week_start"] == "2026-05-26"
    assert loaded["equity"] == pytest.approx(98500.00)


def test_state_dir_missing_returns_empty_defaults(tmp_path: Path) -> None:
    """All loaders return safe empty values when state files do not exist."""
    empty_dir = tmp_path / "nonexistent"
    # Do NOT create the directory — loaders must handle missing gracefully
    assert load_high_water_marks(empty_dir) == {}
    assert load_weekly_baseline(empty_dir) is None
    assert load_daily_baseline(empty_dir) is None
```

- [ ] **Step 2: Run integration tests**

```
python -m pytest tests/integration/test_portfolio_state.py -v
```
Expected: `4 passed`

- [ ] **Step 3: Run full unit suite to confirm no regressions**

```
python -m pytest tests/unit/test_portfolio_manager.py -v
```
Expected: all 23 unit tests pass

- [ ] **Step 4: Commit**

```
git add tests/integration/test_portfolio_state.py
git commit -m "test(portfolio): integration tests for state persistence and high-water mark logic"
```

---

## Task 10: Final Validation

- [ ] **Step 1: Add public exports to `__init__.py`**

```python
# src/agency/portfolio/__init__.py
from agency.portfolio.policy import PortfolioPolicy
from agency.portfolio.snapshot import build_portfolio_snapshot

__all__ = ["PortfolioPolicy", "build_portfolio_snapshot"]
```

- [ ] **Step 2: Run all portfolio tests together**

```
python -m pytest tests/unit/test_portfolio_manager.py tests/integration/test_portfolio_state.py -v
```
Expected: **27 passed** (23 unit + 4 integration)

- [ ] **Step 3: Commit `__init__.py` update**

```
git add src/agency/portfolio/__init__.py
git commit -m "feat(portfolio): export public API from __init__.py"
```

- [ ] **Step 5: Confirm no file exceeds 250 lines**

```
python -c "
import pathlib
for f in pathlib.Path('src/agency/portfolio').glob('*.py'):
    lines = len(f.read_text().splitlines())
    status = 'OK' if lines <= 250 else 'OVER LIMIT'
    print(f'{status:12} {lines:4d}  {f}')
"
```
Expected: all files show `OK`

- [ ] **Step 6: Confirm no broker/FastAPI imports inside portfolio/**

```
python -c "
import pathlib, sys
for f in pathlib.Path('src/agency/portfolio').glob('*.py'):
    text = f.read_text()
    if any(bad in text for bad in ['fastapi', 'alpaca', 'from agency.broker', 'from agency.views', 'from agency.app']):
        print(f'FORBIDDEN import in {f}')
        sys.exit(1)
print('All clean')
"
```
Expected: `All clean`

- [ ] **Step 7: Run the existing test suite to confirm nothing is broken**

```
python -m pytest tests/unit/ -x --tb=short -q
```
Expected: existing tests unaffected (new module does not touch old files)

- [ ] **Step 8: Final commit**

```
git add src/agency/portfolio/
git commit -m "feat(portfolio): complete portfolio manager module — all 27 tests passing

New module src/agency/portfolio/ replaces portfolio logic in services/:
- PortfolioPolicy: updated defaults aligned to 1-3% weekly target
- Tiered exits: Stage 1 flag (+2%, trim), Stage 2 (+4%, close)
- Trailing stop with activation gate (dormant until peak >= 1.5%)
- Time stop after 4 flat trading days
- Portfolio-level circuit breakers (weekly target, daily loss, drawdown)
- Minimum hold enforcement and 24h re-entry cooldown
- All persistent state in research/state/portfolio/ (JSON files)
- 23 unit tests + 4 integration tests, all passing
- Old services/portfolio_monitor.py and services/risk.py untouched"
```

---

## Acceptance Checklist

Before marking this plan complete, verify every item in the spec §13:

- [ ] All 20 unit tests specified in spec §12 pass (covered across tasks 1–8; 23 total including bonus tests)
- [ ] All 4 integration tests pass
- [ ] `build_portfolio_snapshot()` works for empty portfolio, full portfolio with all signals, and all circuit breakers active
- [ ] `PortfolioPolicy.from_env()` loads every field from env vars
- [ ] `PortfolioPolicy` loads from `portfolio-policy.local.json` when present
- [ ] No broker/FastAPI/UI imports inside `src/agency/portfolio/`
- [ ] No file in `src/agency/portfolio/` exceeds 250 lines
