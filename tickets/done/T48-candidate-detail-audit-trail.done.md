# T48: Candidate detail audit trail

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T41, T47

## Goal
Add a read-only candidate detail page that shows selection reports and lifecycle events.

## Context
Users need to answer why a ticker appeared, changed state, or disappeared. The dashboard
candidate list should link into a focused audit view backed by existing report and
lifecycle runtime readers.

## Outputs
- `GET /candidates/{ticker}` HTML detail page.
- `candidate_detail.html` template.
- Timeline summarization helper and tests.
- Dashboard candidate links.

## Acceptance Criteria
1. Candidate list tickers link to their detail page.
2. Detail page shows report count, event count, latest action, and ticker.
3. Selection report rows and lifecycle timeline rows render when present.
4. Empty reports/events render stable empty states.
5. Existing JSON `/candidates/{ticker}/timeline` endpoint remains available.
6. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Client-side filters.
- Event payload expansion.
- Write actions from the dashboard.
