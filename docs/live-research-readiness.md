# Live Research Readiness

T72/T73 need live data inputs before empirical refresh and calibration can run.
Use this checklist to make those inputs explicit.

## Required Inputs

- `SEC_USER_AGENT` in `.env`
  - Format should identify the project and a contact email.
- RSS feeds
  - Pass as `SOURCE,URL` or `SOURCE,TICKER,URL`.
- 13F filer CIKs
  - Pass one or more institutional filer CIKs.
- CUSIP map
  - JSON object mapping CUSIP strings to tickers.

## Dry Run

Copy the template and replace example values:

```powershell
Copy-Item research\config\live-refresh.example.json research\config\live-refresh.local.json
```

Then run:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --dry-run `
  --output-root research\results\t72-readiness
```

The run is ready when `data-refresh-status.json` reports:

- `blocked: false`
- `failed: false`
- each job status is `planned` in dry-run mode

## Live Refresh

After the dry run is unblocked:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --no-dry-run `
  --output-root research\results\t72-live
```

Raw and parquet outputs stay local-only. Commit only compact status/result
artifacts that are small enough to review.

Validate the live outputs:

```powershell
.\.venv\Scripts\python research\scripts\check_live_refresh_outputs.py `
  --status-path research\results\t72-live\data-refresh-status.json
```

The command exits nonzero if the batch failed, any job did not pass, a manifest
has zero rows, or a manifest reports issues.

Write the compact summary artifact:

```powershell
.\.venv\Scripts\python research\scripts\write_live_refresh_summary.py `
  --status-path research\results\t72-live\data-refresh-status.json `
  --output-root research\results\t72-live-summary
```

## Calibration

Once T72 writes usable PIT data, run the research result batch and use the output
to calibrate actionability thresholds for T73.
