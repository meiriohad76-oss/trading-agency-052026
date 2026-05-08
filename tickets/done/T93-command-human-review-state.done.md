# T93: Command Human-Review State

**Status:** complete
**Phase:** 4 validation UX

## Goal

Make recorded paper review decisions visible on the Command review queue so the
main testing cockpit reflects what the user has already reviewed.

## What Changed

- Loaded latest-cycle `HUMAN_REVIEW` lifecycle events for queued candidates.
- Paired review events with selection rows by cycle, ticker, and as-of timestamp.
- Added a Human Review column to the Command review queue.
- Preserved review action buttons so the user can revise paper-only review
  state with a newer lifecycle event.
- Updated planning status so T93 is archived as provisional validation UX.

## Validation

- Unit coverage for queue enrichment with pending and deferred review state.
- Unit coverage for fetching only `HUMAN_REVIEW` timeline events.
- Local paper review smoke wrote a `DEFER` event for AAPL and the Command queue
  rendered it as `Defer`.
