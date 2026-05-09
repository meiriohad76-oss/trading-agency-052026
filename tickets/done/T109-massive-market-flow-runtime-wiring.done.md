# T109: Massive Market-Flow Runtime Wiring

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Make Massive/Polygon stock-trade pressure usable in the paper agency without
blocking the default stocks-only workflow.

## What Changed

- Added `stock_trades` to runtime dataset configs and optional runtime signals.
- Added Live Config and Provider Readiness checks for `POLYGON_API_KEY` or
  `MASSIVE_API_KEY` when `stock_trades` is enabled.
- Updated `.env.example`, live refresh examples, provider docs, deployment docs,
  findings, and phase status.
- Kept market-flow lanes inferred/context-first until empirical H1 coverage
  exists.

## Validation

- Focused runtime-cycle, readiness, provider-readiness, research-batch, and
  refresh-batch tests cover the opt-in wiring.
