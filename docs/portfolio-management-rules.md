# Portfolio Management Rules

This note documents the paper-trading ownership chain and the first portfolio-management rules used by the agency.

## Trade Ownership Chain

1. **Human Review** records approve, defer, or reject on a candidate. Approval is permission to consider the candidate; it is not permission to bypass risk.
2. **Paper Trade Promotion Worker** converts eligible approved `WATCH` rows into paper `BUY` previews. It skips existing positions and ranks candidates by highest conviction, then ticker.
3. **Risk Manager** applies portfolio gates: minimum conviction, source health, policy gates, max new positions per cycle, and projected gross exposure.
4. **Execution Preview Worker** converts an allowed risk decision into a broker-ready order preview. Buy/short notional is account equity multiplied by `default_position_pct`; sell/cover quantity comes from the existing Alpaca paper position.
5. **Execution Broker Worker** submits to Alpaca paper only when broker submission is enabled, the row is `READY`, an order size exists, and human approval is recorded.
6. **Portfolio Manager Worker** monitors existing positions after entry. It flags take-profit, stop-loss, broken-thesis, warning, and no-current-setup cases for review.

If 30 candidates are approved, only the candidates that survive this whole chain can be fulfilled. The current promotion cap is `AGENCY_PAPER_TRADE_MAX_PER_CYCLE`; the portfolio capacity cap is `AGENCY_MAX_NEW_POSITIONS_PER_CYCLE`; gross exposure is capped by `AGENCY_MAX_GROSS_EXPOSURE_PCT`.

## Current Portfolio Rules

- **Take profit:** flag a close/trim review when unrealized gain reaches `AGENCY_TAKE_PROFIT_PCT`.
- **Stop loss:** flag urgent exit review when unrealized loss breaches `AGENCY_STOP_LOSS_PCT`.
- **Hourly performance:** compare current portfolio value with the latest snapshot at least 60 minutes old. If the portfolio return is below `-AGENCY_HOURLY_LOSS_ALERT_PCT`, the Portfolio Monitor shows a loss alert.
- **Trailing stop:** configured as `AGENCY_TRAILING_STOP_PCT`; enforcement requires position high-water tracking, so it is displayed as a policy target for now.

The Portfolio Manager does not auto-close positions. It creates clear review signals; actual paper orders still go through risk, execution preview, human approval, and Alpaca broker submission.

## Config Keys

The rules can be set in `.env` or in `research/config/portfolio-policy.local.json`.

- `AGENCY_DEFAULT_POSITION_PCT`
- `AGENCY_MAX_NEW_POSITIONS_PER_CYCLE`
- `AGENCY_MAX_GROSS_EXPOSURE_PCT`
- `AGENCY_TAKE_PROFIT_PCT`
- `AGENCY_STOP_LOSS_PCT`
- `AGENCY_TRAILING_STOP_PCT`
- `AGENCY_HOURLY_LOSS_ALERT_PCT`
- `AGENCY_BROKER_SUBMIT_ENABLED`
