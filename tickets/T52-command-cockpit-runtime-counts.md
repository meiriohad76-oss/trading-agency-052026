# T52: Command cockpit runtime counts

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T51

## Goal
Make the command page lead with runtime-backed candidate and source counts.

## Outputs
- Command summary helper for candidates, contracts, and source health.
- Action ribbon with real anchors into the page.
- Dashboard template updated to show degraded-source and actionable-candidate counts.
- Unit coverage for summary behavior and rendering.

## Acceptance Criteria
1. Command hero text is derived from runtime readers.
2. Candidate, source, and contract counts are visible.
3. Source-health rows use status-aware tags.
4. Existing dashboard empty states remain stable.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.
