# T21: H1 IC evaluator

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T09, T10, T11-T20

## Goal
Create a reusable H1 evaluation utility that runs PIT-scoped signal functions, aligns their scores with forward returns, and computes IC statistics by horizon.

## Context
The signal lanes now exist, but the project needs a repeatable way to judge whether any lane has measurable edge. This should be importable from notebooks and runnable from scripts.

## Outputs
- `research/src/evaluation/h1_ic.py`
  - `H1ICConfig`
  - `H1ICReport`
  - `evaluate_signal_ic(...)`
- `research/scripts/run_h1_ic.py` CLI for producing CSV/Markdown summaries.

## Acceptance Criteria
1. Signal generation is scoped through `ScopedPITLoader`.
2. Forward returns are computed from loader price data, not raw parquet.
3. Multiple horizons are supported.
4. Empty or missing signal dates are handled cleanly.
5. Output includes mean IC, IC std, t-stat, IR, p-value, and observation count.

## Tests Required
- Unit: a synthetic signal positively correlated with future returns produces positive IC.
- Unit: signal loader cannot peek beyond its scoped `as_of`.
- Unit: missing scores or insufficient data produce rows without crashing.

## Out of Scope
- Actual long-running research run over all real datasets.
- Notebook rendering.
