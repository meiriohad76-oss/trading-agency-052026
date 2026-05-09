# T102: TradeVision Email Agent

**Owner:** codex
**Phase:** 4 validation expansion
**Estimate:** medium
**Dependencies:** T100

## Goal

Add a TradeVision email agent that converts user-received TradeVision alerts into
confirmed unusual-activity evidence for dark-pool, block-trade, options-flow,
and bullish/bearish news signals.

## Context

TradeVision is valuable because it can provide unusual-options, dark-pool,
block-trade, bullish/bearish news, and unusual stock activity alerts. It does
not currently expose a known public API, so the user's subscription emails are
the intended ingestion path.

## Inputs

- T100 email evidence foundation.
- TradeVision emails from the user's approved mailbox/folder.
- Existing `unusual_activity_alerts` dataset and `activity_alerts` signal.
- Existing `news` lane for bullish/bearish news alerts.

## Outputs

- TradeVision-specific parser/classifier for:
  - bullish news,
  - bearish news,
  - dark-pool alerts,
  - block-trade alerts,
  - unusual options activity,
  - options sweeps or flow alerts,
  - unusual stock activity.
- Normalized rows for `unusual_activity_alerts` where the email represents
  confirmed activity.
- Normalized news/catalyst rows where the email represents bullish/bearish news.
- Confidence and verification defaults suitable for paid-subscription email.

## Acceptance Criteria

1. Dark-pool emails produce `alert_type=dark_pool` rows.
2. Block-trade emails produce `alert_type=block_trade` rows.
3. Options-flow/sweep emails produce options-specific alert rows.
4. Bullish/bearish news emails produce news/catalyst evidence rather than trade
   activity rows.
5. Direction is normalized to bullish/bearish/neutral where possible.
6. Duplicate TradeVision alerts are deduped by message id, ticker, alert type,
   and event timestamp.

## Tests Required

- Unit tests for dark-pool, block-trade, options-flow, and news alert fixtures.
- Unit tests for direction normalization.
- Integration test through the T100 local fixture ingest path.

## Out of Scope

- TradeVision website automation.
- Real-time browser scraping.
- Provider API integration unless TradeVision later exposes a documented API.

## Notes

This is the most important subscription-email agent for unusual market activity.
It should feed the same runtime lane as provider/export alerts.
