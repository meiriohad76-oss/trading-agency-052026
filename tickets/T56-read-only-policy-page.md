# T56: Read-only policy page

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T51

## Goal
Add the first portfolio policy page as read-only configuration until validation,
persistence, and audit logging exist.

## Outputs
- `GET /policy` HTML page.
- Static v0 policy sections for targets, capacity, trade defaults, and permissions.
- Disabled action buttons for future editing flows.
- Unit coverage for route rendering and policy section shape.

## Acceptance Criteria
1. Policy route renders through the shared shell.
2. Policy values are visible but not editable.
3. Save/reset/audit actions are disabled.
4. The page states that audit persistence is pending.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.
