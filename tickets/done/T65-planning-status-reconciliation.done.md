# T65: Planning status reconciliation

**Owner:** codex
**Phase:** planning
**Estimate:** small
**Dependencies:** T64

## Goal
Make the planning documents and ticket queue match the actual repo state after T64.

## Outputs
- Completed tickets archived under `tickets/done/`.
- `docs/phase-status.md` with current phase-gate truth and next ticket candidates.
- Planning docs updated to point at the status truth table.
- README and ticket queue README updated for navigation.

## Acceptance Criteria
1. T01-T64 no longer appear as active tickets.
2. The repo explicitly says T29-T64 are provisional scaffolding until empirical
   research results are produced.
3. The next recommended work is visible without reading git history.
4. Documentation-only validation passes.
