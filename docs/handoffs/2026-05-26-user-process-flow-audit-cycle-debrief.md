# User Process Flow Audit Cycles - 2026-05-26

This records the 10-cycle recovery pass run after the operator-flow handoff. The QA server was run locally with `AGENCY_SCHEDULER_ENABLED=false` so dashboard GET requests were not mixed with automatic Massive lane refreshes.

## Cycle Debrief

| Cycle | Goal | Result | Debrief / Improvement |
| --- | --- | --- | --- |
| 04b | Re-run Final Selection triage after trimming generic queue render size. | PASS, 0 failures. | Final Selection generic page stayed under budget once scheduler refresh contention was removed. |
| 05 | Warm repeat of the standard workflow sample. | PASS, 0 failures. | Standard sample was stable; continued tracking route latency. |
| 06 | Full 168 ticker-focused execution sweep. | PASS, 0 failures. | Full-universe execution focus path stayed usable. |
| 07 | Expand candidate detail sample to 48 tickers. | FAIL, 1 failure. | `/final-selection?ticker=NVDA` crossed the 15s budget. Root cause: focused Final Selection still enriched the whole latest cycle. |
| 08 | Re-run 48-candidate sample after focused Final Selection optimization. | PASS, 0 failures. | Focused Final Selection now enriches only the selected ticker while summary counts still describe the latest full cycle. |
| 09 | Standard sample after restart and fixes. | PASS, 0 failures. | Post-fix standard route set stayed stable. |
| 10 | 8-worker stress pass using original concurrency. | FAIL, 4 failures. | Focused Final Selection cache reused another ticker's context. Fixed by preventing focused contexts from poisoning the generic cache. |
| 10b | Repeat 8-worker stress after Final Selection cache fix. | FAIL, 3 failures. | Candidate light pages crossed the route budget. Root cause: `audit=light` still queried timeline and risk decisions for each ticker. |
| 10c | Repeat 8-worker stress after candidate light-path trim. | FAIL, 2 failures. | Candidate failures cleared; `/command` reset under load. Root cause: concurrent Command requests stampeded the expensive dashboard context builder. |
| 10d | Repeat 8-worker stress after Command in-flight cache. | PASS, 0 failures. | Original stress shape passed after Command requests shared one short-lived context build. |

## Fixes Implemented

- Generic Final Selection now renders bounded queue slices instead of the whole universe.
- Focused Final Selection enriches only the selected ticker and keeps full-cycle counts lightweight.
- Focused Final Selection routes no longer cache ticker-specific rows as the generic queue.
- Candidate `audit=light` skips timeline and risk-decision lookups.
- Command dashboard GETs use a short in-flight cache, cleared by operator mutations.
- Massive lane progress now reports an orphaned `running` progress file as needing refresh when no matching worker process exists.
- Date-sensitive lane-progress tests now freeze time for closed-market manifest expectations.

## Verification

- User-process audit final stress pass: `cycle-10d-final-stress-after-command-cache-20260526`, `failure_count=0`.
- Combined regression slice: `314 passed, 2 warnings`.
- Ruff: `All checks passed`.

## Remaining Watch Items

- The QA server for this pass was scheduler-disabled. Operational mode should still be tested separately with scheduler enabled and no operator route stress running at the same time.
- Slowest final stress route was `/final-selection?ticker=CTAS` at 12.5s, under the 15s budget but still worth future optimization.
