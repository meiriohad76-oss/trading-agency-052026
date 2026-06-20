# Unusual Trading Activity Agent - Product Design And Rebuild Specification

Status: draft for expert review  
Audience: product designer, market microstructure expert, quant researcher, data engineer, frontend designer, QA lead  
Primary goal: rebuild the unusual-trading activity agent from scratch as a reliable, explainable, lane-based, user-actionable market-flow module for the Trading Agency.

## 1. Executive Summary

The Unusual Trading Activity Agent should identify, rank, explain, and monitor abnormal equity trading behavior that may indicate institutional participation, liquidity events, informed flow, post-news repricing, or market-wide risk-off/risk-on participation. It should not claim that a trade is "institutional buying" or "dark pool buying" unless the data actually proves that level of specificity. The product must distinguish:

- confirmed provider alerts versus inferred activity from trade prints,
- off-exchange/TRF prints versus named dark-pool venue proof,
- large prints versus ticker-relative block trades,
- unusual volume versus unusual directional pressure,
- high activity that is actionable versus high activity that is merely noisy context.

The rebuilt agent should be a dedicated product module with its own data contract, score contract, UX contract, and QA gates. It should consume raw lane outputs from the Massive Multi-Lane Data Orchestrator and optional confirmed provider alert feeds. It should not independently pull broad raw trade endpoints for each signal. Raw acquisition happens once; derived agents reuse lane artifacts.

## 2. Product Goals

### 2.1 Operator Goals

The user should be able to answer, in plain English:

1. What unusual trading activity was detected?
2. Was it unusual by volume, notional, trade count, off-exchange concentration, block size, price level, timing, or directional pressure?
3. What data source proves it?
4. When was the data captured and how fresh is it?
5. Is it bullish, bearish, mixed, or context-only?
6. How confident is the agent, and why?
7. Is the evidence enough to affect a candidate ranking, or only enough to watch?
8. What should the user check next before approving a paper trade?

### 2.2 System Goals

The system should:

- use only real source data, no testing/fixture rows in production views,
- show live lane state and data health beside every unusual-activity finding,
- reuse raw trade lanes rather than repeatedly querying Massive,
- produce deterministic, auditable calculations,
- separate raw observations from interpretation,
- support replay/backtesting with point-in-time data,
- expose enough metadata for dashboard, candidate detail, and paper-trading gate decisions,
- fail visibly and specifically when data is unavailable, incomplete, loading, or not analyzed.

### 2.3 Non-Goals

The agent should not:

- claim a TRF print is a named dark-pool venue unless the source identifies that venue,
- treat every large print as bullish,
- treat every off-exchange print as institutional accumulation,
- promote a trade from unusual activity alone without corroboration,
- hide incomplete source coverage behind a positive score,
- infer direction from price-only data when trade signing confidence is too low.

## 3. Definitions

### 3.1 Raw Trade Print

A single equity trade record with at least ticker, timestamp, price, size, exchange/venue code where available, conditions where available, and participant/exchange timestamps where available.

### 3.2 Notional

`notional = price * shares`

This is the primary scale metric for large trades because share size alone is not comparable across a $10 stock and a $1,000 stock.

### 3.3 Block Trade Candidate

A trade or cluster of trades that is large relative to both:

- an absolute floor, and
- the ticker's own recent trade-size/notional baseline.

Recommended initial rule:

```text
absolute_block = shares >= 10,000 OR notional >= $200,000
relative_block = shares >= 5x median_trade_size OR notional >= 5x median_trade_notional
large_print = absolute_block AND relative_block
```

This prevents high-liquidity mega-cap names from dominating simply because their normal prints are large.

### 3.4 Off-Exchange / TRF Print

Massive's public materials state that a stock trade with `exchange: 4` and a `trf_id` field is a dark-pool or otherwise off-exchange print. In product language, the agency should display this as "TRF/off-exchange print" unless a source provides named venue identity. Do not display "dark pool buy" as a proven fact from this field alone.

### 3.5 Dark Pool Evidence

Dark pool evidence can be:

- direct: a provider/source explicitly labels a print as dark-pool/off-exchange and includes venue/provenance,
- inferred: Massive trade record has TRF/off-exchange signature,
- contextual: unusual concentration of large off-exchange prints near a price level.

The UX must label which kind of evidence is present.

### 3.6 Signed Pressure

Signed pressure estimates whether activity leaned buyer-side or seller-side:

```text
signed_volume_pressure = signed_volume / total_volume
signed_notional_pressure = signed_notional / total_notional
```

Direction is inferred by trade signing:

1. quote rule when bid/ask are available,
2. tick test fallback when bid/ask are unavailable,
3. unknown/neutral when neither method is reliable.

### 3.7 Unusual Activity

Activity is unusual when the latest observed activity is large relative to the ticker's own baseline:

```text
volume_ratio = latest_volume / median_baseline_volume
notional_ratio = latest_notional / median_baseline_notional
trade_count_ratio = latest_trade_count / median_baseline_trade_count
```

Robust z-score and MAD-score should also be computed to reduce sensitivity to outliers.

## 4. Current Agency Context

The current agency already contains useful pieces that should be preserved conceptually:

- `massive_live_trade_slices`: raw current-day trade prints.
- `massive_premarket_trade_slices`: 04:00-09:30 ET trade activity.
- `massive_block_trade_feed`: local derivation from live trade slices; zero extra Massive requests.
- `buy_sell_pressure`: signed notional/volume pressure.
- `block_trade_pressure`: focus prints by block/TRF/off-exchange notional share and direction.
- `unusual_trade_activity`: trade count, volume, and notional anomaly.
- `pre_market_unusual_activity`: pre-market anomaly context.
- `market_flow_trend`: short trend in signed pressure.
- `activity_alerts`: optional confirmed provider/email alerts for dark pool, block trade, sweep, unusual stock/options activity.

The rebuild should consolidate these into a single product experience while keeping the derived signal lanes independent enough for scoring, testing, and validation.

## 5. Proposed Product Model

### 5.1 Product Name

Recommended internal name:

```text
Unusual Trading Activity Agent
```

Recommended dashboard title:

```text
Unusual Trading Activity
```

Recommended submodules:

1. Flow Pressure
2. Block / Large Print Pressure
3. TRF / Off-Exchange Activity
4. Unusual Volume / Notional
5. Pre-Market Activity
6. Market Flow Trend
7. Confirmed Provider Alerts

### 5.2 Agent Output Types

The agent should output three levels of product evidence:

#### Observation

Raw detected fact:

```json
{
  "ticker": "AVGO",
  "event_type": "trf_off_exchange_cluster",
  "observed_at": "2026-06-06T14:35:22Z",
  "source_lane": "massive_live_trade_slices",
  "source_rows": 12,
  "notional": 440000000,
  "shares": 980000,
  "price_range": [448.10, 451.25],
  "data_health": "ready"
}
```

#### Interpretation

Calculated meaning:

```json
{
  "direction": "bullish",
  "direction_method": "quote_rule_then_tick_test",
  "signed_notional_pressure": 0.72,
  "confidence": 0.74,
  "reason": "TRF/off-exchange focus prints represented 50% of analyzed notional and signed pressure leaned buyer-side."
}
```

#### User Guidance

Plain-English action context:

```json
{
  "operator_line": "AVGO had unusually large TRF/off-exchange prints totaling $440.0M, with +72% signed notional pressure.",
  "recommendation": "Treat as bullish supporting evidence only if price action and another independent lane also confirm. Check whether the prints occurred near VWAP/support/resistance and whether follow-through continued after the prints.",
  "limitations": "TRF/off-exchange identifies off-exchange reporting, not the named institution or venue."
}
```

## 6. Data Sources

### 6.1 Primary Raw Source: Massive Stock Trades

Purpose:

- tick-level trade prints,
- price, size, exchange, conditions, timestamps,
- TRF/off-exchange detection,
- raw input for all market-flow derived lanes.

Required fields:

| Field | Purpose |
|---|---|
| ticker | symbol mapping |
| participant/exchange timestamp | event ordering and freshness |
| price | notional, price level, price impact |
| size | volume, block-size detection |
| exchange | off-exchange/TRF rule |
| trf_id | TRF/off-exchange evidence |
| conditions | exclude/categorize special prints |
| bid/ask, if available | quote-rule trade signing |
| sequence/id | dedupe and ordering |

Lane:

```text
massive_live_trade_slices
```

Timing:

- pre-market and regular market,
- 5-minute cadence while market is active,
- slower cadence after hours unless the user manually refreshes.

### 6.2 Primary Derived Source: Massive Block Trade Feed

Purpose:

- local derivation from live trade slices,
- no additional Massive requests,
- stores focus prints and manifest state.

Lane:

```text
massive_block_trade_feed
```

This lane should be derived only when `massive_live_trade_slices` is usable for the same ticker/date/window.

### 6.3 Pre-Market Trade Slices

Purpose:

- 04:00-09:30 ET activity,
- gap/velocity/volume anomaly before regular session.

Lane:

```text
massive_premarket_trade_slices
```

### 6.4 Daily Bars

Purpose:

- daily volume baseline,
- price trend confirmation,
- ATR/volatility context,
- support/resistance and VWAP-adjacent context if intraday bars are not available.

Lane:

```text
massive_daily_bars
```

### 6.5 Optional Confirmed Alert Sources

Examples:

- TradeVision email exports,
- Unusual Whales export/API,
- Trade Echo/other provider export,
- manual CSV import.

Purpose:

- explicitly provider-labeled dark pool/block/unusual/options alerts,
- independent corroboration,
- optional confidence boost when provider provenance is strong.

Lane:

```text
activity_alerts
```

Rules:

- every alert must have provenance,
- every imported alert must be deduped,
- every alert must be consumed once or marked as already evaluated,
- provider labels must be displayed as provider labels, not as agency-proven facts.

## 7. Lane Architecture

### 7.1 Raw Lanes

| Lane | Pulls Provider? | Purpose | Execution Blocking? |
|---|---:|---|---:|
| `massive_live_trade_slices` | yes | current trade prints | yes for live paper decisions |
| `massive_premarket_trade_slices` | yes | pre-market activity | yes during pre-market |
| `massive_block_trade_feed` | no | derived block/TRF focus feed | yes when block signal is required |
| `massive_daily_bars` | yes | daily baseline and trend | yes |
| `activity_alerts` | optional | confirmed provider alert import | no unless explicitly configured |

### 7.2 Derived Signal Lanes

| Signal | Reads From | Should Pull Massive Directly? |
|---|---|---:|
| `buy_sell_pressure` | `massive_live_trade_slices` | no |
| `block_trade_pressure` | `massive_live_trade_slices`, `massive_block_trade_feed` | no |
| `unusual_trade_activity` | live slices + historical baseline | no |
| `pre_market_unusual_activity` | pre-market slices + baseline | no |
| `market_flow_trend` | rolling live slices | no |
| `activity_alerts` | confirmed alert lane | no |

### 7.3 Data State Contract

Every lane must expose:

```json
{
  "lane_id": "massive_live_trade_slices",
  "ticker": "AVGO",
  "state": "ready",
  "operator_label": "Ready",
  "progress": {
    "requested_tickers": 168,
    "completed_tickers": 168,
    "coverage_pct": 1.0
  },
  "latest_as_of": "2026-06-06T14:35:22Z",
  "freshness_seconds": 120,
  "freshness_sla_seconds": 1800,
  "gaps": [],
  "next_action": {
    "label": "Refresh Live Trade Slices",
    "route": "/scheduler/massive-lanes/massive_live_trade_slices/refresh"
  }
}
```

Allowed states:

| State | Meaning | UX Label |
|---|---|---|
| `ready` | source exists, analyzed, fresh enough | Ready |
| `loading` | source extraction is running | Data is still loading |
| `source_available_not_analyzed` | raw data exists but derived agent has not run | Data loaded, analysis pending |
| `analysis_needs_refresh` | analysis exists but no longer fresh enough | Analysis needs refresh |
| `source_unavailable` | provider/API/file unavailable | Provider unavailable |
| `partial_usable` | incomplete but enough for review context | Usable partial |
| `blocked` | cannot evaluate due to missing required source | Cannot evaluate |
| `disabled_optional` | optional source disabled | Optional source disabled |

Do not use "stale" as a user-facing label.

## 8. Algorithm Design

### 8.1 Preprocessing

For each ticker/window:

1. Normalize ticker to current symbol.
2. Deduplicate trades by provider trade id or `(ticker, timestamp, price, size, exchange, conditions)`.
3. Compute `notional = price * size`.
4. Mark session:
   - pre-market,
   - regular,
   - after-hours.
5. Mark venue:
   - lit exchange,
   - TRF/off-exchange,
   - unknown.
6. Mark special conditions:
   - opening/closing prints,
   - corrections/cancels,
   - odd lots,
   - late reports,
   - average price or derivatively priced if detectable.
7. Trade signing:
   - quote rule when bid/ask is present,
   - tick test fallback,
   - unknown when confidence is insufficient.
8. Compute signed volume and signed notional.

### 8.2 Block / Large Print Detection

Recommended initial detection:

```text
median_size = median(size over ticker/window)
median_notional = median(notional over ticker/window)

absolute_block = size >= 10,000 OR notional >= 200,000
relative_block = size >= 5 * median_size OR notional >= 5 * median_notional

large_print = absolute_block AND relative_block
trf_off_exchange = exchange == 4 AND trf_id is present
focus_print = trf_off_exchange OR large_print OR provider_confirmed_block
```

Recommended expert review:

- determine whether the 10,000 share / $200,000 absolute floor is too low for mega-caps,
- consider market-cap/liquidity buckets,
- consider intraday percentile baselines rather than all-day medians,
- consider excluding prints with conditions that often represent non-directional activity.

### 8.3 Block Trade Pressure

Inputs:

- focus prints,
- total analyzed notional,
- signed focus notional,
- focus count,
- largest focus print multiple.

Calculation:

```text
focus_notional_share = focus_notional / total_notional
directional_pressure = signed_focus_notional / focus_notional
focus_activity_score = focus_notional_share * log1p(focus_trade_count)
block_trade_pressure = directional_pressure * focus_activity_score
```

Enhancements:

```text
largest_print_bonus = clamp(log1p(largest_focus_notional_multiple) / log1p(20), 0, 1)
cluster_bonus = clamp(clustered_focus_notional / focus_notional, 0, 1)
price_level_bonus = 1 if clustered near VWAP/support/resistance else 0

enhanced_block_pressure =
  directional_pressure
  * focus_notional_share
  * log1p(focus_trade_count)
  * (1 + 0.15 * largest_print_bonus + 0.10 * cluster_bonus + 0.10 * price_level_bonus)
```

### 8.4 Buy/Sell Pressure

Inputs:

- total signed notional,
- total signed volume,
- pre-market signed pressure,
- pre-market participation.

Current baseline:

```text
buy_sell_pressure =
  0.45 * net_notional_pressure
  + 0.20 * net_volume_pressure
  + 0.35 * pre_market_net_pressure * min(1, pre_market_volume_share * 4)
```

Recommended refinements:

- separate regular-market and pre-market scores,
- show signing confidence,
- reduce weight when bid/ask is unavailable and tick-test dominates,
- cap influence when sample size is too small.

### 8.5 Unusual Trade Activity

For latest window/day:

```text
trade_count_ratio = latest_trade_count / median_baseline_trade_count
volume_ratio = latest_volume / median_baseline_volume
notional_ratio = latest_notional / median_baseline_notional
```

Robust anomaly:

```text
robust_z = (latest - median_baseline) / robust_sigma
mad_score = abs(latest - median) / MAD
```

Recommended bands:

| Band | Ratio Trigger | Meaning |
|---|---:|---|
| normal | < 1.5x | ordinary |
| attention | >= 1.5x | worth showing |
| strong | >= 2.0x | meaningful anomaly |
| extreme | >= 3.0x or high robust anomaly | major anomaly |

Direction:

```text
activity_direction = sign(latest_signed_notional_pressure)
```

Do not call unusual volume bullish unless the price/pressure context supports it.

### 8.6 Pre-Market Unusual Activity

Inputs:

- pre-market volume,
- pre-market notional,
- pre-market signed pressure,
- pre-market price gap,
- historical pre-market baseline.

Score:

```text
pre_market_activity =
  anomaly_strength(volume, notional)
  * signed_pressure
  * participation_scale
```

UX must show:

- pre-market window,
- latest pre-market volume,
- baseline median,
- gap direction,
- whether regular-market confirmation has occurred yet.

### 8.7 Market Flow Trend

Inputs:

- latest signed notional pressure,
- recent median signed notional pressure,
- latest notional participation.

Calculation:

```text
pressure_delta = latest_net_notional_pressure - prior_median_net_notional_pressure
participation = latest_notional / prior_median_notional
market_flow_trend = pressure_delta * participation_scale
```

Interpretation:

- bullish: pressure improving with enough participation,
- bearish: pressure deteriorating with enough participation,
- neutral: low participation or mixed/flat pressure.

### 8.8 Confirmed Activity Alerts

For provider-confirmed alerts:

```text
alert_pressure =
  direction
  * confidence
  * type_weight
  * log1p(magnitude)
```

Type weights:

- block/dark-pool/large-print: +0.25,
- options activity: +0.20,
- confirmed provider label: confidence multiplier,
- unverified social/marketing signal: no promotion, context only.

## 9. Ranking And Scoring

### 9.1 Per-Ticker Composite

Recommended composite:

```text
raw_activity_score =
  0.25 * unusual_activity_strength
  + 0.25 * block_trade_pressure_strength
  + 0.20 * buy_sell_pressure_strength
  + 0.15 * market_flow_trend_strength
  + 0.10 * pre_market_activity_strength
  + 0.05 * confirmed_alert_strength
```

Then apply:

```text
direction = weighted sign of directional components
confidence = data_quality * method_confidence * corroboration_confidence
actionability = strength * confidence * corroboration_factor
```

### 9.2 Corroboration Boost

Corroboration should increase confidence only when sources are independent:

| Corroboration | Example | Effect |
|---|---|---|
| same raw lane only | unusual notional + block pressure both from same prints | modest |
| raw flow + price action | pressure aligns with price breakout/breakdown | meaningful |
| raw flow + news catalyst | unusual activity after company-specific news | meaningful |
| raw flow + options flow | equity pressure plus call/put flow | meaningful |
| provider alert + raw trade evidence | confirmed alert with matching prints | strong |

### 9.3 Ranking Classes

| Class | Requirement | UX Meaning |
|---|---|---|
| `A` | strong activity + direction + corroboration + fresh data | actionable support |
| `B` | strong activity but limited corroboration | review closely |
| `C` | activity present but direction weak/mixed | context only |
| `D` | weak, stale, incomplete, or noisy | do not use |

### 9.4 Candidate Contribution

Unusual trading should generally be a supporting signal, not a standalone paper-trading trigger.

Recommended effect on candidate score:

- max positive contribution: capped unless corroborated,
- max negative contribution: capped unless confirmed by price/technical/news risk,
- no contribution when lane state is not ready,
- context-only contribution when raw data is partial usable.

## 10. Trigger Rules

### 10.1 Alert Trigger

Trigger an alert when any condition is met:

```text
notional_ratio >= 3.0
volume_ratio >= 3.0
trade_count_ratio >= 3.0
abs(signed_notional_pressure) >= 0.60 AND total_notional >= ticker_min_notional
focus_notional_share >= 0.25 AND focus_notional >= ticker_min_focus_notional
TRF/off_exchange_notional_share >= 0.25 AND total_notional is meaningful
provider_confirmed_dark_pool_or_block_alert
```

### 10.2 Actionability Trigger

Unusual activity becomes actionable support only when:

```text
lane_state == ready
AND data_quality >= minimum
AND confidence >= 0.60
AND activity_strength >= strong
AND at least one corroboration source is present
```

### 10.3 Caution Trigger

Display a caution, not a block, when:

- activity is strong but direction is uncertain,
- activity is from one raw source only,
- off-exchange prints are large but price action conflicts,
- trade signing is low confidence,
- pre-market activity has no regular-market confirmation yet,
- source is partial usable.

### 10.4 Stop / Suppress Trigger

Suppress or context-only when:

- lane is loading,
- source unavailable,
- no raw rows,
- sample too small,
- print conditions imply non-directional/corrected/late prints,
- ticker is outside active universe,
- data is not from the current date/window for live decisions.

## 11. Data Quality And Reliability

### 11.1 Quality Metrics

Every signal output must include:

| Metric | Meaning |
|---|---|
| source lane | exact raw lane |
| manifest path/version | reproducibility |
| source row count | analyzed evidence size |
| coverage percent | universe/ticker completeness |
| latest event timestamp | newest trade used |
| analyzed_at | when agent processed it |
| freshness SLA | maximum acceptable age |
| trade signing method mix | quote/tick/unknown percentages |
| exclusion count | trades removed by condition filters |
| partial/complete status | data completeness |

### 11.2 Freshness Rules

Live trading:

- live trade slices: 30 minutes max,
- block feed: 30 minutes max and must match source lane date/window,
- pre-market: 30 minutes during pre-market,
- daily baseline: latest completed trading day acceptable when market is closed.

Dashboard:

- never show an old value as if current while analysis is loading,
- show "Data is still loading" or "Analysis needs refresh",
- include "last trade used" and "analysis generated" timestamps.

### 11.3 Data Completeness Rules

Per ticker:

```text
complete = raw lane has expected window, row_count verified, no source errors
partial_usable = row_count > 0, latest-first order, enough rows for context
blocked = no rows, provider error, wrong date/window, manifest missing
```

## 12. UX And Display Design

### 12.1 Bottom-Line-Up-Front Card

Each ticker should show:

```text
Unusual Trading Activity: Bullish support / Bearish warning / Mixed / Context only

What happened:
Large TRF/off-exchange prints totaled $440.0M, representing 50% of analyzed notional.

Why it matters:
The prints leaned buyer-side (+72% signed notional pressure) and occurred with unusual notional volume, but this is not proof of a named institution.

What to check:
Confirm price follow-through, VWAP/support level, news catalyst, and options flow before treating this as trade support.
```

### 12.2 Evidence Cards

Cards should use concrete facts:

1. Activity Spike
   - latest notional,
   - baseline median,
   - ratio,
   - band.
2. Direction
   - signed notional pressure,
   - signing method confidence,
   - buy/sell interpretation.
3. Block / TRF
   - focus trade count,
   - focus notional,
   - largest print,
   - threshold used.
4. Timing
   - session,
   - first/last event time,
   - pre-market/regular split.
5. Data Health
   - lane status,
   - latest source timestamp,
   - coverage,
   - refresh action.

### 12.3 Avoid Generic Text

Bad:

```text
Unusual activity detected. This may indicate institutional interest.
```

Good:

```text
AVGO notional was 4.0x its 20-session median. TRF/off-exchange focus prints totaled $440.0M, with +72% signed notional pressure. This is bullish supporting evidence, but not proof of a named buyer.
```

### 12.4 User Actions

Every card must offer:

- Refresh this lane,
- Show raw prints,
- Show calculation,
- Mark as reviewed,
- Add to watch,
- Use as supporting evidence,
- Ignore for this cycle,
- Open related candidate detail.

### 12.5 Dashboard Placement

Command/Cockpit:

- show lane state and top 5 unusual activity names,
- show whether activity can affect paper-trade readiness.

Candidate Detail:

- full explanation and raw evidence.

Signals Dashboard:

- sortable table with all tickers and all market-flow components.

Execution Preview:

- compact caution/support line only; no dense diagnostics.

## 13. Detailed Display Fields

### 13.1 Top-Level Row

| Field | Example |
|---|---|
| ticker | AVGO |
| verdict | Mixed but important |
| direction | buyer-side pressure |
| strength | strong |
| confidence | 0.78 |
| actionability | supporting evidence |
| latest event | 14:35:22 ET |
| source | Massive live trade slices |
| state | Ready |

### 13.2 Expanded Detail

```text
Most unusual metric:
Notional was 4.0x median baseline.

Block/TRF evidence:
4 TRF/off-exchange focus prints, $440.0M total.
Largest print: $180.0M, 6.2x ticker median notional.

Direction:
Signed focus notional: +$316.8M.
Focus pressure: +72.0%.
Signing method: quote rule 68%, tick test 28%, unknown 4%.

Context:
Focus prints represented 50.0% of analyzed notional.
Price moved +1.2% over the same analysis window.

Meaning:
Large off-exchange prints were unusually concentrated and buyer-leaning. Treat as bullish support only if price action and another independent lane confirm.
```

## 14. Data Model

### 14.1 Raw Observation Table

Recommended table:

```text
unusual_activity_observations
```

Columns:

- id,
- ticker,
- as_of_date,
- event_start_ts,
- event_end_ts,
- source_lane,
- source_manifest_id,
- event_type,
- session,
- trade_count,
- total_volume,
- total_notional,
- focus_trade_count,
- focus_notional,
- trf_off_exchange_count,
- trf_off_exchange_notional,
- largest_print_notional,
- largest_print_price,
- price_min,
- price_max,
- conditions_summary_json,
- raw_print_refs_json,
- created_at.

### 14.2 Signal Result Table

Recommended table:

```text
unusual_activity_signal_results
```

Columns:

- ticker,
- cycle_id,
- as_of,
- verdict,
- direction,
- strength,
- confidence,
- actionability,
- activity_score,
- block_trade_score,
- buy_sell_pressure_score,
- pre_market_score,
- market_flow_trend_score,
- confirmed_alert_score,
- data_quality_score,
- corroboration_score,
- evidence_json,
- calculation_json,
- lane_state_json,
- created_at.

## 15. API Contract

### 15.1 Summary Endpoint

```http
GET /api/signals/unusual-activity?cycle_id=...
```

Returns:

```json
{
  "generated_at": "...",
  "lane_states": [],
  "top_alerts": [],
  "tickers": []
}
```

### 15.2 Ticker Detail Endpoint

```http
GET /api/signals/unusual-activity/{ticker}?cycle_id=...
```

Returns:

- verdict,
- component scores,
- raw observation summaries,
- calculation details,
- source/health state,
- user-action recommendations.

## 16. Expert Review Workstreams

### 16.1 Market Microstructure Expert

Questions:

- Which trade conditions should be excluded?
- How should TRF/off-exchange prints be interpreted?
- How should delayed, corrected, or average-price prints be handled?
- Should block thresholds vary by liquidity bucket?
- How should print clusters near VWAP/support/resistance be interpreted?

Deliverable:

- condition-code policy,
- block/dark-pool interpretation policy,
- allowed user-facing language.

### 16.2 Quant Research Expert

Questions:

- What baseline window should be used?
- Should baselines be intraday time-of-day matched?
- What thresholds maximize predictive value?
- Which outcome horizon should be evaluated: 30m, 1h, close-to-close, next day?
- What should be the minimum sample size per ticker?

Deliverable:

- validated scoring formula,
- thresholds by liquidity bucket,
- walk-forward evaluation with HAC/bootstrap significance.

### 16.3 Data Engineer

Questions:

- How to guarantee lane completeness per ticker?
- How to store raw print refs without bloating UI?
- How to avoid re-pulling the same endpoint?
- How to make source manifests immutable/reproducible?

Deliverable:

- lane manifest schema,
- observation/result tables,
- replay harness.

### 16.4 Product Designer

Questions:

- How should a non-expert understand "TRF/off-exchange"?
- How to separate "what happened" from "what it means"?
- How to display caution without blocking user workflow?
- How to make refresh/progress obvious?

Deliverable:

- final card layout,
- candidate detail panel,
- dashboard table,
- mobile/kiosk view.

### 16.5 QA Lead

Questions:

- Which bad states must fail the build?
- How do we test no demo/test data reaches UI?
- How do we test that old data is labeled correctly?
- How do we test ticker context persists across screens?

Deliverable:

- QA matrix,
- automated contract tests,
- screenshot tests,
- replay scenarios.

## 17. Validation Plan

### 17.1 Offline Replay

Use historical Massive trade data:

- replay raw trade slices,
- rebuild observations,
- compute scores,
- compare to future returns/volatility.

### 17.2 Outcomes

Evaluate:

- next 30-minute return,
- next 1-hour return,
- close-to-close return,
- next-day open-to-close,
- realized volatility,
- max adverse excursion,
- whether activity preceded news/earnings events.

### 17.3 Statistical Treatment

Use:

- walk-forward validation,
- ticker-clustered robust statistics,
- HAC/bootstrap p-values for overlapping horizons,
- liquidity bucket controls,
- market/sector beta controls.

### 17.4 Acceptance Criteria

The agent can affect recommendations only when:

- data lanes are reliable,
- score is stable in replay,
- thresholds have positive out-of-sample utility,
- user-facing evidence is concrete,
- false-positive examples are documented.

## 18. QA Matrix

| Scenario | Expected Result |
|---|---|
| raw lane loading | UI says data is still loading; no old score shown as current |
| raw lane ready, derived missing | UI says data loaded, analysis pending |
| TRF/off-exchange detected | UI says TRF/off-exchange, not named dark pool |
| large lit print only | UI says large print, not dark pool |
| high volume, negative pressure | bearish or mixed depending price context |
| high volume, no direction | context only |
| partial usable data | score capped and labeled usable partial |
| stale/old analysis | label "analysis needs refresh" with refresh button |
| source unavailable | provider unavailable, no misleading score |
| ticker outside universe | ignored or shown as outside universe |

## 19. MVP Rebuild Plan

### Phase 1 - Contracts

- Define lane state contract.
- Define observation schema.
- Define signal result schema.
- Define UX text contract.
- Define user-facing terminology policy.

### Phase 2 - Data And Feature Engine

- Build raw print normalizer.
- Build block/TRF detector.
- Build anomaly baseline engine.
- Build trade-signing confidence model.
- Build signal component scores.

### Phase 3 - Dashboard UX

- Build Unusual Activity panel.
- Build ticker detail drawer.
- Build raw evidence inspector.
- Build refresh/progress controls.

### Phase 4 - Validation

- Backtest thresholds.
- Build replay scenarios.
- Compare against provider alerts.
- Tune score weights.

### Phase 5 - Paper-Trading Integration

- Allow unusual activity to support candidate conviction.
- Require corroboration before increasing actionability.
- Show caution instead of hidden blocker when evidence is incomplete.

## 20. Open Questions

1. Should the agent require quote data for high-confidence trade signing?
2. What is the minimum source coverage for live paper-trading support?
3. Should pre-market anomalies decay after regular market opens?
4. Should large off-exchange prints near VWAP be scored differently from prints far from VWAP?
5. Should options flow be part of this agent or a correlated companion agent?
6. Which provider alert source should be considered "confirmed" enough to boost confidence?
7. Should the agent run on all 168 tickers every cycle or only active/recommended/watch tickers?
8. How should the agent handle duplicate articles/alerts referencing the same raw prints?

## 21. Recommended Product Language

Use:

- "TRF/off-exchange print"
- "large print"
- "ticker-relative block candidate"
- "buyer-side/seller-side pressure"
- "supporting evidence"
- "context only"
- "analysis needs refresh"

Avoid:

- "institution bought"
- "dark pool buyer"
- "smart money is buying"
- "guaranteed bullish"
- "stale"
- "blocked" for user-reviewable caution states.

## 22. Final Target Experience

The final agent should feel like a market-flow investigator:

```text
Bottom line:
AVGO has strong unusual trading activity, but the signal is mixed.

What happened:
Notional activity was 4.0x its recent median. TRF/off-exchange prints were concentrated and represented 50% of analyzed notional.

Direction:
Signed focus notional leaned buyer-side at +72%, but price fell after earnings, so interpretation is mixed.

Why it matters:
The flow may show large participants active around the post-earnings repricing. It supports review, not automatic execution.

What to check:
Look for price follow-through, VWAP reclaim, options confirmation, and whether news/fundamentals support the same direction.
```

That is the product standard: concrete data first, interpretation second, user action third, limitations always visible.

## 23. Reference Notes

- Massive stock trades data includes tick-level trade records with price, size, exchange, conditions, and timestamp fields.
- Massive states that an `exchange: 4` trade with a `trf_id` field is a dark-pool or otherwise off-exchange print. The agency should display this conservatively as TRF/off-exchange evidence unless more specific venue proof exists.
- The current Trading Agency implementation already includes lane policies and derived signal lanes that should be treated as a prototype, not the final product contract.
