# T111: Market-Flow H1 Evaluator

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Evaluate market-flow features against forward returns before any runtime-weight
increase.

## What Changed

- The market-flow worker computes H1-style IC rows for each feature and horizon.
- Outputs are written to `market-flow-ic.csv`.

## Validation

- Unit coverage runs the worker against deterministic fixture data and verifies
  calibration artifacts.
