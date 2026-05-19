# T139: Tier-Aware Scheduler Commands

## Status
Done.

## What Changed
- Scheduler jobs now emit bounded commands with the live config path, extraction mode, ticker tier, ETA, and exact refresh window.
- Stock-trade scheduler commands use same-day `--stock-trades-start` and `--stock-trades-end` instead of relying on broad defaults.
- Dataset commands prefer the extraction planner's exact ticker list before falling back to tier tickers, so the dashboard command matches the stated repair/update scope.

## Verification
- `tests/unit/test_scheduler_work_queue.py`
