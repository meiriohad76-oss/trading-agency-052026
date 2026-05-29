# Market Regime Agent — Redesign Spec

**Date:** 2026-05-29  
**Author:** Ohad Meiri  
**Status:** Approved for implementation  
**Audit report:** `docs/market-regime-audit-2026-05-29.md`  
**Context:** Part of the agency v3 redesign. Replaces `src/agency/runtime/market_regime.py`.

---

## 1. Purpose

The Market Regime Agent is a **top-down context layer** that runs on a schedule before, during, and after each trading day. It classifies the broad market and sector environment, maps that environment to each open position and candidate stock, and produces machine-readable modifiers that the portfolio manager and selection pipeline use to adjust conviction thresholds and risk sizing.

**It never auto-executes orders. It produces context; humans act on it.**

---

## 2. Scope

**In scope:**
- `src/agency/market_regime/` — new module (5 files)
- `research/state/market_regime/` — state file directory
- `research/config/ticker-sector-map.json` — static ticker → sector mapping
- `src/agency/views/market_regime.py` — updated view (new snapshot format)
- `src/agency/templates/market_regime.html` — redesigned template
- `docs/TOOLTIP_REGISTRY.md` — extended with all new metric tooltips
- `tests/unit/test_market_regime_analyzer.py` — unit tests (pure analyzer)
- `tests/integration/test_market_regime_fetcher.py` — integration tests (fetcher)

**Out of scope:**
- `src/agency/runtime/market_regime.py` — stays untouched until new module is wired
- Signal selection pipeline wiring (separate ticket)
- Portfolio manager circuit breaker wiring (separate ticket)
- Scheduler configuration (separate ticket)

---

## 3. Module Structure

```
src/agency/market_regime/
    __init__.py         Public exports: build_regime_snapshot, RegimePolicy
    policy.py           RegimePolicy dataclass — all thresholds and modifiers
    fetcher.py          HTTP layer: Massive + FRED → state files (no business logic)
    analyzer.py         Pure computation: regime, sectors, flow, per-stock (no I/O)
    snapshot.py         build_regime_snapshot() — wires fetcher + analyzer
    scheduler.py        schedule_regime_refresh() — pre-market/hourly/post-market hooks
```

**State files** — all under `research/state/market_regime/`:

| File | Written by | Contents |
|---|---|---|
| `etf_bars.json` | fetcher | Sector ETF + benchmark 60D daily OHLCV (Massive daily aggs) |
| `intraday_bars.json` | fetcher | Current prices + session change for sector ETFs (Massive `/v2/snapshot/` — returns `todaysChangePerc` and `prevDay.c`) |
| `premarket_bars.json` | fetcher | Pre-market 5-min bars for sector ETFs (Massive extended-hours) |
| `grouped_daily.json` | fetcher | Full US market breadth — all stocks (Massive grouped daily) |
| `macro_fred.json` | fetcher | 7 FRED series — cached 24h |
| `macro_proxies.json` | fetcher | TLT, GLD, UUP 5D bars (Massive daily) |
| `last_regime.json` | snapshot | Prior regime state for change detection |
| `ticker_sector_map.json` | static | Ticker → sector ETF (AAPL → XLK) — committed to repo |

---

## 4. RegimePolicy

```python
@dataclass(frozen=True)
class RegimePolicy:

    # ── Regime classification thresholds ────────────────────────────
    risk_off_spy_5d_pct: float = -1.5          # SPY 5D ≤ this → RISK_OFF
    risk_off_breadth_pct: float = 35.0         # advancers ≤ this % → RISK_OFF
    risk_off_tlt_5d_pct: float = 1.5           # TLT 5D ≥ this → RISK_OFF (flight to bonds)
    risk_on_spy_5d_pct: float = 1.0            # SPY 5D ≥ this (+ other checks) → RISK_ON
    risk_on_qqq_5d_pct: float = 0.0            # QQQ 5D ≥ this
    risk_on_breadth_pct: float = 55.0          # advancers ≥ this %
    risk_on_vol_cap: float = 20.0              # realized vol < this %
    volatile_vol_threshold: float = 25.0       # realized vol ≥ this % + abs(spy_5d) ≥ 2%
    volatile_abs_move_pct: float = 2.0
    rotating_sector_spread: float = 1.5        # z-score spread ≥ this
    rotating_breadth_min: float = 40.0         # breadth in 40–65% range
    rotating_breadth_max: float = 65.0

    # ── FRED macro thresholds ────────────────────────────────────────
    vix_calm: float = 20.0
    vix_elevated: float = 25.0
    vix_high: float = 35.0
    yield_curve_inverted: float = 0.0          # T10Y2Y < 0 = inverted
    credit_spread_stress_delta_bps: float = 50.0   # 5D HY spread widening > 50 bps
    rate_spike_delta_bps: float = 20.0             # 5D DGS10 rise > 20 bps
    macro_risk_appetite_curve: float = 1.0         # T10Y2Y > this + spreads tight

    # ── Sector state thresholds ──────────────────────────────────────
    cmf_positive: float = 0.0           # CMF > 0 = accumulation confirmed
    cmf_negative: float = 0.0           # CMF < 0 = distribution confirmed
    cmf_period: int = 14                # CMF lookback sessions

    # ── Conviction modifiers (applied to final_conviction) ───────────
    risk_on_modifier: float = 0.03
    risk_off_modifier: float = -0.08
    volatile_modifier: float = -0.05
    neutral_modifier: float = 0.0
    rotating_modifier: float = 0.0
    advancing_confirmed_boost: float = 0.03     # sector ADVANCING + flow confirmed
    advancing_unconfirmed_boost: float = 0.01   # sector ADVANCING, no flow confirmation
    declining_confirmed_penalty: float = -0.05  # sector DECLINING + flow bearish
    declining_unconfirmed_penalty: float = -0.02

    # ── Position size modifiers (multiplier on default_position_pct) ─
    calm_size_multiplier: float = 1.0
    elevated_vol_size_multiplier: float = 0.75
    high_vol_size_multiplier: float = 0.50

    # ── Refresh cadence ──────────────────────────────────────────────
    intraday_refresh_interval_minutes: int = 60
    fred_cache_hours: int = 24
    etf_bars_lookback_days: int = 65        # ~60 trading sessions + buffer
```

All fields loadable from env vars (`AGENCY_<UPPER_SNAKE_CASE>`) or `portfolio-policy.local.json`.

---

## 5. Fetcher Layer

### 5.1 Massive API calls

Reuses `MassiveDailyConfig.from_env()` (`MASSIVE_API_KEY` or `POLYGON_API_KEY`).

| Refresh mode | Endpoint | Tickers | Calls |
|---|---|---|---|
| Pre-market | `/v2/aggs/ticker/{etf}/range/1/day/{start}/{end}` | SPY, QQQ, IWM, DIA, 11 sectors, TLT, GLD, UUP | 18 |
| Pre-market | `/v2/aggs/ticker/{etf}/range/5/minute/{date}/{date}?extended=true` | SPY + 11 sectors | 12 |
| Intraday | `/v2/snapshot/locale/us/markets/stocks/tickers?tickers=...` | SPY + 11 sectors | 1 |
| Post-market | `/v2/aggs/ticker/{etf}/range/1/day/{start}/{end}` | Same 18 ETFs | 18 |
| Post-market | `/v2/aggs/grouped/locale/us/market/stocks/{date}` | All US stocks | 1 |
| All modes | `/v1/marketstatus/now` | — | 1 |

### 5.2 FRED API calls

Uses `fredapi` library. `FRED_API_KEY` env var. 7 series, one call each.

| Series ID | Name | Category | Cache TTL |
|---|---|---|---|
| `VIXCLS` | CBOE VIX | — | 24h |
| `T10Y2Y` | 10Y minus 2Y spread | RATES | 24h |
| `DGS10` | 10Y Treasury yield | RATES | 24h |
| `BAMLH0A0HYM2` | HY OAS | CREDIT | 24h |
| `BAMLC0A0CM` | IG OAS | CREDIT | 24h |
| `STLFSI4` | St. Louis Financial Stress Index | CREDIT | 24h |
| `ICSA` | Initial jobless claims | GROWTH | 24h |

### 5.3 Error handling

Every fetch is wrapped individually. Failures are logged and returned in `FetchSummary.issues`. The fetcher **never raises** to the caller.

| Failure | Effect |
|---|---|
| Single ETF Massive call fails | Skip that ETF; confidence degrades |
| FRED unreachable | `macro_fred.json` not updated; `macro_tilt = NEUTRAL`; quality flag set |
| Grouped daily fails | Breadth uses prior cache; quality flag set |
| All Massive fails | All state files unchanged; analyzer uses prior cache with `data_stale = true` |
| State files missing | Analyzer returns `regime = DATA_LIMITED`, `confidence = 0.0` |

### 5.4 yfinance fallback

Used only when Massive returns no data for a specific ETF date (backfill gap). Not used for intraday or pre-market data.

---

## 6. Analyzer Layer (pure functions, no I/O)

### 6.1 Market Backdrop

**Regime classification (first match wins):**

```
RISK_OFF   if spy_5d ≤ -1.5%
              OR advancers_5d ≤ 35%
              OR (yield_curve < 0 AND credit_spread_delta > +50 bps)
              OR tlt_5d ≥ +1.5%

VOLATILE   if spy_vol_10d ≥ 25% annualized AND abs(spy_5d) ≥ 2%

ROTATING   if sector_zscore_spread ≥ 1.5
              AND 40% ≤ advancers_5d ≤ 65%

RISK_ON    if spy_5d ≥ +1.0%
              AND qqq_5d ≥ 0%
              AND advancers_5d ≥ 55%
              AND spy_vol_10d < 20%

NEUTRAL    — everything else
```

**Vol regime (independent):**
- `CALM` — VIX < 20
- `ELEVATED` — VIX 20–35
- `HIGH` — VIX > 35

**Macro tilt (independent):**
- `DEFENSIVE` — yield_curve < 0 OR credit_spread_delta > +50 bps
- `RISK_APPETITE` — yield_curve > 1.0 AND credit_spread_delta < -10 bps AND tlt_5d < 0
- `NEUTRAL` — everything else

### 6.2 Sector State Machine

Per sector ETF, from daily OHLCV bars:

**Step 1 — RRG quadrant:**
```
# prices[-1] = latest close, prices[-21] = close 20 sessions ago
rs_ratio    = sector_return_20d - spy_return_20d

# rs_ratio_5d_ago uses closes from 5 sessions earlier (prices[-6] to prices[-1])
rs_momentum = rs_ratio_today - rs_ratio_5_sessions_ago

ADVANCING (Leading)   — rs_ratio > 0 AND rs_momentum > 0
TOPPING (Weakening)   — rs_ratio > 0 AND rs_momentum ≤ 0
BASING (Improving)    — rs_ratio ≤ 0 AND rs_momentum > 0
DECLINING (Lagging)   — rs_ratio ≤ 0 AND rs_momentum ≤ 0
```

**Step 2 — CMF(14) + OBV trend:**
```python
# CMF(14)
money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
money_flow_volume     = money_flow_multiplier * volume
cmf_14 = sum(money_flow_volume[-14:]) / sum(volume[-14:])

# OBV trend
obv_trend = "UP" if obv_today > obv_5d_ago else "DOWN"

flow_confirmed = cmf_14 > 0 and obv_trend == "UP"
flow_bearish   = cmf_14 < 0 and obv_trend == "DOWN"
```

**Step 3 — Final conviction boost:**

| State | Flow | Bias | Boost |
|---|---|---|---|
| ADVANCING | confirmed | TAILWIND | +0.03 |
| ADVANCING | not confirmed | TAILWIND (soft) | +0.01 |
| TOPPING | any | NEUTRAL | 0.00 |
| BASING | any | NEUTRAL | 0.00 |
| DECLINING | bearish | HEADWIND | -0.05 |
| DECLINING | not bearish | HEADWIND (soft) | -0.02 |

**Sector ranking** — same z-score composite as current implementation (keep — it works):
`score = 0.2 * z5 + 0.5 * z20 + 0.3 * z60` (excess return vs. SPY, z-scored across 11 sectors)

### 6.3 Per-Stock Context

Reads `ticker_sector_map.json`. For each ticker in the active universe:
```python
sector       = ticker_sector_map.get(ticker)
sector_entry = sector_map.get(sector, {})
conviction_boost = sector_entry.get("conviction_boost", 0.0)
bias         = sector_entry.get("bias", "NEUTRAL")
```

### 6.4 Regime Change Detection

Reads `last_regime.json`. Diffs regime key and sector states. Returns:
- `regime_changed: bool`
- `prior_regime: str`
- `sector_transitions: list[{sector, from_state, to_state}]`

### 6.5 Intraday Drift (lightweight mode)

From `intraday_bars.json` (Massive snapshot endpoint):
- `spy_session_return` = (current_price / prior_close) - 1
- Per sector: `session_return` and `vs_spy`
- `leadership_shift`: any sector's intraday rank differs > 2 positions from morning map

Intraday mode **does not** update `regime`, `sector_state`, or conviction modifiers — advisory only.

---

## 7. Snapshot Output Contract

`build_regime_snapshot()` returns this dict. All downstream consumers read this shape.

```python
def build_regime_snapshot(
    *,
    state_dir: Path,
    broker_positions: list[dict] | None = None,   # from Alpaca adapter
    policy: RegimePolicy | None = None,
    generated_at: str | None = None,
    refresh_mode: Literal["pre_market", "intraday", "post_market", "manual"] = "manual",
    force_fetch: bool = False,
) -> dict:
```

**Top-level keys:**

| Key | Type | Description |
|---|---|---|
| `schema_version` | str | "1.0.0" |
| `generated_at` | str | ISO timestamp UTC |
| `snapshot_type` | str | pre_market / intraday / post_market / manual |
| `data_as_of` | str | ISO date of latest price bar |
| `bluf` | dict | Summary counts and headline |
| `market_backdrop` | dict | Regime, vol regime, macro tilt, modifiers |
| `sector_map` | dict[str, dict] | Per sector ETF: state, scores, flow, bias |
| `per_stock_context` | dict[str, dict] | Per ticker: sector, bias, conviction_boost |
| `breadth` | dict | Full-market advance/decline metrics |
| `macro` | dict | FRED series + proxy ETF readings + tiles list |
| `benchmarks` | list[dict] | SPY, QQQ, IWM, DIA returns |
| `intraday_drift` | dict | Session drift (null outside market hours) |
| `portfolio_context` | dict | Open positions mapped to sector state |
| `data_sources` | list[dict] | 4-element quality panel |

Full JSON shape defined in §4.3 of the audit report (`docs/market-regime-audit-2026-05-29.md`).

---

## 8. Scheduler Hooks

```python
def schedule_regime_refresh(scheduler: APScheduler, state_dir: Path, policy: RegimePolicy) -> None:
    # Pre-market: 07:00 ET, Mon–Fri
    scheduler.add_job(full_refresh, "cron", hour=7, minute=0, day_of_week="mon-fri",
                      kwargs={"mode": "pre_market"})
    # Intraday: every 60 min, 09:30–16:00 ET, Mon–Fri
    scheduler.add_job(intraday_refresh, "cron",
                      minute=0, hour="9-16", day_of_week="mon-fri",
                      kwargs={"mode": "intraday"})
    # Post-market: 16:30 ET, Mon–Fri
    scheduler.add_job(full_refresh, "cron", hour=16, minute=30, day_of_week="mon-fri",
                      kwargs={"mode": "post_market"})
```

Manual refresh triggered by `POST /market-regime/refresh` (existing view route). Uses `/v1/marketstatus/now` to determine appropriate refresh mode.

---

## 9. Dashboard Design

### 9.1 Page Structure

```
market_regime.html
│
├── BLUF BANNER             (regime + vol_regime + data_as_of + regime change alert)
│   └── [↺ Refresh Now] button  → POST /market-regime/refresh (htmx)
│
├── KPI ROW  (4 cards)
│   ├── RISK REGIME
│   ├── VOL (VIX)
│   ├── SPY 5D
│   └── BREADTH
│
├── PORTFOLIO CONTEXT  (3 columns, only shown when broker_connected)
│   ├── HEADWIND positions  (red left border)
│   ├── TOPPING positions   (yellow left border)
│   └── TAILWIND positions  (green left border)
│
├── SECTOR LEADERSHIP  (ranked grid, 3 or 4 per row)
│   └── each card: rank · ticker · state badge · score · S/F · sparkline-style bar · RRG label
│
├── MARKET STATE  (benchmark tile row: SPY · QQQ · IWM · DIA)
│
├── MACRO CONTEXT  (FRED tiles organized by category)
│   ├── RATES:    10Y YIELD · 2S10S
│   ├── CREDIT:   HY OAS · CORP OAS · STRESS INDEX
│   ├── GROWTH:   CLAIMS
│   └── PROXIES:  TLT 5D · GLD 5D · UUP 5D
│
└── <details> DATA SOURCES  (4-column: OHLCV · FRED · COMPUTE · FLOW)
```

### 9.2 Tooltip Registry

Every interactive metric has a `title` attribute tooltip. All entries also recorded in `docs/TOOLTIP_REGISTRY.md`.

| Element | Tooltip text |
|---|---|
| **Regime: Risk On** | "SPY 5D ≥ +1%, breadth ≥ 55%, vol < 20%. Standard approval path for candidates." |
| **Regime: Risk Off** | "Broad market is defensive. SPY 5D ≤ -1.5% or breadth ≤ 35% or bond flight detected. Raise the conviction bar." |
| **Regime: Volatile** | "High realized volatility (≥ 25% annualized) with a large price swing. Reduce position sizes; tighten stops." |
| **Regime: Rotating** | "Sector leadership is split. Market index direction is less useful. Focus on sector alignment per candidate." |
| **Regime: Neutral** | "No strong directional signal. Candidate-specific evidence dominates the decision." |
| **Vol Regime: CALM** | "VIX below 20. Normal fear levels. Standard position sizing applies." |
| **Vol Regime: ELEVATED** | "VIX 20–35. Elevated uncertainty. Reduce new position sizes to 75% of normal." |
| **Vol Regime: HIGH** | "VIX above 35. High fear. Reduce position sizes to 50%. Prefer cash over new entries." |
| **Breadth** | "% of active US equities (8,000+) that advanced over the past 5 sessions. Above 55% = broad participation." |
| **Sector: ADVANCING** | "RS-Ratio positive (outperforming SPY) and RS-Momentum positive (improving). Sector is leading." |
| **Sector: TOPPING** | "RS-Ratio positive but RS-Momentum turning negative. Sector is still ahead but losing steam." |
| **Sector: BASING** | "RS-Ratio negative but RS-Momentum improving. Sector is lagging but showing early recovery." |
| **Sector: DECLINING** | "RS-Ratio negative and RS-Momentum negative. Sector is underperforming and weakening." |
| **Flow confirmed (✓)** | "CMF(14) positive and OBV trend rising — institutional money is accumulating in this sector ETF." |
| **Flow not confirmed** | "Price momentum is present but institutional flow signal (CMF/OBV) does not yet confirm the move." |
| **Momentum score (S)** | "Composite z-score: 20% of 5D, 50% of 20D, 30% of 60D excess return vs SPY. Positive = leadership." |
| **Flow score (F)** | "Chaikin Money Flow (14-day). Positive = institutional accumulation. Negative = distribution. Hard veto below -0.5." |
| **RS-Ratio** | "Sector 20D return minus SPY 20D return. Positive means the sector is outperforming the broad market." |
| **RS-Momentum** | "Change in RS-Ratio over 5 sessions. Positive = the sector's relative strength is improving." |
| **Conviction boost** | "Added to a candidate's final conviction score when its sector is in tailwind. Reduces required conviction floor." |
| **2S10S (T10Y2Y)** | "10-year minus 2-year Treasury yield spread. Below 0 (inverted) is historically a leading recession signal." |
| **HY OAS** | "ICE BofA High Yield Option-Adjusted Spread. Widening spreads signal institutional risk-off. Tightening = risk appetite." |
| **CORP OAS** | "Investment-grade corporate option-adjusted spread. Wider = tighter credit conditions for companies." |
| **STRESS INDEX** | "St. Louis Fed Financial Stress Index. Negative = below-average stress. Rising rapidly = financial system tension." |
| **CLAIMS (ICSA)** | "Weekly initial jobless claims. Rising claims signal a weakening labor market. Watch the 5-week trend." |
| **10Y YIELD** | "10-year Treasury constant maturity rate. Rising fast (>20 bps/week) pressures equity valuations." |
| **TAILWIND (portfolio)** | "Your position's sector is advancing with flow confirmation. The top-down backdrop supports holding." |
| **TOPPING (portfolio)** | "Your position's sector is still positive but losing relative strength. Monitor for deterioration." |
| **HEADWIND (portfolio)** | "Your position's sector is underperforming and weakening. Consider tightening your stop." |
| **Intraday drift** | "Today's session return for each sector ETF vs. SPY. Advisory only — does not change regime or modifiers." |
| **Data as of** | "Latest price bar date used for all regime calculations. Data is sourced from Massive (Polygon.io)." |
| **FRED as of** | "Date of latest FRED values. FRED updates most daily series by 16:00 ET. Cached for 24 hours." |

### 9.3 Sector Card Markup Pattern

```html
<article class="sector-card sector-card-{{ row.state_class }}"
         aria-label="{{ row.label }} sector">
  <div class="sector-card-head">
    <span class="sector-rank">#{{ row.rank }}</span>
    <span class="sector-ticker">{{ row.ticker }}</span>
    <span class="tag tag-{{ row.state_class }}"
          title="{{ tooltips[row.state] }}">{{ row.state }}</span>
  </div>
  <div class="sector-card-scores">
    <span title="{{ tooltips.momentum_score }}">S {{ row.score_label }}</span>
    <span title="{{ tooltips.flow_score }}">
      F {{ row.cmf_14_label }}
      {% if row.flow_confirmed %}
        <span class="flow-check" title="{{ tooltips.flow_confirmed }}">✓</span>
      {% endif %}
    </span>
  </div>
  <div class="sector-card-returns">
    <span class="metric-cell metric-cell-{{ row.return_5d_class }}"
          title="{{ tooltips.return_5d }}">{{ row.return_5d }}</span>
    <span class="metric-cell metric-cell-{{ row.excess_20d_class }}"
          title="{{ tooltips.rs_ratio }}">vs SPY {{ row.excess_20d }}</span>
  </div>
  <div class="sector-momentum-bar" title="{{ tooltips.momentum_score }}">
    <span style="{{ row.score_gauge_style }}"></span>
  </div>
  <footer class="sector-card-footer">
    <span title="{{ tooltips.rrs_label }}">RRG {{ row.quadrant }}</span>
    <span title="{{ tooltips.conviction_boost }}" class="conviction-boost-label
      {% if row.conviction_boost > 0 %}boost-positive
      {% elif row.conviction_boost < 0 %}boost-negative{% endif %}">
      {% if row.conviction_boost > 0 %}+{{ row.conviction_boost_pct }}%{% endif %}
      {% if row.conviction_boost < 0 %}{{ row.conviction_boost_pct }}%{% endif %}
    </span>
  </footer>
</article>
```

### 9.4 FRED Macro Tile Markup Pattern

```html
{% for tile in macro.tiles %}
<article class="macro-tile macro-tile-{{ tile.class }}"
         aria-label="{{ tile.label }}">
  <div class="macro-tile-head">
    <span class="metric-label">{{ tile.label }}</span>
    <span class="tag tag-neutral" title="FRED series ID">{{ tile.id }}</span>
  </div>
  <strong class="macro-value">{{ tile.value }}</strong>
  <span class="macro-badge macro-badge-{{ tile.class }}"
        title="{{ tooltips[tile.id] }}">
    {% if tile.class == "pass" %}+ POSITIVE{% elif tile.class == "warn" %}! NEGATIVE{% else %}= NEUTRAL{% endif %}
    {{ tile.trend }}
  </span>
  <div class="metric-gauge metric-gauge-{{ tile.class }}" aria-hidden="true">
    <span style="{{ tile.gauge_style }}"></span>
  </div>
  <footer class="macro-tile-delta" title="Change vs. prior reading">
    {{ tile.delta }} / {{ tile.as_of }}
  </footer>
</article>
{% endfor %}
```

### 9.5 Portfolio Context Column Layout

```html
<section class="portfolio-context-grid" aria-label="Portfolio sector context">
  {% for column, label, class in [
      ("headwind_positions", "Headwind",  "block"),
      ("topping_positions",  "Topping",   "warn"),
      ("tailwind_positions", "Tailwind",  "pass"),
  ] %}
  <div class="portfolio-context-col portfolio-context-col-{{ class }}">
    <h3 class="portfolio-context-col-head">
      {{ label }}
      <span class="info-tip"
            title="{{ tooltips[column] }}"
            aria-label="{{ label }} explanation">?</span>
    </h3>
    {% for pos in portfolio_context[column] %}
    <article class="portfolio-position-card"
             title="Sector {{ pos.sector }} is {{ pos.sector_state }}">
      <strong>{{ pos.ticker }}</strong>
      <span class="muted-line">{{ pos.sector_label }}</span>
      <span class="tag tag-{{ class }}">{{ pos.sector_state }}</span>
      <p class="position-note">{{ pos.note }}</p>
    </article>
    {% else %}
    <p class="empty-block">No positions in {{ label | lower }} sectors.</p>
    {% endfor %}
  </div>
  {% endfor %}
</section>
```

---

## 10. Integration Points

### 10.1 Portfolio Manager (existing `src/agency/portfolio/circuit_breaker.py`)

> **Note:** This wiring is defined here for completeness but is implemented in a **separate ticket** after both the portfolio manager and market regime modules are complete and tested independently.

```python
# New parameter added to evaluate_circuit_breakers():
def evaluate_circuit_breakers(weekly_perf, daily_perf, regime_context, policy):
    ...
    if regime_context.get("market_backdrop", {}).get("regime") == "RISK_OFF":
        signals.append("MARKET_RISK_OFF")
        new_entries_blocked = True
    if regime_context.get("market_backdrop", {}).get("vol_regime") == "HIGH":
        signals.append("MARKET_HIGH_VOLATILITY")
        reduced_sizing_active = True
```

### 10.2 Selection Pipeline (conviction adjustment)

```python
# Applied in risk module when building risk decisions:
sector_context = regime_snapshot["per_stock_context"].get(ticker, {})
conviction_boost = float(sector_context.get("conviction_boost", 0.0))
adjusted_conviction = min(1.0, max(0.0, candidate.final_conviction + conviction_boost))
```

### 10.3 Portfolio Manager Exit Signals

When a position's sector transitions to `DECLINING`, add `SECTOR_HEADWIND` to `secondary_signals` on the position row. Not an immediate forced exit — surfaces as a `SETUP_WARNING` for human review.

### 10.4 Cockpit Pre-Trade Checklist

One new check in the cockpit's readiness panel:
```
✓ Market regime: Risk On — normal approval path
⚠ Vol: Elevated (VIX 27) — reduce new position sizing to 7.5%
⚠ XLE sector declining — 1 open position in headwind (XOM)
```

---

## 11. ticker-sector-map.json (initial version)

Covers S&P 100 + QQQ holdings. Committed to `research/config/ticker-sector-map.json`. Updated quarterly.

```json
{
  "AAPL":  "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK",
  "GOOGL": "XLC", "GOOG": "XLC", "META": "XLC", "NFLX": "XLC",
  "AMZN":  "XLY", "TSLA": "XLY", "HD":   "XLY", "MCD":  "XLY",
  "JPM":   "XLF", "BAC":  "XLF", "WFC":  "XLF", "GS":   "XLF",
  "JNJ":   "XLV", "UNH":  "XLV", "LLY":  "XLV", "PFE":  "XLV",
  "XOM":   "XLE", "CVX":  "XLE", "COP":  "XLE",
  "CAT":   "XLI", "HON":  "XLI", "GE":   "XLI", "UPS":  "XLI",
  "PG":    "XLP", "KO":   "XLP", "PEP":  "XLP", "WMT":  "XLP",
  "NEE":   "XLU", "DUK":  "XLU", "SO":   "XLU",
  "AMT":   "XLRE","PLD":  "XLRE","EQIX": "XLRE",
  "LIN":   "XLB", "APD":  "XLB", "SHW":  "XLB",
  "BRK.B": "XLF", "SPGI": "XLF", "BLK":  "XLF"
}
```
*(Full 100+ ticker map in the committed file — this is an excerpt.)*

---

## 12. Tests

### Unit tests — `tests/unit/test_market_regime_analyzer.py`

All tests use fixture JSON dicts. No HTTP calls. No file I/O.

| Test | Verifies |
|---|---|
| `test_risk_off_on_negative_spy` | regime = RISK_OFF when SPY 5D ≤ -1.5% |
| `test_risk_off_on_low_breadth` | regime = RISK_OFF when advancers ≤ 35% |
| `test_risk_off_on_bond_flight` | regime = RISK_OFF when TLT 5D ≥ +1.5% |
| `test_volatile_regime` | regime = VOLATILE when vol ≥ 25% and abs move ≥ 2% |
| `test_risk_on_all_conditions` | regime = RISK_ON when all conditions met |
| `test_neutral_fallthrough` | regime = NEUTRAL when no rule matches |
| `test_vol_regime_calm` | vol_regime = CALM when VIX < 20 |
| `test_vol_regime_high` | vol_regime = HIGH when VIX > 35 |
| `test_macro_tilt_defensive` | macro_tilt = DEFENSIVE when yield curve inverted |
| `test_macro_tilt_risk_appetite` | macro_tilt = RISK_APPETITE when curve > 1 and spreads tight |
| `test_sector_advancing_quadrant` | rs_ratio > 0, rs_momentum > 0 → ADVANCING |
| `test_sector_topping_quadrant` | rs_ratio > 0, rs_momentum ≤ 0 → TOPPING |
| `test_sector_declining_quadrant` | rs_ratio ≤ 0, rs_momentum ≤ 0 → DECLINING |
| `test_sector_basing_quadrant` | rs_ratio ≤ 0, rs_momentum > 0 → BASING |
| `test_flow_confirmed` | CMF > 0 and OBV trend UP → flow_confirmed = True |
| `test_flow_bearish` | CMF < 0 and OBV trend DOWN → flow_bearish = True |
| `test_advancing_confirmed_boost` | ADVANCING + flow_confirmed → conviction_boost = +0.03 |
| `test_declining_confirmed_penalty` | DECLINING + flow_bearish → conviction_boost = -0.05 |
| `test_per_stock_context_lookup` | AAPL → XLK sector, inherits XLK boost |
| `test_regime_change_detected` | prior NEUTRAL, current RISK_OFF → regime_changed = True |
| `test_no_regime_change` | same regime → regime_changed = False |
| `test_intraday_drift_computed` | session return and vs_spy computed from snapshot data |
| `test_data_limited_on_empty_inputs` | empty state files → regime = DATA_LIMITED |
| `test_snapshot_schema_has_required_keys` | output dict has all 13 top-level keys |
| `test_policy_defaults_match_spec` | all RegimePolicy defaults match §4 values |

### Integration tests — `tests/integration/test_market_regime_fetcher.py`

| Test | Verifies |
|---|---|
| `test_etf_bars_roundtrip` | write → load from state dir |
| `test_fred_cache_hit` | second call within 24h reads cache, no HTTP call |
| `test_fred_failure_non_blocking` | FRED error doesn't raise; quality flag set |
| `test_grouped_daily_breadth_coverage` | grouped daily result has advancers/decliners counts |

---

## 13. Acceptance Criteria

1. All 25 unit tests pass.
2. All 4 integration tests pass.
3. `build_regime_snapshot()` returns a dict with all 13 required top-level keys for:
   - Empty state dir (DATA_LIMITED regime)
   - Pre-market mode with all data present
   - Intraday mode (drift-only, regime unchanged)
4. Every metric on the dashboard has a `title` tooltip attribute.
5. FRED failure returns `macro_tilt = NEUTRAL` and sets `data_sources[1].status = WARN`.
6. `RegimePolicy` loads all fields from env vars correctly.
7. No file in `src/agency/market_regime/` exceeds 300 lines.
8. No HTTP calls inside `analyzer.py`.

---

## 14. What Codex Must NOT Do

- Do not modify `src/agency/runtime/market_regime.py` — it stays untouched.
- Do not call HTTP endpoints inside `analyzer.py` — it is pure computation only.
- Use `AGENCY_<UPPER_SNAKE_CASE>` naming for all new env vars.
- Use `datetime.now(UTC)` — never `datetime.utcnow()`.
- Use `from __future__ import annotations` at the top of every file.
- Do not add Streamlit, React, or any frontend framework — templates are Jinja2/htmx.
- Add `fredapi>=0.5.1` to `pyproject.toml` dependencies — it is not currently listed.
- Do not add any other new `pip` dependencies.
