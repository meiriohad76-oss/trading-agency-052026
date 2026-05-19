# T136: Leveraged Alternative Review Advisor

**Status:** complete
**Phase:** 4 operate

## What Changed

- Added `agency.services.leveraged_alternatives`.
- Added conservative policy controls, disabled by default.
- Added a local leveraged ETF catalog example.
- Added candidate-detail and execution-preview dashboard panels.
- Added advisory-only ETF and defined-risk option alternative construction.
- Added explicit naked-option-write blocking.

## Guardrails

- Candidates below 85% conviction never receive leveraged alternatives.
- Hard risk/policy blockers prevent leveraged alternatives.
- All alternatives are advisory-only and never auto-submit.
- Defined-risk options are disabled by default.
- Naked option writing is blocked.

## Validation

- T136 unit tests passed.
- Candidate and execution dashboard smoke tests passed.
- Focused ruff and mypy checks passed.
