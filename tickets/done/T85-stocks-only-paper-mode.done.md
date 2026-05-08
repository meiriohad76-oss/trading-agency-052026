# T85: Stocks-only paper mode

**Owner:** codex
**Phase:** 4 validation prep
**Status:** done

## Goal

Let the first user-test loop proceed without an unusual-options provider by
making the default PIT runtime cycle stocks-only while keeping the
options/activity-alert lane available for later provider integration.

## Delivered

- Changed the default runtime lane set to stocks-only.
- Kept `activity_alerts` available as an explicit optional lane.
- Added replay freshness support for PIT paper tests.
- Updated readiness to evaluate source health used by the latest cycle, so stale
  optional provider rows do not block stocks-only replay.
- Documented the stocks-only replay inspection command.

## Acceptance Notes

1. Options/unusual-activity provider work is deferred, not removed.
2. The first stocks-only replay can reach `ready_for_paper_validation`.
3. Current-date live validation still needs a market-data provider that returns
   bars after `2025-12-31` in this environment.
