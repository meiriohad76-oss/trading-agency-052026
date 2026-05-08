# First Version Test Checklist

Use this checklist after starting the local paper runtime with:

```powershell
.\scripts\start_local_runtime.ps1
```

If the script reports that the local runtime is already running on port 8000,
keep using the existing browser session. Stop that server and rerun the script only
when you need to load newly changed Python or template code.

Open `http://127.0.0.1:8000/` and inspect the app in this order.

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

curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/status/live-config
curl.exe http://127.0.0.1:8000/status/live-readiness
curl.exe http://127.0.0.1:8000/status/paper-review
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

There should be no `BLOCK` checks. A yfinance `WARN` is acceptable for historical
replay, but switch to Alpaca before current-date validation if yfinance is stale.

If yfinance remains stale, switch the local refresh config to Alpaca and set
credentials in `.env`:

```powershell
notepad .env
notepad research\config\live-refresh.local.json
```

Use these local settings:

```json
"market_data_provider": "alpaca",
"market_data_feed": "iex",
"market_data_adjustment": "all",
"market_data_base_url": "https://data.alpaca.markets"
```

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
- Any confusing label, missing count, or overloaded table gets a follow-up ticket.

## Follow-Up Tracks

- Live research unblock: configure `SEC_USER_AGENT`, RSS feeds, 13F filer CIKs,
  and CUSIP mapping, then run T72/T73.
- Live runtime unblock: refresh PIT datasets close to the test date and add the
  provider feed for unusual activity alerts before enabling the options/activity
  lane.
- Runtime hardening: improve seeded scenarios, audit drill-downs, and failure-state
  explanations.
