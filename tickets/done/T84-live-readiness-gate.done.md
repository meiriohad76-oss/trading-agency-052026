# T84: Live paper readiness gate

**Owner:** codex
**Phase:** 3 provisional runtime
**Status:** done

## Goal

Make the latest persisted PIT-backed paper cycle inspectable as a single
readiness verdict instead of forcing the operator to infer readiness from raw
source-health, selection, risk, and metrics rows.

## Delivered

- Added a pure live-readiness evaluator for source health, latest-cycle
  selection reports, and latest-cycle risk decisions.
- Added `/status/live-readiness`.
- Added readiness gauges to `/metrics`.
- Added a Command-page Live Readiness panel with blocker rows.
- Updated first-version and deployment inspection docs.
- Added unit and e2e coverage for the evaluator, endpoint, metrics, and page.

## Acceptance Notes

1. The gate remains paper-only and does not enable broker submission.
2. Stale, unavailable, or rate-limited sources make the cycle context-only.
3. A cycle is ready only when source health is clean, at least one candidate is
   reviewable, and risk has at least one non-blocked decision.
