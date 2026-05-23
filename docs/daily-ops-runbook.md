# Daily Operations Runbook

**Last updated:** 2026-05-14
**Mode:** Paper trading — no real orders

## Quick Start

```powershell
.\.venv\Scripts\python scripts\run_daily_ops.py
```

This runs all four steps below in sequence. Any failure prints a recovery hint
and stops.

## Manual Steps

### 1. Operational Readiness Check (~10s)

```powershell
.\.venv\Scripts\python scripts\check_operational_readiness.py
```

Checks: API keys present, live config valid, latest cycle reviewable.
**On failure:** read the printed checklist and fix the flagged item.

### 2. Market-Aware Data Refresh (~2–10 min)

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json
```

Runs the correct datasets for the current market phase.
**On failure:** open `research/results/latest-data-refresh/data-refresh-status.json` — the
`failed_datasets` field names the datasets to re-run.

**Re-run one dataset:**
```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --datasets prices_daily
```

### 3. PIT Runtime Cycle (~30s)

```powershell
.\.venv\Scripts\python scripts\run_first_version_pipeline.py `
  --email-max-emails 5 `
  --email-max-article-links 2
```

Builds the cycle and persists selection reports to Postgres.
**On failure:** check the server log at `http://127.0.0.1:8000/health`.

### 4. Review Queue Check (~5s)

```powershell
.\.venv\Scripts\python scripts\check_paper_review_status.py
```

Prints pending/approved/deferred counts.
**Next step:** open `http://127.0.0.1:8000/command` and approve, defer, or reject
each WATCH candidate.

## Scheduler Mode (automated, background)

If `AGENCY_SCHEDULER_ENABLED=true` in `.env`, the FastAPI server automatically
runs data refresh on the market-aware schedule. You only need to run steps 3
and 4 manually (or wait for the next automated cycle).

## Subscription Email Watch

To continuously ingest subscription emails throughout the day, run in a
separate terminal:

```powershell
.\.venv\Scripts\python research\scripts\watch_subscription_emails.py `
  --config research\config\subscription-email.local.json
```

The script holds a lock file at `research/data/.email-watch.lock` while running.
Starting a second instance exits with a clear error.

## Recovery Reference

| Symptom | Command |
|---|---|
| No candidates in queue | Check source health: `http://127.0.0.1:8000/status/source-health` |
| Dataset refresh failed | Re-run: `run_data_refresh_batch.py --datasets <name>` |
| Cycle fails to build | Check PIT data: `.\.venv\Scripts\python research\scripts\check_live_refresh_outputs.py` |
| Dashboard unreachable | Restart server: `.\scripts\start_dev.ps1` |
| Email agent fails | Check provider readiness: `http://127.0.0.1:8000/status/provider-readiness` |
| Lock file stale | Delete: `research\data\.email-watch.lock` |
