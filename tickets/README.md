# Tickets Queue

Open ticket specs live in this directory. Completed ticket specs live in
`tickets/done/` with a `.done.md` suffix.

Current project status is tracked in `docs/phase-status.md`.

## Status Convention

- `T<NN>-<slug>.md` - open ticket, ready to work.
- `T<NN>-<slug>.in-progress.md` - currently being worked.
- `tickets/done/T<NN>-<slug>.done.md` - merged or reconciled as complete.

## Current Queue

There are no active open ticket specs after T76.

Completed archive:

- T01-T64: merged implementation tickets.
- T65: planning/status reconciliation.
- T66: research result runner batch.
- T67: data refresh batch.
- T68: actionability gate v1.
- T69: runtime audit tables.
- T70: scheduler, metrics, and structured logging.
- T71: deployment and backup checkpoint.
- T74: runtime audit wiring for manual/scheduled cycles.
- T75: runtime audit API and dashboard visibility.
- T76: first-version user-test checklist and e2e smoke.

## Next Ticket Candidates

Use `docs/phase-status.md` as the source of truth before drafting the next ticket.

Recommended next batch:

| Ticket | Purpose |
| --- | --- |
| T72 | Live data-refresh execution and compact empirical result commit. |
| T73 | Actionability threshold calibration after empirical H1-H5 results. |

## How To Assign A Ticket

1. Confirm dependencies in `docs/phase-status.md`.
2. Add a new `T<NN>-<slug>.md` file in this directory.
3. Create branch `feat/T<NN>-<slug>`.
4. Implement, validate, open a PR, and merge to `main`.
5. Move the completed ticket to `tickets/done/T<NN>-<slug>.done.md`.
