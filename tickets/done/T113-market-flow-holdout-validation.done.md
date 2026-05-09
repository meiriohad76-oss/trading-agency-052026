# T113: Market-Flow Holdout Validation

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Avoid optimizing market-flow signals on the same data used for approval.

## What Changed

- The worker splits feature dates into train and holdout windows.
- Runtime eligibility requires minimum train and test observation counts.
- Holdout precision and mean return decide whether a feature is eligible for
  runtime weight.

## Validation

- Unit coverage checks that insufficient coverage keeps the verdict
  context-only.
