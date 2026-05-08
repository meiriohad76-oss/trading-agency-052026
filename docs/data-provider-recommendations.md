# Data Provider Recommendations

**Last reviewed:** 2026-05-08

The codebase now has three optional market-activity lanes:

- `options_anomaly`: inferred from option-chain snapshots.
- `options_flow`: inferred call/put pressure from option-chain snapshots.
- `activity_alerts`: confirmed provider/export alerts for dark-pool prints,
  block trades, unusual options activity, options sweeps, and unusual stock
  activity.

## Recommended Stack

1. Keep the current core stack:
   - Alpaca for current daily stock bars.
   - SEC EDGAR for company facts, Form 4, and 13F.
   - RSS feeds for public forward news.

2. Add one confirmed activity provider first:
   - Preferred first candidate: Unusual Whales API.
   - Reason: one integration can cover options flow, dark-pool trades, off/lit
     trades, alerts, and ticker-level options analytics.
   - Use it to populate `unusual_activity_alerts`.

3. If Unusual Whales API access or cost is not acceptable:
   - Use Benzinga Unusual Options Activity for options alerts.
   - Use Benzinga Block Trades API for large options block-trade alerts.
   - Keep FINRA OTC/ATS transparency data as delayed context, not as a
     real-time action trigger.

4. Add raw historical options data only if H1/H2 research needs it:
   - Polygon/Massive options is a good API-first candidate for historical and
     real-time OPRA-based options trades/quotes.
   - ThetaData is a strong research-data candidate if we need deeper historical
     options and Greeks coverage.

## Implementation Order

1. Run current stocks-only paper testing.
2. Choose the confirmed activity provider.
3. Add one provider-specific puller that normalizes into the existing
   `unusual_activity_alerts` schema.
4. Import at least several weeks of forward or historical alerts.
5. Re-run H1 for `activity_alerts`, `options_anomaly`, and `options_flow`.
6. Enable optional runtime lanes only if coverage and validation are acceptable.

## Current Decision

Do not buy a raw OPRA/historical options package yet. The first missing data is
confirmed alert coverage for dark-pool, block-trade, and unusual-options events.
Buy or trial that first; add raw historical options only if the confirmed-alert
lane is useful or if H1 needs deeper options history.
