# Tickets Queue

Open ticket specs live in this directory. Completed ticket specs live in
`tickets/done/` with a `.done.md` suffix.

Current project status is tracked in `docs/phase-status.md`.

## Status Convention

- `T<NN>-<slug>.md` - open ticket, ready to work.
- `T<NN>-<slug>.in-progress.md` - currently being worked.
- `tickets/done/T<NN>-<slug>.done.md` - merged or reconciled as complete.

## Current Queue

There are no active open ticket specs after T73/T80.

Completed archive:

- T01-T64: merged implementation tickets.
- T65: planning/status reconciliation.
- T66: research result runner batch.
- T67: data refresh batch.
- T68: actionability gate v1.
- T69: runtime audit tables.
- T70: scheduler, metrics, and structured logging.
- T71: deployment and backup checkpoint.
- T72: live data-refresh execution and compact result summary.
- T73: actionability threshold calibration.
- T74: runtime audit wiring for manual/scheduled cycles.
- T75: runtime audit API and dashboard visibility.
- T76: first-version user-test checklist and e2e smoke.
- T77: live research refresh readiness config.
- T78: demo audit seed wiring.
- T79: SEC Form 4 live refresh tolerance.
- T80: live data refresh validation hardening.

## Next Ticket Candidates

Use `docs/phase-status.md` as the source of truth before drafting the next ticket.

Recommended next batch:

No numbered ticket is selected. Use the first-version testing checklist next, then
open a ticket for wider H1 coverage or stronger ticker-tagged source ingestion.

## How To Assign A Ticket

1. Confirm dependencies in `docs/phase-status.md`.
2. Add a new `T<NN>-<slug>.md` file in this directory.
3. Create branch `feat/T<NN>-<slug>`.
4. Implement, validate, open a PR, and merge to `main`.
5. Move the completed ticket to `tickets/done/T<NN>-<slug>.done.md`.
