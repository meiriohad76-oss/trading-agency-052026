# T89: Alpaca Current-Date Refresh Hardening

**Status:** complete
**Phase:** 4 validation unblock

## Goal

Make the Alpaca daily-bar path reliable enough for current-date local validation
on Windows.

## What Changed

- Updated the Alpaca downloader to use the Windows trust store when `truststore`
  is available, matching the SEC client TLS behavior.
- Cleared transient raw DataFrame attrs from normalized Alpaca bars so pandas can
  write Parquet files without trying to serialize Python `date` objects.
- Fixed data-refresh job duration stamps so completed jobs report elapsed
  subprocess time instead of the pre-run timestamp delta.
- Kept slow dataset ETA baselines from being replaced by averages from quick
  completed jobs.
- Added SEC transport-error retries so transient Form 4 read failures do not
  fail the whole refresh immediately.
- Treated same-day daily-bar manifests as fresh for the current paper cycle,
  avoiding false stale-source blocks caused by date-only midnight timestamps.

## Validation

- Focused Alpaca unit coverage for TLS context selection and Parquet-safe
  normalized output attrs.
- Batch unit coverage that elapsed command duration is measured after the runner
  finishes.
- ETA unit coverage that slow running datasets keep their baseline estimate.
- SEC client unit coverage for retrying transient read errors.
- Live runtime coverage that same-day daily prices stay fresh through the
  current validation day.
- Live focused `prices_daily` refresh succeeded against Alpaca through
  `2026-05-08`.
