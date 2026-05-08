# T86: Market Data Provider Slot

**Status:** complete
**Phase:** 4 validation unblock

## Goal

Add an opt-in daily stock-bar provider slot so current-date refreshes are not
hard-wired to yfinance when it stops returning fresh bars in the local
environment.

## What Changed

- Kept yfinance as the default daily price provider.
- Added an Alpaca daily stock-bars provider that can be selected with
  `--provider alpaca`.
- Added live refresh config fields for market-data provider, feed, adjustment,
  and base URL.
- Added batch blocking when Alpaca is selected but `ALPACA_API_KEY` and
  `ALPACA_SECRET_KEY` are not present.
- Updated price manifests to record provider source metadata.
- Renamed runtime price source identity to `daily-market-bars` so runtime
  readiness is not tied to one vendor name.

## Validation

- Unit coverage added for Alpaca bar normalization, paginated downloader
  requests, live refresh config parsing, and refresh-job blocking.

## Operator Note

Set `market_data_provider` to `alpaca` in the local live refresh config and add
Alpaca credentials to `.env` before attempting true current-date live validation.
