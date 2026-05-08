# T83: Live PIT runtime cycle

**Owner:** codex
**Phase:** 3 provisional runtime
**Status:** done

## Goal

Wire local PIT research data into the paper runtime cycle so the dashboard can
show real data-derived paper candidates instead of only deterministic demo seed
rows.

## Delivered

- Added a PIT-backed runtime cycle builder for local research manifests.
- Added source-health generation from dataset manifests.
- Added research-score to `SignalResult` adaptation for runtime lanes.
- Added a `scripts/run_live_runtime_cycle.py` command that can persist the
  generated cycle into Postgres and write compact run summaries.
- Added unit coverage for healthy and unavailable-source runtime paths.

## Acceptance Notes

1. The runner remains paper-only and never submits broker orders.
2. Missing or stale data degrades/blocks through the existing evidence,
   deterministic, risk, and execution-preview gates.
3. Real live behavior still depends on refreshing local PIT data close to the
   intended `as_of` date.
