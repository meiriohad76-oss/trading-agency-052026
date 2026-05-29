# Market Regime Agent — Audit & Redesign Report

**Date:** 2026-05-29  
**Author:** Ohad Meiri  
**Status:** Draft — pending design decisions (see §8)  
**References:**  
- Current runtime: `src/agency/runtime/market_regime.py`  
- Current view: `src/agency/views/market_regime.py`  
- Current template: `src/agency/templates/market_regime.html`  
- External repo: https://github.com/meiriohad76-oss/SECTOR_MOMENTUM_AND_ROTATION

---

## 1. Executive Summary

The current Market Regime agent was built as a **read-only, research-reference dashboard** — a place to check the broad market backdrop before reviewing candidates. It is not wired into any decision-making pipeline. The portfolio manager, risk module, and candidate selection pipeline all ignore it entirely.

Meanwhile, the external SECTOR_MOMENTUM_AND_ROTATION repo contains a **production-grade, 7-pillar sector analysis methodology** with backtest validation, state machines, institutional flow analysis, and macro integration — far more sophisticated than what the agency currently uses.

The redesign goal is to **connect the market regime to the actual trading decisions**: entry conviction, exit signals, and portfolio-level circuit breakers. The methodology should draw from the best of both the current implementation and the external repo, while staying proportionate to the short-term investing rhythm (1–3% weekly, 2–5 day holds).

**Three-sentence verdict on the current implementation:**  
The data pipeline and sector ETF calculations are sound. The regime classification logic is reasonable but uses the wrong time horizons for a short-term investing system (20D/60D windows are too slow). There is zero integration between regime output and the rest of the agency — the whole module is decorative.

---

## 2. Current Implementation Audit

### 2.1 What Exists

| Component | Description |
|---|---|
| `runtime/market_regime.py` | Loads sector ETF + universe prices from parquet, computes returns (5D/20D/60D), breadth (% above SMA20/50, advancers), and classifies a regime. Pure function, no side effects. |
| `views/market_regime.py` | Async view that wraps the runtime, adds broker status and data-health context, caches result for `MARKET_REGIME_CONTEXT_CACHE_SECONDS`. |
| `market_regime.html` | Jinja2 template: regime banner, 6 KPI cards, benchmark table (SPY/QQQ/IWM/DIA), 11 sector cards with momentum scores and guidance, data quality panel. |

### 2.2 What Works Well

**Keep these — they are solid:**

- **Sector ETF relative momentum** — excess return vs. SPY across 5D/20D/60D with z-score ranking is the right approach. Well-implemented.
- **Universe breadth** — % above SMA20, % above SMA50, 5D advancers ratio. Correct metrics, cleanly computed.
- **Regime classification vocabulary** — Risk On / Risk Off / High Dispersion / Balanced maps well to what an operator actually needs to know. The label-plus-guidance pattern is good UX.
- **Confidence score** — coverage-weighted confidence that suppresses the regime when data is thin. Prevents false signals on stale data.
- **Data quality panel** — source-backed check, ETF coverage, price lag. Correct fail-safe behavior.
- **PIT discipline** — reads from parquet via the PIT loader. No lookahead.

### 2.3 What Is Wrong or Missing

#### 2.3.1 Wrong time horizons for the actual trading rhythm

The primary decision signal uses `return_20d` (one month) as the regime driver. For a system targeting **2–5 day holds**, the relevant signal is **3–10 days**, not 20 days. The 20D window means the regime reflects where the market was 4 weeks ago, not where it is now.

**Fix:** Add `return_3d` and `return_5d` as primary regime inputs alongside 20D (which becomes confirmation, not the driver).

#### 2.3.2 Zero integration with the decision pipeline

The regime output is never read by:
- The portfolio manager (circuit breakers)
- The risk module (conviction adjustments)
- The candidate selection pipeline (sector alignment check)
- The exit signal system (sector headwind as a SETUP_WARNING trigger)

The entire module is currently decorative — a nice page to look at, not a working component.

#### 2.3.3 No volatility regime

High-volatility markets require wider stops, lower position sizing, and higher conviction thresholds. There is no measure of current market volatility in the system. VIX or SPY realized volatility (which is computable from existing parquet data) would serve this purpose.

#### 2.3.4 No macro tilt

The current regime uses price-only signals. For a short-term investing system, the bond/equity relationship (TLT vs. SPY), the dollar (DXY), and gold (GLD) are useful free proxies for risk appetite shifts. These are all in the existing universe of pullable data.

#### 2.3.5 No stock-to-sector mapping

The dashboard shows sector leadership, but there is no function that answers: *"AAPL is in Technology (XLK), and XLK is currently a Tailwind — therefore AAPL gets a sector boost."* This per-stock context is the most useful output the regime could produce.

#### 2.3.6 No regime change detection

If the regime was Risk On yesterday and is Risk Off today, that transition is more actionable than either state alone. There is no tracking of prior regime state, no transition alert, and no "regime changed since last review" flag.

#### 2.3.7 Sector guidance is generic, not actionable

The current sector guidance text ("Technology is adding top-down support; same-sector candidates may need less extra corroboration") is correct but vague. It should produce a **concrete modifier**: `+0.05 conviction boost` or `raise the bar: require confirmed signal count ≥ 3`.

#### 2.3.8 Dashboard layout problems

- The sector cards grid is dense and hard to scan — 11 equally-sized cards with similar text.
- The regime banner has navigation buttons ("Open signals", "Open final selection") that are unrelated to the page content.
- The data quality panel takes up significant space but is rarely needed during normal operation.
- There is no panel showing how the current portfolio positions are affected by the regime.

---

## 3. External Repo Review (SECTOR_MOMENTUM_AND_ROTATION)

### 3.1 What It Contains

A production-grade sector rotation system with:
- **7-pillar composite scoring** (momentum, Mansfield RS, RRG, trend filters, macro, institutional flow)
- **6-state machine** (STAGE_2_BULLISH → HOLD → WARNING → EXIT → BEARISH_STAGE_4 → STAGE_1_BASING)
- **Walk-forward backtest** with calibration, evidence gates, and bootstrap confidence intervals
- **FRED macro integration** (20 economic indicators)
- **Institutional flow analysis** (CMF, OBV, MFI, RVOL, block trades, dark pools, 13F)
- **Alert system** (Telegram, Slack, Discord, email digests, RSS, iCal)
- **Full Streamlit UI** with RRG quadrant charts, sparklines, comparison cards

### 3.2 What Is Directly Useful for the Agency

| Element from external repo | How to adapt for agency |
|---|---|
| **RRG quadrant concept** (Leading / Weakening / Lagging / Improving) | Replace the current "stance" labels (Tailwind/Neutral/Headwind) with a 4-quadrant model. More nuanced: a sector in "Weakening" is not a Headwind yet, but it's deteriorating. |
| **6-state vocabulary** (STAGE_2_BULLISH, WARNING, EXIT) | Simplify to 4 states for the agency: `ADVANCING`, `TOPPING`, `DECLINING`, `BASING`. Maps directly to entry/hold/exit/watch decisions. |
| **Volatility regime** (VIX + realized vol) | Use SPY realized volatility from existing daily bars. No new data source needed. |
| **Macro tilt proxies** (TLT, GLD, DXY, ^VIX) | All available via yfinance or existing parquet. Simple 3-indicator tilt: bonds-equity relationship, dollar direction, commodities. |
| **Institutional flow at sector level** (CMF, OBV on ETFs) | Apply CMF + OBV to sector ETFs (XLK, XLE, etc.) using existing daily bar data. No paid data needed. Adds a flow confirmation layer to the sector momentum ranking. |
| **Regime change detection + alert** | Persist prior regime state to a small JSON file. On each run, diff against prior state and flag transitions. |
| **Portfolio context panel** | Show each open position's sector alignment in a dedicated section. The external repo does this with a portfolio analyzer. |

### 3.3 What Is Overkill for the Agency (Do Not Import)

| Element | Why to skip |
|---|---|
| Full 7-pillar scoring (Mansfield RS, full RRG formula) | Too complex for top-down context. The agency needs a 1-3 sentence sector verdict, not a 7-factor report card per sector. |
| Full Streamlit UI | Agency runs FastAPI/Jinja2. Visual concepts are useful; the framework is not. |
| FRED API integration (20 indicators) | Overkill for 1-3% weekly targets. 3 free proxies (TLT, GLD, DXY) give 90% of the macro tilt for free. |
| Walk-forward backtest engine | Agency has its own research pipeline. The regime module provides context, not strategy. |
| Alert system (Telegram, Slack, webhooks) | Agency already has an email/notification path. Regime changes surface in the dashboard. |
| SEC 13F institutional holdings | Too lagged (quarterly) for 2-5 day holds. Not relevant. |
| Full SQLite journal | Agency already has PostgreSQL-backed audit trail. |
| Personal trades tracker, P&L tracker | That's the portfolio manager's job. |

---

## 4. Redesigned Purpose

### 4.1 Core Mission (one sentence)

> The Market Regime Agent provides a **top-down context layer** that runs before and during each trading day, classifies the market and sector environment, maps that environment to each open position and candidate, and produces machine-readable modifiers that the portfolio manager and selection pipeline use to adjust conviction thresholds and risk sizing.

### 4.2 When It Runs

| Phase | When | What it does |
|---|---|---|
| **Pre-market** | 07:00–09:00 local (before market open) | Full regime refresh: benchmarks, sectors, breadth, vol regime, macro tilt. Outputs the day's context. Stores regime state for change detection. |
| **Intraday (light)** | Every 30 min during market hours | Refreshes sector ETF prices only. Updates the "intraday drift" indicator — are sectors moving in/against their morning direction? Does NOT recompute the full regime. |
| **Post-market** | 16:30–17:00 local (after close) | Full regime refresh with closing prices. Updates regime state. Compares to morning snapshot. Flags any regime changes. |

### 4.3 Three Outputs

**Output 1 — Market Backdrop**
```json
{
  "regime": "RISK_ON" | "RISK_OFF" | "ROTATING" | "VOLATILE",
  "vol_regime": "CALM" | "ELEVATED" | "HIGH",
  "macro_tilt": "RISK_APPETITE" | "DEFENSIVE" | "NEUTRAL",
  "confidence": 0.0–1.0,
  "new_entries_bias": "NORMAL" | "CAUTIOUS" | "BLOCKED",
  "conviction_modifier": -0.10 to +0.05
}
```

**Output 2 — Sector Alignment Map**
```json
{
  "XLK": { "state": "ADVANCING", "quadrant": "Leading", "score": 1.24, "flow_confirmed": true },
  "XLE": { "state": "TOPPING",   "quadrant": "Weakening", "score": 0.31, "flow_confirmed": false },
  ...
}
```

**Output 3 — Per-Stock Context**
```json
{
  "AAPL": { "sector": "XLK", "sector_state": "ADVANCING", "sector_bias": "TAILWIND", "conviction_boost": 0.03 },
  "XOM":  { "sector": "XLE", "sector_state": "TOPPING",   "sector_bias": "NEUTRAL",  "conviction_boost": 0.0 },
  "NVDA": { "sector": "XLK", "sector_state": "ADVANCING", "sector_bias": "TAILWIND", "conviction_boost": 0.03 }
}
```

---

## 5. Redesigned Methodology

### 5.1 Market Backdrop Classification

**Primary inputs (short-term, 3–5 day windows) — all from Massive daily aggs:**
- `SPY_return_5d`: broad tape direction
- `QQQ_return_5d`: growth/tech confirmation
- `breadth_5d_advancers`: % of **full US market** advancing over 5 days (from Massive grouped daily — not just S&P 100)
- `SPY_realized_vol_10d`: 10-day rolling standard deviation of SPY daily returns × √252 (from Massive SPY bars)

**Confirmation inputs (medium-term, 20D) — from Massive parquet:**
- `SPY_return_20d`, `breadth_above_sma20`

**Macro tilt — FRED (primary) + ETF proxies (intraday):**
- `FRED_VIXCLS`: official VIX level (daily, cached)
- `FRED_T10Y2Y`: yield curve spread (daily, cached)
- `FRED_BAMLH0A0HYM2`: credit spread (daily, cached)
- `TLT_return_5d` via Massive: intraday bond direction (updates during market hours)
- `GLD_return_5d` via Massive: safe-haven flight indicator
- `UUP_return_5d` via Massive: dollar strength (potential equity headwind)

**Regime rules:**

| Regime | Trigger |
|---|---|
| `RISK_OFF` | SPY 5D ≤ -1.5% OR breadth_5d_advancers ≤ 35% OR TLT 5D ≥ +1.5% |
| `VOLATILE` | SPY_realized_vol_10d ≥ 25% annualized AND ABS(SPY_5D) ≥ 2% |
| `ROTATING` | Sector spread (best minus worst sector score) ≥ 1.5 AND breadth 40–65% |
| `RISK_ON` | SPY 5D ≥ +1% AND breadth ≥ 55% AND vol < 20% |
| `NEUTRAL` | Everything else |

**Conviction modifier per regime:**

| Regime | Min conviction floor | New position sizing | Stop-loss |
|---|---|---|---|
| `RISK_ON` | +0.03 boost | Normal (10%) | Normal (-2%) |
| `NEUTRAL` | No change | Normal | Normal |
| `ROTATING` | No change | Normal | Tighten to -1.5% |
| `VOLATILE` | +0.05 boost | Reduce to 5–7% | Tighten to -1.5% |
| `RISK_OFF` | +0.08 boost (much harder to approve) | Reduce to 5% | Tighten to -1.5% |

### 5.2 Sector State Machine (4 states, adapted from external repo)

Each sector ETF (XLK, XLE, etc.) gets one of 4 states, derived from its quadrant position:

**Quadrant classification (RRG-inspired):**
- **RS-Ratio** = sector 20D return vs. SPY 20D return (positive = outperforming)
- **RS-Momentum** = current RS-Ratio vs. 5-day-ago RS-Ratio (positive = improving)

| Quadrant | RS-Ratio | RS-Momentum | State |
|---|---|---|---|
| **Leading** | Positive | Positive | `ADVANCING` |
| **Weakening** | Positive | Negative | `TOPPING` |
| **Lagging** | Negative | Negative | `DECLINING` |
| **Improving** | Negative | Positive | `BASING` |

**Flow confirmation (from OBV and CMF on sector ETF daily bars):**
- If 5D OBV trend is rising AND 5D CMF > 0 → `flow_confirmed = true`
- This upgrades or validates the state; mismatch between price momentum and flow is a warning.

**Conviction modifier per sector state:**

| State | Bias | Conviction modifier for stocks in this sector |
|---|---|---|
| `ADVANCING` + flow_confirmed | Tailwind | +0.03 |
| `ADVANCING` without flow | Tailwind (soft) | +0.01 |
| `TOPPING` | Neutral-to-caution | 0.00 |
| `BASING` | Neutral | 0.00 |
| `DECLINING` + flow_confirmed (bearish) | Headwind | -0.05 (raises required floor) |
| `DECLINING` without flow | Headwind (soft) | -0.02 |

### 5.3 Stock-to-Sector Mapping

A static lookup table maps each ticker in the active universe to its primary GICS sector ETF. This table is maintained in `research/config/ticker-sector-map.json`. Updates happen quarterly (aligned with S&P 100 rebalances).

```json
{
  "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK",
  "XOM": "XLE", "CVX": "XLE",
  "JPM": "XLF", "BAC": "XLF",
  ...
}
```

The regime agent uses this to produce the per-stock context output (§4.3 Output 3).

### 5.4 Regime Change Detection

The agent persists the prior regime snapshot to `research/state/market_regime/last_regime.json`. On each full refresh, it diffs:
- Regime key change (e.g., RISK_ON → RISK_OFF)
- Any sector transitioning from ADVANCING to TOPPING or DECLINING

Transitions are flagged as `regime_changed: true` and surfaced in the dashboard banner and in the pre-trade checklist.

### 5.5 Intraday Drift (lightweight, during market hours)

Runs every 30 minutes using 15-minute delayed ETF prices from yfinance. Computes:
- `SPY_intraday_drift`: current session return (today's price vs. prior close)
- For each sector: intraday return vs. SPY intraday return
- `intraday_leadership_shift`: flags if any sector's intraday rank deviates > 2 positions from morning sector map

This does NOT change the regime classification. It surfaces as a "watch" indicator in the dashboard.

---

## 6. Redesigned Dashboard

### 6.1 Page Structure

```
┌─────────────────────────────────────────────────────┐
│  REGIME BANNER                                       │
│  Today: RISK_ON / CALM vol / RISK_APPETITE macro    │
│  [Regime changed from NEUTRAL since yesterday]      │
└─────────────────────────────────────────────────────┘

┌──────────┬──────────┬──────────┬──────────┐
│ Regime   │ Vol Reg  │ SPY 5D   │ Breadth  │
│ Risk On  │ Calm     │ +1.4%    │ 67%      │
└──────────┴──────────┴──────────┴──────────┘

┌─────────────────────────────────────────────────────┐
│  SECTOR QUADRANT MAP  (4-quadrant RRG layout)        │
│  Leading: XLK (+1.24), XLF (+0.81)                  │
│  Weakening: XLE (+0.31)                             │
│  Improving: XLI (-0.12)                             │
│  Declining: XLRE (-1.44), XLU (-0.98)               │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  YOUR PORTFOLIO CONTEXT                              │
│  AAPL — XLK — ADVANCING ✓ Tailwind                  │
│  XOM  — XLE — TOPPING   ⚠ Neutral                   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  MACRO TILT                                         │
│  TLT -0.3% | GLD +0.2% | UUP -0.1% | Vol 14.2%     │
│  "Risk appetite intact — bonds, gold neutral"       │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  FULL SECTOR TABLE (collapsible)                    │
│  Rank | Sector | State | Score | Flow | 5D | 20D    │
└─────────────────────────────────────────────────────┘

<details> Data Quality </details>    ← collapsible, not primary
```

### 6.2 Panels Added vs. Current

| Panel | Status | Change |
|---|---|---|
| Regime banner | Keep + improve | Add regime-changed indicator, remove nav buttons |
| 4 KPI cards | Keep, shrink | Remove Leading/Weakest sector KPIs (shown in quadrant) |
| **Sector Quadrant Map** | **New** | 4-quadrant layout (Leading/Weakening/Improving/Declining) replaces 11 individual sector cards |
| Benchmark table | Keep | Add `return_5d` as primary column (currently secondary) |
| **Volatility Regime** | **New** | SPY realized vol + VIX proxy indicator |
| **Macro Tilt** | **New** | TLT/GLD/UUP/VIX 5D returns with plain-text interpretation |
| **Portfolio Context** | **New** | Open positions mapped to their sector state |
| Data quality | Keep, demote | Move to collapsible `<details>` section |
| Universe breadth | Keep, move | Integrate into regime KPIs row |
| Sector guidance text | Rewrite | Replace generic text with specific conviction modifier |

### 6.3 Sector Quadrant Card Design

Each sector gets a compact card with:
- Ticker + sector name
- Quadrant badge (Leading/Weakening/Improving/Declining)
- Momentum score (z-score)
- Flow confirmation dot (green = confirmed, grey = not confirmed)
- 5D return vs. SPY

Cards are arranged in a 4-column quadrant grid, not a linear list. This matches the mental model of "where is this sector in its rotation cycle?"

---

## 7. Integration Points with the Agency

### 7.1 Portfolio Manager Circuit Breaker

The market backdrop output feeds directly into the existing circuit breaker:

```python
# In circuit_breaker.py — new input alongside weekly/daily P&L:
def evaluate_circuit_breakers(weekly_perf, daily_perf, regime_context, policy):
    if regime_context["regime"] == "RISK_OFF":
        signals.append("MARKET_RISK_OFF")
        new_entries_blocked = True
    if regime_context["vol_regime"] == "HIGH":
        signals.append("MARKET_HIGH_VOLATILITY")
        reduced_sizing_active = True
    ...
```

### 7.2 Stock Selection — Conviction Adjustment

The per-stock context (Output 3) is passed to the selection pipeline. Each candidate's `final_conviction` is adjusted:

```python
# In selection pipeline / risk module:
sector_context = regime_snapshot["per_stock"].get(ticker, {})
conviction_modifier = sector_context.get("conviction_boost", 0.0)
adjusted_conviction = candidate.final_conviction + conviction_modifier
# The bar is effectively raised for headwind sectors, lowered for tailwind sectors.
```

### 7.3 Portfolio Manager Exit Signals

When a position's sector transitions from `ADVANCING` or `TOPPING` to `DECLINING`, the portfolio manager adds `SECTOR_HEADWIND` to the position's secondary signals (not an immediate exit, but a "review before the next cycle" flag).

### 7.4 Pre-Trade Checklist on Cockpit

The cockpit's pre-trade checklist gains one new check:

```
✓ Market regime: Risk On — normal approval path
✓ Vol regime: Calm — normal position sizing
⚠ XLE sector declining — 2 positions in headwind sector (XOM, CVX)
```

---

## 8. Data Source Analysis

The redesigned agent uses three data sources in a defined priority and cadence hierarchy. Massive replaces yfinance as the primary market data provider — it is already integrated, has no API rate cap, provides richer intraday data, and is available for all ETFs and equities needed.

---

### 8.1 Massive (Polygon.io) — Primary Market Data

**Why Massive is primary, not yfinance:**
- No rate cap (user has paid subscription) — yfinance is capped at ~500 requests/hour, making hourly intraday refreshes across 15+ ETFs impractical
- 15-minute delayed data (vs. yfinance's end-of-day only for free tier)
- Consistent API structure already wired into the codebase (`massive_daily.py`, `massive_grouped_daily.py`, `massive.py`)
- Provides intraday bars (minute/hour), pre-market bars, and snapshots — yfinance does not reliably provide these

**Polygon.io endpoints used by the agent:**

| Endpoint | What it provides | When used |
|---|---|---|
| `/v2/aggs/ticker/{etf}/range/1/day/{start}/{end}` | Daily OHLCV for individual ETFs (SPY, QQQ, sector ETFs, TLT, GLD, UUP) | Pre-market + post-market regime calculation |
| `/v2/aggs/ticker/{etf}/range/1/hour/{date}/{date}` | Hourly intraday bars for sector ETFs | Intraday drift refresh (every 60 min) |
| `/v2/aggs/ticker/{etf}/range/5/minute/{date}/{date}?extended=true` | Pre-market bars (04:00–09:30) | Pre-market regime analysis |
| `/v2/aggs/grouped/locale/us/market/stocks/{date}` | ALL US stocks OHLCV in one call | Full-market breadth calculation (advancers/decliners) |
| `/v2/snapshot/locale/us/markets/stocks/tickers?tickers=SPY,QQQ,XLK,...` | Real-time current price + change for a list of tickers | Intraday quick refresh (instant, no bars needed) |
| `/v2/aggs/ticker/{etf}/prev` | Previous session's close | Pre-market context (previous day's close vs. current pre-market) |
| `/v1/marketstatus/now` | Is the market open / pre-market / closed | Controls which refresh mode runs |

**What Massive enables that the current implementation cannot do:**

1. **True full-market breadth** — the grouped daily endpoint returns ALL US equities in one call. The current implementation only measures breadth within the S&P 100 + QQQ universe (~168 tickers). With grouped daily, breadth covers the full US market (8,000+ tickers), giving a much more accurate advance-decline picture.

2. **Pre-market sector direction** — 5-minute pre-market bars for sector ETFs show whether sectors are gapping up or down before the open. This is the most actionable signal for the pre-market regime run.

3. **Intraday sector snapshots** — the snapshot endpoint returns current prices for all listed tickers instantly, with no computation needed. The hourly intraday drift refresh becomes a single HTTP call rather than multiple parquet reads.

4. **Volume-based signals on sector ETFs** — OHLCV bars include volume, enabling CMF and OBV computation on sector ETFs without pulling individual trade prints. This replaces the need to run the full stock_trades pipeline for sector flow confirmation.

**Data already in the pipeline that this agent reuses:**
- `prices_daily` parquet (from `massive_daily.py`) — already used for 60–100 day historical returns in current implementation. No change needed.
- `stock_trades` parquet — the existing buy/sell pressure and market flow lanes remain unchanged. The regime agent does NOT read trade prints directly.

---

### 8.2 FRED API — Macro Context Layer

FRED provides economic time series that cannot be derived from price data alone. For a 2–5 day holding system, the most relevant series are those that update daily and signal shifts in the macro risk environment.

**FRED series used by the agent:**

| Series ID | Name | Frequency | What it tells you |
|---|---|---|---|
| `VIXCLS` | CBOE Volatility Index | Daily | Fear gauge. > 25 = elevated, > 35 = high. Better than ^VIX from yfinance (official source). |
| `T10Y2Y` | 10-Year minus 2-Year Treasury Spread | Daily | Yield curve. < 0 = inverted = historical recession precursor + risk-off signal. |
| `BAMLH0A0HYM2` | ICE BofA HY Option-Adjusted Spread | Daily | Credit spread. Widening = institutional risk-off. Rising fast = equity headwind. |
| `DGS10` | 10-Year Treasury Constant Maturity Rate | Daily | Rate level. Rising fast (>20 bps/week) = equity valuation headwind. |
| `DFF` | Effective Federal Funds Rate | Daily | Rate regime context (not a timing signal, but affects sector rotation). |

**FRED macro regime rules:**

| Condition | Signal | Effect on regime |
|---|---|---|
| VIXCLS > 35 | High fear | `vol_regime = HIGH` → reduces position sizing |
| VIXCLS 25–35 | Elevated fear | `vol_regime = ELEVATED` → tighten stops |
| VIXCLS < 20 | Calm | `vol_regime = CALM` → normal sizing |
| T10Y2Y < 0 | Inverted yield curve | `macro_tilt = DEFENSIVE` (strong signal) |
| BAMLH0A0HYM2` rising > 50 bps in 5 days | Credit stress | `macro_tilt = DEFENSIVE` |
| DGS10 rising > 20 bps in 5 days | Rate spike | Raise conviction floor by +0.05 |
| All three neutral | Normal | `macro_tilt = NEUTRAL` |
| T10Y2Y > 1 AND BAMLH0A0HYM2 falling | Risk appetite | `macro_tilt = RISK_APPETITE` |

**FRED data cadence:**
- FRED updates most daily series by ~16:00 ET
- The post-market regime refresh reads the latest FRED values
- FRED data is cached locally for 24 hours — no repeated API calls during market hours
- A FRED connection failure does NOT block the regime calculation — macro tilt defaults to `NEUTRAL` if FRED is unavailable

**What FRED adds over free ETF proxies (TLT, GLD, UUP):**
- `T10Y2Y` is the actual yield curve spread, not TLT's price (which reflects duration + credit + supply)
- `BAMLH0A0HYM2` is actual credit spreads — there is no ETF proxy that captures this cleanly
- `VIXCLS` is the official VIX from CBOE, not ^VIX from yfinance (which can lag)

**Free ETF proxies (TLT, GLD, UUP) are STILL USED** alongside FRED for intraday context:
- During market hours (when FRED data hasn't updated yet), TLT/GLD/UUP intraday moves provide real-time macro tilt signals
- FRED provides the baseline; ETF intraday moves update against that baseline

---

### 8.3 yfinance — Fallback Only

yfinance is kept as a fallback for:
1. Historical data backfill when Massive parquet data is missing for a specific ETF date
2. Development/testing environments without a Massive API key

**yfinance is NOT the primary source for any market regime calculation** in the redesigned system. Every endpoint previously served by yfinance is replaced by a Massive equivalent.

---

### 8.4 Data Source Priority Matrix

| Data needed | Primary | Fallback | Not available |
|---|---|---|---|
| Daily ETF bars (SPY, sector ETFs) | Massive daily aggs | yfinance | — |
| Intraday ETF bars (hourly) | Massive intraday aggs | yfinance 1h | — |
| Pre-market ETF bars | Massive extended-hours aggs | — | yfinance (unreliable) |
| Full-market breadth (all US stocks) | Massive grouped daily | — | yfinance (no bulk endpoint) |
| Current intraday price snapshot | Massive snapshot endpoint | yfinance latest | — |
| VIX level | FRED VIXCLS | ^VIX via yfinance | — |
| Yield curve spread | FRED T10Y2Y | Compute TLT - SHY spread (approximate) | — |
| Credit spreads | FRED BAMLH0A0HYM2 | — | No free equivalent |
| 10Y rate direction | FRED DGS10 | TLT inverse (approximate) | — |
| Macro tilt proxies (bonds/gold/dollar) | TLT/GLD/UUP via Massive | yfinance | — |

---

## 9. Audit Findings Summary

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| F1 | 20D return used as primary regime signal — wrong cadence for 2-5 day holds | High | Shift to 5D primary, 20D confirmation |
| F2 | Zero integration with portfolio manager, risk, or selection pipeline | Critical | Wire Output 1 into circuit breakers, Output 3 into conviction adjustments |
| F3 | No volatility regime | High | Add SPY 10D realized vol as vol regime indicator |
| F4 | No macro tilt | Medium | Add TLT/GLD/UUP 5D returns as free proxies |
| F5 | No stock-to-sector mapping | High | Build `ticker-sector-map.json` lookup + per-stock context output |
| F6 | No regime change detection | Medium | Persist prior state, diff on each run, flag transitions |
| F7 | Sector cards are linear list — hard to scan | Medium | Replace with 4-quadrant RRG-inspired layout |
| F8 | Intraday regime not tracked during market hours | Medium | Add 30-min lightweight sector drift refresh |
| F9 | Sector guidance is generic text, not actionable modifier | Medium | Replace with concrete conviction_modifier values |
| F10 | Dashboard has nav buttons unrelated to page function | Low | Remove, keep regime-specific actions only |
| F11 | Data quality panel is always visible | Low | Move to collapsible `<details>` |
| F12 | yfinance used as primary data source — rate-capped, no intraday, no pre-market | High | Replace with Massive (Polygon.io) as primary; yfinance as fallback only |
| F13 | Breadth computed only over S&P 100 + QQQ universe (~168 tickers) | Medium | Use Massive grouped daily for full US market breadth (8,000+ tickers) |
| F14 | No pre-market regime signal before market open | High | Add pre-market sector bar analysis via Massive extended-hours endpoint |
| F15 | No macro context (yield curve, credit spreads, VIX level) | High | Add FRED: VIXCLS, T10Y2Y, BAMLH0A0HYM2, DGS10 |

---

## 10. Open Design Decisions

**Answered:**
- ✅ Q1 — Intraday refresh: **automatic every 60 min + manual button**
- ✅ Q2 — Macro tilt: **FRED API + Massive ETF proxies + yfinance as fallback**. Massive is the primary market data provider (no rate cap).

**Still open:**

**Q3 — Sector flow confirmation: include in v1 or defer?**
CMF + OBV on sector ETF daily bars (from existing Massive parquet) adds flow validation to the sector state machine. This is ~50 lines of code and requires no new data. Include it in the initial build, or start with price-momentum only and add flow in a second iteration?

**Q4 — Portfolio context panel: live broker positions or selection reports?**
The "Your portfolio context" section mapping open positions to their sector state can pull from (a) the live Alpaca broker adapter (authoritative, requires broker connected) or (b) the latest approved selection reports (works offline). Which source?
