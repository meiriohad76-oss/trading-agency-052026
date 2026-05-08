# T70: Scheduler, metrics, and structured logging

**Owner:** codex
**Phase:** 3 provisional runtime scaffolding
**Status:** done

## Goal

Add lightweight runtime observability primitives needed before local paper testing.

## Delivered

- Added a small async scheduler primitive with due checks, skip states, success
  payloads, and failure reporting.
- Added Prometheus text rendering for runtime source health, selection, and risk
  counters.
- Exposed `/metrics` on the FastAPI app with resilient bootstrap fallbacks.
- Added compact structured JSON logging for the manual agency cycle runner.
- Added unit coverage for scheduler behavior, metrics text, `/metrics`, and log
  rendering.

## Acceptance Notes

1. The scheduler is an embeddable primitive, not a long-running production daemon.
2. Metrics remain useful when the database is unavailable by reporting bootstrap
   source-health status and zero report/decision counts.
3. The manual cycle runner now prints machine-readable artifact counts after a
   successful commit.
