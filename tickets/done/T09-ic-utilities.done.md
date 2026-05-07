# T09: IC and statistical utilities

**Owner:** claude-code
**Phase:** 1 (research)
**Estimate:** medium (2-6h)
**Dependencies:** T01, T04

## Goal
Implement the statistical primitives used by every H1 hypothesis test: information coefficient (Spearman), IC standard error and t-stat, IC information ratio (IR), forward-return computation, and multiple-comparison correction.

## Context
Statistical correctness here is non-negotiable. A subtle off-by-one in forward returns or a survivorship-tainted alignment will silently bias every signal verdict. Hypothesis testing without multiple-comparison correction will produce false-positive lanes that look real but aren't. Reference: `research-brief.md` H1 method, §6 Risks → Multiple-comparisons overfit.

## Inputs
- T04's PIT loader (for prices).
- Standard scientific stack: numpy, pandas, scipy, statsmodels.

## Outputs
- `research/src/statistics/forward_returns.py`:
  - `compute_forward_returns(prices: DataFrame, horizons: list[int]) -> DataFrame` — given OHLCV with multi-ticker rows, returns per-(date, ticker) forward returns at each horizon. Uses adjusted close. PIT-correct (forward returns at date D use prices D+1 through D+horizon, not anything before D).
- `research/src/statistics/ic.py`:
  - `compute_ic(scores: Series, forward_returns: Series) -> ICResult` — Spearman rank correlation per cross-section, returns time-series of IC.
  - `ICResult` dataclass: `ic_series`, `mean_ic`, `ic_std`, `t_stat`, `information_ratio`, `n_observations`.
  - `compute_ic_panel(scores: DataFrame, forward_returns: DataFrame) -> ICResult` — panel IC across multiple tickers and dates.
- `research/src/statistics/multiple_comparisons.py`:
  - `bonferroni_adjust(p_values: list[float]) -> list[float]`
  - `benjamini_hochberg_adjust(p_values: list[float]) -> list[float]`
- `research/src/statistics/turnover_costs.py`:
  - `apply_costs(returns: Series, turnover: Series, bps: float) -> Series` — adjust returns for transaction costs given turnover and per-side cost in basis points.

## Acceptance Criteria
1. Forward returns are PIT-correct: at date D with horizon=5, the return uses prices on D+1 to D+5 (not D-4 to D).
2. IC computation handles missing data (NaN scores or NaN returns) by excluding the (date, ticker) pair from that cross-section, not the whole date.
3. `ICResult.t_stat` matches manual computation on a fixture (`mean_ic / (ic_std / sqrt(n_observations))`).
4. Multiple-comparison adjustment matches reference implementations (compare to `statsmodels.stats.multitest.multipletests` for both methods).
5. Turnover-cost adjustment produces expected output on a known fixture (e.g., 100% turnover at 5 bps round-trip = -10 bps per period).
6. All functions are pure (no I/O, no clock reads). Random seeds, if needed, are injected.
7. Type hints throughout; mypy strict passes.
8. Comprehensive docstrings explaining the statistical contract and PIT assumptions.

## Tests Required
- `tests/unit/test_forward_returns.py`: known fixture, manual computation, assert match.
- `tests/unit/test_ic.py`:
  - Perfect-correlation fixture: IC = 1.0.
  - Anti-correlation fixture: IC = -1.0.
  - No-correlation fixture: IC ≈ 0 with high p-value.
  - Panel IC matches per-cross-section averaging.
- `tests/unit/test_multiple_comparisons.py`: compare against `statsmodels` for known p-value lists.
- `tests/unit/test_turnover_costs.py`: known fixture, manual cost calc, assert match.
- Property-based test (hypothesis library): ICResult.t_stat is invariant under linear scaling of inputs.

## Out of Scope
- The actual signal generators (one ticket per lane in later batch).
- The walk-forward backtest harness (T10).
- Visualization (notebooks handle plotting using matplotlib/plotly).

## Notes for Implementer
- Use scipy.stats.spearmanr or rank + Pearson; prefer rank-based to handle non-linear monotone relationships. Document choice.
- Be careful with the `nan_policy` argument — `omit` is what we want, but the IC's `n_observations` should reflect the actually-used pairs.
- The IC standard error formula: when each cross-section IC is treated as an iid observation, `ic_std = std(ic_series) / sqrt(len(ic_series))`. Document this and the Newey-West alternative for autocorrelated IC series.
- Turnover convention: `turnover = sum(|w_t - w_{t-1}|) / 2` per period (one-sided turnover). Document.
- These functions are used in critical paths; aim for 100% test coverage.
