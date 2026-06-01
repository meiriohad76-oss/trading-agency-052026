# UXC-013 Full Workflow Rehearsal

Date: 2026-06-01
Branch: `feat/ux-product-audit-20260529`
Temporary QA URL: `http://127.0.0.1:8017`

## Scope

Rehearsed the operator path from cockpit/candidate review through focused execution-preview routing, while preserving the lane model and using live lane/status artifacts rather than demo data.

## Fixes Made

- PIT stock-trade loader now tolerates optional columns missing across mixed Parquet partitions.
- UX QA scripts now expect the current `ux-v3-cockpit-primary-20260601` build marker.
- Readiness accepts `auto-lane-refresh-*` cycles as live operational cycles.
- Process-flow audit samples review-queue tickers first and uses `requests` for local HTTP fetches to avoid false `WinError 10054` failures from Python `urllib`.
- Premarket Massive lane is optional outside premarket and no longer blocks the operator flow.
- Source-health warnings are softened when critical lane proof is available for review.
- Candidate evidence currentness now keeps caution-only derived signal refreshes reviewable when rows exist, while raw lane proof refreshes still block until refreshed.
- Lane-state payload now carries derived `produced_count` / `expected_count` so review-caution logic can reason from real coverage.

## Live Lane Refresh Evidence

- `massive_live_trade_slices`: `ready_for_review`, 100% manifest coverage, latest proof `2026-06-01 18:33:44 UTC`.
- `massive_block_trade_feed`: `ready_for_review`, 100% manifest coverage, latest proof `2026-06-01 18:35:05 UTC`.
- `massive_premarket_trade_slices`: `disabled_optional`, not required outside premarket.

## Verification

- `.\.venv\Scripts\python scripts\check_operational_readiness.py --base-url http://127.0.0.1:8017 --min-queue 1`
  - PASS: `ready=true`, `blocker_count=0`, `queue_count=12`, `review_operational_ready=true`.
- `.\.venv\Scripts\python scripts\check_local_runtime.py --base-url http://127.0.0.1:8017 --min-selection-reports 1 --min-risk-decisions 1`
  - PASS: health `ok`, 20 selection reports, 20 risk decisions.
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus panels --output research\results\ux-qa\cockpit-full-workflow-uxc-013-stable-final`
  - PASS: failure_count `0` across desktop, kiosk, and mobile panel checks.
- `.\.venv\Scripts\python scripts\check_user_process_flow_audit.py --base-url http://127.0.0.1:8017 --output research\results\ux-qa\user-process-uxc-013-stable-final2 --max-tickers 20 --candidate-pages --focus-route-sample-size 10 --route-budget-seconds 12 --workers 1`
  - PASS: failure_count `0`; audited 20 tickers, 20 execution status contracts, 10 focused execution routes, 20 candidate pages.
- `.\.venv\Scripts\python -m pytest tests\unit\test_pit_loader.py tests\unit\test_live_readiness.py tests\unit\test_data_load_status.py tests\unit\test_ops_scripts.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_lane_state.py -q`
  - PASS: 221 passed.
- `.\.venv\Scripts\python -m ruff check ...`
  - PASS for touched runtime/view/script/test files.

## Notes

- The stable process audit was run with `AGENCY_SCHEDULER_ENABLED=false` so automatic lane refreshes would not roll the cycle during the snapshot. Before that stable run, the live and block trade lanes were refreshed through the scheduler refresh endpoints.
- A scheduler-enabled probe earlier passed operational readiness with zero blockers, but concurrent audit stress can create cycle churn and misleading candidate-action failures. The stable audit is the operator-flow proof; scheduler-enabled operation should be checked separately with live jobs enabled and no concurrent route-stress run.
- Current status remains review-ready, not full paper-execution-ready: `tradable_ready=false` / `Ready With Partial Lanes` because non-critical warnings remain and no human reviews have been recorded in this fresh cycle.
