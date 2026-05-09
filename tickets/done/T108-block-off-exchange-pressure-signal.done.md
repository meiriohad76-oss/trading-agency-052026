# T108: Block/Off-Exchange Pressure Signal

**Status:** complete
**Phase:** 4 validation expansion

## Goal

Expose a market-flow context lane for large and off-exchange stock prints.

## What Changed

- Added `signals.block_trade_pressure`.
- Scores large/off-exchange focus prints by directional pressure, notional share,
  and focus count.
- Added runtime opt-in lane `block_trade_pressure`.
- Kept confirmed provider dark-pool labels in the separate `activity_alerts`
  lane.

## Validation

- Unit coverage confirms positive large/off-exchange pressure ranks above
  negative pressure and tracks block/off-exchange counts.
