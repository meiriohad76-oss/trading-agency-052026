# T58: Risk decision persistence and API

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T57

## Goal
Persist and read risk decisions as first-class runtime artifacts.

## Outputs
- SQLAlchemy `risk_decisions` table metadata.
- Alembic migration `0005_risk_decisions`.
- Runtime upsert/list helpers.
- `/risk/decisions` and `/risk/decisions/{ticker}` API reads.
- Persistence helper that writes risk decision plus lifecycle event.

## Acceptance Criteria
1. Risk decisions are keyed by `cycle_id`, `ticker`, and `as_of`.
2. Upserts validate the `risk-decision` contract.
3. API reads validate returned payloads and fall back to `[]` when DB is unavailable.
4. Lifecycle event persistence is available through the service helper.
5. Existing dashboard `/risk` route remains HTML.
