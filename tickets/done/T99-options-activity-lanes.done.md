# T99: Options Anomaly And Activity-Alert Lanes

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Make options anomaly, options flow, dark-pool, block-trade, and unusual-options
signals available as explicit opt-in lanes before choosing a paid provider.

## What Changed

- Added `options_anomaly` as an inferred option-chain signal.
- Kept `options_flow` and added both options lanes to optional runtime wiring.
- Expanded `activity_alerts` with explicit dark-pool, sweep, and
  unusual-options counts.
- Added `runtime_signals` to live refresh config so optional lanes can be
  enabled from `research/config/live-refresh.local.json`.
- Updated live config readiness and docs to explain inferred options-chain
  anomalies versus confirmed provider/export alerts.

## Validation

- Unit coverage for options anomaly scoring.
- Unit coverage for dark-pool, sweep, and options-activity alert counts.
- Unit coverage for config parsing and optional runtime dataset requirements.
