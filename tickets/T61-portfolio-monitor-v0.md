# T61: Portfolio monitor v0

**Owner:** codex
**Phase:** 2 (UX/build)
**Estimate:** small
**Dependencies:** T53

## Goal
Add the first read-only portfolio monitor contract, backend snapshot, and dashboard page.

## Outputs
- `portfolio-monitor` JSON Schema contract.
- `build_portfolio_monitor` service.
- `/portfolio-monitor` page and nav link.
- Unit tests for empty and classified position snapshots.

## Acceptance Criteria
1. Monitor snapshots validate against the contract.
2. Empty portfolio state is stable.
3. Existing positions can be classified as hold, review, close candidate, or no setup.
4. The page clearly states it does not close positions automatically.
5. No broker position reads are performed yet.
