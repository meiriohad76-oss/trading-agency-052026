# First Version Test Checklist

Use this checklist after starting the local paper runtime with:

```powershell
.\scripts\start_local_runtime.ps1
```

This starts the server without demo data. Use `.\scripts\start_local_runtime.ps1 -SeedDemo`
only for isolated UI demos, not live-paper operation.

If the script reports that the local runtime is already running on port 8000,
keep using the existing browser session. Stop that server and rerun the script only
when you need to load newly changed Python or template code.

Open `http://127.0.0.1:8000/` and inspect the app in this order.

For the fastest bounded live-paper loop from already-refreshed PIT data, run:

```powershell
.\.venv\Scripts\python scripts\run_first_version_pipeline.py `
  --email-max-emails 1 `
  --email-max-article-links 1 `
  --check-dashboard
```

This ingests at most one matching subscription email, analyzes at most one linked
article, runs a persisted PIT paper cycle, and then checks dashboard readiness.
Add `--refresh-data` only when you deliberately want to call external data
providers again.

## Manual Page Walk

1. Command
   - Candidate count is visible.
   - Live Config shows whether credentials and refresh inputs are ready.
   - Data source status is visible.
   - Candidate ticker links open detail pages.

2. Final Selection
   - Actions, conviction, gates, risk flags, and rationale are readable.
   - Page is read-only.

3. Risk
   - Allowed, warned, and blocked states are understandable.
   - Gate detail explains the decision.

4. Execution Preview
   - Submit gate is closed.
   - Every row reads as paper-only, not broker execution.

5. Audit
   - Agent runs, risk snapshots, and execution states are visible.
   - Cycle IDs and timestamps are understandable enough to debug a run.

6. Candidate Detail
   - Latest action matches the final-selection table.
   - Timeline/audit rows are readable when present.

## Machine Checks

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1

.\.venv\Scripts\python scripts\check_paper_review_status.py `
  --min-queue 1

.\.venv\Scripts\python scripts\check_operational_readiness.py `
  --min-queue 1

curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/status/live-config
curl.exe http://127.0.0.1:8000/status/live-readiness
curl.exe http://127.0.0.1:8000/status/paper-review
curl.exe http://127.0.0.1:8000/status/operational-readiness
curl.exe http://127.0.0.1:8000/metrics
curl.exe http://127.0.0.1:8000/audit/agent-runs
```

## Live PIT Cycle Inspection

After live refresh outputs exist, run a PIT-backed paper cycle:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --output-root research\results\t83-live-runtime-cycle

Get-Content research\results\t83-live-runtime-cycle\live-runtime-cycle-summary.md
```

For the first stocks-only replay test, use:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --as-of 2025-12-31 `
  --replay-freshness `
  --output-root research\results\t85-stocks-only-replay
```

Then rerun the local runtime check and inspect the Command, Final Selection,
Risk, Execution Preview, and Audit pages. The summary can show `WATCH`
candidates while risk still blocks or warns them if source health is stale,
unavailable, or missing paid-provider activity data; that is expected until the
refresh is current enough for paper validation.

The Command page and `/status/live-readiness` should agree on the live-readiness
verdict and blocker count.

## Current-Date Market Data

Before a refresh, check the Command page Live Config panel or:

```powershell
curl.exe http://127.0.0.1:8000/status/live-config
```

There should be no `BLOCK` checks. The local config now expects Massive for
research market data, so add `POLYGON_API_KEY` or `MASSIVE_API_KEY` in `.env`
before current-date validation.

```powershell
notepad .env
notepad research\config\live-refresh.local.json
```

Use these local settings:

```json
"market_data_provider": "massive",
"massive_base_url": "https://api.polygon.io",
"runtime_universe": "active",
"runtime_max_tickers": 250
```

`runtime_universe="active"` makes the paper cycle use the active PIT S&P 100 +
QQQ membership instead of only the small refresh ticker list. If `/status/live-config`
shows a `Runtime data coverage` warning, the full universe is wired but one or
more local datasets still need staged refreshes before the queue is fully
operational.

Before widening coverage, generate a quota-aware active-universe plan:

```powershell
.\.venv\Scripts\python research\scripts\plan_active_universe_refresh.py `
  --config research\config\live-refresh.local.json `
  --as-of 2026-05-08

Get-Content research\results\active-universe-refresh-plan\active-universe-refresh-plan.md
```

The planner reads the local Massive usage ledger and emits only the batches that
fit the remaining local request budget. `stock_trades` uses the configured
single-day live window, not the full historical research window.

Then run a current-date refresh and a persisted paper cycle:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --end 2026-05-08 `
  --no-dry-run

.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --config research\config\live-refresh.local.json `
  --as-of 2026-05-08 `
  --output-root research\results\t86-current-live-cycle
```

While the refresh runs, the Command page shows Data Loading progress by polling
`research/results/latest-data-refresh/data-refresh-status.json`. Set
`DATA_REFRESH_STATUS_PATH` if you write the batch status to another location.

## Pass Criteria

- The app clearly says paper/demo mode.
- No screen offers real order submission.
- The main path from candidate to risk to execution preview to audit is traceable.
- Live readiness explains whether the latest persisted cycle is reviewable or
  context-only.
- Live Config identifies missing credentials or refresh inputs without showing
  secret values.
- Long data refreshes show progress, current dataset, and ETA.
- Paper review status is visible on Command, candidate detail, and
  `/status/paper-review`.
- `/status/operational-readiness` and `scripts/check_operational_readiness.py`
  return `ready: true` before first-version paper testing starts.
- Any confusing label, missing count, or overloaded table gets a follow-up ticket.

## Follow-Up Tracks

- Live research unblock: configure `SEC_USER_AGENT`, RSS feeds, 13F filer CIKs,
  and CUSIP mapping, then run T72/T73.
- Live runtime unblock: refresh PIT datasets close to the test date and add the
  provider feed for unusual activity alerts before enabling the options/activity
  lane.
- Runtime hardening: improve seeded scenarios, audit drill-downs, and failure-state
  explanations.
