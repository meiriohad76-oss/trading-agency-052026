# T90: Current-Date Paper Cycle Reviewability

**Status:** complete
**Phase:** 4 validation unblock

## Goal

Make the first current-date paper cycle reviewable after live data refreshes
instead of leaving it mechanically blocked by unused sources or review-only rows.

## What Changed

- Runtime risk now evaluates only source-health rows used by the latest
  selection reports, so unused stale sources do not degrade risk decisions.
- Position-cap and gross-exposure checks now apply only to trade actions, not
  `WATCH` or `NO_TRADE` rows.
- Same-day daily-bar manifests remain fresh for current-date paper cycles even
  though their manifest timestamps are date-only midnight values.

## Validation

- Unit coverage for ignoring unused stale sources in runtime risk.
- Unit coverage that `WATCH` rows do not spend trade capacity.
- Unit coverage that same-day daily bars stay fresh through the validation day.
- Live current-date paper cycle persisted with `ready_for_paper_validation`.
