# Tickets Queue

Open ticket specs live in this directory. Completed ticket specs live in
`tickets/done/` with a `.done.md` suffix.

Current project status is tracked in `docs/phase-status.md`.

## Status Convention

- `T<NN>-<slug>.md` - open ticket, ready to work.
- `T<NN>-<slug>.in-progress.md` - currently being worked.
- `tickets/done/T<NN>-<slug>.done.md` - merged or reconciled as complete.

## Current Queue

There are no active open ticket specs after T65.

Completed archive:

- T01-T64: merged implementation tickets.
- T65: planning/status reconciliation.

## Next Ticket Candidates

Use `docs/phase-status.md` as the source of truth before drafting the next ticket.

Recommended next batch:

| Ticket | Purpose |
| --- | --- |
| T66 | Research result runner batch for H1/H2/H3/H4/H5 artifacts. |
| T67 | Actionability gate v1 with per-lane thresholds and corroboration. |
| T68 | Runtime audit tables for agent runs, prompt audit, execution state, risk snapshots. |
| T69 | Scheduler, `/metrics`, and structured runtime logging. |
| T70 | Deployment/backups checkpoint for Pi-oriented reproducibility. |

## How To Assign A Ticket

1. Confirm dependencies in `docs/phase-status.md`.
2. Add a new `T<NN>-<slug>.md` file in this directory.
3. Create branch `feat/T<NN>-<slug>`.
4. Implement, validate, open a PR, and merge to `main`.
5. Move the completed ticket to `tickets/done/T<NN>-<slug>.done.md`.
