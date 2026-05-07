# T22: H1 verdict synthesis tool

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** small-medium (2-6h)
**Dependencies:** T21

## Goal
Convert H1 IC result tables into lane-level verdicts with multiple-comparison correction.

## Context
The research brief requires one verdict per lane: survive, drop, or inconclusive, with IC, t-stat, IR, and adjusted significance. This tool produces that table deterministically.

## Outputs
- `research/src/evaluation/verdicts.py`
  - `synthesize_horizon_verdicts(...)`
  - `summarize_signal_verdicts(...)`
  - `verdicts_to_markdown(...)`

## Acceptance Criteria
1. Applies Bonferroni and Benjamini-Hochberg corrections.
2. Marks significant positive IC rows as survive.
3. Marks significant negative IC rows as inverse candidates.
4. Marks underpowered rows as inconclusive.
5. Produces a compact Markdown summary for `findings.md`.

## Tests Required
- Unit: p-value adjustments are applied in original row order.
- Unit: significant positive, significant negative, weak, and underpowered rows get expected verdicts.
- Unit: signal-level summary chooses the strongest available horizon.

## Out of Scope
- Human interpretation of economic plausibility.
- Updating `docs/research-brief.md` findings sections with real results.
