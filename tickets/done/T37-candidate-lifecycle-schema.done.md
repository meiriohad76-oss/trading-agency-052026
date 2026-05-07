# T37: Candidate lifecycle event schema

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T35

## Goal
Add the append-only table for candidate lifecycle events.

## Context
v2 must explain why a ticker appeared, changed state, or disappeared. Candidate lifecycle
events are the audit trail that ties universe, deterministic, LLM, final, risk, and
execution states together.

## Outputs
- SQLAlchemy metadata for `candidate_lifecycle_events`.
- Alembic migration `0004_candidate_lifecycle_events`.
- Unit tests for table metadata and migration linkage.

## Acceptance Criteria
1. Table is keyed by `event_id`.
2. Table stores cycle, ticker, event type, event time, status, optional reason, and payload.
3. Indexes support cycle/ticker lookup and event-type/time scans.
4. Migration follows `0003_selection_reports`.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Lifecycle repository helpers.
- Event schemas.
- Dashboard lifecycle view.
