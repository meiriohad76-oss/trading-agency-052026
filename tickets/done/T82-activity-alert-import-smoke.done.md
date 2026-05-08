# T82: Activity alert import smoke test

**Owner:** codex
**Phase:** 1 research expansion
**Status:** done

## Goal

Make real paid/provider activity-alert exports easy to test before importing
them into the live local research dataset.

## Delivered

- Added an isolated smoke-test script for local activity-alert CSV imports.
- Added compact JSON/Markdown coverage summaries with ticker, source,
  direction, alert-type, notional, premium, and timestamp coverage.
- Added unit coverage for the summary verdicts and rendered Markdown.
- Updated live research readiness instructions with the smoke-test command
  and the follow-up live import command.

## Acceptance Notes

1. The smoke path writes under `research/results/` and does not mutate
   `research/data/parquet` or live manifests.
2. The script exits nonzero when the import is blocked or lacks confirmed
   evidence.
3. Use a real TradeVision/provider export by replacing the example CSV path in
   the documented command.
