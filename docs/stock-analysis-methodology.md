# Trading Agency Stock Analysis Methodology

Generated: 2026-05-27

This document describes the current code-backed methodology used by the Trading
Agency when it analyzes one stock. It covers the data considered, the signal
agents that transform the data, the scoring and "grade" path, the decision and
paper-trading gates, and where Zacks Rank and Seeking Alpha Quant Rating should
enter the next version.

This is a methodology and operator-reference document, not a trading
recommendation.

## Executive Summary

The agency does not assign a single standalone analyst letter grade. It creates a
stock-level evidence pack, then derives:

- `direction`: bullish, bearish, or neutral per signal.
- `actionability`: actionable, context-only, or suppressed per signal.
- `deterministic score`: a weighted average of actionable signal scores.
- `conviction`: absolute value of the deterministic score, capped at 1.0.
- `final action`: normally `WATCH` or `NO_TRADE` after deterministic and LLM
  review.
- `paper order readiness`: a separate promotion, risk, approval, broker, and
  execution-preview process.

The current deterministic WATCH threshold is `0.50`. The code requires at least
two usable independent sources and at least one confirmed signal before a stock
can pass the evidence-breadth gate. Bearish scores are currently preserved as
`NO_TRADE`; the agency does not automatically short from bearish research
signals unless later policy enables that path.

The LLM reviewer is supervised and advisory. It reviews summary-level evidence,
fails safe to `NO_REVIEW`, cannot override hard policy gates, and cannot promote
a deterministic `NO_TRADE` into a trade.

## High-Level Block Diagram

```text
Provider credentials, policy, universe
              |
              v
Raw data acquisition lanes
  - daily bars, live trade slices, pre-market slices, block feed
  - SEC company facts, Form 4, 13F
  - RSS/news, subscription emails/articles
  - options chains, activity alerts, broker snapshot
              |
              v
Normalized PIT storage
  - parquet datasets
  - manifests with checksums, row counts, coverage, timestamps
  - lane state and source health
              |
              v
PIT loader and runtime source-health agent
              |
              v
Signal agents
  fundamentals | insider | institutional | abnormal volume
  technical analysis | sector momentum | news | subscription thesis
  activity alerts | buy/sell pressure | block trade pressure
  unusual activity | pre-market unusual activity | market-flow trend
  options flow | options anomaly
              |
              v
Signal adapter and actionability gate
  score -> direction -> actionability -> provenance/freshness/confidence
              |
              v
Evidence pack per ticker
  actionable signals, context signals, suppressed signals, data quality
              |
              v
Deterministic selection
  evidence gates + weighted score + WATCH threshold
              |
              v
LLM review, top-ranked WATCH candidates only by default
              |
              v
Final selection report
              |
              v
Human research approval
              |
              v
Paper-trade promotion
              |
              v
Risk manager
              |
              v
Execution preview and hash-bound order approval
              |
              v
Alpaca paper broker, if explicitly enabled
```

## Data Sources Considered

| Data source | What it contributes | Current role |
| --- | --- | --- |
| Active universe | The ticker set to analyze. | Defines which symbols are evaluated. |
| Daily OHLCV bars | Price, volume, moving averages, returns, sector ETF returns, chart setup. | Core market-data input. |
| Massive stock trades | Delayed confirmed trade prints, signed volume/notional, pre-market activity, block/off-exchange focus rows. | Market-flow and technical context. |
| Massive lane manifests | Lane-level coverage, progress, latest timestamp, and readiness. | Controls freshness and operational readiness. |
| SEC company facts | Revenue, net income, free cash flow, assets, liabilities. | Confirmed fundamentals signal. |
| SEC Form 4 | Insider buy/sell transactions. | Confirmed insider signal. |
| SEC 13F | Institutional holdings and quarterly share changes. | Confirmed institutional signal. |
| RSS/news rows | Ticker-resolved headlines, summaries, source IDs, event taxonomy. | Confirmed headline context and signal. |
| Portfolio News Agent / subscription emails | Seeking Alpha, Zacks, TradeVision, and article thesis evidence after user-authorized access. | Context-only thesis signal and news/email evidence. |
| Activity alert imports | Provider/export rows for block, dark-pool, unusual stock, sweep, and unusual options alerts. | Confirmed alert signal when data exists. |
| Options chains | Call/put volume, open interest, IV, bid/ask/last, premium, volume/open-interest anomaly. | Optional options-flow and anomaly lanes. |
| Alpaca paper broker | Account, positions, open orders, clock, paper-order status. | Portfolio/risk/execution readiness, not research alpha. |

All runtime signals are expected to be point-in-time safe through the PIT loader
and backed by manifests. The source-health layer converts manifest timestamps
into domain-specific freshness states that are carried into evidence packs and
risk decisions.

## Runtime Signal Lanes

The code defines these runtime lanes:

| Lane | Dataset | Source tier | Verification | Confidence |
| --- | --- | --- | --- | --- |
| `fundamentals` | SEC company facts | official filing | confirmed | 0.80 |
| `insider` | SEC Form 4 | official filing | confirmed | 0.80 |
| `institutional` | SEC 13F | official filing | confirmed | 0.80 |
| `abnormal_volume` | daily bars | inferred from bars | inferred | 0.70 |
| `technical_analysis` | daily bars plus optional trades | inferred from bars | inferred | 0.65 |
| `sector_momentum` | daily bars | inferred from bars | inferred | 0.70 |
| `news` | news RSS | RSS headline | confirmed | 0.60 |
| `subscription_thesis` | subscription emails | paid subscription email | confirmed | 0.65 |
| `activity_alerts` | unusual activity alerts | paid subscription email/export | confirmed | 0.80 |
| `buy_sell_pressure` | stock trades | inferred from trade prints | inferred | 0.55 |
| `block_trade_pressure` | stock trades | inferred from trade prints | inferred | 0.55 |
| `unusual_trade_activity` | stock trades | inferred from trade prints | inferred | 0.55 |
| `pre_market_unusual_activity` | stock trades | inferred from trade prints | inferred | 0.55 |
| `market_flow_trend` | stock trades | inferred from trade prints | inferred | 0.55 |
| `options_flow` | options chains | market data | inferred | 0.55 |
| `options_anomaly` | options chains | market data | inferred | 0.55 |

Code default runtime lanes are the stock-only core lanes:
`fundamentals`, `insider`, `institutional`, `abnormal_volume`,
`technical_analysis`, `sector_momentum`, and `news`. Configured runtime jobs can
add optional lanes such as Massive market-flow, options, subscription thesis, and
activity alerts.

## Signal Methodologies

### Fundamentals Agent

Purpose: measure financial quality from official SEC company facts.

Data used: revenue, net income, free cash flow, total assets, and total
liabilities.

Calculation:

1. Compute net margin: `net_income / revenue`.
2. Compute free-cash-flow margin: `free_cash_flow / revenue`.
3. Compute leverage: `total_liabilities / total_assets`.
4. Use inverse leverage as `-leverage`.
5. Cross-sectionally z-score net margin, FCF margin, and inverse leverage.
6. Average those z-scores into `composite_score`.

Interpretation: higher scores mean better profitability, better cash generation,
and less balance-sheet leverage versus the current universe.

Primary module: `research/src/signals/fundamentals.py`.

### Insider Agent

Purpose: detect recent insider buying or selling pressure from SEC Form 4.

Data used: transaction type, shares, price, filer, and filing/provenance fields.

Calculation:

1. Look back 90 days by default.
2. Treat Form 4 code `P` as buy and `S` as sell.
3. Estimate transaction value as `shares * price` when price exists, otherwise
   shares.
4. Compute net transaction value: buy value minus sell value.
5. Cross-sectionally z-score net transaction value.

Interpretation: high scores mean relative insider accumulation; low scores mean
relative insider selling/distribution.

Primary module: `research/src/signals/insider.py`.

### Institutional Agent

Purpose: detect institutional accumulation or distribution from 13F holdings.

Data used: total shares held, total change from previous quarter, holder count,
and quarter end date.

Calculation:

1. Read latest PIT-safe 13F holdings payload.
2. Compute total share change from the prior quarter.
3. Compute change ratio: share change divided by total shares held.
4. Cross-sectionally z-score both change and change ratio.
5. Average them into `institutional_score`.

Interpretation: high scores mean relative institutional accumulation; low scores
mean relative distribution. This lane is confirmed but naturally delayed because
13F filings lag reality.

Primary module: `research/src/signals/institutional.py`.

### Sector Momentum Agent

Purpose: measure sector leadership.

Data used: sector ETF daily bars and SPY as broad-market benchmark.

Calculation:

1. Compute lookback return for sector ETFs over 60 days by default.
2. Compute SPY return over the same available window.
3. Subtract SPY return from each sector ETF return.
4. Cross-sectionally z-score excess returns.

Interpretation: high values show leadership versus broad market; low values show
lagging sectors.

Primary module: `research/src/signals/sector_momentum.py`.

### Abnormal Volume Agent

Purpose: identify ticker-relative volume spikes with price-direction context.

Data used: daily OHLCV bars.

Calculation:

1. Use a 60-day default lookback.
2. Exclude the latest bar from the baseline.
3. Compute median positive historical volume.
4. Compute RVOL: latest volume divided by baseline median volume.
5. Compute robust z-score and robust MAD score against the historical baseline.
6. Sign the pressure by the latest price return.
7. Compute `signed_volume_pressure = sign(latest_return) * max(log(RVOL), 0)`.
8. Rank the signed pressure cross-sectionally into `abnormal_volume_score`.

Bands:

- Normal: below 1.5x RVOL.
- Attention: at least 1.5x RVOL.
- Strong: at least 2.0x RVOL or robust anomaly score at attention level.
- Extreme: at least 3.0x RVOL or robust anomaly score at extreme level.

Trend confluence: latest return is compared with broader lookback return.
Agreement increases confidence; conflict reduces confidence.

Interpretation: a volume spike adds conviction only when it is large relative to
that ticker's own baseline and its price direction is clear.

Primary modules: `research/src/signals/abnormal_volume.py`,
`research/src/signals/calibration.py`.

### Technical Analysis Agent

Purpose: score the stock's chart setup using repeatable technical indicators and
price/volume structure.

Data used: daily OHLCV bars, SPY/QQQ benchmark bars, chart pattern engine,
optional external indicator pack, and optional recent Massive trade pressure.

Methodology tag:

```text
sma20_50_200_trend; rsi14_macd_momentum; volume_confirmation;
relative_strength_vs_spy_qqq; candle_regime; chart_patterns;
optional_indicator_pack; massive_trade_pressure
```

Calculation:

1. Trend score: price versus SMA20/SMA50/SMA200 plus SMA20/SMA50 slope.
2. Momentum score: RSI14, MACD histogram change, and 20-day rate of change.
3. Volume confirmation: signed latest volume pressure plus recent accumulation.
4. Relative strength: ticker return versus SPY/QQQ benchmark return.
5. Candle regime: recent five-day blue/pink/neutral candle state based on close,
   EMA20, RSI, MACD, and volume.
6. Chart pattern score: named pattern summary from the pattern engine.
7. External indicator score: ADX, Aroon, CCI, Bollinger/Keltner/Donchian,
   Chaikin Money Flow, MFI, OBV slope, VWAP distance, StochRSI, Williams %R
   where available.
8. Volatility risk score: penalizes overextension and broken support using SMA20
   distance and ATR percent.
9. Massive trade pressure: recent net-notional pressure from trade prints.

Current weights:

| Component | Weight |
| --- | ---: |
| Trend | 0.20 |
| Momentum | 0.16 |
| Volume confirmation | 0.12 |
| Relative strength | 0.12 |
| Candle regime | 0.09 |
| Massive trade pressure | 0.09 |
| Chart patterns | 0.07 |
| Volatility risk | 0.05 |
| External indicator pack | 0.10 |

Interpretation: positive scores indicate constructive chart evidence; negative
scores indicate distribution, broken support, overextension risk, or weak
momentum. The agent also emits a human-readable setup summary, support,
resistance, and invalidation level.

Primary module: `research/src/signals/technical_analysis.py`.

### Trade Classifier

Purpose: convert raw trade prints into signed activity used by market-flow
signals.

Data used: Massive stock trades with price, size, timestamps, exchange/condition
fields, and bid/ask when available.

Calculation:

1. Keep valid, non-corrected, positive price and size prints.
2. Convert timestamps to Eastern session labels: pre-market, regular,
   after-hours, or out-of-session.
3. Compute notional as `price * size`.
4. Assign direction using quote rule when bid/ask are available:
   price above midpoint is buy-side, below midpoint is sell-side.
5. Fall back to tick test when quote fields are not available.
6. Compute signed volume and signed notional.
7. Mark off-exchange candidates using TRF/FINRA/dark/off-exchange markers.
8. Mark absolute block candidates using at least 10,000 shares or $200,000
   notional.

Interpretation: this is an inference of trade pressure, not a direct exchange
aggressor-side feed. Quote-rule rows carry higher direction confidence than
tick-test rows.

Primary module: `research/src/market_flow/classification.py`.

### Buy/Sell Pressure Agent

Purpose: infer broad buyer/seller pressure from recent trade prints.

Data used: Massive stock trade activity frames.

Calculation:

1. Compute net signed volume pressure:
   `sum(signed_volume) / total_volume`.
2. Compute net signed notional pressure:
   `sum(signed_notional) / total_notional`.
3. Compute pre-market signed pressure and scale it by pre-market participation.
4. Combine:
   `0.45 * net_notional_pressure + 0.20 * net_volume_pressure +
   0.35 * pre_market_pressure * participation_scale`.
5. Rank the combined pressure cross-sectionally into
   `buy_sell_pressure_score`.

Interpretation: positive values indicate inferred buyer pressure; negative
values indicate inferred seller pressure. The lane is inferred and should be
treated as corroborating evidence unless confirmed by other sources.

Primary modules: `research/src/signals/buy_sell_pressure.py`,
`research/src/market_flow/features.py`.

### Block Trade Pressure Agent

Purpose: detect directional pressure from large and off-exchange prints without
letting naturally high-liquidity tickers dominate.

Data used: Massive stock trade prints and market-flow activity frames.

Block logic:

- Absolute floor: 10,000 shares or $200,000 notional.
- Relative floor: at least 5x the ticker's median trade size or median notional.
- Off-exchange prints are focus candidates.
- Exchange prints require the absolute and relative logic before they are treated
  as meaningful focus rows.

Calculation:

1. Build a focus set of block/off-exchange prints.
2. Compute focus notional share: focus notional divided by total notional.
3. Compute directional pressure: signed focus notional divided by focus notional.
4. Compute:
   `directional_pressure * focus_notional_share * log1p(focus_trade_count)`.
5. Rank cross-sectionally into `block_trade_pressure_score`.

Interpretation: positive values show large/off-exchange pressure aligned to the
buy side; negative values show sell-side pressure. Thresholds are stock-relative,
not only fixed global values.

Primary modules: `research/src/signals/block_trade_pressure.py`,
`research/src/market_flow/features.py`.

### Unusual Trade Activity Agent

Purpose: identify signed trade-print activity spikes versus a ticker's own
recent baseline.

Data used: daily aggregation of Massive trade prints.

Calculation:

1. Aggregate daily trade count, volume, notional, and net notional pressure.
2. Use prior days as baseline.
3. Compute latest-vs-median ratios for trade count, notional, and volume.
4. Compute robust z-score and MAD anomaly metadata.
5. Use the largest activity ratio above 1.0 as anomaly magnitude.
6. Score:
   `net_notional_pressure * log1p(max(anomaly - 1, 0))`.
7. Rank cross-sectionally into `unusual_trade_activity_score`.

Interpretation: activity is meaningful when the activity spike is unusual for
that ticker and aligns with signed pressure.

Primary modules: `research/src/signals/market_flow_activity.py`,
`research/src/market_flow/features.py`.

### Pre-Market Unusual Activity Agent

Purpose: detect early-session unusual activity before the regular market open.

Data used: Massive pre-market trade slices and historical pre-market aggregation.

Calculation:

1. Aggregate pre-market volume, notional, and signed notional pressure.
2. Compare latest pre-market volume/notional to prior pre-market median.
3. Use the larger volume or notional ratio as anomaly magnitude.
4. Score:
   `pre_market_pressure * log1p(max(anomaly - 1, 0))`.
5. If no baseline exists, scale by pre-market share of total activity.
6. Rank cross-sectionally into `pre_market_unusual_activity_score`.

Interpretation: useful as early warning and context, but should not be a
standalone trade trigger.

Primary modules: `research/src/signals/market_flow_activity.py`,
`research/src/market_flow/features.py`.

### Market-Flow Trend Agent

Purpose: identify whether signed notional pressure is improving or deteriorating
over recent trade-print windows.

Data used: daily Massive trade-print aggregation.

Calculation:

1. Compute latest net notional pressure.
2. Compute median prior net notional pressure.
3. Compute pressure delta: latest minus prior median.
4. Compute participation from latest notional versus prior median notional.
5. Score:
   `0.65 * latest_pressure + 0.35 * pressure_delta *
   max(participation, 0.25)`.
6. Rank cross-sectionally into `market_flow_trend_score`.

Interpretation: positive values indicate improving buyer participation; negative
values indicate worsening seller participation.

Primary modules: `research/src/signals/market_flow_activity.py`,
`research/src/market_flow/features.py`.

### Activity Alerts Agent

Purpose: use provider-confirmed or email-exported activity alerts when available.

Data used: unusual stock activity, block trade, dark pool, sweep, options block,
options flow, and unusual options activity alerts.

Calculation:

1. Group alerts by ticker.
2. Determine direction from alert direction fields such as bullish/buy/call/long
   or bearish/sell/put/short.
3. Determine magnitude from notional, premium, price times volume, volume, or 1.0.
4. Weight direction by confidence.
5. Add type weights: block-trade types get extra weight, options activity types
   get extra weight.
6. Use `direction * confidence * type_weight * log1p(magnitude)`.
7. Sum alert pressures and rank cross-sectionally.

Interpretation: this is the best lane for true provider-confirmed block/dark
pool/options activity when a trusted provider/export is connected.

Primary module: `research/src/signals/activity_alerts.py`.

### Options Flow Agent

Purpose: infer directional options pressure from option-chain snapshots.

Data used: option type, volume, open interest, implied volatility, and snapshot
timestamp.

Calculation:

1. Use the latest option-chain snapshot.
2. Sum call volume and put volume.
3. Compute call share: `call_volume / total_volume`.
4. Compute pressure: `(call_share - 0.5) * log1p(total_volume)`.
5. Rank cross-sectionally into `options_flow_score`.

Interpretation: call-heavy volume produces positive pressure; put-heavy volume
produces negative pressure. This is inferred from chain snapshots and is less
specific than a true paid options-flow feed.

Primary module: `research/src/signals/options_flow.py`.

### Options Anomaly Agent

Purpose: find unusual options activity in chain snapshots.

Data used: volume, open interest, bid, ask, last price, option type, and snapshot
date.

Calculation:

1. Use the latest option-chain snapshot.
2. Estimate premium with midpoint price, falling back to last price.
3. Compute call premium, put premium, gross premium, and net premium.
4. Compute volume/open-interest ratio.
5. Count unusual contracts where volume is at least 100 and either open interest
   is zero or volume/open-interest is at least 2.0.
6. Score signed pressure as:
   `sign(net_premium) * log1p(gross_premium) * log1p(volume_to_oi)`.
7. Rank cross-sectionally into `options_anomaly_score`.

Interpretation: positive values indicate call-premium dominance with unusual
activity; negative values indicate put-premium dominance.

Primary module: `research/src/signals/options_anomaly.py`.

### News Agent

Purpose: convert ticker-resolved RSS/news rows into a compact headline signal
and event taxonomy.

Data used: title, summary, feed/source, URL/source ID, ticker match status, and
ticker match confidence.

Ticker mapping:

1. Rows are included only when ticker-match status is scorable:
   `resolved` or `feed_ticker`.
2. Rows must have ticker-match confidence of at least 0.70.
3. Generic RSS rows that are not confidently mapped to a ticker are not used for
   ticker-level scoring.

Sentiment calculation:

1. Count deterministic positive and negative terms in title plus summary.
2. Assign each headline a sentiment of +1, -1, or 0.
3. Weight each headline by ticker-match confidence.
4. Normalize by weighted headline count, so high-coverage tickers do not win
   only because they have more headlines.
5. Cross-sectionally z-score the ticker sentiment rate into `news_score`.

Event taxonomy:

- Guidance
- Earnings
- Litigation/regulatory
- SEC filing
- Analyst action
- M&A
- Product
- General

Single-use consumption: live runtime can load a consumed-news ledger, filter out
already-used news IDs, and record source IDs used by the cycle so one headline is
not reused repeatedly as fresh evidence.

Interpretation: positive news scores mean recently mapped headlines are
directionally bullish after confidence weighting; negative scores mean bearish
headline evidence. This is headline-level evidence, not a deep article thesis.

Primary modules: `research/src/signals/news.py`,
`research/src/live_runtime/signals.py`.

### Subscription Thesis and Article Evidence Agent

Purpose: convert user-authorized subscription emails and opened article summaries
into ticker-specific thesis context.

Data used: Portfolio News Agent article summaries, subscription email events,
linked content status, direction, confidence, thesis, key points, service, event
type, and timestamps.

Eligibility:

1. Only analyzed link statuses are included:
   `article_analyzed` or `article_analyzed_deterministic_fallback`.
2. The event must have linked-content summary text.
3. The ticker must match the analyzed event.

Calculation:

1. Group analyzed article events by ticker.
2. Sort newest first.
3. Convert article direction to score:
   bullish = +0.65, bearish = -0.65, neutral/mixed = 0.
4. Multiply by confidence.
5. Apply recency decay with factor 0.65 per older event.
6. Average weighted scores and clamp to [-1, 1].
7. Emit a concise thesis summary with service, event type, direction, thesis,
   relevance, and key points.

Important behavior: `subscription_thesis` is context-only by design and excluded
from evidence breadth. It can explain a candidate, but it does not count as a
confirmed breadth source for deterministic WATCH gating.

Email sync and mini-cycle behavior: when the Portfolio News Agent finishes, the
agency bridge exports new article summaries into `subscription_emails`, detects
affected tickers, and can run ticker-scoped mini cycles for `subscription_thesis`
and `news`. The dashboard can show "Email evidence synced", affected tickers,
"Mini analysis running", and "Stock analysis updated".

Primary modules: `research/src/signals/subscription_thesis.py`,
`src/agency/runtime/portfolio_news_agent_bridge.py`,
`src/agency/runtime/email_evidence_refresh.py`.

## Score Normalization and Signal Actionability

Every signal is converted into a schema-valid `SignalResult`.

Direction:

- Score greater than `+0.05`: `BULLISH`.
- Score less than `-0.05`: `BEARISH`.
- Otherwise: `NEUTRAL`.

Default actionability:

- `ACTIONABLE`: absolute score at least `0.50` and confidence at least `0.50`.
- `CONTEXT_ONLY`: absolute score at least `0.10`.
- `SUPPRESSED`: too weak, unavailable, or unsafe for current use.

Freshness:

- `UNAVAILABLE` suppresses the signal.
- Aging data may remain context-only or produce warning state downstream.
- Freshness is computed from source timestamps and the dataset's freshness
  domain.

The actionability gate can further demote or suppress signals based on source
availability, duplication, insufficient corroboration, or lane-specific policy.

Primary modules: `src/agency/services/signal_adapters.py`,
`src/agency/services/actionability_gate.py`.

## Evidence Pack Construction

The Evidence Pack Agent groups all signal results for one ticker.

It produces:

- `actionable_signals`
- `context_signals`
- `suppressed_signals`
- `data_quality`

Data quality includes:

- Worst freshness across usable signals.
- Independent source count.
- Confirmed signal count.
- Inferred signal count.
- Blockers such as no signals, no usable signals, or all sources unavailable.

`subscription_thesis` is excluded from the data-quality breadth calculation so a
paid article thesis can explain a setup but cannot by itself satisfy the
evidence breadth needed for a tradeable WATCH.

Primary module: `src/agency/services/evidence_pack.py`.

## Deterministic Grade and Conviction

The Deterministic Selection Agent is where the stock's machine grade is
calculated.

Policy gates:

1. Evidence breadth:
   - Requires at least two usable independent sources.
   - Requires at least one confirmed signal.
   - Blocks when there are no usable signal results.
2. Freshness:
   - `UNAVAILABLE` blocks.
   - Aging or stale freshness warns.
   - Fresh evidence passes.

Lane weights:

| Lane | Weight |
| --- | ---: |
| Fundamentals | 1.20 |
| Institutional | 1.00 |
| Insider | 0.90 |
| Activity alerts | 0.90 |
| Sector momentum | 0.80 |
| Abnormal volume | 0.70 |
| Options flow | 0.70 |
| Technical analysis | 0.65 |
| News | 0.60 |
| Buy/sell pressure | 0.50 |
| Pre/post gap | 0.50 |
| Unusual trade activity | 0.45 |
| Pre-market unusual activity | 0.45 |
| Block trade pressure | 0.40 |
| Market-flow trend | 0.40 |
| Options anomaly | 0.40 |
| Subscription thesis | 0.00 |

Weighted score:

```text
weighted_score = sum(signal_score * lane_weight) / sum(lane_weight)
conviction = min(1.0, abs(weighted_score))
```

Decision:

- If any policy gate blocks: `NO_TRADE`, score `0`, conviction `0`.
- If no actionable signals exist: `NO_TRADE`.
- If score is at least `0.50`: `WATCH`.
- If score is less than or equal to `-0.50`: `NO_TRADE` with
  `bearish_action_not_enabled`.
- Otherwise: `NO_TRADE` because signal strength is below threshold.

Primary module: `src/agency/services/deterministic_rules.py`.

## LLM Review

The OpenAI LLM Review Agent is a supervised reviewer, not an execution engine.

Default behavior:

- Disabled unless `AGENCY_ENABLE_LLM_REVIEW` is enabled.
- Uses `gpt-4.1-mini` by default.
- Reviews at most 10 candidates automatically.
- Reviews top-ranked deterministic WATCH candidates first.
- Prompt is built from summarized evidence only.
- Prompt content is redacted and hash-audited.

Guardrails:

- The LLM never executes trades.
- It cannot override hard policy gates.
- It cannot promote deterministic `NO_TRADE` into a trade.
- If the provider fails, the output is a safe `NO_REVIEW`.

Allowed actions include `AGREE`, `DISAGREE`, `DEFER`,
`NEEDS_MORE_EVIDENCE`, `NO_TRADE`, `WATCH`, `CLOSE_REVIEW`, and `NO_REVIEW`.

Primary modules: `src/agency/services/llm_review.py`,
`src/agency/services/final_selection.py`.

## Final Selection

The Final Selection Agent merges deterministic rules and LLM review.

Rules:

- Hard deterministic policy blockers remain hard blockers.
- If deterministic action is `NO_TRADE`, a promoting LLM action is blocked.
- If deterministic action is `WATCH` and the LLM demotes or asks for more
  evidence, the final action becomes `CLOSE_REVIEW`.
- Otherwise the deterministic action is preserved.

Output:

- `SelectionReport`
- deterministic decision
- LLM review
- policy gates
- risk flags
- evidence pack
- lifecycle events

Primary module: `src/agency/services/final_selection.py`.

## Human Approval, Paper Promotion, Risk, and Execution

Research approval and order approval are intentionally separate.

### Human Review Agent

Records user decisions such as approve, defer, or reject for the current
selection report. Approval is hash-bound to the current report so old approval
state cannot silently approve a changed report.

Primary module: `src/agency/services/human_review.py`.

### Paper Trade Promotion Worker

Converts an approved `WATCH` into a paper `BUY` preview only if promotion checks
pass.

Default requirements:

- Paper promotion enabled.
- Alpaca paper broker ready.
- Final action is `WATCH`.
- Conviction meets paper-promotion threshold.
- No promotion-blocking risk flags.
- Selection policy gates have no hard blocks unless operator manual advance
  acknowledges overridable paper-only blocks.
- Source count meets threshold.
- Confirmed signal count meets threshold.
- Critical evidence is fresh.
- No existing position conflict.
- No open order conflict.
- Current human research approval matches the current report hash.
- Per-cycle max promotions not exceeded.

Primary module: `src/agency/services/paper_trade_promotion.py`.

### Risk Manager

Applies portfolio and data-quality guardrails:

- Final action is orderable or review-only.
- Short-sale policy.
- Selection policy gate status.
- Minimum final conviction.
- Runtime source health.
- New-position capacity.
- Gross exposure cap.
- Risk flags.

Review-only actions convert hard blocks into caution messages so the user can
still review a WATCH candidate without creating a paper order.

Primary module: `src/agency/services/risk.py`.

### Execution Preview Worker

Builds a no-submit paper order preview from a risk decision.

It determines:

- side: BUY, SELL, SHORT, COVER, or NONE
- preview state: READY, DISABLED, or BLOCKED
- notional or quantity
- time in force
- order-intent hash
- submit eligibility
- reasons

Only READY previews with concrete size, policy support, broker/account support,
and required approvals can be submitted.

Primary module: `src/agency/services/execution_preview.py`.

## Main Agents and Responsibilities

| Agent / worker | Responsibility |
| --- | --- |
| Data refresh and scheduler | Pull source data, update manifests, respect market-aware lane policy, expose ETA/progress. |
| Massive lane orchestrator | Separate daily bars, live slices, pre-market slices, block feed, backtest tape, reference, and options flow lanes. |
| Lane state registry | Normalize lane state into plain states such as loading, loaded but unanalyzed, needs refresh, unavailable, ready for review, and ready for paper execution. |
| PIT loader | Serve only point-in-time data known as of the runtime date. |
| Source health agent | Translate manifests into source freshness and availability. |
| Signal agents | Convert raw datasets into ticker-level scores and summaries. |
| Signal adapter | Normalize score, direction, actionability, confidence, freshness, and provenance. |
| Actionability gate | Demote or suppress weak, unsafe, or unavailable evidence. |
| Evidence pack agent | Group per-ticker evidence and compute source breadth/data quality. |
| Deterministic selection agent | Apply policy gates and weighted scoring to create WATCH/NO_TRADE. |
| LLM review agent | Review top candidates with strict advisory guardrails. |
| Final selection agent | Merge deterministic and LLM results into the final candidate report. |
| Human review agent | Record operator approve/defer/reject decisions. |
| Paper promotion worker | Convert approved WATCH rows into paper BUY previews when policy permits. |
| Risk manager | Apply portfolio, exposure, source-health, and risk-flag checks. |
| Execution preview worker | Build hash-bound paper order intents without submitting. |
| Alpaca paper broker worker | Submit paper orders only when explicitly enabled and all gates pass. |
| Portfolio monitor | Reassess open positions and exits against latest evidence and policy. |
| Dashboard/cockpit | Present BLUF, lane state, evidence, candidate, risk, execution, and broker state. |

## Current Limits and Important Interpretations

- "Grade" means the deterministic weighted score plus final action, not an
  analyst-style A/B/C rating.
- Market-flow lanes are inferred from trade prints and should be corroborating
  unless supported by confirmed activity alerts or other evidence.
- News RSS currently depends on confident ticker mapping. Generic headlines that
  are not confidently resolved should not influence stock-level scoring.
- Subscription article thesis is powerful explanatory context, but currently
  does not count as breadth-confirming evidence for deterministic WATCH gating.
- SEC-based signals are official and confirmed, but they are naturally slower
  than market data.
- Options lanes are optional and inferred from chain snapshots unless a richer
  options-flow provider is added.
- Paper trading is intentionally gated after research. A high research score is
  not the same as an orderable paper trade.

## Next-Version Additions: Zacks Rank and SA Quant Rating

Zacks Rank and Seeking Alpha Quant Rating are not currently first-class core
scoring lanes in the deterministic engine. They may appear indirectly inside
subscription email/article evidence, but that is not equivalent to explicit
rank/rating lanes.

Recommended next-version design:

| New lane | Source | Proposed role |
| --- | --- | --- |
| `zacks_rank` | User-authorized Zacks email alerts or export/API if available. | Confirmed subscription factor. Rank 1/2 positive, rank 3 neutral, rank 4/5 negative, with recency and ticker match provenance. |
| `sa_quant_rating` | User-authorized Seeking Alpha email alerts/export if available. | Confirmed subscription factor. Strong Buy/Buy positive, Hold neutral, Sell/Strong Sell negative, with factor-change metadata when available. |

Implementation requirements:

1. Store raw rank/rating events with source ID, provider, ticker, event time,
   rank/rating value, prior value, URL/email provenance, and match confidence.
2. Add explicit PIT datasets and manifests rather than burying them inside free
   text summaries.
3. Define freshness SLA by provider and event type.
4. Add signal modules that convert rank/rating values to bounded scores.
5. Add deterministic lane weights only after backtest or forward validation.
6. Display these as named evidence cards so the operator can see the actual rank
   or rating and timestamp.

## Primary Code References

| Area | Main files |
| --- | --- |
| Runtime lane definitions | `research/src/live_runtime/config.py` |
| Runtime cycle orchestration | `research/src/live_runtime/cycle.py`, `src/agency/services/cycle.py` |
| Runtime signal building | `research/src/live_runtime/signals.py` |
| Signal implementations | `research/src/signals/*.py`, `research/src/market_flow/*.py` |
| Signal adapter and actionability | `src/agency/services/signal_adapters.py`, `src/agency/services/actionability_gate.py` |
| Evidence pack | `src/agency/services/evidence_pack.py` |
| Deterministic scoring | `src/agency/services/deterministic_rules.py` |
| LLM review and final selection | `src/agency/services/llm_review.py`, `src/agency/services/final_selection.py` |
| Human review | `src/agency/services/human_review.py` |
| Paper promotion | `src/agency/services/paper_trade_promotion.py` |
| Risk | `src/agency/services/risk.py` |
| Execution preview | `src/agency/services/execution_preview.py` |
| Email evidence bridge | `src/agency/runtime/portfolio_news_agent_bridge.py`, `src/agency/runtime/email_evidence_refresh.py` |
| Lane state | `src/agency/runtime/lane_state.py` |
