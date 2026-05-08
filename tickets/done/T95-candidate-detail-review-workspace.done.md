# T95: Candidate Detail Review Workspace

**Status:** complete
**Phase:** 4 validation UX

## Goal

Make candidate detail pages usable as review workspaces, not only lifecycle
logs, by showing the current paper-review state and review controls for the
latest selection report.

## What Changed

- Added a candidate review summary derived from the latest selection report and
  matching `HUMAN_REVIEW` lifecycle event.
- Added a Paper Review panel to candidate detail pages.
- Added approve, defer, and reject review actions to candidate detail pages.
- Added empty-state handling when a ticker has no selection report.
- Updated planning status so T95 is archived as provisional validation UX.

## Validation

- Unit coverage for reviewed and missing-report candidate review summaries.
- Existing candidate detail render coverage remains green.
