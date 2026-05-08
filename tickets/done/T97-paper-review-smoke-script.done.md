# T97: Paper Review Smoke Script

**Status:** complete
**Phase:** 4 validation UX

## Goal

Give the user a one-command PowerShell smoke check for paper-review queue and
progress state during first-version testing.

## What Changed

- Added `scripts/check_paper_review_status.py`.
- The script calls `/status/paper-review` and validates minimum queue,
  minimum reviewed, and optional maximum pending thresholds.
- Updated the first-version testing checklist with the new script and endpoint.
- Tightened the existing local-runtime fetch helper typing.
- Updated planning status so T97 is archived as provisional validation UX.

## Validation

- Unit coverage for paper-review status summarization.
- Focused script lint, pytest, and mypy checks pass.
