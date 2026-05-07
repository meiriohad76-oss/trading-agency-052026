# T63: Demo runtime seed

**Owner:** codex
**Phase:** 2 (developer experience)
**Estimate:** small
**Dependencies:** T57-T62

## Goal
Add a deterministic local seed command that populates the runtime dashboard with
schema-valid paper/demo data.

## Outputs
- Demo runtime seed service.
- `scripts/seed_demo_runtime.py` command.
- README instructions for local use.
- Unit tests for seeded artifact validity and persistence write flow.

## Acceptance Criteria
1. Seed artifacts validate against source-health, selection-report, risk-decision,
   execution-preview, and lifecycle contracts.
2. Demo data includes allowed, blocked, and warned risk states.
3. Demo data includes ready, blocked, and disabled execution preview states.
4. The seed command writes only local paper/demo runtime artifacts.
5. No broker calls or real order submissions are performed.
