# Phase Status

**Status:** reconciled after T66
**Owner:** Ohad Meiri
**Last updated:** 2026-05-07

This document is the operational truth table for the repo. It separates merged
implementation scaffolding from accepted phase gates.

## Current Truth

- T01-T66 are archived under `tickets/done/`.
- The repo contains Phase 0 foundation, Phase 1 research machinery, Phase 2
  contracts/dashboard scaffolding, and early Phase 3 runtime orchestration.
- T29-T64 are provisional build scaffolding until empirical H1-H5 results exist.
- The dashboard and cycle runner are local paper/demo tools. They are not a live
  trading system and do not submit broker orders.

## Phase Gates

| Phase | Planned gate | Current status | Next action |
| --- | --- | --- | --- |
| Phase 0 setup | Repo runnable; provenance-wrapped values persist end to end. | Complete for local development. | Keep Docker/Python setup green. |
| Phase 1 research | Validated lanes, realistic profile, thresholds, plan revision. | Scaffolding complete; empirical results pending. | Run data refresh and H1/H2/H3/H4/H5 result jobs. |
| Phase 2 design | Design doc, finalized schemas, UX prototype, test plan. | Partially implemented ahead of gate with provisional contracts. | Reconcile after findings; write explicit design/test plan. |
| Phase 3 build | Components built with all three test layers green. | Early scaffolding exists through T64. | Add missing services only after status stays explicit. |
| Phase 4 validate | Paper-test against live data; user testing; threshold adjustment. | Not started. | Wait for Phase 3 readiness. |
| Phase 5 operate | Production paper trading and learning loop. | Not started. | Wait for Phase 4 validation. |

## High-Priority Gaps

1. Empirical result artifacts under `research/results/` are blocked by missing
   PIT manifests beyond universe membership.
2. Actionability gates need per-lane source count, freshness, deduplication, and
   inferred-signal corroboration rules.
3. Runtime audit persistence lacks agent-run rows, prompt/response audit, execution
   state history, and richer risk snapshots.
4. Scheduler, `/metrics`, structured JSON logging, deployment, and backups are not
   implemented yet.
5. Portfolio policy is still static/read-only, not persisted or user-editable.
6. Paid-sub email ingestion and research mailbox decisions remain open.

## Next Ticket Candidates

| Ticket | Purpose |
| --- | --- |
| T67 | Data refresh batch for prices, SEC facts/Form 4/13F, RSS, and options manifests. |
| T68 | Actionability gate v1 with per-lane thresholds and corroboration. |
| T69 | Runtime audit tables for agent runs, prompt audit, execution state, risk snapshots. |
| T70 | Scheduler, `/metrics`, and structured runtime logging. |
| T71 | Deployment/backups checkpoint for Pi-oriented reproducibility. |

## Operating Rule

Any new feature ticket should say whether it is provisional scaffolding or accepted
phase-gate work. Research verdicts in `docs/findings.md` remain the authority for
which signal lanes become action-weighted.
