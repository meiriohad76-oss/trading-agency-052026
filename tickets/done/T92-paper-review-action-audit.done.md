# T92: Paper Review Action Audit

**Status:** complete
**Phase:** 4 validation UX

## Goal

Let the user record a paper review decision from the Command review queue and
make that decision visible in the candidate lifecycle audit.

## What Changed

- Added `HUMAN_REVIEW` to the candidate lifecycle event contract.
- Added a human-review service that builds and persists append-only lifecycle
  events for `APPROVE`, `DEFER`, and `REJECT`.
- Added paper-only review action buttons to each Command review queue row.
- Added a POST route that records the review event and redirects to the
  candidate audit page.
- Updated planning status so T92 is archived as provisional validation UX.

## Validation

- Unit coverage for human-review event building and persistence.
- Contract coverage for `HUMAN_REVIEW` lifecycle events.
- FastAPI coverage for the review POST route and queue action URLs.
