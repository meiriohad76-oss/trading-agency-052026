# Trading Agency — Full Signals Audit
**Date:** 2026-05-31  
**Auditor:** Claude Code (Stock Investor × Product Design × QA)  
**Scope:** All signal agents/workers (`research/src/signals/`, `research/src/market_flow/`), scoring architecture, UX/display layer (`signals.html`, `signal_evidence.py`, `views/signals.py`, `views/_shared.py`)  
**Output format:** Audit findings + UX critique + recommendations — ready for planning and implementation

---

## Severity Legend

- 🔴 **CRITICAL** — Correctness bug or fundamental professional relevance failure; a trader acting on this signal could be misled  
- 🟠 **HIGH** — Significant UX gap, missing context, or scoring inconsistency that reduces trust or clarity  
- 🟡 **MEDIUM** — Display text is generic, missing explanation, or label is confusing  
- 🔵 **LOW** — Polish, copy, minor inconsistency

---

## Executive Summary

The trading agency's signal pipeline is **architecturally sound** — the PIT-safe data loading, cross-sectional scoring, and inspector evidence system are well-designed. However, the system has **three critical gaps** that must be resolved before an experienced investor can confidently act on its output:

1. **The fundamentals signal has known correctness bugs** (period mismatch that can flip sign) and has the highest lane weight of any signal — a compounding risk. (Already tracked in `docs/audits/fundamentals-agent-audit-2026-05-30.md`.)

2. **The scoring scale is inconsistent across lanes.** Some lanes use `directional_rank_score` (bounded [-1, 1], cross-sectional), some use `zscore` (unbounded), and the subscription thesis lane uses fixed hardcoded values (±0.65). The displayed score number means something fundamentally different depending on which lane produced it, but the UI shows all scores the same way.

3. **The "Summary" column in the signal table falls back to generic descriptive text** — `"{lane}: direction {direction}; no lane summary was persisted for this row"` — which tells an investor nothing they couldn't read from the other columns. The inspector panel (what Triggered, detail, cards) is excellent but is hidden behind a click.

**Additional findings:** 21 specific issues catalogued below, covering signal professional relevance, scoring thresholds, display text quality, and missing explanatory context.

---

## Part 1 — Scoring Architecture Audit

### How scores work (current system)

| Concept | Value | Description |
|---|---|---|
| `score` | float, varies by lane | Signed strength of signal; positive = bullish |
| `direction` | BULLISH / BEARISH / NEUTRAL | Determined by: BULLISH if score > +0.05, BEARISH if score < −0.05 |
| `confidence` | 0.0 – 1.0 | Lane-specific estimate of signal reliability |
| `actionability` | ACTIONABLE / CONTEXT_ONLY / SUPPRESSED | ACTIONABLE requires \|score\| ≥ 0.5 AND confidence ≥ 0.5 |

### FINDING S-01 🔴 Score scale is not comparable across lanes

**Problem:** Different signal workers produce scores on fundamentally different scales:

| Lane | Scoring method | Typical range | What it means |
|---|---|---|---|
| `abnormal_volume` | `directional_rank_score` on `signed_volume_pressure` | −1.0 to +1.0 | Relative rank within today's universe cross-section |
| `technical_analysis` | Weighted composite, then `score_dict` | Uncapped | Absolute multi-factor score |
| `fundamentals` | `composite_score` (quality + growth + valuation + forward sub-scores) | Uncapped | Absolute composite |
| `insider` | `zscore` of `net_transaction_value` | Unbounded | Standard deviations from universe mean |
| `institutional` | Mean of two z-scores | Unbounded | Average z-score |
| `news` | `zscore` of `sentiment_score` | Unbounded | Standard deviations from universe mean |
| `subscription_thesis` | Fixed: BULLISH=+0.65, BEARISH=−0.65, NEUTRAL=0.0 | Fixed | Not a scored value at all |
| Market flow lanes | `directional_rank_score` | −1.0 to +1.0 | Relative rank within cross-section |

**Impact:** The score "+0.72" means "ranked 72nd percentile in the universe today" for an abnormal_volume signal and means nothing consistent for a fundamentals signal. A user comparing scores across lanes in the table is comparing apples to oranges.

**Required fix:** Either (a) normalize all lane scores to the same scale before display, or (b) show each score in the context of its own lane's scale with a clear legend. At minimum, the inspector must explain what the score number means for each specific lane.

---

### FINDING S-02 🟠 Actionability threshold is hidden from the user

**Problem:** The system classifies a signal as ACTIONABLE only when `|score| ≥ 0.5 AND confidence ≥ 0.5`. This threshold is configuration, not display content. A signal with score +0.48 and 90% confidence shows as "Context Only" with no explanation of why. A signal with score +0.92 and 40% confidence also shows as "Context Only" — for a completely different reason.

**Impact:** Users see the tag (ACTIONABLE / CONTEXT ONLY / SUPPRESSED) but cannot understand why a seemingly strong signal is classified as context-only.

**Required fix:** The `suppression_reason` field is already computed — it needs to be surfaced in the inspector. When a signal is CONTEXT_ONLY, show: "Score +0.48 is below the actionability threshold of ±0.50" or "Confidence 40% is below the 50% minimum."

---

### FINDING S-03 🟡 Direction epsilon (±0.05) creates a NEUTRAL gap that confuses

**Problem:** A score of +0.04 (tiny bullish lean) shows direction = "NEUTRAL." This is correct engineering — the epsilon prevents noise from getting a direction — but visually confusing. A user sees a positive score and a NEUTRAL direction and wonders if the system has a bug.

**Required fix:** Add a tooltip or one-line explanation in the inspector facts panel: "Direction is NEUTRAL because the score (+0.04) is below the ±0.05 threshold needed to assign a direction."

---

### FINDING S-04 🟡 "Conviction" column in signal table is candidate-level, not signal-level

**Problem:** The signal table shows two columns next to each other: **Conviction** (`report_conviction_pct` = the candidate's overall conviction percentage) and **Confidence** (`confidence_pct` = the signal's lane-level confidence). These sound related but measure completely different things. Conviction is how confident the engine is in the final WATCH/BUY/NO_TRADE decision for the candidate. Confidence is how reliable this specific signal's source is.

**Impact:** A signal with 95% confidence and a 30% conviction candidate creates a reading that looks like the signal is being underused.

**Required fix:** Rename "Conviction" column to "Candidate Conviction" with a clear header tooltip: "The engine's overall conviction for this candidate, considering all signals. Not a per-signal score." Or move it out of the signal row and show it only in the inspector.

---

## Part 2 — Per-Signal Agent Audit

### 2.1 Abnormal Volume

**What it measures:** Whether a stock's latest daily volume is abnormally high compared to its own historical median, and whether that volume spike occurred while the price moved in a direction.

**How it triggers:** Latest volume ÷ median baseline volume (prior bars in a 60-day window, excluding the trigger bar). Positive result = volume above median. Then signed by the latest price return to determine direction.

**Why bullish:** High volume with price UP = interpreted as accumulation pressure. Institutions and momentum buyers tend to drive larger-than-normal volume when they accumulate shares, which pushes price up.

**Why bearish:** High volume with price DOWN = distribution pressure. Large sellers typically need volume to exit, driving price down.

**Score meaning:** `directional_rank_score` on `signed_volume_pressure` — this is a **cross-sectional rank**, meaning a score of +0.80 means this ticker had the 80th-percentile signed volume pressure in the universe today, not that it had 80% conviction.

**Conviction level:** Medium. Volume is a necessary but not sufficient signal. High volume with price up could be short covering, retail FOMO, or genuine institutional accumulation — the signal can't distinguish. The confluence check (trend agreement) partially addresses this.

**Professional relevance:** ✅ **High** — Volume anomalies are one of the most widely-used institutional signals. The 60-day baseline with median (not mean) is a good choice; it's resistant to outliers.

**FINDING AV-01 🟡** The `volume_signal_band` (normal/attention/strong/extreme) is computed and stored but **not shown in the inspector cards**. The band tells an investor whether 1.6x is just "attention" or 3.5x is "extreme" — which matters a lot for conviction. It's in the frame but missing from `_abnormal_volume_evidence` display.

**FINDING AV-02 🔵** Trend agreement ("uptrend_confirmed" / "downtrend_confirmed" / "trend_conflict") is stored but not surfaced in the inspector. A volume spike during an existing uptrend is more convincing than one that contradicts the trend.

---

### 2.2 Technical Analysis

**What it measures:** A multi-factor technical score combining: price trend (SMA stack), momentum (RSI, MACD), volume confirmation, relative strength vs SPY/QQQ, candle regime (blue/pink candles), chart pattern recognition, trade pressure (from Massive prints), and volatility risk (ATR).

**How it triggers:** Weighted composite score. Each sub-component contributes positively (bullish factor) or negatively (bearish factor). The sign of the composite determines direction.

**Why bullish:** Price is above rising SMA20/50/200, RSI is elevated but not overbought, volume confirms recent moves, the stock is outperforming the benchmark, recent candles are "blue" (up-close), and a bullish chart pattern is active.

**Why bearish:** Price is below SMAs or SMAs are declining, momentum is weak or negative, volume doesn't confirm moves, the stock underperforms the benchmark, recent candles are "pink" (down-close), and distribution patterns are active.

**Score meaning:** Absolute composite (not cross-sectionally normalized). A score of +0.50 means the bullish factors outweigh bearish factors — it's not a rank.

**Conviction level:** High. This is the most thorough and professionally credible signal in the system. It incorporates 8 distinct sub-factors with established technical analysis methodology.

**Professional relevance:** ✅✅ **Very High** — SMA trend, RSI, MACD, relative strength, and chart pattern recognition are standard professional technical analysis tools.

**FINDING TA-01 🟡** The methodology string `TA_METHODOLOGY = "sma20_50_200_trend; rsi14_macd_momentum; ..."` is stored but only shown in one inspector card ("Methodology") with the raw underscore-formatted string. It should be rendered as a human-readable description of each component and its direction contribution.

**FINDING TA-02 🔵** The "Driver mix" card shows the full driver breakdown in a comma-separated string. This is good but hard to read at a glance. A small horizontal contribution bar or a ranked list would be clearer.

**FINDING TA-03 🔵** Volatility risk score is described as "ATR %; overextension or high ATR subtracts from the setup." The word "subtracts" is clear but the card value shows a signed number — if it's −0.25, a user might read it as "bearish" when it actually means "volatility risk penalty applied." The framing should explicitly say "this is a risk-adjustment penalty."

---

### 2.3 Fundamentals

**What it measures:** A composite of four sub-scores (quality, growth, valuation, forward) derived from SEC EDGAR filings: net margin, FCF margin, ROE, ROA, leverage, revenue growth, net income growth, FCF growth, trailing P/E, forward P/E, EPS beat rate.

**Why bullish:** Strong margins, positive FCF, growing revenue/earnings, low leverage, reasonable valuation multiple, consistently beating EPS estimates.

**Why bearish:** Negative margins, negative FCF, declining revenue/earnings, high leverage, expensive valuation, or consistently missing estimates.

**Score meaning:** `composite_score` — an aggregation of sub-scores. Not normalized cross-sectionally in the worker; the lane weight of 1.2 (highest of all lanes) amplifies whatever raw score emerges.

**Conviction level:** HIGH WEIGHT but currently LOW RELIABILITY due to known bugs.

**Professional relevance:** ✅✅ **Very High** in concept — fundamentals are the bedrock of long-term stock analysis. But:

**FINDING F-01 🔴 CRITICAL (already tracked in fundamentals-agent-audit-2026-05-30.md)**  
Period-alignment mismatch can silently invert the `net_margin` sign. A company with positive net income may score as bearish because of a mismatch between annual and quarterly filing periods. This signal has the **highest lane weight (1.2)** of any signal, making a sign inversion maximally damaging.

**FINDING F-02 🟠 HIGH**  
Fundamentals inspector shows margins, ROE, ROA, leverage, and growth metrics — but gives no context for what "good" values look like. A net margin of 8% shown to an investor in isolation is meaningless without sector context. A semiconductor company with 8% net margin is poor; a grocery retailer with 8% net margin is excellent.

**FINDING F-03 🟡**  
The "Filing period" card correctly shows the period (e.g., "Q4 2025") and alignment status but uses the phrase "SEC period alignment is X" — an internal pipeline term. Should read: "Using quarterly data from Q4 2025, which matches the selected annual period."

---

### 2.4 Insider Transactions

**What it measures:** Net dollar value of Form 4 open-market purchases minus sales by company insiders (officers, directors, 10%+ owners) over a 90-day lookback.

**How it triggers:** For each ticker, sum all Form 4 purchase values and subtract sale values. Then cross-sectionally z-score the `net_transaction_value` across the universe.

**Why bullish:** Net positive means insiders bought more than they sold in dollar terms. Insiders buying with their own money is widely considered a strong positive signal — they have access to material non-public information about the company's prospects (within legal limits) and are putting their own capital at risk.

**Why bearish:** Net negative means insiders sold more than they bought. Insider selling is a weaker signal than buying because insiders sell for many reasons (diversification, tax, estate planning, exercise of options) — but significant concentrated selling without buying is a caution flag.

**Score meaning:** Z-score of `net_transaction_value` — how many standard deviations this ticker's insider net dollar flow is above or below the universe mean. Unbounded.

**Conviction level:** Medium-to-High for buying; Low-to-Medium for selling.

**Professional relevance:** ✅ **High for concentrated buying; Medium for selling.**

**FINDING IN-01 🟠 HIGH — No insider type weighting**  
The signal treats a $500K purchase by a board member the same as a $500K purchase by the CEO. In professional insider analysis, CEO and CFO transactions (C-suite insiders with highest information access) are given materially more weight than board member transactions. This is currently not differentiated.

**FINDING IN-02 🟡 — No option exercise filtering explanation**  
The code correctly filters to only transaction codes "P" (open-market purchase) and "S" (sale), excluding option exercises. But the inspector doesn't tell the user this — showing "Buy / sell value" without noting that option grants and exercises are excluded. A sophisticated investor will wonder if the buy value includes automatic compensation grants.

**FINDING IN-03 🔵 — 90-day lookback may include stale transactions**  
If an insider bought shares 89 days ago at a price 40% lower, and the stock has since risen 40%, that "bullish" signal may be outdated. There is no recency weighting on insider transactions. The "Latest transaction" card date helps — but the bulk metrics aggregate equally across the full window.

---

### 2.5 Institutional Holdings (13F)

**What it measures:** Net change in shares held by institutional investors filing 13F reports, comparing current quarter to prior quarter for tracked holders.

**How it triggers:** Z-score of net share change across the universe, averaged with z-score of the change ratio (net change / current shares).

**Why bullish:** Net accumulation — institutions added to their position, implying they believe the stock is worth more.

**Why bearish:** Net distribution — institutions reduced their position, implying they are exiting or trimming.

**Score meaning:** Mean of two z-scores (absolute change and ratio). Unbounded.

**Conviction level:** **Low**. Despite the professional aura of "institutional flow," 13F data is inherently stale.

**Professional relevance:** 🟡 **Low-to-Medium** — critically limited by data staleness.

**FINDING INST-01 🔴 CRITICAL — 13F data has a 45-day filing delay**  
13F filings must be submitted within 45 days of quarter-end. The "current quarter" 13F data showing on the dashboard is at minimum 45 days old and sometimes months old. Using this as a real-time "institutional accumulation" signal is fundamentally misleading. A stock that institutions accumulated heavily in Q1 but have since sold in Q2 would still show as "bullish" because the Q1 13F just filed. The inspector note says "13F holdings are delayed quarterly SEC filings" — this is good. But the signal is still classified as ACTIONABLE when it scores well, which it should not be.

**FINDING INST-02 🟡 — "Current-basis change" label is confusing**  
The card "Current-basis change" shows "Net share change divided by current shares held; this is not a price return." The "this is not a price return" disclaimer suggests users may confuse a 15% share count change for a 15% return. The label should be "Position size change (%)" and the detail should be clearer.

**FINDING INST-03 🔵 — Implied value/share should not exist**  
The card "Implied value/share" shows "Filing value divided by shares; this is not the execution price." This computed metric has no analytical value and could mislead (a 2019 13F value / current shares is meaningless). Remove this card.

---

### 2.6 News

**What it measures:** Sentiment of recent ticker-tagged RSS headlines using a small fixed vocabulary of positive and negative terms.

**Positive terms:** upgrade, beats, beat, raises, raised, buy, outperform, surges, approval  
**Negative terms:** downgrade, misses, miss, cuts, cut, sell, lawsuit, probe, falls

**How it triggers:** For each headline tagged to a ticker with sufficient confidence, count matching positive and negative terms. `sentiment_score = positive_count - negative_count`. Cross-sectionally z-score the sentiment scores.

**Why bullish:** More bullish term matches than bearish term matches in the 3-day window.

**Why bearish:** More bearish term matches than bullish term matches.

**Score meaning:** Z-score of net term count. Unbounded.

**Conviction level:** **Low.** The methodology is extremely simple — 9 positive terms, 9 negative terms, no ML, no entity resolution beyond ticker matching, no understanding of context or negation.

**Professional relevance:** 🔴 **Low — but useful as context (currently correctly classified as CONTEXT_ONLY)**  
This is one of the weakest signals professionally, and it is correctly kept as a context lane. However the UX doesn't explain why — a user seeing "news: context only" doesn't understand that this is an intentional design choice, not a data quality problem.

**FINDING N-01 🟠 HIGH — Vocabulary is dangerously simple**  
The word "cuts" matches bearish terms — but "cuts prices" (bullish for a consumer company gaining market share) would score identically to "cuts guidance" (bearish). The term list has no phrase matching, no negation handling ("did not miss," "beats and raises"), and no context disambiguation. The signal will routinely misclassify nuanced headlines.

**FINDING N-02 🟡 — 3-day lookback should be visible in the inspector**  
The lookback window (3 days) is not shown in the news inspector. A user reading "6 headlines" doesn't know if that's 6 from the last 3 days or 6 from the last 3 months.

**FINDING N-03 🟡 — No explanation that this is keyword-only, not ML sentiment**  
The inspector says "Counts ticker-tagged headlines and simple bullish/bearish terms across the recent news window." The word "simple" understates the limitation. The inspector should explicitly say: "This lane uses a fixed keyword list, not an ML sentiment model. It cannot distinguish 'beats and raises guidance' from 'beats drums of war.'"

---

### 2.7 Buy/Sell Pressure

**What it measures:** Whether the aggregate of delayed Massive trade prints leans toward buyer-side or seller-side pressure, using trade signing inference (quote rule when bid/ask available, tick test fallback).

**How it triggers:** Net signed notional = buy-inferred notional minus sell-inferred notional. Combined with pre-market pressure (weighted at 35%) and volume pressure (weighted at 20%). `directional_rank_score` across the universe.

**Why bullish:** Inferred buy-side notional substantially exceeds sell-side notional across the session's delayed prints.

**Why bearish:** Inferred sell-side notional substantially exceeds buy-side notional.

**Score meaning:** Cross-sectional rank of buy/sell pressure. Bounded [-1, 1].

**Conviction level:** Medium. Trade signing from delayed prints with the quote/tick rule is a standard institutional approach, but it's inferential — not confirmed buyer identity.

**Professional relevance:** ✅ **Medium-to-High** when the data source covers sufficient print volume.

**FINDING BSP-01 🟡 — "Inferred" not prominent enough**  
The inspector says "This is not a confirmed buyer identity; it is a directional reconstruction from delayed Massive trade prints." This disclaimer is in the `detail` section (second paragraph) — it should be in the headline or be a prominent warning card. Trade direction inference is frequently wrong on individual prints.

**FINDING BSP-02 🟡 — Total analyzed notional scope not clear**  
"Total analyzed notional includes all delayed prints in the slice, not just off-exchange prints." The user won't know why this distinction matters without more context. The key insight is: if a stock trades $500M/day normally, $2M in "signed notional" is meaningless, while for a $50M/day stock it's significant. Scale context relative to normal volume is missing.

---

### 2.8 Block Trade Pressure

**What it measures:** Whether focused large and off-exchange (TRF) prints are directionally buy- or sell-pressured, with relative thresholds that normalize for ticker liquidity.

**How it triggers:** A "focused" print must either (a) be an explicit TRF/off-exchange print or (b) meet BOTH an absolute floor (≥10K shares or ≥$200K notional) AND a relative floor (≥5× the ticker's own median print). Signed focused notional pressure × focus notional share × log count participation = block trade score.

**Why bullish:** Large, off-exchange, or relatively-oversized prints lean buyer-side.

**Why bearish:** Large, off-exchange, or relatively-oversized prints lean seller-side.

**Score meaning:** Directional rank of block-print pressure score. Bounded [-1, 1].

**Conviction level:** Medium-to-High. Block trade anomalies are a standard institutional signal — large buyers and sellers operate in dark pools and through large print trades. The relative threshold (5× ticker median) is a smart design choice.

**Professional relevance:** ✅ **High.** Block trade flow analysis is a genuine edge in professional trading desks.

**FINDING BTP-01 🟡 — "TRF/off-exchange means reported through FINRA TRF; it is useful large-print evidence, not proof of a dark-pool venue"**  
This disclaimer (correct) is buried in the `detail_text`. Many users will associate "off-exchange" with dark pools and draw stronger conclusions than the data supports. This should be a prominent inspector card, not a prose footnote.

**FINDING BTP-02 🔵 — "Threshold basis" card is unclear**  
The card label "Threshold basis" and its computed values (`_block_threshold_value`, `_block_threshold_detail`) are not shown in the read code sample — but the concept "what threshold was used to classify blocks for this specific ticker" is important and should be explicit: "For this ticker, a block requires ≥ $200K notional AND ≥ 5× the $18K median print."

---

### 2.9 Unusual Trade Activity

**What it measures:** Whether this trading session's aggregate trade count, volume, or notional is unusually high versus this ticker's own recent daily baseline.

**How it triggers:** Compute latest/median ratios for trade count, notional, and volume. Classify into anomaly bands (normal/attention/strong/extreme). Sign the anomaly by the session's net notional pressure direction.

**Why bullish:** Activity spike (count, volume, or notional) is unusually high AND the signed pressure is buyer-side.

**Why bearish:** Activity spike is unusually high AND signed pressure is seller-side.

**Score meaning:** Selected `market_flow_feature` value — directional rank. Bounded [-1, 1].

**Conviction level:** Medium. Activity spikes that correlate with directional pressure are meaningful, but the baseline comparison can be noisy for tickers with variable daily activity.

**Professional relevance:** ✅ **Medium-to-High** — unusual activity detection is standard quantitative screening.

**FINDING UTA-01 🟡 — "Most unusual metric" should explain the ranking logic**  
When volume is 8× normal, trade count is 3×, and notional is 5×, the inspector shows "Volume anomaly" as the "most unusual metric" but doesn't explain how it picks among multiple elevated metrics. The user should know this uses the highest anomaly ratio.

---

### 2.10 Pre-Market Unusual Activity

**What it measures:** Whether pre-market session volume or notional is unusually high versus this ticker's own pre-market baseline, signed by pre-market pressure direction.

**Why bullish:** Pre-market volume/notional spike with buyer-side pre-market pressure.

**Why bearish:** Pre-market volume/notional spike with seller-side pre-market pressure.

**Professional relevance:** ✅ **Medium** — useful early context, correctly identified in `signal-methodology.md` as "not a standalone trade trigger."

**FINDING PMUA-01 🟡 — Pre-market baseline comparison should show the time window**  
Unlike regular session data, pre-market has much lower total volume. A 3× pre-market spike in absolute terms may represent a trivial dollar amount. The baseline window and the absolute notional should both be visible to the user for context.

---

### 2.11 Market-Flow Trend

**What it measures:** Whether the current session's signed notional pressure is improving or deteriorating versus the recent daily median pressure.

**Why bullish:** Latest net signed notional pressure > prior median pressure (buyer flow is strengthening).

**Why bearish:** Latest net signed notional pressure < prior median pressure (seller flow is strengthening or buyer flow is weakening).

**Professional relevance:** ✅ **Medium** — flow trend context is useful for intraday timing, correctly kept as a context/corroborating lane.

**FINDING MFT-01 🔵 — "Participation scaling" is unclear**  
The card "Trend participation" shows a percentage but the detail "Participation scaling from latest notional versus recent median notional" is too abstract. Should read: "What fraction of a normal-volume day's notional was analyzed; low participation means the trend signal has less weight."

---

### 2.12 Subscription Thesis

**What it measures:** Whether analyzed subscription newsletter/email articles express a bullish or bearish thesis on this ticker.

**How it triggers:** Subscription emails are analyzed for ticker mentions and overall thesis direction. Recency-weighted (decay factor 0.65 per day). Direction score: BULLISH = +0.65, BEARISH = −0.65, NEUTRAL = 0.0, MIXED = 0.0.

**Why bullish:** A subscription email/newsletter has a bullish thesis on this stock within the lookback window (10 days).

**Why bearish:** A subscription email/newsletter has a bearish thesis on this stock.

**Conviction level:** Medium — subscription newsletter analysis can be very high-quality (research boutiques, sector-specialist analysts) or low-quality (retail-focused email blasts). The system doesn't currently differentiate source quality.

**Professional relevance:** ✅ **Medium** — subscription analyst theses are a real edge in information processing, but the fixed ±0.65 direction score is not a measured confidence value.

**FINDING ST-01 🟠 HIGH — Fixed ±0.65 score is not a confidence measurement**  
Every bullish article scores exactly +0.65 regardless of whether the thesis is a 3-page deep-dive with financial model or a one-paragraph blurb. The score represents "there was a bullish article" not "how strongly bullish." This should be weighted by source quality tier or thesis depth.

**FINDING ST-02 🟡 — "10-day lookback" not visible in inspector**  
A user seeing a subscription thesis signal from 9 days ago doesn't know how close it is to expiry.

---

### 2.13 Options Flow

**What it measures:** Balance of call-side versus put-side premium, volume, and open-interest in the recent option chain.

**Why bullish:** Call-side premium or volume dominates put-side (market participants paying up for upside exposure).

**Why bearish:** Put-side premium or volume dominates call-side (market participants paying up for downside protection).

**Professional relevance:** ✅ **High** in concept. Options flow is one of the best real-time positioning signals. However, this is the lane for which the inspector currently falls back to `_fallback_evidence_from_detail` for many rows, suggesting the reconstructor is incomplete.

**FINDING OF-01 🟠 HIGH — Options flow inspector is a fallback in most cases**  
`LANE_EXPLANATIONS` for `options_flow` says: "This inspector shows the persisted runtime summary, direction, source ID, confidence, and timestamp for the option-chain row so the user can audit what was counted." This is a fallback description — the live reconstruction of put/call ratio, premium split, and OI changes that the other lanes show is missing. Options flow is a high-conviction signal that deserves a full dedicated inspector.

**FINDING OF-02 🟡 — No put/call ratio explicitly shown**  
Even in the fallback, the most meaningful options flow metric — the put/call ratio — is not surfaced. The inspector should always show: call premium %, put premium %, call volume %, put volume %, and call OI %.

---

### 2.14 Options Anomaly

**What it measures:** Unusual spikes in options activity (volume, premium, OI) on either call or put side versus a baseline.

**Professional relevance:** ✅ **High** — options anomalies (unusual call buying, sudden spike in put OI) are some of the most reliable institutional positioning signals used by professional desks.

**FINDING OA-01 🟠 HIGH — Same fallback issue as options_flow**  
`LANE_EXPLANATIONS` for `options_anomaly` is also a prose fallback. No dedicated reconstruction shows the actual anomaly metrics. This is a premium signal in professional settings that should have a full card-based inspector showing: baseline call/put volume, current volume, anomaly ratio, and which strike/expiry clusters are driving the anomaly.

---

### 2.15 Prepost (Extended Hours)

**What it measures:** Extended-hours (pre- and post-market) volume or notional plus signed pressure from those sessions.

**Why bullish:** Extended-hours activity elevated with buyer-side signed pressure.

**Why bearish:** Extended-hours activity elevated with seller-side signed pressure.

**Professional relevance:** ✅ **Medium** — extended hours activity around earnings, news events, or overnight developments is useful context.

**FINDING PP-01 🟡 — Inspector is a stored-summary fallback**  
The `prepost` lane uses `_fallback_evidence_from_detail` — it shows the stored runtime summary and provenance, not a reconstructed metric breakdown. A full inspector should show pre-market vs post-market split, total volume, and signed pressure separately.

---

### 2.16 Sector Momentum

**What it measures:** Whether the stock's sector ETF is outperforming or underperforming its own recent return baseline.

**Why bullish:** The sector (e.g., XLK for tech) has positive momentum relative to its historical baseline — a rising tide for this stock's group.

**Why bearish:** The sector has negative momentum — headwinds for this group.

**Professional relevance:** ✅ **Medium** — sector momentum is a valid macro-to-micro signal. If XLK is weak, tech stocks face sector headwinds regardless of individual fundamentals.

**FINDING SM-01 🟡 — Inspector is a stored-summary fallback**  
The `sector_momentum` lane uses the fallback path. A full inspector should show: sector ETF, current sector return, sector baseline return, relative to SPY/QQQ.

---

### 2.17 Activity Alerts

**What it measures:** Pre-stored upstream activity alert rows that have already classified volume/notional/trade count vs baseline.

**Professional relevance:** ✅ **Medium** — these use the stored alert summary and provenance, preserving upstream classification.

**FINDING AA-01 🔵 — Inspector relies entirely on stored provenance**  
By design, activity alerts preserve the upstream system's summary. This is architecturally correct. However the inspector should label this explicitly: "This signal uses the upstream alert system's classification, not a real-time reconstruction."

---

## Part 3 — UX & Display Audit

### 3.1 Signal Table (Before Expanding Inspector)

**FINDING UX-01 🔴 CRITICAL — "Summary" column falls back to generic descriptive text**  
The most visible column in the table — Summary — currently falls back to:

> `"{lane}: direction {direction}; no lane summary was persisted for this row."`

For example: `"Technical Analysis: direction bullish; no lane summary was persisted for this row."`

This contains **zero information the user cannot already see from the Ticker, Pipeline/Type, and Direction columns.** When a signal doesn't have a runtime summary stored, it must generate one from available evidence — the score, the reason code, and the inspector headline data. A user scanning 30 signal rows to triage the most interesting ones is completely unserved by this fallback.

**Required fix:** Generate a minimum-viable summary from available fields when no runtime summary exists:
- For `abnormal_volume`: `"Volume {ratio}x normal, price {+X%}; {band} anomaly band"` — from the `trigger_headline` data
- For `technical_analysis`: `"Setup: {setup_label}, RSI {rsi14}, trend {trend_score:+.1f}"` 
- For `fundamentals`: `"Net margin {net_margin}%, FCF margin {fcf_margin}%"`
- For `insider`: `"Net insider flow: {buy_value} buys vs {sell_value} sells ({directional_transactions} transactions)"`
- etc.

---

**FINDING UX-02 🟠 HIGH — Score column shows a raw number with no scale context**  

The score `+0.72` or `−0.34` means nothing without knowing the scale. A user can't know if +0.72 is 72% of maximum, 72nd percentile, or 0.72 standard deviations. Every row shows a different lane's score type but they're all formatted identically with no scale label.

**Required fix:** Add a `score_context` field per row shown as a subscript or tooltip: "Ranked 72nd percentile in universe" for rank scores, or "0.72 standard deviations above mean" for z-scores.

---

**FINDING UX-03 🟡 — "Bucket" column label is confusing**  

"Bucket" is an internal classification term. The column values ("Actionable", "Context", "Suppressed") are clear, but the column header "Bucket" is jargon. Should be "Treatment" or "Role."

---

**FINDING UX-04 🟡 — "Inspect Signal" button is the only gateway to all meaningful information**  

The entire inspector — headline, detail, cards, interpretation, decision effect, alignment — is hidden behind a click. For a user reviewing 20+ signals, expanding each one individually is tedious. The table row should show at least the trigger headline as a tooltip or expandable micro-text.

---

**FINDING UX-05 🟡 — No column explaining why a signal is suppressed**  

When a signal is Suppressed, the user sees a "Suppressed" badge and a score — but `suppression_reason` is not in the visible table (only in the inspector facts panel). Common reasons like "below_actionability_threshold", "source_unavailable", or "stale_evidence" should appear as a small tag next to the Suppressed badge without requiring an inspector click.

---

### 3.2 Signal Inspector Panel (After Expanding)

**Overall assessment: The inspector is well-designed and informative.** The `trigger_headline`, `trigger_detail`, card grid, interpretation_text, decision_effect_text, and decision_alignment_text are all explanatory and non-generic (when present). The main issues are:

**FINDING UX-06 🟡 — "Agency Interpretation" text is redundant when trigger_headline is good**  

The `interpretation_text` in `_apply_concrete_inspection_text` reads:
> `"{lane} hard evidence for {ticker}: {headline}{concise_detail} Direction is {direction}; score {score}."`

When the headline already says this, the "Agency Interpretation" section adds very little. It should either be removed or elevated to explain something the headline doesn't — e.g., "Why does this matter for the trade decision?" rather than re-summarizing the headline.

---

**FINDING UX-07 🟡 — "Judgment Alignment" section has only 6 cases and uses generic phrasing**  

The alignment text only matches on `direction × action` pairs. The current outputs are:
- "Supports the current WATCH posture for AAPL."
- "Works against the current WATCH posture and should be read as caution."

These are correct but thin. For a sophisticated investor, "supports the WATCH posture" is too brief. The text should include "because this bullish volume signal suggests accumulation pressure that is consistent with the reason we're watching this candidate."

---

**FINDING UX-08 🔵 — Inspector facts panel labels use internal terminology**  

| Current label | More investor-friendly label |
|---|---|
| "Actionability" | "Role in Decision" |
| "Quality" | "Signal Quality" |
| "Reason Codes" | "Why This Was Classified" |
| "Reason Meaning" | "What This Means" |
| "Provenance" | "Data Source" |
| "Current Candidate" | "Candidate State" |

---

### 3.3 Lane Summary Cards (Signal Data Health Section)

**FINDING UX-09 🟡 — "Signal Data Health" title doesn't explain what these cards are**  

The section heading is "Signal Data Health" but these cards show the state of each signal **pipeline/lane** — whether it's configured, whether it has data this cycle, and its runtime effect. "Signal Data Health" sounds like a data freshness report; it should be "Signal Pipelines" or "Active Signal Processes."

---

**FINDING UX-10 🟡 — "Muted" label in lane card counter is non-standard**  

The lane card shows four counts: Rows, Action, Context, **Muted**. "Muted" corresponds to "Suppressed" signals in the table. Using different terminology in two places for the same concept creates confusion. Choose "Suppressed" or "Excluded" and use it consistently.

---

**FINDING UX-11 🟡 — Lane card shows `runtime_effect` but not what the effect means**  

`runtime_effect` is a prose string like "action-weighted: contributes directly to final conviction score." This is good. But the ordering (configured → state → runtime_effect → top signal) creates a wall of information with no visual hierarchy.

---

**FINDING UX-12 🔵 — "State" tag values use internal code: `action_weighted`, `corroborating`, `disabled`**  

The state tags map to CSS classes (pass/warn/block) but the displayed values are internal codes. The state should read: "Drives decisions" (action_weighted), "Supports context only" (corroborating), "Disabled" (disabled).

---

### 3.4 Page-Level Summary Section (KPI Grid + Headline)

**FINDING UX-13 🟠 — Summary section "detail" is generic boilerplate regardless of state**  

When signals are running normally, `detail` reads:
> "Latest-cycle signal audit across X selection report(s). Use this page to check whether each lane is firing, actionable, fresh, and aligned with the candidate decisions."

This is **identical every time** — it describes what the page is for, not what the current state is. If 8 of 11 lanes have actionable signals, the summary should say that. If the top bullish signal is abnormal volume at +0.85 for NVDA, the summary should name it.

**Required fix:** Make the summary dynamic:
- If any ACTIONABLE signals exist: "X actionable signals across Y lanes. Strongest: {top lane} for {top ticker} ({score})."
- If all signals are context or suppressed: "No actionable signals this cycle — all signals are context-only or suppressed. {reason}."
- Show the actual distribution: "8 bullish, 3 bearish, 12 neutral across the current cycle."

---

**FINDING UX-14 🟡 — KPI grid "Actionable" description says "can drive decisions" — not specific enough**  

"Can drive decisions" is passive. The text should match what an investor would care about: "Included in the final conviction score" for Actionable, "Explains context but does not add to the score" for Context, "Recorded for audit but excluded from scoring" for Suppressed.

---

## Part 4 — Professional Conviction Gaps

### Signals the system lacks that matter professionally

These are not code bugs — they are gaps in signal coverage. Listed for planning purposes:

| Missing Signal | Why It Matters | Data Source Candidates |
|---|---|---|
| Short interest / borrow rate | High short interest + positive price = squeeze setup; increasing borrow cost = trouble | FINRA short volume data, IHS Markit |
| Earnings surprise magnitude | Analysts revise estimates post-earnings; magnitude of surprise is the actual signal | FMP earnings history |
| Analyst revision momentum | Multiple analysts revising estimates in the same direction is a strong leading indicator | FMP analyst estimates |
| Insider cluster buying | Multiple different insiders buying simultaneously is much stronger than one buyer | Already in Form 4 data — needs filer-type grouping |
| Price target upgrade/downgrade magnitude | An analyst raising target from $100 to $180 (80% upside) is very different from $100 to $102 | FMP analyst estimates |
| Management change event | New CEO/CFO is a major catalyst either direction | SEC 8-K parser |
| Share buyback authorization | Board-approved buyback signals management confidence | SEC 8-K parser |
| Dividend cut/raise | High-conviction signal for dividend-paying stocks | SEC 8-K parser |
| Credit rating change | Downgrade = immediate institutional forced selling risk | Moody's/S&P (limited public access) |
| Relative sector performance (individual stock vs sector) | Sector-lagging stocks under distribution; leaders under accumulation | Existing price data, sector ETF mapping |

---

## Part 5 — Summary of All Findings

| ID | Severity | Category | One-Line Description |
|---|---|---|---|
| S-01 | 🔴 CRITICAL | Scoring | Score scale is not comparable across lanes |
| S-02 | 🟠 HIGH | Scoring | Actionability threshold is hidden from users |
| S-03 | 🟡 MEDIUM | Scoring | Direction epsilon creates unexplained NEUTRAL gap |
| S-04 | 🟡 MEDIUM | Scoring | "Conviction" column is candidate-level, not signal-level |
| AV-01 | 🟡 MEDIUM | Abnormal Volume | Volume band (normal/attention/strong/extreme) not shown in inspector |
| AV-02 | 🔵 LOW | Abnormal Volume | Trend agreement not surfaced |
| TA-01 | 🟡 MEDIUM | Technical Analysis | Methodology string shown as raw code, not human-readable |
| TA-02 | 🔵 LOW | Technical Analysis | Driver mix card hard to read at a glance |
| TA-03 | 🔵 LOW | Technical Analysis | "Subtracts" framing unclear for volatility risk |
| F-01 | 🔴 CRITICAL | Fundamentals | Period mismatch bug can invert net_margin sign (tracked separately) |
| F-02 | 🟠 HIGH | Fundamentals | No sector context for margin/ROE values |
| F-03 | 🟡 MEDIUM | Fundamentals | "SEC period alignment" is internal pipeline term |
| IN-01 | 🟠 HIGH | Insider | No insider type weighting (CEO vs board member) |
| IN-02 | 🟡 MEDIUM | Insider | No explicit statement that option exercises are excluded |
| IN-03 | 🔵 LOW | Insider | 90-day window has no recency weighting |
| INST-01 | 🔴 CRITICAL | Institutional | 13F data is 45+ days stale — should not be ACTIONABLE |
| INST-02 | 🟡 MEDIUM | Institutional | "Current-basis change" label confusing |
| INST-03 | 🔵 LOW | Institutional | "Implied value/share" card is misleading, no value |
| N-01 | 🟠 HIGH | News | Fixed 9-term vocabulary misclassifies nuanced headlines |
| N-02 | 🟡 MEDIUM | News | 3-day lookback window not visible in inspector |
| N-03 | 🟡 MEDIUM | News | No disclaimer that this is keyword-only, not ML sentiment |
| BSP-01 | 🟡 MEDIUM | Buy/Sell Pressure | "Inferred" disclaimer not prominent enough |
| BSP-02 | 🟡 MEDIUM | Buy/Sell Pressure | No scale context for signed notional relative to ticker's normal volume |
| BTP-01 | 🟡 MEDIUM | Block Trade | TRF/dark-pool disclaimer buried in prose |
| BTP-02 | 🔵 LOW | Block Trade | "Threshold basis" card values unclear |
| UTA-01 | 🟡 MEDIUM | Unusual Trade Activity | "Most unusual metric" selection logic not explained |
| PMUA-01 | 🟡 MEDIUM | Pre-Market Activity | Pre-market baseline window not visible |
| MFT-01 | 🔵 LOW | Market Flow Trend | "Participation scaling" too abstract |
| ST-01 | 🟠 HIGH | Subscription Thesis | Fixed ±0.65 score is not a confidence measurement |
| ST-02 | 🟡 MEDIUM | Subscription Thesis | 10-day lookback window not visible |
| OF-01 | 🟠 HIGH | Options Flow | Inspector is a fallback — no reconstructed metrics |
| OF-02 | 🟡 MEDIUM | Options Flow | Put/call ratio not shown even in fallback |
| OA-01 | 🟠 HIGH | Options Anomaly | Inspector is a fallback — no reconstructed metrics |
| PP-01 | 🟡 MEDIUM | Prepost | Inspector is a stored-summary fallback |
| SM-01 | 🟡 MEDIUM | Sector Momentum | Inspector is a stored-summary fallback |
| AA-01 | 🔵 LOW | Activity Alerts | Inspector should label that it's upstream-system data |
| UX-01 | 🔴 CRITICAL | UX | Summary column falls back to generic descriptive text |
| UX-02 | 🟠 HIGH | UX | Score column shows raw number with no scale context |
| UX-03 | 🟡 MEDIUM | UX | "Bucket" column header is jargon |
| UX-04 | 🟡 MEDIUM | UX | All meaningful context hidden behind "Inspect" click |
| UX-05 | 🟡 MEDIUM | UX | Suppression reason not visible in table row |
| UX-06 | 🟡 MEDIUM | UX | "Agency Interpretation" redundant when headline is good |
| UX-07 | 🟡 MEDIUM | UX | "Judgment Alignment" text is thin — only 6 cases |
| UX-08 | 🔵 LOW | UX | Inspector facts panel uses internal terminology |
| UX-09 | 🟡 MEDIUM | UX | "Signal Data Health" section title unclear |
| UX-10 | 🟡 MEDIUM | UX | "Muted" vs "Suppressed" inconsistency |
| UX-11 | 🟡 MEDIUM | UX | Lane card information hierarchy flat |
| UX-12 | 🔵 LOW | UX | State tag values show internal codes |
| UX-13 | 🟠 HIGH | UX | Page summary "detail" text is boilerplate |
| UX-14 | 🟡 MEDIUM | UX | KPI "can drive decisions" description too passive |

**Total:** 49 findings: 5 Critical, 10 High, 25 Medium, 9 Low

---

## Part 6 — Recommended Implementation Priority

### Tier 1: Fix Immediately (Correctness + Trust)

1. **F-01** — Fundamentals period mismatch bug (tracked in fundamentals audit)
2. **INST-01** — Institutional signals classified as ACTIONABLE despite 45+ day data delay; force to CONTEXT_ONLY with reason "13f_data_delayed"
3. **S-01** — Add score scale context to inspector; at minimum label each score as "Cross-section rank" vs "Z-score" vs "Fixed tier score"
4. **UX-01** — Replace the generic fallback summary with lane-specific generated summaries using inspector headline data

### Tier 2: High-Impact UX (Investor Clarity)

5. **S-02** — Surface actionability threshold reason in inspector when CONTEXT_ONLY or SUPPRESSED
6. **UX-13** — Make page summary dynamic (state, top signal, distribution)
7. **OF-01 + OA-01** — Build dedicated inspector reconstructors for options_flow and options_anomaly
8. **N-01** — Add note to news inspector explaining keyword-only methodology limitation
9. **ST-01** — Weight subscription thesis score by source quality/depth rather than fixed ±0.65
10. **UX-02** — Add score scale context (rank / z-score / fixed) as subscript or tooltip in table

### Tier 3: Polish & Professional Depth

11. **IN-01** — Insider type weighting (CEO/CFO > board member)
12. **F-02** — Add sector-relative context for fundamentals margins
13. **AV-01** — Surface volume band in abnormal volume inspector cards
14. **PP-01 + SM-01** — Build dedicated inspector reconstructors for prepost and sector momentum
15. **UX-03 through UX-14** — UX label improvements (Bucket → Treatment, Muted → Suppressed, state code display, etc.)

### Tier 4: New Signals (Coverage Expansion)

16. Short interest / borrow rate signal
17. Analyst revision momentum signal
18. Insider cluster detection (multiple filers same week)
19. SEC 8-K event classifier (buyback, dividend, management change)

---

## Part 7 — What Good Looks Like (Target State)

When a user opens the signals dashboard, they should be able to:

1. **In 30 seconds:** See how many actionable signals fired, which direction they lean, and which tickers have the strongest signal convergence.

2. **In 2 minutes:** For any specific ticker, read in plain English: which signal fired, exactly what it detected, what data it used, when that data was collected, why it's classified as bullish or bearish, and how much weight it contributes to the decision.

3. **In 5 minutes:** Understand why the system chose WATCH vs NO_TRADE for a specific candidate based on the signal evidence, without needing to understand the internal pipeline architecture.

The existing inspector panel (for lanes that have dedicated reconstructors) is very close to achieving #2 and #3. The primary gaps are: the table row level (#1), the score scale (#2), the institutional data staleness (#3), and the options/prepost/sector fallback inspectors.

---

*End of audit. Next step: invoke `writing-plans` skill to create implementation plan from Tier 1 and Tier 2 findings.*
