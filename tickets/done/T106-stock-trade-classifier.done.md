# T106: Stock Trade Classifier

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Classify delayed stock prints into PIT-safe trade features usable by research
signals without claiming unavailable aggressor-side truth.

## What Changed

- Added trade session classification for pre-market, regular, after-hours, and
  out-of-session prints.
- Added tick/zero-tick direction inference.
- Added notional, signed volume, signed notional, off-exchange, and block-print
  features.
- Filtered corrections and invalid price/size rows.

## Validation

- Unit coverage for direction inference, missing optional fields, pre-market
  classification, off-exchange detection, and block-trade detection.
