# T75: Runtime audit visibility

**Owner:** codex
**Phase:** 3 provisional runtime scaffolding
**Status:** done

## Goal

Expose the runtime audit trail written by T74 so local paper testing can inspect
cycle runs, risk snapshots, execution states, and prompt audit readiness.

## Delivered

- Added audit API endpoints for agent runs, prompt audits, risk snapshots, and
  execution states.
- Added a read-only `/audit` dashboard page and sidebar navigation.
- Added runtime readers for risk snapshots and execution states.
- Added unit coverage for endpoint fallbacks, injected readers, dashboard rendering,
  and row summarization.

## Acceptance Notes

1. Audit endpoints fall back to empty lists if the database is unavailable.
2. Prompt audits are visible as soon as prompt-producing runtime paths start
   writing them.
3. Execution states remain paper-preview trace rows, not broker submissions.
