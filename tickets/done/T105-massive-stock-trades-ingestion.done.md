# T105: Massive Stock Trades Ingestion

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Add an opt-in local refresh path for Massive/Polygon delayed stock trade prints.

## What Changed

- Added `research/scripts/pull_massive_stock_trades.py`.
- Added `market_flow.massive` normalization for Massive/Polygon trade rows.
- Added partitioned `stock_trades` parquet storage and manifest writing.
- Wired `stock_trades` into refresh-batch config, jobs, status, ETA, and
  live-config parsing.

## Validation

- Unit coverage for short-field normalization, provenance, delayed
  `timestamp_as_of`, storage, and refresh job blocking.
