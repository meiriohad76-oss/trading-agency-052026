# T98: Operational Readiness Gate

**Status:** complete
**Phase:** 4 validation UX

## Goal

Give the user one API endpoint and one CLI command that says whether the local
paper agency is operational enough for first-version testing.

## What Changed

- Added `/status/operational-readiness`.
- Added `scripts/check_operational_readiness.py`.
- Combined API health, live config readiness, data-refresh state, live runtime
  readiness, paper-review queue, human-review progress, paper-mode safety, and
  key-presence checks into one verdict.
- Updated README, deployment notes, first-version testing checklist, and phase
  status to make the new check part of the normal local smoke path.

## Validation

- Unit coverage for ready-with-attention and blocked readiness outcomes.
- Endpoint coverage for the combined status route.
- Script coverage for operational readiness summary parsing.
