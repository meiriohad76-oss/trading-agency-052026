# T87: Data Loading Progress

**Status:** complete
**Phase:** 4 validation usability

## Goal

Make long data refreshes visible to the user with progress, current dataset,
and ETA instead of leaving the dashboard silent while sources load.

## What Changed

- Data refresh batches now write incremental `data-refresh-status.json` updates
  before each job starts, while a job is running, and after each job finishes.
- Status JSON now includes per-job timing plus a `progress` block with state,
  percent complete, current dataset, and ETA.
- The default refresh output is now `research/results/latest-data-refresh/`.
- Added `/status/data-refresh` for the dashboard to read the latest progress.
- Added a Command-page Data Loading panel with a progress bar, ETA, job count,
  current dataset, and updated timestamp.
- Added lightweight polling JavaScript for live progress updates.

## Validation

- Unit coverage for incremental batch progress writes.
- Unit coverage for status-file parsing and `/status/data-refresh`.
- Dashboard rendering coverage for the new Data Loading panel and static script.
