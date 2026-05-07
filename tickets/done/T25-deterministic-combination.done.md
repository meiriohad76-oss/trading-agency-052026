# T25: Deterministic signal combination

**Owner:** codex
**Phase:** 1 (H2 combination)
**Estimate:** medium (2-6h)
**Dependencies:** T11-T24

## Goal
Create a deterministic signal-combination utility that turns multiple lane score functions into one weighted score function.

## Context
H2 asks whether a weighted combination of surviving lanes beats the best single lane. The combination must be deterministic, PIT-safe, and easy to perturb during sweeps.

## Outputs
- `research/src/evaluation/combination.py`
  - `SignalWeight`
  - `combine_signal_scores(...)`
  - `combined_signal_fn(...)`
  - `weights_from_ic(...)`

## Acceptance Criteria
1. Each component signal receives the same `as_of`, universe, and scoped loader.
2. Scores are z-normalized per lane before weighted averaging.
3. Missing tickers in one lane do not remove them from all lanes.
4. IC-derived weights ignore non-positive or missing IR values.
5. Output is deterministic.

## Tests Required
- Unit: weighted combination matches a hand-computed fixture.
- Unit: missing lane scores are handled cleanly.
- Unit: IC table produces expected normalized weights.

## Out of Scope
- Choosing final production weights.
- Regime-conditioned weights.
