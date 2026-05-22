# UX Redesign V3 Cockpit Handoff - 2026-05-22

## Branch And Commits

- Branch: `feat/ux-redesign-v3-cockpit`
- Pre-handoff checkpoint: `458391f Record cockpit paper rehearsal`
- Ticket 16 commit: this handoff commit, `Set cockpit as primary entrypoint` (use `git log -1 --oneline` for the exact hash)

## What Shipped

- Ticket 15 controlled paper-trade rehearsal was recorded at `research/results/ux-redesign-v3-qa/paper-rehearsal-20260522-1348.md`.
- The rehearsal is a valid no-submit safety rehearsal, not a successful paper order rehearsal.
- Cockpit is now the primary visible operating entrypoint:
  - brand link points to `/cockpit`
  - sidebar Operate section lists Cockpit first
  - Command remains available as an explicit `/command` route
  - `/` still renders the old command dashboard
- Added route/navigation regression coverage for the cockpit-first navigation and `/command` parallel route.

## Exact Verification

### Ticket 15 Rehearsal Evidence

```powershell
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
```

Result: expected blocked state for no-submit rehearsal.

- Data loaded and analyzed: 5 data blocker(s), 5 warning(s)
- Runtime cycle proof was too old for trading submission
- 20 candidates pending human review

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
```

Result: pass.

- `health=ok`
- `selection_reports=20`
- `risk_decisions=20`
- `/` first byte 2.06s within 3.0s budget
- `/reports/selection` total 2.166s within 5.0s budget

```powershell
.\.venv\Scripts\python scripts\run_paper_broker_validation.py
```

Result: pass.

- Alpaca broker connected
- mode: paper
- account status: ACTIVE
- open orders: 0
- positions: 2

Execution-preview status during rehearsal:

- preview rows: 168
- orderable paper previews: 0
- submit-ready previews: 0
- review-only rows: 20
- blocked rows: 148
- submit gate: closed
- blocker: `massive-stock-trades source-health row is 1597s old; refresh critical evidence before submitting.`

### Ticket 16 TDD And Route Verification

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py -q
```

RED result before implementation:

- `test_cockpit_is_primary_operating_entrypoint` failed because the brand still linked to `/`.
- `test_command_dashboard_has_explicit_parallel_route` failed because `/command` did not exist.

GREEN result after implementation:

- `10 passed in 4.60s`

### Focused Test Suites

The plan's literal first focused-suite command referenced `tests\unit\test_cockpit_state.py`, which does not exist in this checkout. I used the current equivalent cockpit inventory instead.

```powershell
$cockpitTests = Get-ChildItem tests\unit -Filter 'test_cockpit*.py' | ForEach-Object { $_.FullName }
.\.venv\Scripts\python -m pytest @cockpitTests tests\unit\test_fastapi_app.py tests\unit\test_data_load_status.py tests\unit\test_scheduler_work_queue.py -q
```

Result:

- `371 passed`
- 3 warnings from small-sample signal z-score tests

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_ops_scripts.py tests\unit\test_massive_stock_trades.py tests\unit\test_massive_orchestrator.py tests\unit\test_data_refresh_progress.py tests\unit\test_scheduler_runner.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_reports_api.py tests\unit\test_risk_api.py -q
```

Result:

- `161 passed`
- 1 warning from pagination-completeness uncertainty test coverage

### Runtime And Browser QA

Server restart command used these runtime settings:

- `PYTHONPATH=C:\Users\meiri\trading_agency\src;C:\Users\meiri\trading_agency\research\src`
- `DATABASE_URL=sqlite+aiosqlite:///research/results/agency-scheduler.sqlite`
- `AGENCY_SCHEDULER_ENABLED=false`
- `AGENCY_COCKPIT_QA_SCENARIOS=true`

Runtime checks:

- `curl.exe -s -S http://127.0.0.1:8000/health` returned `{"status":"ok","service":"trading-agency-v2"}`
- `/command` returned HTTP `200`
- `/cockpit` rendered with brand pointing to `/cockpit`
- `/cockpit` sidebar navigation listed Cockpit before Command

```powershell
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --output research/results/ux-redesign-v3-qa/final
```

Result:

- `failure_count=0`
- viewports checked: desktop 1920, desktop 1366, kiosk 1280, mobile 390
- no console errors
- no page errors
- no horizontal overflow
- BLUF visible
- phase rail visible
- candidate area visible
- submit gate safe
- no unreadable controls reported

## Screenshot And QA Artifact Paths

- Final browser QA report: `research/results/ux-redesign-v3-qa/final/cockpit-ux-qa.json`
- Final preflight payload: `research/results/ux-redesign-v3-qa/final/cockpit-preflight.json`
- Final screenshots: `research/results/ux-redesign-v3-qa/final/`
- Ticket 15 rehearsal report: `research/results/ux-redesign-v3-qa/paper-rehearsal-20260522-1348.md`
- Ticket 15 screenshots and JSON: `research/results/ux-redesign-v3-qa/paper-rehearsal-20260522-1348/`

## Known Limitations

- No paper order was submitted in Ticket 15 because the runtime had 0 orderable paper previews.
- The Alpaca paper broker connection was valid, but the paper submit gate stayed closed because critical evidence freshness was not current enough.
- Operational readiness was blocked by data freshness and pending human review, not by broker connectivity.
- The current run happened in a market-closed/off-hours context, so the next true paper-submit rehearsal should start with lane refresh and source-health proof.
- The browser QA screenshots and large JSON payloads are under `research/results/**`, which is ignored by git. This keeps large-file growth contained. The committed evidence is the Markdown report and this handoff, with local artifact paths for inspection.

## Next Recommended Ticket

Run a fresh live-readiness and paper-submit rehearsal only after:

1. Refreshing the execution-critical Massive/source-health proof through the lane model.
2. Resolving enough pending human research approvals for at least one candidate to become orderable.
3. Confirming `/status/execution-preview` reports `orderable_count >= 1` and `submit_ready_count >= 1`.
4. Re-running `scripts\run_paper_broker_validation.py`.

Do not seed demo candidates, force orderability, or bypass the freshness gate. The next useful milestone is a real paper-order rehearsal with one naturally orderable preview.
