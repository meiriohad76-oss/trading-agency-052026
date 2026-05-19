# T142: Off-Hours Baseline Repair

## Status
Done.

## What Changed
- Heavy baseline/force repairs for SEC and support datasets are deferred during pre-market, regular market, and after-hours decision windows.
- The scheduler exposes baseline repair status, ETA, tier, and commands for quiet-window execution.

## Verification
- `tests/unit/test_market_batching.py`
- `tests/unit/test_scheduler_work_queue.py`

