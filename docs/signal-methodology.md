# Signal Methodology

This file summarizes the currently implemented signal calculations used by the
agency. Market-flow lanes remain corroborating/context lanes until walk-forward
validation promotes their weights.

## Daily Abnormal Volume

- Data source: daily OHLCV bars from the PIT price loader.
- Baseline: positive historical volume in the requested lookback window, excluding
  the latest bar.
- Calculation: latest volume divided by median baseline volume, plus robust
  z-score and MAD-score against the baseline distribution.
- Bands: normal below 1.5x RVOL, attention at 1.5x, strong at 2.0x, extreme at
  3.0x or robust anomaly score above the configured threshold.
- Direction: the volume signal is signed by latest price return.
- Confluence: latest price return is compared with the broader lookback price
  trend. Agreement increases signal confidence; conflict reduces it.

## Technical Analysis

- Data source: daily OHLCV bars plus recent Massive trade-pressure context.
- Methodology tag: `sma20_50_200_trend; rsi14_macd_momentum;
  volume_confirmation; relative_strength_vs_spy_qqq; candle_regime;
  chart_patterns; optional_indicator_pack; massive_trade_pressure`.
- Calculation: weighted score from trend, momentum, volume confirmation,
  relative strength versus SPY/QQQ, candle regime, chart pattern engine, optional
  indicator pack, volatility risk, and Massive trade pressure.
- Interpretation: positive scores indicate constructive chart evidence; negative
  scores indicate distribution, broken support, overextension risk, or weak
  momentum.

## Buy/Sell Pressure

- Data source: Massive stock trade prints, through the raw trade lane or PIT
  activity-frame aggregation.
- Trade signing: quote rule is used when bid/ask are available; tick test is the
  fallback. Output includes direction method and confidence for new classified
  rows.
- Calculation: combines net signed notional pressure, net signed volume pressure,
  and pre-market signed pressure weighted by pre-market participation.
- Interpretation: positive values indicate buyer-side pressure; negative values
  indicate seller-side pressure.

## Block Trade Pressure

- Data source: Massive stock trade prints.
- Absolute floors: at least 10,000 shares or 200,000 notional.
- Relative test: block candidates are compared with the ticker's own median trade
  size and notional; relative blocks require at least 5x the ticker median.
- Focus set: off-exchange prints are always focus candidates; exchange prints
  require both the absolute floor and the relative test.
- Calculation: signed focus notional pressure multiplied by focus notional share
  and a log count participation term.
- Interpretation: stock-relative blocks prevent naturally high-liquidity tickers
  from dominating only because their ordinary prints are large.

## Unusual Trade Activity

- Data source: daily aggregation of Massive trade prints.
- Baseline: recent ticker-level daily trade count, volume, and notional.
- Calculation: latest count, volume, and notional ratios versus median baseline,
  plus robust z/MAD anomaly scores.
- Bands: normal, attention, strong, or extreme using the same calibration
  thresholds as abnormal volume.
- Interpretation: activity only adds conviction when the activity spike is large
  for that specific ticker and aligns with signed pressure.

## Pre-Market Unusual Activity

- Data source: Massive pre-market trade slices and daily pre-market aggregation.
- Baseline: recent ticker-level pre-market volume and notional.
- Calculation: latest pre-market volume/notional ratios versus baseline, signed
  by pre-market pressure and scaled by participation.
- Interpretation: useful as early context before the regular session, but not a
  standalone trade trigger.

## Market-Flow Trend

- Data source: rolling daily Massive trade-print aggregation.
- Calculation: latest net notional pressure, pressure delta versus recent median,
  and a participation term based on latest notional versus prior median notional.
- Interpretation: positive values show improving buyer participation; negative
  values show worsening seller participation.

## News

- Data source: ticker-resolved RSS/news rows from the PIT news loader, including
  generic RSS rows after ticker-resolution checks and subscription-email-derived
  news rows.
- Ticker relation: only rows with scorable ticker-match status and sufficient
  ticker-match confidence are included.
- Sentiment: deterministic headline/summary term scoring normalized by weighted
  headline coverage, so high-coverage tickers do not win only by headline count.
- Event taxonomy: guidance, earnings, litigation/regulatory, SEC filing, analyst
  action, M&A, product, and general.
- Output: headline counts, weighted sentiment, source IDs for single-use
  consumption, event type counts, and dominant event type.
