# T115: Massive Historical Market-Flow Backtest

**Status:** complete
**Phase:** 4 validation

## What Changed

- Ran the market-flow worker against the local Massive/Polygon `stock_trades`
  manifest for the active 168-ticker universe.
- Wrote backtest artifacts under
  `research/results/t115-massive-market-flow-backtest/`.
- Extended the calibration markdown/JSON with coverage diagnostics so the
  verdict explains whether a lane has enough feature, IC, and holdout coverage.

## Result

- Feature rows: 168.
- Feature dates: 1.
- Feature tickers: 168.
- IC observations: 0.
- Max holdout selections: 0.
- Verdict: `context_only_until_more_coverage`.

The Massive lane is operational as context evidence, but the available
historical trade-print coverage is not deep enough to promote market-flow lanes
to higher runtime weight yet.

## Validation

- `run_market_flow_worker.py` wrote all expected T115 artifacts.
- Focused market-flow, Massive ingestion, readiness, dashboard, and T136 tests
  passed: `98 passed`.
- Focused ruff check passed.
- Focused mypy check passed.
