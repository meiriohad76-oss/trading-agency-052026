# Phase Status

**Status:** reconciled after T109
**Owner:** Ohad Meiri
**Last updated:** 2026-05-09

This document is the operational truth table for the repo. It separates merged
implementation scaffolding from accepted phase gates.

## Current Truth

- T01-T99 and T105-T109 are archived under `tickets/done/`.
- T100-T104 remain open backlog tickets for subscription-email evidence agents.
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
| Phase 4 validate | Paper-test against live data; user testing; threshold adjustment. | Current-date live data refresh and a persisted stocks-only paper cycle are ready for user inspection. The Command dashboard, candidate detail pages, `/status/paper-review`, `/status/operational-readiness`, and CLI smoke checks now support paper-review inspection and audit capture. | Run the operational readiness smoke check, then start inspection from the Command review queue. |
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
8. Options/unusual-activity lanes are implemented and opt-in:
   `options_anomaly`, `options_flow`, and `activity_alerts`. Provider selection
   is still deferred for confirmed options/dark-pool alerts; the default runtime
   lane set remains stocks-only.
9. Current-date live validation can now select `market_data_provider="alpaca"`;
   local credentials are required and are checked by Live Config before refresh.
10. Data refresh batches now write incremental progress and ETA status; the
    Command page polls the latest status file while data is loading, and command
    duration stamps now measure elapsed subprocess time.
11. `/status/live-config` and the Command-page Live Config panel show refresh
    config and credential readiness without exposing secret values.
12. Current-date local validation produced a `ready_for_paper_validation` cycle
    with WATCH candidates and paper-only risk decisions.
13. The Command dashboard now pairs latest-cycle reviewable selection reports
    with risk decisions so paper candidates can be inspected from one queue.
14. Paper review decisions can be recorded as append-only candidate lifecycle
    events from the Command review queue.
15. The Command review queue now shows the latest recorded human-review state
    for each current-cycle candidate.
16. The Command dashboard now summarizes review progress for the latest paper
    cycle, including pending, approved, deferred, and rejected counts.
17. Candidate detail pages now show latest paper-review state and the same
    approve/defer/reject review actions as the Command queue.
18. `/status/paper-review` exposes the current paper-review queue and progress
    summary for CLI checks and future automation.
19. `scripts/check_paper_review_status.py` provides a one-command smoke check
    for paper-review queue and progress thresholds.
20. `/status/operational-readiness` and
    `scripts/check_operational_readiness.py` combine health, live config, data
    refresh, live runtime, paper review, and key-presence checks into one local
    first-version readiness gate.
21. Optional options/activity runtime wiring now supports forward option-chain
    anomaly scoring plus confirmed provider/export alerts for dark-pool,
    block-trade, and unusual-options activity.
22. `/status/provider-readiness` and the Command dashboard now show the
    whole-agency provider-key checklist without exposing secret values. Missing
    future-provider keys stay planned instead of blocking the current paper flow.
23. Subscription-email agents are now planned as T100-T104: a shared mailbox
    evidence foundation plus separate Seeking Alpha, TradeVision, and Zacks
    agents, followed by orchestration and calibration.
24. Massive/Polygon delayed stock trades are now wired as an opt-in
    `stock_trades` dataset with `buy_sell_pressure` and `block_trade_pressure`
    runtime lanes. These lanes are inferred from confirmed prints and require
    `POLYGON_API_KEY` or `MASSIVE_API_KEY` only when enabled.

## Next Ticket Candidates

The active backlog is T100-T104. Recommended order is T100 first, then T101-T103
in parallel if ownership is split, then T104 once all subscription-email agents
can emit fixture evidence. After the user adds a Massive/Polygon key, run a
small live `stock_trades` refresh and keep market-flow lanes context-only until
H1 has enough coverage to retest them.

## Operating Rule

Any new feature ticket should say whether it is provisional scaffolding or accepted
phase-gate work. Research verdicts in `docs/findings.md` remain the authority for
which signal lanes become action-weighted.
