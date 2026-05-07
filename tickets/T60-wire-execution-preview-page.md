# T60: Wire execution preview page

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T57, T59

## Goal
Replace the execution placeholder with runtime-generated paper preview rows.

## Outputs
- Execution page context builds risk decisions and execution previews from current reports.
- Preview queue table with state, side, risk decision, size, and reason.
- Summary counts for ready, blocked, and disabled previews.
- Submit controls remain disabled.

## Acceptance Criteria
1. `/execution-preview` renders through the shared shell.
2. Empty reports still show a stable empty state.
3. Preview rows appear when final selection reports exist.
4. The submit gate remains visibly closed.
5. No broker call or order submission is performed.
