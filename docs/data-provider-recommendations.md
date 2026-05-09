# Data Provider Recommendations

**Last reviewed:** 2026-05-09

This is the provider stack for the whole agency. Current local operation is
paper-only; optional providers become useful as we add their connectors and
validate each signal lane.

## Provider Matrix

| Priority | Provider | Agency area | Local key | Current status |
| --- | --- | --- | --- | --- |
| 1 | Alpaca | Daily stock bars | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | Wired |
| 1 | SEC EDGAR | Company facts, Form 4, 13F | `SEC_USER_AGENT` | Wired |
| 1 | RSS feeds | Forward public news | none | Wired |
| 2 | OpenFIGI | CUSIP/ticker/security mapping | `OPENFIGI_API_KEY` | Planned |
| 2 | Benzinga | News, calendars, ratings, unusual activity | `BENZINGA_API_KEY` | Planned |
| 2 | Unusual Whales | Dark-pool, options flow, unusual activity | `UNUSUAL_WHALES_API_KEY` | Planned |
| 3 | FRED | Macro/rate regime filters | `FRED_API_KEY` | Planned |
| 3 | Polygon/Massive | Raw stock/options market data | `POLYGON_API_KEY` or `MASSIVE_API_KEY` | Planned |
| 3 | ThetaData | Deep historical options research | `THETADATA_USERNAME`, `THETADATA_PASSWORD` | Planned |
| 3 | FINRA OTC Transparency | Delayed market-structure context | none | Planned |
| Later | OpenAI | Supervised LLM review calls | `OPENAI_API_KEY` | Optional |

## Implementation Order

1. Keep Alpaca, SEC EDGAR, and RSS as the operational stocks-only paper stack.
2. Add OpenFIGI before expanding 13F coverage, so CUSIP mapping is repeatable.
3. Add one confirmed activity provider next: Unusual Whales if the API plan is
   acceptable, otherwise Benzinga unusual-activity endpoints.
4. Import several weeks of confirmed activity alerts, then re-run H1/H2 before
   enabling `activity_alerts`, `options_anomaly`, or `options_flow` in runtime.
5. Add FRED only once macro filters are part of candidate scoring.
6. Buy deep historical options data only after the alert lane proves useful.

## Local Readiness

Provider keys belong in `.env` only. The dashboard and
`/status/provider-readiness` show key names and present/missing status without
exposing secret values.

Optional activity/options lanes are already represented in the data model:

- `options_anomaly`: inferred from option-chain snapshots.
- `options_flow`: inferred call/put pressure from option-chain snapshots.
- `activity_alerts`: confirmed provider/export alerts for dark-pool prints,
  block trades, unusual options activity, options sweeps, and unusual stock
  activity.

Until provider-specific connectors exist, confirmed activity data enters through
`research/config/activity-alerts.example.csv` copied to a local ignored CSV and
referenced by `activity_alerts_csv` in `research/config/live-refresh.local.json`.
