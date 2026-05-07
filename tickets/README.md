# Tickets Queue

Open ticket specs live in this directory. Completed ticket specs live in
`tickets/done/` with a `.done.md` suffix.

Current project status is tracked in `docs/phase-status.md`.

## Status Convention

- `T<NN>-<slug>.md` - open ticket, ready to work.
- `T<NN>-<slug>.in-progress.md` - currently being worked.
- `tickets/done/T<NN>-<slug>.done.md` - merged or reconciled as complete.

## Current Queue

There are no active open ticket specs after T66.

Completed archive:

- T01-T64: merged implementation tickets.
- T65: planning/status reconciliation.
- T66: research result runner batch.

## Next Ticket Candidates

Use `docs/phase-status.md` as the source of truth before drafting the next ticket.

Recommended next batch:

| Ticket | Purpose |
| --- | --- |
| T67 | Data refresh batch for prices, SEC facts/Form 4/13F, RSS, and options manifests. |
| T68 | Actionability gate v1 with per-lane thresholds and corroboration. |
| T69 | Runtime audit tables for agent runs, prompt audit, execution state, risk snapshots. |
| T70 | Scheduler, `/metrics`, and structured runtime logging. |
| T71 | Deployment/backups checkpoint for Pi-oriented reproducibility. |

## How To Assign A Ticket

1. Confirm dependencies in `docs/phase-status.md`.
2. Add a new `T<NN>-<slug>.md` file in this directory.
3. Create branch `feat/T<NN>-<slug>`.
4. Implement, validate, open a PR, and merge to `main`.
5. Move the completed ticket to `tickets/done/T<NN>-<slug>.done.md`.
