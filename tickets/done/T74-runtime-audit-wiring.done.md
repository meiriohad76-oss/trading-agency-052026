# T74: Runtime audit wiring

**Owner:** codex
**Phase:** 3 provisional runtime scaffolding
**Status:** done

## Goal

Record runtime audit rows automatically when manual or scheduled paper cycles are
persisted.

## Delivered

- Added runtime audit artifact construction for agent runs, risk snapshots, and
  execution states.
- Wired `persist_runtime_cycle` to write audit artifacts in the same transaction
  as source health, selection reports, risk decisions, and lifecycle events.
- Updated the manual cycle runner to stamp audit start/finish times.
- Added unit coverage for audit artifact contracts and injected persistence
  writers.

## Acceptance Notes

1. Run IDs are deterministic by cycle id and trigger for idempotent local reruns.
2. Prompt audit rows remain available at the repository layer but are not emitted
   until a real prompt-producing runtime path exists.
3. The app remains paper/demo only; execution states are previews, not broker
   submissions.
