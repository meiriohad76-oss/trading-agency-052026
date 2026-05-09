# T114: Market-Flow Runtime Calibration

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Feed market-flow research results back into the selection workflow conservatively.

## What Changed

- Added `market-flow-calibration.json` and `.md` outputs.
- Added low default deterministic weights for `buy_sell_pressure`,
  `block_trade_pressure`, and `options_anomaly`.
- Added actionability rules so inferred market-flow lanes can participate only
  when confirmed corroboration exists.
- Documented the worker in `docs/market-flow-worker.md`.

## Validation

- Unit coverage verifies inferred market-flow actionability with confirmed
  corroboration and worker calibration output.
