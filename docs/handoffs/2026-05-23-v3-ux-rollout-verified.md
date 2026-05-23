# V3 UX Rollout Verified Handoff

Date: 2026-05-23
Repo: `C:\Users\meiri\trading_agency`
Branch: `feat/ux-redesign-v3-cockpit`

## Current State

The V3 cockpit and dashboard rollout is verified for review-subset operation.

- `/` renders the V3 cockpit.
- `/command` remains available as the legacy command dashboard.
- Dashboard live-data QA passes across desktop and mobile routes.
- Cockpit panel screenshot QA passes across desktop, kiosk, and mobile viewports.
- Massive live trade readiness no longer fails hard when the lane manifest and coverage metadata are older than the latest completed trading session but current `stock_trades` Parquet rows prove ticker coverage.
- Current runtime is review-ready, not full-universe tradable: market-flow signal coverage is partial, so execution should remain gated by the normal paper-trading policy.

## Fix Added In This Continuation

The real artifact failure shape was:

- `massive_live_trade_slices.json` covered `2026-05-15`.
- `stock_trades/_coverage.json` also only covered `2026-05-15`.
- `stock_trades.json` and per-ticker Parquet files contained `2026-05-22` rows.

`src/agency/runtime/data_load_status.py` now falls back to exact per-ticker Parquet `trade_date` row counts when the lane manifest and coverage metadata are older but the stock-trades source manifest covers the readiness date.

This produces an actionable warning with proof detail instead of a hard blocker:

- `ready=True`
- `review_operational_ready=True`
- `tradable_ready=False`
- `blocker_count=0`
- stock trades: `167/168` usable, `1` partial or missing

## Verification Evidence

Unit and route tests:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_data_load_status.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_massive_orchestrator.py tests\unit\test_signal_evidence.py -q
```

Result: `76 passed in 111.99s`

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_data_load_status.py tests\unit\test_fastapi_app.py tests\unit\test_reports_api.py tests\unit\test_ux_audit_implementation.py tests\unit\test_v3_ux_rollout.py tests\unit\test_massive_orchestrator.py tests\unit\test_signal_evidence.py -q
```

Result: `299 passed, 2 warnings in 341.12s`

Cockpit-specific no-demo guard:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_no_demo_data.py -q
```

Result: `6 passed in 1.50s`

Ruff:

```powershell
.\.venv\Scripts\python -m ruff check scripts\check_dashboard_live_data_qa.py scripts\check_cockpit_ux_qa.py src\agency\runtime\data_load_status.py src\agency\runtime\signal_evidence.py src\agency\views\cockpit.py src\agency\views\final_selection.py src\agency\dashboard.py src\agency\api\reports.py tests\unit\test_cockpit_routes.py tests\unit\test_data_load_status.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_fastapi_app.py tests\unit\test_reports_api.py tests\unit\test_v3_ux_rollout.py tests\unit\test_signal_evidence.py tests\unit\test_massive_orchestrator.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_ux_qa_script.py
```

Result: `All checks passed!`

Dashboard live-data QA:

```powershell
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py --readiness-scope review-subset
```

Result: `failure_count=0`

Screenshots: `research/results/latest-ui-live-data-qa/`

Cockpit browser QA:

```powershell
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/ --focus panels --output research/results/ux-redesign-v3-qa/final-root
```

Result: `failure_count=0`

Screenshots and report: `research/results/ux-redesign-v3-qa/final-root/`

Diff hygiene:

```powershell
git diff --check
```

Result: exit 0; Git emitted only the existing CRLF normalization warning for `src/agency/views/final_selection.py`.

## Current Local Server

A local QA server was started with:

```powershell
$env:PYTHONPATH = "$(Resolve-Path .)\src;$(Resolve-Path .)\research\src"
$env:DATABASE_URL = "sqlite+aiosqlite:///research/results/agency-scheduler.sqlite"
$env:AGENCY_SCHEDULER_ENABLED = "false"
$env:AGENCY_COCKPIT_QA_SCENARIOS = "true"
.\.venv\Scripts\python -m uvicorn agency.app:app --host 127.0.0.1 --port 8000
```

Health probe returned:

```json
{"status":"ok","service":"trading-agency-v2"}
```

## Known Remaining Limits

- Full-universe tradable readiness is still false because market-flow signal rows cover a subset, not all 168 active tickers.
- Subscription-email article links still need login confirmation; this is a context warning, not the blocker fixed here.
- The runtime should continue to repair lane manifests through the lane model; no broad direct stock-trade batch should be reintroduced.

## Next Recommended Step

Use the running local app for manual operator review:

1. Open `http://127.0.0.1:8000/`.
2. Check cockpit BLUF, data-health proof text, and candidate cards.
3. Open `/execution-preview` and verify paper-trading remains gated unless a real orderable preview exists.
4. If the user accepts the V3 review state, continue with a controlled paper-trade rehearsal.
