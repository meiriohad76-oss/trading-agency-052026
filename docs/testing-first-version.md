# First Version Test Checklist

Use this checklist after starting the local paper runtime with:

```powershell
.\scripts\start_local_runtime.ps1
```

Open `http://127.0.0.1:8000/` and inspect the app in this order.

## Manual Page Walk

1. Command
   - Candidate count is visible.
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

curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/metrics
curl.exe http://127.0.0.1:8000/audit/agent-runs
```

## Pass Criteria

- The app clearly says paper/demo mode.
- No screen offers real order submission.
- The main path from candidate to risk to execution preview to audit is traceable.
- Any confusing label, missing count, or overloaded table gets a follow-up ticket.

## Follow-Up Tracks

- Live research unblock: configure `SEC_USER_AGENT`, RSS feeds, 13F filer CIKs,
  and CUSIP mapping, then run T72/T73.
- Runtime hardening: improve seeded scenarios, audit drill-downs, and failure-state
  explanations.
