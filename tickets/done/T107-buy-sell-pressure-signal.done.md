# T107: Buy/Sell Pressure Signal

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Expose a conservative inferred buy/sell pressure lane from delayed stock prints.

## What Changed

- Added `signals.buy_sell_pressure`.
- Added PIT loader support for the `stock_trades` dataset.
- Added signal registry and research-batch dataset requirements.
- Added runtime opt-in lane `buy_sell_pressure`.

## Validation

- Unit coverage confirms positive signed print pressure ranks above negative
  pressure and that pre-market contribution is tracked.
