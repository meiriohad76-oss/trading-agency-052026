# T23: Realistic strategy profile tool

**Owner:** codex
**Phase:** 1 (H4 realistic profile)
**Estimate:** medium (2-6h)
**Dependencies:** T10, T21

## Goal
Wrap the walk-forward harness into a reusable profile report that produces the H4 metrics table.

## Outputs
- `research/src/evaluation/profile.py`
  - `StrategyProfile`
  - `profile_strategy(...)`
  - `profile_to_frame(...)`

## Acceptance Criteria
1. Runs through `WalkForward`.
2. Computes `PerformanceReport`.
3. Includes an honest comparison to the 3% weekly planning target.
4. Produces a single-row DataFrame suitable for CSV/Markdown output.

## Tests Required
- Unit: profile report matches a toy strategy's performance.
- Unit: weekly target gap is computed deterministically.

## Out of Scope
- Real production strategy selection.
- LLM review.
