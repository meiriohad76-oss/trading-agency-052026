# T115: Massive Historical Market-Flow Backtest

**Owner:** codex
**Phase:** 4 (validate)
**Estimate:** medium
**Dependencies:** T105-T114, local `MASSIVE_API_KEY` or `POLYGON_API_KEY`

## Goal

When Massive/Polygon historical stock-trade data is available, run a real
historical backtest for the market-flow lanes and decide whether
`buy_sell_pressure` or `block_trade_pressure` should remain context-only or
become eligible for runtime weight in paper review.

## Context

T105-T109 wired delayed stock-trade ingestion and inferred market-flow runtime
lanes. T110-T114 added the market-flow analysis worker, IC checks, threshold
sweeps, holdout validation, and calibration artifacts. This ticket is the live
data validation pass that uses actual Massive coverage.

The agency is not focused on real-time trading. Massive trade prints should be
used as historical/near-real-time evidence for paper-review selection, not as a
standalone broker-execution trigger.

## Inputs

- `MASSIVE_API_KEY` or `POLYGON_API_KEY` in local `.env`.
- `research/config/live-refresh.local.json` with `stock_trades` enabled.
- Massive/Polygon `stock_trades` parquet and manifest from
  `research/scripts/pull_massive_stock_trades.py` or the refresh batch.
- Existing `prices_daily` parquet and manifest for forward-return labels.
- Existing market-flow worker:
  `research/scripts/run_market_flow_worker.py`.
- Target ticker universe for the first validation pass.

## Outputs

- Local historical `stock_trades` parquet partitions and manifest.
- Backtest artifacts under `research/results/t115-massive-market-flow-backtest/`:
  - `market-flow-features.csv`
  - `market-flow-ic.csv`
  - `market-flow-threshold-sweep.csv`
  - `market-flow-calibration.json`
  - `market-flow-calibration.md`
- A compact markdown summary suitable for review/commit, excluding raw trade
  data.
- Updated runtime guidance for `buy_sell_pressure` and `block_trade_pressure`.
- Updated docs if the result changes paper-review expectations.

## Implementation Plan

1. Pull a bounded historical sample for the configured universe.
2. Confirm `stock_trades` manifests report enough dates, tickers, rows, and no
   blocking issues.
3. Build market-flow features using only point-in-time available prints and the
   configured delayed-data lag.
4. Compute forward returns for 5-day and 20-day horizons.
5. Run IC checks and threshold sweeps with train/test separation.
6. Require minimum train and holdout sample sizes before allowing runtime
   weighting.
7. Keep both market-flow lanes context-only if holdout evidence is weak,
   unstable, or under-covered.
8. If a lane passes, update calibration guidance for paper-review weighting only;
   do not enable live trading.

## Acceptance Criteria

1. Historical Massive refresh runs without blocking failures for the selected
   ticker/date scope.
2. `stock_trades` manifest records row count, ticker count, date range, source,
   and issues.
3. Backtest uses point-in-time inputs and does not leak future returns into
   feature construction.
4. Calibration artifact clearly states one of:
   `market_flow_weight_eligible`, `context_only_until_retest`, or
   `context_only_until_more_coverage`.
5. Runtime guidance includes suggested threshold, horizon, holdout precision,
   holdout mean return, sample counts, and suggested weight for each lane.
6. No raw Massive trade parquet or large result artifacts are committed.
7. Paper-review behavior is changed only if holdout validation passes.

## Tests Required

- `ruff check .`
- `mypy src research\src`
- `pytest tests\unit\test_massive_stock_trades.py tests\unit\test_market_flow_worker.py tests\unit\test_market_flow_signals.py`
- Manual: run a small live Massive pull for 2-3 tickers and confirm the worker
  writes all expected artifacts.
- Manual: review `market-flow-calibration.md` before changing runtime weights.

## Out of Scope

- Options-flow backtesting.
- True dark-pool provider labels beyond inferred off-exchange/TRF prints.
- Live order execution or broker automation.
- Storing or committing raw Massive data.

## Notes

The initial backtest can start with a narrow universe and widen after the pull
speed, quota limits, and historical depth are understood. If Massive plan limits
make a broad historical pull expensive, prefer a staged pull: 10 high-liquidity
tickers first, then expand to the production universe.
