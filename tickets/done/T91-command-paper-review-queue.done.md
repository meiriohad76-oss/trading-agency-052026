# T91: Command Paper Review Queue

**Status:** complete
**Phase:** 4 validation UX

## Goal

Make the latest paper-cycle candidates easier to inspect from the Command
dashboard without requiring the user to hop between raw candidate, risk, and
final-selection pages first.

## What Changed

- Added a latest-cycle paper review queue to the Command dashboard.
- Paired reviewable selection reports with their matching risk decisions by
  cycle, ticker, and as-of timestamp.
- Prioritized non-blocked risk decisions before waiting or blocked rows.
- Added direct links from each queue row to candidate detail, Risk, and Final
  Selection pages.
- Updated planning status so T91 is archived as provisional validation UX.

## Validation

- Unit coverage for the review queue pairing and dashboard empty state.
- Existing FastAPI dashboard tests remain green.
