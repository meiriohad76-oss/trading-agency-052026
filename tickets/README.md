# Tickets Queue

Open ticket specs live in this directory. Completed ticket specs live in
`tickets/done/` with a `.done.md` suffix.

Current project status is tracked in `docs/phase-status.md`.

## Status Convention

- `T<NN>-<slug>.md` - open ticket, ready to work.
- `T<NN>-<slug>.in-progress.md` - currently being worked.
- `tickets/done/T<NN>-<slug>.done.md` - merged or reconciled as complete.

## Current Queue

T100-T104 are open backlog tickets for subscription-email evidence agents.

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
- T81: unusual activity alert lane.
- T82: isolated activity-alert CSV smoke test.
- T83: PIT-backed local paper runtime cycle.
- T84: live paper readiness gate.
- T85: stocks-only paper mode with options deferred.
- T86: market-data provider slot for daily bars.
- T87: data loading progress and ETA visibility.
- T88: live refresh config and credential readiness visibility.
- T89: Alpaca current-date refresh hardening.
- T90: current-date paper cycle reviewability.
- T91: Command paper review queue.
- T92: paper review action audit capture.
- T93: Command human-review state visibility.
- T94: Command review progress summary.
- T95: candidate detail review workspace.
- T96: paper review status API.
- T97: paper review smoke-check script.
- T98: operational readiness API and smoke-check script.
- T99: optional options anomaly and activity-alert runtime lanes.
- T105: Massive/Polygon stock-trades ingestion.
- T106: stock-trade classifier for sessions, direction, and block/off-exchange
  features.
- T107: buy/sell pressure signal from delayed trade prints.
- T108: block/off-exchange pressure signal from delayed trade prints.
- T109: Massive market-flow runtime, readiness, and docs wiring.
- T110: market-flow feature worker.
- T111: market-flow H1 evaluator.
- T112: market-flow threshold optimizer.
- T113: market-flow holdout validation.
- T114: market-flow runtime calibration.
- PR #82: provider readiness checklist.

## Next Ticket Candidates

Use `docs/phase-status.md` as the source of truth before drafting the next ticket.

Recommended next batch:

- T100: shared subscription-email evidence foundation.
- T101: Seeking Alpha email agent for analyst articles, news, and Quant ranking
  changes.
- T102: TradeVision email agent for bullish/bearish news, dark-pool, block
  trade, and unusual options/activity alerts.
- T103: Zacks email agent for news, rank changes, and analyst recommendations.
- T104: orchestration, dashboard readiness, deduplication, and calibration for
  all subscription-email agents.

## How To Assign A Ticket

1. Confirm dependencies in `docs/phase-status.md`.
2. Add a new `T<NN>-<slug>.md` file in this directory.
3. Create branch `feat/T<NN>-<slug>`.
4. Implement, validate, open a PR, and merge to `main`.
5. Move the completed ticket to `tickets/done/T<NN>-<slug>.done.md`.
