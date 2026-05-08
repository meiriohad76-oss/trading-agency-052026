# T81: Unusual activity alert lane

**Owner:** codex
**Phase:** 1 research expansion
**Status:** done

## Goal

Add a PIT-clean ingestion and signal scaffold for confirmed block-trade,
dark-pool, and unusual-activity alerts from paid/provider exports.

## Delivered

- Added `unusual_activity_alerts` as a manifest-backed PIT dataset.
- Added local CSV import for paid/confirmed activity alerts, including
  provenance, dedupe, parquet storage, and manifest writing.
- Added `PITLoader.activity_alerts(...)` plus the `activity_alerts` H1 signal
  registry entry.
- Added refresh-batch config and CLI support for an optional
  `activity_alerts_csv` input.
- Added unit coverage for CSV normalization, storage, PIT filtering, scoring,
  refresh jobs, and research-batch dataset requirements.

## Acceptance Notes

1. Block trades and unusual stock activity now have a separate confirmed alert
   lane instead of being conflated with bar-derived abnormal volume.
2. The lane is forward-only until real provider exports or historical email
   archives are imported.
3. The deterministic runtime remains conservative: this lane is not considered
   research-validated until H1 coverage exists.
