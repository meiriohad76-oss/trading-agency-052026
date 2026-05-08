# Phase Status

**Status:** reconciled after T88
**Owner:** Ohad Meiri
**Last updated:** 2026-05-08

This document is the operational truth table for the repo. It separates merged
implementation scaffolding from accepted phase gates.

## Current Truth

- T01-T88 are archived under `tickets/done/`.
- The repo contains Phase 0 foundation, Phase 1 research machinery, Phase 2
  contracts/dashboard scaffolding, and Phase 3 runtime orchestration through a
  PIT-backed local paper cycle.
- T29-T64 are provisional build scaffolding until empirical H1-H5 results exist.
- The dashboard and cycle runner are local paper/demo tools. They are not a live
  trading system and do not submit broker orders.

## Phase Gates

| Phase | Planned gate | Current status | Next action |
| --- | --- | --- | --- |
| Phase 0 setup | Repo runnable; provenance-wrapped values persist end to end. | Complete for local development. | Keep Docker/Python setup green. |
| Phase 1 research | Validated lanes, realistic profile, thresholds, plan revision. | Live H1 calibration is inconclusive; conservative thresholds are active. | Test first version, then widen H1 coverage or improve ticker-tagged sources. |
| Phase 2 design | Design doc, finalized schemas, UX prototype, test plan. | Partially implemented ahead of gate with provisional contracts. | Reconcile after findings; write explicit design/test plan. |
| Phase 3 build | Components built with all three test layers green. | Runtime can persist seeded, PIT-backed, and stocks-only replay paper cycles. | Keep first-version path stable during testing. |
| Phase 4 validate | Paper-test against live data; user testing; threshold adjustment. | Stocks-only PIT replay is ready for user inspection; current-date live validation has an Alpaca provider slot, visible refresh progress/ETA, and visible config readiness checks, but still needs local credentials. | Configure Alpaca credentials only after the Live Config panel has no blockers, run a current-date refresh, then watch progress on Command and run a persisted live paper cycle. |
| Phase 5 operate | Production paper trading and learning loop. | Not started. | Wait for Phase 4 validation. |

## High-Priority Gaps

1. Live refresh inputs are configured locally and T72 has a compact committed
   summary under `research/results/t72-live-summary/`. Raw/parquet data remains
   local-only.
2. T73 calibrated the deterministic `WATCH` gate to require two usable independent
   sources and at least one confirmed signal. No tested H1 lane is standalone-validated.
3. Runtime audit persistence and read-only visibility are wired for manual,
   scheduled, seeded, and PIT-backed local paper cycles; prompt audit capture
   waits for live LLM calls.
4. Lightweight scheduler, `/metrics`, structured JSON logging, local deployment
   commands, and backup/restore scripts exist.
5. First-version manual inspection checklist and server-side e2e smoke coverage exist.
6. `/status/live-readiness`, Command-page readiness, and readiness metrics explain
   whether the latest cycle is reviewable or context-only.
7. Portfolio policy is still static/read-only, not persisted or user-editable.
8. Options/unusual-activity providers are explicitly deferred to backlog; the
   default runtime lane set is stocks-only.
9. Current-date live validation can now select `market_data_provider="alpaca"`,
   but it still needs local Alpaca credentials before bars past `2025-12-31`
   can be tested in this environment.
10. Data refresh batches now write incremental progress and ETA status; the
    Command page polls the latest status file while data is loading.
11. `/status/live-config` and the Command-page Live Config panel show refresh
    config and credential readiness without exposing secret values.

## Next Ticket Candidates

No active numbered ticket is selected. Recommended next work is clearing any
Live Config blockers, configuring local Alpaca credentials, and running a
current-date live refresh/cycle smoke while watching the Command-page Data
Loading panel.

## Operating Rule

Any new feature ticket should say whether it is provisional scaffolding or accepted
phase-gate work. Research verdicts in `docs/findings.md` remain the authority for
which signal lanes become action-weighted.
