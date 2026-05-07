# T24: Universe / horizon / threshold sweep tool

**Owner:** codex
**Phase:** 1 (H5 sweep)
**Estimate:** medium (2-6h)
**Dependencies:** T10, T23

## Goal
Create a deterministic parameter-sweep helper over the walk-forward harness.

## Outputs
- `research/src/evaluation/sweep.py`
  - `SweepPoint`
  - `run_parameter_sweep(...)`
  - threshold wrapper for signal functions
- `research/scripts/run_walk_forward_sweep.py`

## Acceptance Criteria
1. Sweeps holding period, max positions, score threshold, sizing rule, exposure, and costs.
2. Uses the same walk-forward harness as H4.
3. Returns a sortable DataFrame with Sharpe, CAGR, max drawdown, turnover, and chosen parameters.
4. Thresholds filter low-conviction signal scores before target weights are computed.

## Tests Required
- Unit: threshold wrapper removes low absolute scores.
- Unit: sweep returns one row per parameter point.
- Unit: best row can be selected by Sharpe subject to a max drawdown ceiling.

## Out of Scope
- Running expensive real sweeps.
- Auto-updating production defaults.
