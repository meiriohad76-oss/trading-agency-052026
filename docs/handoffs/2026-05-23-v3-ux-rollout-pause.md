# V3 UX Rollout Pause Handoff

Paused at: 2026-05-23
Repo: `C:\Users\meiri\trading_agency`
Branch: `feat/ux-redesign-v3-cockpit`

## Current Goal

Finish the V3 UX rollout for all screens, test and QA rigorously, then commit.
Do not deploy to the Raspberry Pi unless the user asks again; the latest scope is commit only.

## Clean Process State

At final handoff cleanup:

- No `check_dashboard_live_data_qa.py` or `check_cockpit_ux_qa.py` process remains running.
- No uvicorn `agency.app:app` server remains running.
- Port `8000` was checked after cleanup and was no longer serving `/health`.

Resume by starting a deliberate fresh local server with `PYTHONPATH` set:

```powershell
$env:PYTHONPATH = "$(Resolve-Path .)\src;$(Resolve-Path .)\research\src"
.\.venv\Scripts\python -m uvicorn agency.app:app --host 127.0.0.1 --port 8000
```

Direct uvicorn without `PYTHONPATH=src;research\src` fails with `ModuleNotFoundError: No module named 'news'`.

## What Was Fixed In This Continuation

- `/` now renders the V3 Cockpit. The legacy command dashboard remains at `/command`.
- The cockpit root now renders the shared `Displayed Data Health` panel.
- The live-readiness proof path now falls back to `stock_trades` coverage metadata when `massive_live_trade_slices.json` is out of window but stored trade coverage proves the latest completed trading session.
- `scripts/check_dashboard_live_data_qa.py` was hardened:
  - page navigation timeout is 60s,
  - JSON readiness probe timeout is 45s with 3 attempts,
  - every route gets a fresh Playwright page,
  - root screenshot naming is `cockpit-root`, not the old misleading `command` label.

## Verification Completed

Targeted regressions were run and passed:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py::test_root_cockpit_exposes_displayed_data_health tests\unit\test_data_load_status.py::test_data_load_status_uses_stock_trade_coverage_when_live_lane_manifest_is_older -q
```

Result:

```text
2 passed in 5.54s
```

Endpoint probe after a clean server restart showed review-ready with zero hard blockers:

```text
data_state      : attention
data_ready      : True
data_review     : True
data_tradable   : False
data_blockers   : 0
health_status   : context_stale
health_reliable : True
full_verdict    : ready_with_partial_lanes
full_review     : True
full_blockers   : 0
```

`stock_trades` after the fallback fix:

```text
status_label         : Attention
status_class         : warn
source_status        : DEGRADED
source_freshness     : PARTIAL
loaded_ticker_count  : 168
usable_ticker_count  : 167
partial_ticker_count : 1
detail               : Proof came from stock_trades coverage metadata because the latest massive_live_trade_slices lane manifest covers 2026-05-15 to 2026-05-15, not 2026-05-22.
```

Direct route probe after a clean server restart:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/candidates/NVDA -UseBasicParsing -TimeoutSec 90
```

Result: HTTP 200, about 22.5s, response length about 125,396, data-health panel present.

## Browser QA Status

The final browser QA run was intentionally stopped because the user paused. Earlier runs show:

- V3 UI health-panel checks are clean across the major routes once the server is fresh.
- Operational readiness failures cleared after the stock-trade coverage fallback.
- Remaining risk is route latency, especially `/candidates/NVDA`.
- The candidate route can still time out in a full browser sweep when the single-worker local server is busy.

Do not claim the V3 rollout is complete until this passes fresh:

```powershell
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py --readiness-scope review-subset
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/ --focus panels --output research/results/ux-redesign-v3-qa/final-root
```

## Known Next Blocker

`/candidates/NVDA` is too slow for reliable browser QA.

Profiling notes:

- `candidate_detail_context("NVDA")` took about 30-50s in local probes.
- `_enrich_candidate_report_signals()` took about 55.8s in one isolated profile.
- Slow work comes from reconstructing rich signal evidence frames, including abnormal-volume reconstruction and other PIT/signal reads.

Recommended next ticket:

```text
T-next: Make candidate detail route fast and reliable.
Definition of done:
- /candidates/NVDA responds under 15s on a clean local server, preferably under 5s.
- Rich evidence remains available, but heavy signal reconstruction is cached, bounded, or loaded lazily.
- Browser QA passes with failure_count=0.
```

## Files Touched In This Continuation

- `src/agency/runtime/data_load_status.py`
- `src/agency/views/cockpit.py`
- `src/agency/templates/cockpit.html`
- `scripts/check_dashboard_live_data_qa.py`
- `tests/unit/test_cockpit_routes.py`
- `tests/unit/test_data_load_status.py`

There are many other dirty V3 rollout files from the broader work. Do not reset them.

## Resume Sequence

1. Check no stale QA/server processes exist:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'check_dashboard_live_data_qa|check_cockpit_ux_qa|uvicorn agency\.app:app' }
```

2. Start one clean server with `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "$(Resolve-Path .)\src;$(Resolve-Path .)\research\src"
.\.venv\Scripts\python -m uvicorn agency.app:app --host 127.0.0.1 --port 8000
```

3. Re-run targeted tests:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py::test_root_cockpit_exposes_displayed_data_health tests\unit\test_data_load_status.py::test_data_load_status_uses_stock_trade_coverage_when_live_lane_manifest_is_older -q
```

4. Optimize candidate detail if browser QA still times out.

5. Run final verification:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_data_load_status.py tests\unit\test_fastapi_app.py tests\unit\test_reports_api.py tests\unit\test_ux_audit_implementation.py tests\unit\test_v3_ux_rollout.py -q
.\.venv\Scripts\python -m ruff check scripts\check_dashboard_live_data_qa.py scripts\check_cockpit_ux_qa.py src\agency\runtime\data_load_status.py src\agency\views\cockpit.py src\agency\dashboard.py tests\unit\test_cockpit_routes.py tests\unit\test_data_load_status.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_fastapi_app.py tests\unit\test_reports_api.py tests\unit\test_v3_ux_rollout.py
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py --readiness-scope review-subset
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/ --focus panels --output research/results/ux-redesign-v3-qa/final-root
git diff --check
git status --short
```

Only after those checks are green, commit with:

```text
Complete V3 cockpit UX rollout
```
