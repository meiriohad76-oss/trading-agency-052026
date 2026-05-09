# T104: Subscription Agent Orchestration And Calibration

**Owner:** codex
**Phase:** 4 validation expansion
**Estimate:** medium
**Dependencies:** T101, T102, T103

## Goal

Wire the subscription email agents into the runtime and evaluate whether their
signals improve selection quality.

## Context

After Seeking Alpha, TradeVision, and Zacks agents exist, the agency needs a
single orchestration path that runs them periodically, reports source health,
dedupes overlapping events, and calibrates actionability thresholds.

## Inputs

- T101 Seeking Alpha email agent.
- T102 TradeVision email agent.
- T103 Zacks email agent.
- Existing live refresh, runtime cycle, readiness, and actionability calibration
  tooling.

## Outputs

- Subscription-agent refresh command or scheduled job.
- Source-health rows for each subscription service.
- Deduped cross-provider catalyst/activity event view.
- Dashboard/readiness visibility for subscription agents.
- Calibration report showing whether subscription-email evidence adds edge.

## Acceptance Criteria

1. A single command can run all enabled subscription agents.
2. Each service can be enabled/disabled independently.
3. Source health shows last successful email ingest per service.
4. Duplicate events across SA/Zacks/TradeVision/RSS collapse into one event with
   multiple source references.
5. Runtime evidence packs can include subscription-agent evidence with clear
   provenance.
6. Calibration output states whether subscription signals remain context-only or
   can influence WATCH/BUY decisions.

## Tests Required

- Unit tests for provider enable/disable config.
- Unit tests for cross-provider event deduplication.
- Runtime-cycle smoke test with fixture subscription evidence.
- Calibration/report generation test.

## Out of Scope

- Adding new paid API providers.
- Browser automation for subscription websites.
- Broker order execution.

## Notes

Keep the first runtime behavior conservative: subscription evidence can upgrade
confidence and corroboration, but direct action weighting should wait for
forward validation.
