# T112: Market-Flow Threshold Optimizer

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Sweep market-flow pressure thresholds and measure success rate/mean return.

## What Changed

- Added threshold sweeps for positive market-flow pressure.
- Reports train/test selected counts, positive-return precision, mean return,
  and median return.
- Outputs are written to `market-flow-threshold-sweep.csv`.

## Validation

- Fixture tests verify the worker can recommend runtime eligibility only when
  threshold coverage passes train and holdout checks.
