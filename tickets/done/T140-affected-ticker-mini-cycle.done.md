# T140: Affected-Ticker Mini-Cycle

## Status
Done.

## What Changed
- The scheduler includes an affected-ticker mini-cycle planner.
- Event rows dedupe by ticker and event type, then generate one-ticker runtime-cycle commands for the impacted lanes.

## Verification
- `tests/unit/test_scheduler_work_queue.py`

