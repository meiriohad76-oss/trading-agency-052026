# Fundamentals Analysis Agent — Full Audit & Gap Analysis

**Date:** 2026-05-30
**Auditor:** Claude Code (analysis session)
**Scope:** `research/src/signals/fundamentals.py`, `research/src/sec/company_facts_parser.py`,
`research/src/pit/sec_views.py`, `src/agency/runtime/signal_evidence.py`, `signals.html` display,
plus data-source research across Massive/Polygon, yfinance, FMP, and EDGAR.

---

## Executive Summary

The fundamentals lane uses the **highest lane weight (1.2) of any signal** yet is built on the
narrowest factor set (3 ratios from a single point-in-time snapshot). It has a silent period-mismatch
bug that can invert the sign of `net_margin`, stores 7+ years of quarterly data but discards all
history after loading, misses the forward-looking data most operators actually use to make decisions,
and displays computed scores with no colour, no period context, and no universe calibration.

This audit covers:
- Two critical correctness bugs that need fixing before the lane scores are trustworthy
- 30+ missing indicators grouped by category, each mapped to a concrete data source
- Full data-source availability matrix across Massive, yfinance, FMP, and EDGAR
- Evidence display and dashboard UX gaps
- A recommended architecture for a fully-featured fundamentals signal

---

## 1. Current Architecture

### 1.1 Data Source

**SEC EDGAR Company Facts API** (`https://data.sec.gov/api/xbrl/companyfacts/{CIK}.json`)
Free public API. Pulled by `research/scripts/pull_sec_company_facts.py`.
Stored as PIT-safe Parquet under `research/data/parquet/sec_company_facts/`.
Refresh cadence: 7-day max age by default (`sec_company_facts_max_age_days = 7`).

**XBRL metrics currently extracted** (`research/src/sec/company_facts_parser.py`):

| Stored metric | XBRL tags | Form types |
|---|---|---|
| `revenue` | Revenues, RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet | 10-K, 10-Q |
| `net_income` | NetIncomeLoss | 10-K, 10-Q |
| `operating_cash_flow` | NetCashProvidedByUsedInOperatingActivities | 10-K, 10-Q |
| `capital_expenditures` | PaymentsToAcquirePropertyPlantAndEquipment | 10-K, 10-Q |
| `free_cash_flow` | **Derived**: operating_cash_flow − capex (same accession number required) | 10-K, 10-Q |
| `total_assets` | Assets | 10-K, 10-Q |
| `total_liabilities` | Liabilities | 10-K, 10-Q |
| `shares_outstanding` | EntityCommonStockSharesOutstanding | 10-K, 10-Q, 8-K |

`shares_outstanding` is **pulled and stored but never used** in scoring or display.

### 1.2 PIT Loading

`PITLoader.fundamentals(ticker, as_of)` in `research/src/pit/loader.py` filters the Parquet to
records where `timestamp_as_of <= as_of`, then hands the ticker's frame to `fundamentals_from_frame()`
in `research/src/pit/sec_views.py`.

`fundamentals_from_frame()` builds the payload by keeping **the latest row per metric**:
```python
latest_by_metric.setdefault(str(row["metric"]), row)   # sec_views.py:27
```
This discards the entire historical time series. A ticker with 30 quarters of `revenue` data in the
Parquet produces a single revenue figure at the signal boundary.

### 1.3 Scoring — `fundamental_factor_frame()`

Three factors, equal weight in the composite (`research/src/signals/fundamentals.py`):

| Factor | Formula | Direction |
|---|---|---|
| `net_margin` | net_income / revenue | Higher = better |
| `fcf_margin` | free_cash_flow / revenue | Higher = better |
| `inverse_leverage` | −(total_liabilities / total_assets) | Higher = better (less debt) |

Each factor is **cross-sectionally z-scored** across the active universe (minimum 2 tickers).
Composite = mean of three z-scores.

**Lane weight: 1.2** — the highest of any lane in the system
(technical_analysis: 0.65, insider: 0.9, news: 0.6, all market-flow lanes: 0.4–0.5).

### 1.4 Lane Configuration

| Parameter | Value |
|---|---|
| Dataset | `sec_company_facts` |
| Source | `sec-company-facts` |
| Source tier | `OFFICIAL_FILING` |
| Verification | `CONFIRMED` |
| Freshness domain | `SEC_FUNDAMENTALS` |
| Confidence | 0.8 (default — not explicitly set in `LANE_CONFIGS`) |
| Lane weight | 1.2 |
| Max data age | 7 days |

---

## 2. Critical Defects (Fix Before Trusting Scores)

### Defect 1 — Period Mismatch in Ratio Computation

**File:** `research/src/pit/sec_views.py:27`

`fundamentals_from_frame()` picks the latest filing row per metric independently. There is no
guarantee that `net_income` and `revenue` come from the same period or even the same filing form.
If `net_income` was last updated by a 10-Q (3-month figure, e.g., Q3) and `revenue` was last updated
by a 10-K (12-month figure), then:

```
net_margin = 3-month net_income / 12-month revenue ≈ 0.25 × true_margin
```

The resulting `net_margin` would be approximately ¼ of the true annual margin. After z-scoring this
against other tickers' correctly-matched periods, the score is wrong in direction and magnitude.

**Fix direction:** Before computing ratios, filter to a single consistent period.
Prefer the latest 10-Q period; fall back to 10-K if no 10-Q is available.
The `form` and `period_end` columns are stored in Parquet — use them.

---

### Defect 2 — No Unit Validation

**File:** `research/src/pit/sec_views.py:15–33`

The Parquet stores a `unit` column (USD, shares, EUR, USD/shares) but
`fundamentals_from_frame()` drops it and reads raw `value` directly. Some companies file certain
metrics in thousands of USD, others in full USD. A company that files `total_assets` in thousands
would produce a leverage ratio of `liabilities_USD / assets_thousand_USD = 1000× actual leverage`.

**Fix direction:** After selecting the latest row per metric, assert that all monetary metrics share
the same `unit` (or normalise to USD), and reject rows whose `unit` does not match expectations.

---

### Defect 3 — FCF Silently Missing for Financial Firms

**File:** `research/src/sec/company_facts_parser.py:151–170`

FCF is derived by joining `operating_cash_flow` and `capital_expenditures` on the **same
accession number**. Financial institutions (banks, insurance, REITs) frequently do not report
`PaymentsToAcquirePropertyPlantAndEquipment` because they have no significant PP&E. For these
tickers, no FCF row is produced and the composite score is computed from only two factors
(net_margin + inverse_leverage) rather than three — without any flag that a component is missing.

**Fix direction:** When FCF is absent, note it in the evidence payload and set FCF weight to 0
in the composite rather than silently computing a 2-factor average.

---

## 3. Indicator Gaps

The user requested: current vs. forward P/E, PEG, PEGY, revenue growth trend (QoQ/YoY), margin
growth trend (QoQ/YoY), cash flow trend (QoQ/YoY), R&D spending trend (QoQ/YoY), profit growth
rate trend (QoQ/YoY), sales growth (QoQ/YoY), EPS (QoQ/YoY), EPS consistency (each Q vs. prior year's Q).

Below is the complete indicator map, including the user's list and additional critical factors,
organised by category.

---

### 3.1 Growth Trends — Can Be Built from Existing EDGAR Data

The Parquet already stores all historical filings. The scoring code currently discards history after
`latest_by_metric`. If the scoring layer is updated to retain 5+ quarters, all of the following
can be computed from the existing data with **zero new data sources**.

| Indicator | Formula | XBRL field needed | Already stored? |
|---|---|---|---|
| Revenue growth QoQ | (rev_Q / rev_Q-1) − 1 | `revenue` | ✅ |
| Revenue growth YoY | (rev_Q / rev_Q-4) − 1 | `revenue` | ✅ |
| Revenue growth acceleration | Δ(YoY_growth): is the growth rate itself increasing? | `revenue` | ✅ |
| Gross margin level | gross_profit / revenue | **`gross_profit`** — not currently parsed | ❌ |
| Gross margin trend QoQ/YoY | Δ(gross_margin) | **`gross_profit`** | ❌ |
| Operating margin level | operating_income / revenue | **`operating_income`** | ❌ |
| Operating margin trend QoQ/YoY | Δ(operating_margin) | **`operating_income`** | ❌ |
| Net margin trend QoQ/YoY | Δ(net_margin) | `net_income`, `revenue` | ✅ |
| EBITDA level | — | **`ebitda`** or calculate from operating_income + D&A | ❌ |
| EBITDA margin | ebitda / revenue | **`ebitda`** | ❌ |
| FCF trend QoQ/YoY | Δ(free_cash_flow) | `operating_cash_flow`, `capital_expenditures` | ✅ |
| FCF margin trend | Δ(fcf_margin) | `free_cash_flow`, `revenue` | ✅ |
| Net income trend QoQ/YoY | Δ(net_income) | `net_income` | ✅ |
| Profit growth rate | (ni_Q / ni_Q-1) − 1 | `net_income` | ✅ |
| R&D spending level | r_and_d / revenue | **`research_and_development`** | ❌ |
| R&D spending trend QoQ/YoY | Δ(r_and_d/revenue) | **`research_and_development`** | ❌ |
| EPS basic | net_income / shares_outstanding | `net_income`, `shares_outstanding` | ✅ (calc) |
| EPS diluted | — | **`diluted_eps`** via NetIncomeLossAvailableToCommonStockholdersDiluted / diluted_shares | ❌ |
| EPS trend QoQ/YoY | Δ(EPS) | same as above | partial |
| EPS consistency | σ(EPS_Q vs EPS_Q-4 across 8 quarters) | EPS time series | partial |

**XBRL tags to add to `METRIC_TAGS` in `company_facts_parser.py`** (all free from EDGAR):

```python
"gross_profit":         ("GrossProfit",),
"operating_income":     ("OperatingIncomeLoss",),
"ebitda":              ("EarningsBeforeInterestTaxesDepreciationAndAmortization",),
"depreciation_amortization": ("DepreciationAndAmortization", "DepreciationDepletionAndAmortization"),
"research_development": ("ResearchAndDevelopmentExpense",),
"interest_expense":     ("InterestExpense", "InterestAndDebtExpense"),
"diluted_eps":          ("EarningsPerShareDiluted",),
"diluted_shares":       ("WeightedAverageNumberOfDilutedSharesOutstanding",),
"current_assets":       ("AssetsCurrent",),
"current_liabilities":  ("LiabilitiesCurrent",),
"long_term_debt":       ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligation"),
"retained_earnings":    ("RetainedEarningsAccumulatedDeficit",),
"total_equity":         ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
```

These additions require:
- One change to `company_facts_parser.py` — add to `METRIC_TAGS`
- A new pull cycle to backfill the Parquet with the new tags
- Scoring code to compute and z-score the new factors

**No new data subscriptions required.**

---

### 3.2 Valuation Ratios — Require Market Price + Financial Data

These require combining market price (already available in the PIT price data) with financial metrics.

| Indicator | Formula | Source | Notes |
|---|---|---|---|
| Trailing P/E | price / EPS_TTM | Price (existing) + EPS from EDGAR | EPS_TTM = sum of 4 quarters |
| Forward P/E | price / forward_EPS_consensus | Price + **analyst estimate** | See §4 |
| P/S ratio | market_cap / revenue_TTM | Price + EDGAR | market_cap = price × shares_outstanding |
| P/B ratio | market_cap / book_value | Price + EDGAR (equity) | book_value = total_equity |
| EV/EBITDA | enterprise_value / EBITDA | Price + EDGAR | EV = market_cap + net_debt |
| EV/Revenue | enterprise_value / revenue_TTM | Price + EDGAR | |
| FCF yield | FCF_TTM / market_cap | EDGAR (FCF) + price | high yield = cheap |
| Earnings yield | EPS_TTM / price | EDGAR + price | inverse of P/E |
| Net debt / EBITDA | (total_debt − cash) / EBITDA | EDGAR | need `cash_and_equivalents`, `long_term_debt` |

Most of these can be **computed entirely from data already available** (EDGAR + price) once the
XBRL parser additions in §3.1 are in place. No new external subscription is strictly required for
trailing valuations.

---

### 3.3 Forward-Looking & Consensus Data — Require External Source

This is the most critical gap. The entire column of "what the market expects" is absent from the
current fundamentals model. These are the indicators that determine whether a stock is "cheap vs.
expectations" rather than just cheap vs. history.

| Indicator | Description | Best Free Source | Paid Source |
|---|---|---|---|
| Forward P/E | price / forward_EPS_consensus | yfinance `.info["forwardPE"]` | Massive Benzinga add-on |
| Forward EPS estimate | Consensus EPS for current & next FY | yfinance `earnings_estimate` | FMP `analyst-estimates` |
| Forward revenue estimate | Consensus revenue for current & next FY | yfinance `revenue_estimate` | FMP `analyst-estimates` |
| EPS surprise | Actual EPS vs. consensus at report | FMP `earnings-surprises` (250/day free) | Massive Benzinga `earnings` |
| EPS revision trend | Is consensus going up or down? | yfinance `eps_trend` | FMP (paid) |
| EPS estimate upward/downward revisions | Count of analyst upgrades vs. downgrades | yfinance `eps_revisions` | — |
| Revenue surprise | Actual revenue vs. consensus at report | FMP free | Massive Benzinga |
| Analyst price target | Mean/median/high/low target price | yfinance `analyst_price_targets` | FMP `price-target` |
| Number of analysts | Analyst coverage count | yfinance `.info["numberOfAnalystOpinions"]` | FMP |
| Buy/hold/sell ratings | Analyst rating breakdown | yfinance `recommendations` | FMP `analyst-recommendations` |
| PEG ratio | P/E / forward_EPS_growth_rate | FMP `ratios` (free) | — |
| PEGY ratio | P/E / (EPS_growth + dividend_yield) | Calculated from above | — |
| Historical P/E time series | P/E ratio over trailing years | FMP (5 years free, 30 years paid) | — |
| Earnings calendar | When is the next earnings report? | yfinance `earnings_dates` | FMP (paid) |

---

### 3.4 Additional Critical Indicators Not in User's List

These are standard quantitative factor research indicators that should be in a professional
fundamentals model.

| Indicator | Category | Why It Matters | Source |
|---|---|---|---|
| **Return on Equity (ROE)** | Profitability | Buffett/Munger quality metric | EDGAR (net_income / equity) |
| **Return on Invested Capital (ROIC)** | Profitability | Best single indicator of capital allocation quality | EDGAR (NOPAT / invested_capital) |
| **Return on Assets (ROA)** | Profitability | Efficiency across capital structures | EDGAR (net_income / total_assets) |
| **Current ratio** | Liquidity | Short-term financial health | EDGAR (current_assets / current_liabilities) |
| **Quick ratio** | Liquidity | More conservative than current ratio | EDGAR (cash + receivables) / current_liab |
| **Net debt** | Leverage | Cash-adjusted debt position | EDGAR (long_term_debt − cash) |
| **Debt/Equity** | Leverage | Capital structure risk | EDGAR |
| **Accruals ratio (Sloan)** | Earnings quality | (net_income − operating_CF) / assets; high = risk of earnings manipulation | EDGAR |
| **FCF / Net income** | Earnings quality | How much of stated profit is real cash? High = high quality | EDGAR |
| **Gross margin** | Pricing power | Apple has 44%; commodity firms have 5% | EDGAR (need gross_profit tag) |
| **Operating leverage** | Cost structure | % change in operating income vs. % change in revenue | EDGAR |
| **Revenue beat rate** | Consensus accuracy | How consistently does this company beat revenue estimates? | FMP earnings-surprises (historical) |
| **EPS beat rate** | Consensus accuracy | Same for EPS | FMP earnings-surprises |
| **Guidance beat rate** | Management credibility | Does management guide conservatively? | FMP corporate-guidance |
| **Dilution rate** | Shareholder returns | YoY change in diluted_shares outstanding | EDGAR |
| **Book value per share growth** | Asset accumulation | YoY growth in book_value / shares | EDGAR |
| **Enterprise value** | Valuation basis | market_cap + net_debt — used for EV multiples | Price + EDGAR |
| **Free cash flow yield** | Valuation | FCF / market_cap — Warren Buffett's preferred metric | Price + EDGAR |
| **Piotroski F-Score** | Multi-factor quality | 9-point profitability/leverage/efficiency composite | EDGAR |
| **Altman Z-Score** | Distress risk | Bankruptcy predictor; catches deteriorating balance sheets | EDGAR |

---

## 4. Data Source Decision Matrix

### 4.1 What Massive (Polygon.io) Now Provides

Since the audit started, Polygon has rebranded to "Massive" and now offers financial statement
endpoints. These are on the **Advanced plan ($199/mo)** — not on the current plan.

| Massive endpoint | Fields | Added value vs. existing SEC EDGAR |
|---|---|---|
| `/stocks/financials/v1/income-statements` | revenue, gross_profit, R&D, operating_income, EBITDA, net_income, diluted_EPS, diluted_shares | Better normalisation; period/form tagging included |
| `/stocks/financials/v1/cash-flow-statements` | operating CF, capex, investing CF, financing CF, dividends, change in cash | Pre-tagged by period/form |
| `/stocks/financials/v1/balance-sheets` | total_assets, total_liabilities, equity, cash, total_debt, current_assets/liabilities | Balance sheet with current ratio components |
| `/stocks/financials/v1/ratios` | trailing P/E, P/S, P/B, EV/EBITDA, ROE, ROA, current_ratio, debt-to-equity | Pre-calculated ratios |
| `/partners/benzinga/earnings` | actual_EPS, estimated_EPS, surprise, surprise_pct, actual_revenue, estimated_revenue | **Additive**: true earnings surprise vs. consensus |
| `/partners/benzinga/corporate-guidance` | projected EPS/revenue ranges from company guidance | **Additive**: management guidance history |

**Verdict on Massive financials:** Mostly replicates EDGAR data we already have, better normalised.
The **only additive value at $199/mo** is the Benzinga earnings surprise data and pre-calculated ratios.
FMP achieves the same earnings surprise coverage for free (250 req/day).

### 4.2 yfinance — Free, Already In Codebase

yfinance is already used for prices and options (`pull_yfinance_daily.py`, `pull_yfinance_options.py`).
Adding fundamentals is a natural extension with **zero new dependencies**.

| yfinance attribute | Provides | Caveats |
|---|---|---|
| `.info["forwardPE"]` | Forward P/E snapshot | Point-in-time only; Yahoo's calculation |
| `.info["trailingPE"]` | Trailing P/E | Same as above |
| `.info["forwardEps"]` | Forward EPS (consensus) | |
| `.info["trailingEps"]` | Trailing EPS | |
| `.info["pegRatio"]` | PEG ratio | **Currently broken** since June 2025 (issue #2570) |
| `.info["targetMeanPrice"]` | Analyst mean price target | |
| `.info["targetMedianPrice"]` | Analyst median price target | |
| `.info["numberOfAnalystOpinions"]` | Analyst coverage count | |
| `.info["revenueGrowth"]` | YoY revenue growth (TTM) | Single value |
| `.info["earningsGrowth"]` | YoY EPS growth | Single value |
| `.info["operatingMargins"]` | Operating margin (TTM) | |
| `.info["profitMargins"]` | Net margin (TTM) | |
| `.info["returnOnEquity"]` | ROE (TTM) | |
| `.info["returnOnAssets"]` | ROA (TTM) | |
| `.earnings_estimate` | Forward EPS by period (current Q, next Q, FY, next FY) | Best free source for forward estimates |
| `.revenue_estimate` | Forward revenue by period | |
| `.eps_trend` | EPS estimate revisions (current vs. 7/30/60/90 days ago) | Analyst momentum signal |
| `.eps_revisions` | Count of upward/downward EPS revisions | |
| `.analyst_price_targets` | full stats on analyst targets | |
| `.earnings_history` | Historical EPS actual vs. estimated + surprise | 4-5 quarters deep |
| `.quarterly_income_stmt` | Last 4-5 quarters, normalised | 4–5 quarter limit; same source as EDGAR |

**Rate limits:** No official limit; de facto ~2,000 requests/hour before throttling.
With 100 universe tickers, a daily `.info` refresh = 100 req; fine.

**Risk:** Unofficial API. Yahoo can break it without notice. Has broken multiple times.
Use only for forward-looking data that has no official alternative.

### 4.3 FMP Free Tier — Best Free Source for Consensus & Surprises

250 requests/day. No API key required for registration tier (free tier requires sign-up, but is free).
5 years historical depth; 5 quarters of quarterly history.

| FMP endpoint | Provides | req/call |
|---|---|---|
| `/earnings-surprises/{symbol}` | Actual EPS vs. consensus at each report; surprise amount and % | 1 |
| `/analyst-estimates/{symbol}` | Forward EPS low/avg/high + revenue estimates + analyst counts | 1 |
| `/ratios/{symbol}?period=quarter` | Historical quarterly P/E, P/S, P/B, EV/EBITDA, PEG, ROE, ROA | 1 |
| `/price-target/{symbol}` | Analyst price target: mean, median, low, high, count | 1 |
| `/analyst-stock-recommendations/{symbol}` | Strong buy/buy/hold/sell/strong sell counts | 1 |
| `/historical/earning_calendar/{symbol}` | Past earnings dates and results | 1 (paid for future) |
| `/income-statement/{symbol}?period=quarter` | 5 years quarterly; same EDGAR data, normalised | 1 |

**Usage budget:** 100 universe tickers × 3 endpoints = 300 req/day. Just over the free limit.
For 60–80 tickers: fits in 250/day easily.

**Verdict:** FMP free tier is the best available source for:
- Historical P/E, PEG ratio time series (5 years)
- Earnings surprises (actual vs. consensus) going back many years
- Forward consensus estimates (EPS + revenue) with low/high ranges

### 4.4 EDGAR — Underutilised Historical Depth

The Parquet already stores **all historical XBRL filings** filed since ~2009 for covered tickers.
The current scoring uses only 1 data point per metric. If `fundamentals_from_frame()` is changed
to return a time series (multiple period rows per metric), the scoring layer can compute all the
QoQ/YoY trends in §3.1 with zero additional API calls.

EDGAR history depth: 7+ years (limited by when the pull scripts have been running). Full EDGAR
history goes back to 2009 for most large caps.

---

## 5. Recommended Additional XBRL Tags

Add these 14 metrics to `METRIC_TAGS` in `company_facts_parser.py`. They are free from EDGAR
and unlock most of the §3.1 indicators immediately.

```python
METRIC_TAGS = {
    # ... existing tags ...

    # Income statement additions
    "gross_profit":               ("GrossProfit",),
    "operating_income":           ("OperatingIncomeLoss",),
    "ebitda": (
        "EarningsBeforeInterestTaxesDepreciationAndAmortization",
        "OperatingIncomeLoss",   # fallback; add DA separately
    ),
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ),
    "research_development":       ("ResearchAndDevelopmentExpense",),
    "interest_expense":           ("InterestExpense", "InterestAndDebtExpense"),
    "income_tax_expense":         ("IncomeTaxExpense",),
    "diluted_eps":                ("EarningsPerShareDiluted",),
    "diluted_shares":             ("WeightedAverageNumberOfDilutedSharesOutstanding",),

    # Balance sheet additions
    "current_assets":             ("AssetsCurrent",),
    "current_liabilities":        ("LiabilitiesCurrent",),
    "long_term_debt": (
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligation",
    ),
    "cash_and_equivalents":       ("CashAndCashEquivalentsAtCarryingValue", "Cash"),
    "total_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
}
```

---

## 6. Revised Scoring Architecture

### Current (3-factor single-period)
```
composite = z(net_margin) + z(fcf_margin) + z(-leverage) / 3
```

### Recommended (multi-factor, multi-period, category-weighted)

```
quality_score   = z(gross_margin_ttm)
                + z(operating_margin_ttm)
                + z(roe_ttm)
                + z(fcf_yield)
                + z(fcf_income_ratio)    # FCF quality

growth_score    = z(revenue_growth_yoy)
                + z(eps_growth_yoy)
                + z(fcf_growth_yoy)
                + z(revenue_beat_rate)   # from FMP earnings-surprises
                + z(earnings_beat_rate)  # same source

value_score     = z(-trailing_pe)       # low P/E = good
                + z(-ev_ebitda)
                + z(fcf_yield)
                + z(-peg_ratio)          # from FMP ratios

momentum_score  = z(eps_revision_trend)  # from yfinance eps_trend
                + z(analyst_upside_pct)  # from yfinance/FMP price targets

composite = 0.35 × quality_score
          + 0.30 × growth_score
          + 0.25 × value_score
          + 0.10 × momentum_score
```

Each sub-score is independently z-scored before weighting.
Tickers missing a component (e.g., no analyst coverage) get component weight redistributed to
the present components — never silently dropped to 0.

---

## 7. Evidence Display & UX Gaps

### 7.1 Signal Inspect Panel (`_fundamentals_evidence()`)

Current 4-card layout:

| Card | Current | Gap |
|---|---|---|
| Net margin | Shows value | **Tone is always "neutral"** regardless of value |
| FCF margin | Shows value | **Same** |
| Leverage | Shows value | **Same** |
| Composite score | Shows +/−N.NN | **No colour; no indication of direction is good/bad** |

Additional missing cards:
- **Filing period** — operator cannot see whether this is Q3 2025 or FY 2024 data
- **Form type** — 10-K vs. 10-Q is stored in Parquet but not surfaced
- **Revenue (absolute)** — $500M revenue company vs. $500B company look identical in ratios
- **Universe context** — "+0.45 composite" means nothing without "vs. 87 peers, range −2.1 to +2.3"
- **Period consistency warning** — when period mismatch is detected (Defect 1), show a "⚠ period mismatch" card
- **Missing component flag** — when FCF is absent (financial firms), show which factors were excluded

### 7.2 Trigger Headline

Current:
> "AAPL fundamentals score reflects net margin +21.4%, free-cash-flow margin +25.3%, and leverage 85.1%."

Issues:
- Leverage 85.1% for AAPL is technically correct (it has negative book equity) but reads as alarming
- No period mentioned — is this the Q2 2025 10-Q or FY2024 10-K?
- No indication that AAPL's leverage is *better* in context than it looks in isolation

### 7.3 Lane Card (Signals Page)

Current: `dataset: sec_company_facts / source: sec-company-facts`

Issues:
- Machine-readable IDs instead of operator-readable labels
- No filing date or fiscal period shown
- `avg_score: +0.34` — no context for what this z-score means
- `top_ticker: AAPL / score: +0.72 / ...` — score not labelled as z-score

Suggested additions to `_signal_lane_row()`:
- Latest filing period covered (e.g., "Q3 2025")
- Number of tickers with stale data (last filing > 90 days old)
- Data as-of date from the manifest

### 7.4 Command Page Lane Summary

The command page groups fundamentals with insider and institutional as "support lanes".
This is correct categorically. Gap: there is no indicator of when the last 10-K or 10-Q was
filed per ticker, or how many tickers in the active universe have data gaps.

---

## 8. Priority Matrix

### Tier 1 — Fix Defects Before Trusting Scores

| # | Issue | File | Effort |
|---|---|---|---|
| D1 | Period mismatch in ratio computation | `pit/sec_views.py:27` | Medium |
| D2 | Unit validation on monetary metrics | `pit/sec_views.py` | Small |
| D3 | FCF missing flag for financial firms | `signals/fundamentals.py` | Small |

### Tier 2 — Add EDGAR Data at Zero Cost

| # | What | Change | Effort |
|---|---|---|---|
| E1 | Add 14 XBRL tags to parser | `sec/company_facts_parser.py` | Small |
| E2 | Compute QoQ/YoY growth trends in scorer | `signals/fundamentals.py` | Medium |
| E3 | Compute trailing P/E, P/S, P/B, EV/EBITDA in scorer | `signals/fundamentals.py` | Medium |
| E4 | Surface `gross_margin`, `operating_margin` in inspect panel | `runtime/signal_evidence.py` | Small |
| E5 | Add filing period and form type to inspect cards | `runtime/signal_evidence.py` | Small |
| E6 | Fix inspect card tones (green for positive, red for negative) | `runtime/signal_evidence.py` | Small |
| E7 | Surface `shares_outstanding` in scoring (EPS calculation) | `signals/fundamentals.py` | Small |

### Tier 3 — Add yfinance Forward Data (Free, Moderate Reliability Risk)

| # | What | New file | Effort |
|---|---|---|---|
| Y1 | Pull `.info` snapshot per ticker (forward P/E, forward EPS, analyst target) | `research/src/fundamentals/yfinance_snapshot.py` | Medium |
| Y2 | Pull `earnings_estimate` and `revenue_estimate` | same file | Small |
| Y3 | Store as PIT-safe state file (no parquet needed — weekly refresh) | JSON state file | Small |
| Y4 | Add forward_pe, eps_estimate, analyst_target to inspect panel | `signal_evidence.py` | Small |
| Y5 | Add `eps_trend` direction to scoring as momentum sub-factor | `signals/fundamentals.py` | Medium |

### Tier 4 — Add FMP Earnings Surprises & Analyst Estimates (Free, 250 req/day)

| # | What | New file | Effort |
|---|---|---|---|
| F1 | Pull `/earnings-surprises/{symbol}` for universe | `research/src/fundamentals/fmp_earnings.py` | Medium |
| F2 | Pull `/analyst-estimates/{symbol}` for universe | same file | Small |
| F3 | Pull `/ratios/{symbol}?period=quarter` (historical P/E, PEG) | same file | Small |
| F4 | Compute EPS beat rate and revenue beat rate | `signals/fundamentals.py` | Medium |
| F5 | Add historical P/E to inspect panel | `signal_evidence.py` | Small |

### Tier 5 — Architecture (After Tiers 1–4)

| # | What | Effort |
|---|---|---|
| A1 | Split composite into 4 sub-scores (quality/growth/value/momentum) | Large |
| A2 | Weight sub-scores by category (0.35/0.30/0.25/0.10) | Small |
| A3 | Surface sub-scores in inspect panel as separate cards | Medium |
| A4 | Add Piotroski F-Score and Sloan accruals ratio | Medium |
| A5 | Add universe context to inspect panel ("z-score vs N peers") | Small |

---

## 9. Data Source Summary for Decision Making

| Source | Cost | Forward data | Earnings surprises | Hist. P/E | Analyst targets | Risk |
|---|---|---|---|---|---|---|
| **EDGAR (existing)** | Free | ❌ | ❌ | ❌ | ❌ | Low — official API |
| **yfinance** | Free | ✅ excellent | ✅ 4 quarters | ❌ | ✅ full stats | **High — unofficial, can break** |
| **FMP free tier** | Free (250/day) | ✅ with ranges | ✅ deep history | ✅ 5 years | ✅ full stats | Low — official API |
| **Alpha Vantage free** | Free (25/day) | ✅ snapshot only | ✅ snapshot | ❌ | ✅ single value | Low — official API, very rate-limited |
| **FMP paid ($59/mo)** | $59/mo | ✅ 30 yr depth | ✅ 30 yr depth | ✅ 30 years | ✅ | Low |
| **Massive Advanced ($199/mo)** | $199/mo | ❌ (financials only) | ✅ via Benzinga add-on | ❌ | ❌ | Low — already integrated |

**Recommended stack for Tier 3–4 implementation:**
1. **Primary:** FMP free tier for earnings surprises, analyst estimates, historical P/E/PEG
2. **Secondary:** yfinance for forward P/E, analyst targets, EPS revision trends
3. **Fallback:** If yfinance breaks for a metric, FMP usually covers it

---

## 10. PEGY Ratio — Specific Note

The user asked about PEGY (Peter Lynch's Price/Earnings to Growth + Yield):

```
PEGY = P/E / (EPS_growth_rate + Dividend_yield)
```

This requires:
- P/E ratio — computable from price + EPS (EDGAR + existing price data)
- Forward EPS growth rate — yfinance `growth_estimates` or FMP `analyst-estimates`
- Dividend yield — yfinance `.info["dividendYield"]` or calculated from EDGAR dividend payments

PEGY is most useful for dividend-paying value stocks and less relevant for high-growth tech names
(where dividend yield ≈ 0, making PEGY ≈ PEG). The implementation should set PEGY = None when
dividend yield is negligible (<0.5%) rather than implying a false precision advantage over PEG.

---

## Appendix: Files Affected by Each Tier

**Tier 1 (defect fixes):**
- `research/src/pit/sec_views.py` — period-alignment fix
- `research/src/signals/fundamentals.py` — FCF missing flag

**Tier 2 (EDGAR expansion):**
- `research/src/sec/company_facts_parser.py` — add XBRL tags
- `research/src/signals/fundamentals.py` — new factors and trend computation
- `src/agency/runtime/signal_evidence.py` — enriched inspect cards
- `src/agency/views/signals.py` — lane card improvements

**Tier 3 (yfinance forward data):**
- `research/src/fundamentals/` — new module
- `research/scripts/pull_yfinance_fundamentals.py` — new pull script
- `research/src/pit/manifest.py` — new dataset name
- `research/src/pit/loader.py` — new `forward_estimates(ticker, as_of)` method

**Tier 4 (FMP earnings surprises):**
- `research/src/fundamentals/fmp_earnings.py` — new FMP client
- `research/scripts/pull_fmp_earnings.py` — new pull script
- `research/src/sec/company_facts_parser.py` — possibly extend
- `research/src/signals/fundamentals.py` — beat rate factors
