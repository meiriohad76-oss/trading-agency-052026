# T94: Command Review Progress

**Status:** complete
**Phase:** 4 validation UX

## Goal

Make current-cycle paper review progress visible from the Command dashboard so
the user can tell how much of the queue remains to inspect.

## What Changed

- Added a review-progress summary derived from Command review queue rows.
- Added reviewed and pending counts to the top Command metrics.
- Added pending, approved, deferred, and rejected counts to the Review Queue
  panel.
- Updated the Review Queue panel status tag to show complete, pending, or empty
  state.
- Updated planning status so T94 is archived as provisional validation UX.

## Validation

- Unit coverage for pending and complete review-progress states.
- Existing dashboard render coverage remains green.
- Local paper state shows AAPL deferred and the remaining three candidates
  pending.
