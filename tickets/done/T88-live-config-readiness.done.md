# T88: Live Config Readiness

**Status:** complete
**Phase:** 4 validation usability

## Goal

Show whether the local live-refresh configuration and required credentials are
ready before the operator starts a refresh.

## What Changed

- Added a live config readiness helper that inspects the selected refresh config,
  provider choice, ticker inputs, SEC inputs, RSS feeds, 13F inputs, CUSIP map,
  and activity-alert CSV.
- Added Alpaca credential presence checks without exposing secret values.
- Added `/status/live-config` for machine-readable readiness inspection.
- Added a Command-page Live Config panel with provider, dataset, ticker, blocker,
  and per-check detail rows.
- Documented the readiness check in first-version testing and deployment notes.

## Validation

- Unit coverage for blocked Alpaca credentials, ready configured inputs,
  yfinance warning behavior, and the `/status/live-config` endpoint.
- Dashboard coverage for the Live Config panel and Review config action.
