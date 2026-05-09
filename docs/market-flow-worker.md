# Market-Flow Analysis Worker

The market-flow analysis worker is the research-side agent for Massive/Polygon
`stock_trades`. It turns delayed confirmed stock prints into reusable features,
tests those features against forward returns, sweeps thresholds, and writes a
runtime calibration recommendation.

The worker does not make live trading decisions. It produces evidence about
whether market-flow lanes should stay context-only or become eligible for more
runtime weight after holdout validation.

## Inputs

- `stock_trades` parquet and manifest from Massive/Polygon.
- `prices_daily` parquet and manifest for forward-return labels.
- A static ticker list for the calibration run.

## Command

```powershell
.\.venv\Scripts\python research\scripts\run_market_flow_worker.py `
  --start 2024-01-01 `
  --end 2026-05-08 `
  --ticker AAPL `
  --ticker MSFT `
  --ticker NVDA `
  --horizon 5 `
  --horizon 20 `
  --output-root research\results\t110-market-flow-worker
```

Useful controls:

- `--lookback-days`: trade-print lookback used to build features.
- `--step-days`: evaluation cadence.
- `--threshold`: repeatable positive pressure thresholds to test.
- `--min-train-observations` and `--min-test-observations`: coverage floors
  before any runtime-weight recommendation is allowed.

## Outputs

- `market-flow-features.csv`: feature panel by date and ticker.
- `market-flow-ic.csv`: H1-style IC rows for each feature and horizon.
- `market-flow-threshold-sweep.csv`: train/test threshold precision and mean
  forward-return checks.
- `market-flow-calibration.json`: machine-readable runtime guidance.
- `market-flow-calibration.md`: human-readable summary.

## Runtime Use

The runtime lanes are already opt-in:

- `buy_sell_pressure`
- `block_trade_pressure`

Both remain inferred lanes. The actionability gate requires confirmed
corroboration from another source before an inferred market-flow signal can help
produce a `WATCH`. The deterministic engine includes low default weights for
these lanes; the worker tells us whether those weights should stay at context
levels or be increased after real holdout evidence.

## Interpretation

Treat `market_flow_weight_eligible` as permission to run a reviewed paper test,
not as permission to trade live. Treat `context_only_until_more_coverage` as the
normal initial state until the Massive historical pull covers enough dates and
tickers.
