# T53: Final selection dashboard

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T50, T51

## Goal
Add a read-only final selection page that displays persisted `SelectionReport` payloads
from the `build_final_selection` contract shape.

## Outputs
- `GET /final-selection` HTML page.
- Report row helper for final action, deterministic action, LLM review, policy gates,
  risk flags, and evidence counts.
- Empty state for repositories with no selection reports.
- Unit coverage using a report produced by `build_final_selection`.

## Acceptance Criteria
1. Final selection route renders through the shared shell.
2. Rows link to candidate audit pages.
3. Policy gates and LLM rationale are visible for stored reports.
4. The page is read-only and does not trigger engine work.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.
