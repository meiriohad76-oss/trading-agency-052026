# T143: Massive Multi-Lane Data Orchestrator

## Status
Done.

## What Changed
- Reworked the Massive orchestrator into a strict raw-acquisition model:
  `massive_daily_bars`, `massive_live_trade_slices`, `massive_premarket_trade_slices`,
  `massive_block_trade_feed`, `massive_backtest_trade_tape`, `massive_reference`,
  and `massive_options_flow`.
- Added a derived signal requirement map so market-flow, pre-market, technical-analysis,
  and backtest signals declare which raw Massive lanes must be ready before they run.
- Prevented duplicate Massive trade endpoint pulls: block trades are now a local
  derivation from `massive_live_trade_slices`, not a separate raw API pull.
- Added lane-level manifests under `research/data/manifests/massive_lanes/` and wired
  the stock-trade and grouped-daily Massive pull scripts to write them.
- Wired the raw/derived Massive lane plan into the market-aware refresh plan,
  scheduler status API, command dashboard system-health board, and scheduler panel.
- Added live dashboard rendering for lane status, purpose, ticker tier, cadence, ETA,
  request budget, manifest coverage, freshness requirement, source-health status,
  and concrete refresh command.
- Added responsive styling and polling updates so the new lane table stays readable on desktop and mobile.

## Verification
- `.\.venv\Scripts\mypy research\src\data_refresh\massive_orchestrator.py research\src\data_refresh\massive_lane_manifest.py research\src\data_refresh\market_batching.py src\agency\runtime\scheduler_work_queue.py research\scripts\plan_market_aware_refresh.py research\scripts\pull_massive_stock_trades.py research\scripts\pull_massive_grouped_daily.py`
- `.\.venv\Scripts\python -m pytest tests\unit\test_massive_orchestrator.py tests\unit\test_scheduler_work_queue.py tests\unit\test_massive_stock_trades.py tests\unit\test_massive_grouped_daily.py`
- `.\.venv\Scripts\python -m pytest tests\unit\test_market_batching.py tests\unit\test_data_refresh_batch.py tests\unit\test_data_refresh_progress.py tests\unit\test_data_load_status.py tests\unit\test_full_live_readiness.py tests\unit\test_runtime_scheduler.py tests\unit\test_scheduler_runner.py`
- `.\.venv\Scripts\python research\scripts\plan_market_aware_refresh.py --config research\config\live-refresh.local.json --output-root research\results\latest-market-aware-refresh-plan`
- `.\.venv\Scripts\python -m pytest tests\unit` (960 passed)
- `.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py` (failure_count=0)
