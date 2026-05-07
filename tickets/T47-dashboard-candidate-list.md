# T47: Dashboard candidate list

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T40, T45

## Goal
Show recent selection-report candidates on the server-rendered dashboard.

## Context
Selection report API reads are available. The dashboard should surface the latest
candidates without triggering engine work and should degrade cleanly when no database is
configured.

## Outputs
- Dashboard context includes recent selection report summaries.
- Candidate table in `dashboard.html`.
- CSS for candidate status tags and empty state.
- Unit tests for dashboard rendering and row summarization.

## Acceptance Criteria
1. Dashboard loads candidate rows from the selection report runtime reader.
2. Empty or unavailable reports render a stable "No candidates yet" state.
3. Candidate rows show ticker, action, conviction, gate status, risk flag count, and as-of.
4. Existing health, contracts, and source-status dashboard content remains visible.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Candidate detail pages.
- Running selection engines from the dashboard.
- Client-side interactivity.
