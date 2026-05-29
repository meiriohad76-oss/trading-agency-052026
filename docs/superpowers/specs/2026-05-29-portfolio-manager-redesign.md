# Portfolio Manager — Redesign Spec

**Date:** 2026-05-29  
**Author:** Ohad Meiri  
**Status:** Approved for implementation  
**Context:** Part of the agency v3 redesign. This module is the first component being rewritten.

---

## 1. Purpose

The Portfolio Manager monitors open positions against a defined exit rule set, generates
prioritized human-review recommendations with suggested actions, and enforces portfolio-level
circuit breakers that block new entries when risk limits are hit.

**The Portfolio Manager never auto-executes orders. It surfaces decisions; humans make them.**

---

## 2. Background and Motivation

The original system (`services/portfolio_monitor.py`, `services/risk.py`) was built with
day-trading patterns in mind — hourly P&L alerts, sub-minute freshness checks, a source-health
gating system that blocked exits. The actual goal is **short-term investing targeting 1–3%
weekly gains on 2–5 day holds**. This spec redesigns the module to match that rhythm.

Key problems being fixed:
- `take_profit_pct = 8.0` was a 4× overshoot of the weekly target
- No tiered / partial exit logic
- No time-based exit (dead capital rule)
- No portfolio-level weekly target tracking
- Minimum hold days declared but not enforced in exit logic
- Trailing stop fired from day 1 (wrong for multi-day holds)
- No re-entry cooldown after a stop-loss

---

## 3. Scope

**In scope:**
- `PortfolioPolicy` dataclass with updated defaults
- `PortfolioManager` — core snapshot builder
- All exit signal types (per-position and portfolio-level)
- Persistent state management (high-water marks, stage1 tracking, entry timestamps,
  weekly baseline, re-entry cooldowns)
- Unit tests for every exit rule and circuit breaker

**Out of scope:**
- Order execution (that is the Execution module's responsibility)
- Position sizing for new entries (that is the Risk module's responsibility)
- Fetching market data (positions arrive from the broker adapter)
- UI / template rendering

---

## 4. Exit Signal Types — Per Position

Signals are evaluated in priority order. The highest-priority triggered signal wins for the
`exit_signal` field. Lower-priority signals are recorded in `secondary_signals`.

### 4.1 STOP_LOSS — URGENT

**Trigger:** `unrealized_plpc <= -stop_loss_pct`  
**Default threshold:** -2.0%  
**Minimum hold enforcement:** Does NOT apply. Stop-loss fires immediately, any day.  
**Recommended action:** Close full position.  
**Notes:** This is a hard capital-protection rule. The system must surface it regardless
of any other state.

### 4.2 THESIS_BROKEN — HIGH

**Trigger:** Latest selection cycle for this ticker returns `final_action == "NO_TRADE"`
or `final_conviction < thesis_broken_conviction_floor`  
**Default threshold:** `thesis_broken_conviction_floor = 0.40`  
**Minimum hold enforcement:** Does NOT apply.  
**Recommended action:** Close full position.  
**Notes:** The research thesis that justified entry no longer holds. Exit to redeploy capital
into fresher opportunities.

### 4.3 TAKE_PROFIT_STAGE_2 — NORMAL

**Trigger:** `unrealized_plpc >= take_profit_stage2_pct`  
**Default threshold:** +4.0%  
**Minimum hold enforcement:** Applies. Does not fire before `minimum_hold_days` trading days.  
**Recommended action:** Close remaining position (whether full or post-stage-1 remainder).  
**Notes:** If Stage 1 has already executed, this fires when the *remaining* position's
unrealized gain reaches +4% from the original entry price.

### 4.4 TRAILING_STOP — NORMAL

**Trigger:** `(high_water_mark - unrealized_plpc) >= trailing_stop_pct`  
  AND `high_water_mark >= trailing_stop_activates_at_pct`  
**Default thresholds:** `trailing_stop_pct = 1.5%`, `trailing_stop_activates_at_pct = 1.5%`  
**Minimum hold enforcement:** Does not explicitly apply, but the activation gate
(`high_water_mark >= 1.5%`) provides natural protection in the first hours of a hold.  
**Recommended action:** Close remaining position.  
**Notes:** The trailing stop is DORMANT until the position has peaked at ≥ +1.5%. This
prevents getting stopped out on normal intraday noise on the first day of a hold. Once
activated, it fires when the drawdown from peak reaches `trailing_stop_pct`.

### 4.5 TAKE_PROFIT_STAGE_1 — NORMAL

**Trigger:** `unrealized_plpc >= take_profit_stage1_pct`  
  AND held for >= `minimum_hold_days` full trading days  
  AND `stage1_executed == False` for this position  
**Default threshold:** +2.0%  
**Recommended action:** Agent recommends trimming 50% of position. Human decides the
actual trim size at review time.  
**Output fields:** `suggested_trim_pct = 0.50`, `suggested_trim_qty` (calculated from
current broker position quantity), `breakeven_stop_recommendation = True`  
**Notes:** After stage 1 executes (tracked in persistent state), the system:
  - Records `stage1_executed = True` for this ticker
  - Sets `breakeven_stop_recommended = True` on the remaining position display
  - Continues tracking the remaining quantity toward Stage 2

### 4.6 TIME_STOP — LOW

**Trigger:** Position held > `time_stop_days` full trading days  
  AND `abs(unrealized_plpc) < time_stop_flat_threshold_pct`  
**Default thresholds:** `time_stop_days = 4`, `time_stop_flat_threshold_pct = 0.5`  
**Recommended action:** Review for exit. This is dead capital — the thesis did not play out.  
**Notes:** Not urgent. The system flags it as a "consider redeployment" review item, not
a forced exit.

### 4.7 SETUP_WARNING — INFO

**Trigger:** Current selection report for this ticker has `risk_flags` or a policy gate
with status `WARN`  
**Recommended action:** Review before adding any new exposure to this ticker.  
**Notes:** Not an exit signal on its own. Surfaces alongside `HOLD` to show the operator
that the thesis is intact but has caveats.

### 4.8 HOLD — no action needed

**Trigger:** None of the above rules are triggered.  
**No recommended action.** Position is on track.

---

## 5. Portfolio-Level Circuit Breakers

Evaluated against the portfolio account snapshot and the weekly baseline (portfolio equity
at Monday open in the current calendar week).

| Signal | Trigger | Effect on new entries |
|---|---|---|
| `WEEKLY_TARGET_APPROACH` | Weekly P&L ≥ +2.5% | Reduce recommended new position size to 5% |
| `WEEKLY_TARGET_REACHED` | Weekly P&L ≥ +3.0% | Block new entries until Monday open |
| `DAILY_CIRCUIT_BREAKER` | Daily P&L ≤ -3.0% | Risk-off: block new entries, flag all open positions for review |
| `WEEKLY_DRAWDOWN_LIMIT` | Weekly P&L ≤ -6.0% | Risk-off: block new entries |

"Weekly P&L" = `(current_equity - weekly_baseline_equity) / weekly_baseline_equity * 100`.  
"Daily P&L" = `(current_equity - daily_open_equity) / daily_open_equity * 100`.  
Weekly baseline resets at Monday market open. Daily baseline resets at each market open.

Circuit breaker state is included in every portfolio snapshot and must be consumed by
the entry/research pipeline to suppress new candidate promotions when triggered.

---

## 6. Minimum Hold & Re-entry Cooldown

### 6.1 Minimum Hold

- `minimum_hold_days = 2` trading days (unchanged from current)
- Counting rule: `trading_days_held` starts at 0 on the entry day and increments by 1
  after each NYSE session close. A position entered on Monday has `trading_days_held = 1`
  after Monday close, `= 2` after Tuesday close. Stage 1 fires when `trading_days_held >= 2`,
  meaning the earliest possible Stage 1 flag is at Tuesday close for a Monday entry.
- `STOP_LOSS` and `THESIS_BROKEN` are exempt — they fire immediately regardless of hold days.
- All other profit-taking signals (`TAKE_PROFIT_STAGE_1`, `TAKE_PROFIT_STAGE_2`,
  `TRAILING_STOP`, `TIME_STOP`) require `trading_days_held >= minimum_hold_days`.

### 6.2 Re-entry Cooldown

- After a `STOP_LOSS` exit is recorded on a ticker, the system records a cooldown timestamp.
- For `reentry_cooldown_hours = 24` after the exit, the Portfolio Manager emits a
  `REENTRY_BLOCKED` flag for that ticker.
- The entry pipeline must check this flag before promoting the ticker as a new BUY candidate.

---

## 7. Persistent State

All state files live under `research/state/portfolio/`. They are JSON, human-readable,
and safe to delete (the system rebuilds from broker positions on next run, though some
history — like entry timestamps — may be lost).

| File | Schema | Description |
|---|---|---|
| `high_water_marks.json` | `{ "AAPL": 2.34, ... }` | Peak unrealized P&L % per ticker |
| `stage1_executed.json` | `{ "AAPL": { "executed": true, "executed_at": "2026-05-29T..." } }` | Stage 1 trim tracking per ticker |
| `entry_timestamps.json` | `{ "AAPL": { "opened_at": "2026-05-27T...", "trading_days_held": 2 } }` | Entry time and trading day counter |
| `weekly_baseline.json` | `{ "week_start": "2026-05-26", "equity": 98500.00 }` | Portfolio equity at Monday open |
| `daily_baseline.json` | `{ "date": "2026-05-29", "equity": 99200.00 }` | Portfolio equity at day open |
| `reentry_cooldowns.json` | `{ "AAPL": { "blocked_until": "2026-05-30T..." } }` | Re-entry cooldown expiry per ticker |

---

## 8. Policy Dataclass

```python
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
    reduced_position_pct: float = 5.0       # used after weekly target approach
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

    # Broker / execution gates
    live_trading_enabled: bool = False
    broker_submit_enabled: bool = False
    allow_short_trades: bool = False
```

All fields must be loadable from:
1. Environment variables (`AGENCY_<UPPER_SNAKE>`)
2. A JSON policy file at `research/config/portfolio-policy.local.json`
3. The database (single-row `portfolio_policy` table, id=1)

Priority: env > file > db > dataclass defaults.  
Exception: `live_trading_enabled`, `broker_submit_enabled`, `allow_short_trades` are
env/file only — the UI cannot override them.

---

## 9. Output — Portfolio Snapshot

The `build_portfolio_snapshot()` function returns one dict matching the schema below.
This is the single output contract of the Portfolio Manager.

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-05-29T08:00:00Z",
  "mode": "PAPER",

  "circuit_breaker": {
    "active": false,
    "signals": [],
    "new_entries_blocked": false,
    "reduced_sizing_active": false,
    "recommended_position_pct": 10.0
  },

  "weekly_performance": {
    "week_start": "2026-05-26",
    "baseline_equity": 98500.00,
    "current_equity": 99450.00,
    "weekly_pl": 950.00,
    "weekly_return_pct": 0.965,
    "target_pct": 3.0,
    "pct_of_target_reached": 32.2
  },

  "daily_performance": {
    "date": "2026-05-29",
    "baseline_equity": 99200.00,
    "current_equity": 99450.00,
    "daily_pl": 250.00,
    "daily_return_pct": 0.252
  },

  "summary": {
    "position_count": 3,
    "urgent_count": 0,
    "action_needed_count": 1,
    "hold_count": 2,
    "gross_exposure_pct": 30.0,
    "available_capacity_pct": 50.0,
    "cash_pct": 70.0
  },

  "positions": [
    {
      "ticker": "AAPL",
      "side": "LONG",
      "quantity": 10,
      "market_value": 2150.00,
      "unrealized_pl": 50.00,
      "unrealized_plpc": 0.0238,
      "trading_days_held": 2,
      "stage1_executed": false,
      "high_water_mark_pct": 2.45,
      "trailing_stop_active": true,
      "trailing_stop_drawdown_pct": 0.07,
      "exit_signal": "TAKE_PROFIT_STAGE_1",
      "exit_priority": "NORMAL",
      "exit_reason": "Unrealized gain of 2.38% reached the +2.0% Stage 1 target after 2 trading days.",
      "secondary_signals": [],
      "recommendation": {
        "action": "TRIM",
        "suggested_trim_pct": 0.50,
        "suggested_trim_qty": 5,
        "breakeven_stop_recommendation": true,
        "rationale": "Secure half the position at target. Move stop to break-even on the remainder."
      },
      "reentry_cooldown_active": false,
      "classification": "ACTION_NEEDED",
      "urgency": "NORMAL",
      "pnl_label": "$50.00 / +2.38%",
      "thesis_validity": "Thesis still valid"
    }
  ],

  "reentry_blocks": {
    "TSLA": {
      "blocked_until": "2026-05-30T10:30:00Z",
      "reason": "Stop-loss exit recorded 2026-05-29T10:30:00Z"
    }
  }
}
```

---

## 10. Core Function Signature

```python
def build_portfolio_snapshot(
    *,
    broker_positions: list[dict],        # from Alpaca adapter
    account: dict,                        # from Alpaca adapter
    selection_reports: list[dict],        # latest cycle selection reports
    state_dir: Path,                      # path to research/state/portfolio/
    policy: PortfolioPolicy | None = None,
    generated_at: str | None = None,
) -> dict:
    ...
```

The function:
1. Loads all persistent state from `state_dir`
2. Evaluates portfolio-level circuit breakers
3. For each open position, evaluates exit rules in priority order
4. Builds and returns the snapshot dict
5. Updates persistent state (high-water marks, trading day counters)
6. Does NOT write state for stage1_executed or reentry_cooldowns — those are written
   only when the human confirms an action via the UI

---

## 11. Module Structure

```
src/agency/portfolio/
    __init__.py
    policy.py          # PortfolioPolicy dataclass + load_policy()
    state.py           # load/save all persistent state files
    exit_rules.py      # _evaluate_exit_signal() — all 8 signal types
    circuit_breaker.py # _evaluate_circuit_breakers()
    performance.py     # weekly/daily P&L calculation
    snapshot.py        # build_portfolio_snapshot() — main entry point
    _types.py          # typed dicts / dataclasses for internal use
```

The old `src/agency/services/portfolio_monitor.py` and the portfolio sections of
`src/agency/services/risk.py` are replaced by this module. The old files stay in
place until the new module passes all tests and the UI is wired to the new output.

---

## 12. Tests

### Unit tests — `tests/unit/test_portfolio_manager.py`

All tests use in-memory state (no file I/O). Policy is passed explicitly.

| Test | What it verifies |
|---|---|
| `test_stop_loss_fires_on_day_1` | STOP_LOSS triggers at -2% regardless of hold days |
| `test_thesis_broken_fires_on_day_1` | THESIS_BROKEN triggers when conviction < 0.40 |
| `test_take_profit_stage1_requires_minimum_hold` | Stage 1 does NOT fire on day 1 |
| `test_take_profit_stage1_fires_after_minimum_hold` | Stage 1 fires after 2 trading days at +2% |
| `test_take_profit_stage2_fires_after_stage1` | Stage 2 fires at +4% after stage 1 executed |
| `test_trailing_stop_dormant_below_activation_gate` | Trailing stop does not fire at +0.5% peak |
| `test_trailing_stop_activates_after_gate` | Trailing stop fires when peak ≥ 1.5% and drawback ≥ 1.5% |
| `test_time_stop_fires_after_4_flat_days` | TIME_STOP fires after 4 days and < ±0.5% move |
| `test_time_stop_does_not_fire_if_moving` | TIME_STOP suppressed if position moved > ±0.5% |
| `test_hold_when_no_rules_triggered` | Returns HOLD when no signal is triggered |
| `test_stage1_suppressed_when_already_executed` | No double-trigger of stage 1 |
| `test_circuit_breaker_weekly_target_reached` | `new_entries_blocked = True` at +3% weekly |
| `test_circuit_breaker_daily_loss` | `new_entries_blocked = True` at -3% daily |
| `test_circuit_breaker_weekly_target_approach` | `reduced_sizing_active = True` at +2.5% weekly |
| `test_weekly_drawdown_limit` | `new_entries_blocked = True` at -6% weekly |
| `test_reentry_cooldown_active` | `reentry_cooldown_active = True` within 24h of stop-loss exit |
| `test_reentry_cooldown_expired` | `reentry_cooldown_active = False` after 24h |
| `test_recommendation_fields_present_for_stage1` | Stage 1 output has `suggested_trim_pct = 0.50` and `suggested_trim_qty` |
| `test_policy_defaults_match_spec` | All PortfolioPolicy defaults match values in this spec |
| `test_snapshot_schema_valid` | Output dict matches the output schema in §9 |

### Integration tests — `tests/integration/test_portfolio_state.py`

| Test | What it verifies |
|---|---|
| `test_high_water_marks_persist_and_load` | write → read roundtrip is correct |
| `test_weekly_baseline_resets_on_monday` | new week → baseline equity updates |
| `test_daily_baseline_resets_on_market_open` | new day → daily baseline updates |
| `test_state_dir_missing_returns_empty_defaults` | graceful degradation when state files absent |

---

## 13. Acceptance Criteria

1. All 20 unit tests pass.
2. All 4 integration tests pass.
3. `build_portfolio_snapshot()` output validates against the §9 schema for:
   - an empty portfolio (no positions)
   - a portfolio with all 8 signal types triggered across 8 positions
   - a portfolio with all 4 circuit breakers active simultaneously
4. `PortfolioPolicy.from_env()` correctly loads every field from env vars.
5. `PortfolioPolicy` loads from `portfolio-policy.local.json` when file exists.
6. No import of broker, FastAPI, or UI code inside `src/agency/portfolio/`.
7. No file in `src/agency/portfolio/` exceeds 250 lines.

---

## 14. What Codex Must NOT Do

- Use the naming convention `AGENCY_<UPPER_SNAKE_CASE_FIELD_NAME>` for all env vars
  (e.g. `AGENCY_TAKE_PROFIT_STAGE1_PCT`, `AGENCY_TIME_STOP_DAYS`). Do not invent
  alternative prefixes.
- Do not auto-execute any orders or write to the broker adapter.
- Do not modify `src/agency/services/portfolio_monitor.py` or `src/agency/services/risk.py`
  — those files stay untouched until the new module is wired in.
- Do not add a database dependency to `exit_rules.py` or `circuit_breaker.py` — those
  functions are pure (take inputs, return outputs, no I/O).
- Do not use `datetime.now()` without `tz=UTC`.
