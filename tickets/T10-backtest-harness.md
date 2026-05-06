# T10: Walk-forward backtest harness

**Owner:** claude-code
**Phase:** 1 (research)
**Estimate:** large (6h+)
**Dependencies:** T04, T09

## Goal
Implement the walk-forward backtesting engine that drives H4 (realistic strategy profile) and H5 (universe / horizon / threshold sweep). One canonical engine; every backtest in v2 runs through it.

## Context
This is the second load-bearing component after the PIT loader. A bug here invalidates the entire research output. Walk-forward methodology (rolling re-estimation, no peeking forward) is the difference between a real backtest and self-deception. Reference: `research-brief.md` H4 method, §6 Risks.

## Inputs
- T04 PIT loader (only data interface).
- T09 statistical utilities.
- Optional: `vectorbt` library for the underlying simulation engine (recommended).

## Outputs
- `research/src/backtests/walk_forward.py`:
  - `WalkForwardConfig` dataclass: in-sample window, out-of-sample window, step size, rebalance frequency, max positions, position sizing rule, max gross exposure, cost model (bps per side, slippage bps).
  - `WalkForward` class: takes a config, a signal-generation callable `signal_fn(as_of, universe) -> dict[ticker, score]`, and a date range. Iterates: for each rebalance date, get current universe (from PIT loader), call `signal_fn` with `as_of=rebalance_date`, rank/select positions, simulate returns until next rebalance, repeat.
- `research/src/backtests/portfolio.py`:
  - `Portfolio` model: positions, equity curve, trade log.
  - Position sizing rules: `equal_weight`, `score_weighted`, `volatility_targeted`.
- `research/src/backtests/metrics.py`:
  - `compute_performance(equity_curve: Series, trades: DataFrame) -> PerformanceReport` — Sharpe, CAGR, max DD, recovery time, hit rate, average win/loss, turnover, time-in-market.
- `research/src/backtests/regimes.py`:
  - `subset_by_regime(returns: Series, regime_dates: DataFrame) -> dict[str, Series]` — split returns by predefined regime windows (2020 COVID, 2022 bear, etc.) for stress testing.

## Acceptance Criteria
1. Walk-forward correctness: at simulation time T, `signal_fn` is called with `as_of=T` and may only access PIT-correct data. The harness enforces this by passing the loader scoped to T.
2. No look-ahead: a synthetic `signal_fn` that "peeks forward" (uses prices at T+1) must be detectable by tests.
3. Realistic costs applied: round-trip transaction cost is applied on every position change; slippage is applied on entry and exit.
4. Re-running the same config + signal_fn produces byte-identical results (deterministic).
5. Performance metrics match a hand-computed fixture on a known toy strategy (e.g., "always long SPY" → returns match SPY's actual returns minus costs).
6. The harness handles the edge cases: ticker delisted mid-window (force-close), insufficient capital for sizing rule (warn + skip), zero candidates on a rebalance date (stay flat).
7. Memory profile fits on a Pi for the full universe over 7 years (target: < 4 GB peak).

## Tests Required
- `tests/unit/test_walk_forward.py`:
  - Toy strategy: random scores, reproducibility.
  - PIT enforcement: synthetic signal_fn that tries to access future data raises.
  - Cost application: known turnover * cost = known drag on returns.
  - Position sizing rules: each rule produces expected weights on a fixture.
- `tests/unit/test_metrics.py`: known equity curves, known performance metrics.
- `tests/integration/test_walk_forward_real_data.py`: trivial buy-and-hold-SPY strategy run through the harness should reproduce SPY's actual returns within slippage tolerance.
- Property test: total return = sum of period returns - sum of costs (within rounding).

## Out of Scope
- Multi-strategy portfolio combination (Phase 2 if needed).
- Live trading integration — the harness is research-only.
- Margin/leverage simulation — Phase 1 is cash-only long/short.
- Benchmark-relative metrics beyond Sharpe (Phase 1 stays absolute).

## Notes for Implementer
- vectorbt is the recommended underlying engine; it handles the simulation efficiently and supports walk-forward natively. Wrap it; don't expose its API directly.
- Walk-forward window choice: start with 2-year IS / 6-month OOS / monthly step as defaults. Make configurable.
- The `signal_fn` contract is: `def signal_fn(as_of: date, universe: set[str], loader: PITLoader) -> dict[str, float]`. The loader passed in is scoped — it cannot return data with `timestamp_as_of > as_of`. Implement the scoping.
- For long/short: scores can be positive (long) or negative (short); top-N positive go long, top-N negative go short, sized to net or gross target per config.
- Slippage convention: half-spread on entry + half-spread on exit. Total round-trip = full spread. Plus fixed slippage in bps.
- Document all assumptions visible in the API docstring; backtest readers must understand what's modeled and what's not.
- This module gets thorough review; budget time for the review cycle.
