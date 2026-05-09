# T110: Market-Flow Feature Worker

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Create a dedicated worker that turns Massive/Polygon `stock_trades` into a
research-ready market-flow feature panel.

## What Changed

- Added `market_flow.features`.
- Added `market_flow_feature_frame` for reusable buy/sell and block/off-exchange
  feature generation.
- Added `research/scripts/run_market_flow_worker.py`.

## Validation

- Unit coverage confirms feature generation from fixture trade prints.
