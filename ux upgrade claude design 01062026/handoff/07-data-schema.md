# 07 · Data Schema

The prototype's data lives in `cockpit/data.js` as a single global `window.COCKPIT_DATA`. **Treat this as placeholder material.** Codex defines the real schema from the backend. This doc documents the *shape* the UI consumes so the contract between agent and cockpit is clear.

## Top-level structure

```js
COCKPIT_DATA = {
  cycle:           { ... },   // current cycle metadata
  market:          { ... },   // top-down regime data
  engines:         [ ... ],   // health of each agent engine
  funnel:          { ... },   // pipeline counts (universe → final)
  candidates:      [ ... ],   // ranked candidates this cycle
  positions:       [ ... ],   // current portfolio
  account:         { ... },   // exposure, cash, caps
  sectors:         [ ... ],   // 11 sectors with state
  sources:         [ ... ],   // data source health (Universe panel)
  universeBlocked: [ ... ],   // tickers excluded with reason
  signals:         [ ... ],   // evidence log (Signals panel)
  auditLifecycle:  { ... },   // per-ticker decision traces (Audit panel)
  policy:          { ... },   // editable thresholds & flags (Policy panel)
  monitorEvents:   [ ... ],   // between-cycle event stream (Monitor panel)
}
```

Each section below documents one slice.

## `cycle`

```ts
{
  id: string;              // e.g. "C-14:32" — human-readable cycle identifier
  asOf: string;            // e.g. "14:32 UTC"
  nextIn: string;          // e.g. "13 min" — human string for the next cycle
  mode: "PAPER" | "LIVE";  // v1: always "PAPER"
  submitEnabled: boolean;
  sourcesDegraded: number;
  sourcesTotal: number;
}
```

The `nextIn` string is **derived from a numeric cycle interval** in the real backend. The UI does a local countdown via `useCockpitCountdown` — the backend just needs to provide the interval (or the next cycle's UTC timestamp).

## `market`

```ts
{
  regime: string;            // "balanced · risk-on tilt" — human label
  spy20d: number;            // % return, e.g. 2.4
  vix: number;               // e.g. 14.8
  breadth: number;           // 0-100, % above 50dma
  dispersion: number;        // 0-1
  longThreshold: number;     // e.g. 0.56
  sectorsTailwind: number;
  sectorsPressure: number;
  sectorsUnavail: number;
}
```

The four arc gauges in Variation A read from this + `account`.

## `engines`

```ts
Array<{
  name: string;                       // e.g. "Universe registry"
  state: "live" | "stale" | "down";
  age: string;                        // e.g. "6m", "19h"
}>
```

The engine strip and the topbar's "X of Y engines live" both read this. **If any engine has state="down", the outage scenario triggers.** Stale does not trigger.

`age` should be derived from a timestamp on the backend side.

## `funnel`

```ts
{
  universe: number;
  universeReady: number;
  fundamentalsPass: number;
  fundamentalsWatch: number;
  signals: number;
  deterministic: number;
  llmAgree: number;
  final: number;
  blockedByPolicy: number;
}
```

Used by Variation C's "funnel crumbs" strip and by both variations' "scanned X tickers, Y final" copy.

## `candidates` — the main payload

```ts
Array<{
  ticker: string;
  name: string;
  sector: string;
  direction: "long" | "short";
  detConviction: number;         // 0-1
  llmConviction: number;         // 0-1
  finalConviction: number;       // 0-1 — primary sort key
  status: "approved" | "blocked" | "demoted" | "rejected";
  blocker: string | null;        // human-readable reason if not approved
  price: number;                 // limit price for the order
  qty: number;                   // suggested share qty
  notional: number;              // qty × price (rounded)
  stopPct: number | null;        // % below entry, e.g. -4.7
  targetPct: number | null;      // % above entry, e.g. 8.9
  earningsDays: number;          // days until next earnings
  evidence: Array<{
    tier: "confirmed" | "inferred";
    source: string;              // e.g. "SEC Form 4", "Sector ETF"
    text: string;                // one-line claim
  }>;
  concerns: string[];            // each is a one-liner risk flag
  llmRationale: string;          // one paragraph, agent's voice
  gates: Array<{
    name: string;                // e.g. "Min conviction"
    val: string;                 // e.g. "0.78 ≥ 0.62"
    ok: boolean;
    warn?: boolean;              // ok=true but close to limit
  }>;
}>
```

**Sort:** the UI sorts by `finalConviction` descending. Backend should produce candidates in any order; the UI handles sort.

**Status semantics:**
- `approved` = agent's recommendation; user can approve/defer/reject
- `blocked` = policy rule blocks this trade; user cannot approve
- `demoted` = LLM downgraded the score below the bar
- `rejected` = below threshold; here for transparency / audit

The user can only act on `approved`. The other three are visible-but-not-actionable, with `blocker` explaining why.

**Conviction columns:** `detConviction` is the deterministic model's output; `llmConviction` is the LLM reviewer's; `finalConviction` is the final blended score the agent acts on. All three are shown in the deep-dive panel.

## `positions`

```ts
Array<{
  ticker: string;
  entered: string;          // ISO date, "2026-04-22"
  entry: number;            // entry price
  current: number;          // current price
  stop: number;             // current stop price
  target: number;           // current target price
  daysHeld: number;
  status: "hold" | "review" | "close";  // agent's recommendation
  thesis: string;           // one-line setup status
}>
```

The UI computes P/L and stop distance from `entry / current / stop`. **Don't store derived values** in the payload — compute in the UI so they stay in sync with prices.

## `account`

```ts
{
  grossExposure: number;          // current %
  grossPostTrade: number;         // % if all staged orders fill
  grossCap: number;               // policy cap %
  cashAvailable: number;          // current cash %
  cashCap: number;                // policy floor %
  largestName: number;            // current largest name %
  largestNameCap: number;         // policy cap %
  openOrders: number;
  openOrdersCap: number;
  buyingPower: number;            // dollars (Alpaca paper)
  weekPnl: number;                // % WTD
  weekTarget: number;             // % WTD target
}
```

**`grossPostTrade` is a UI-side computation in the real product** — it depends on which orders are staged. The prototype hardcodes 84%; in production this number should update as the user approves/defers candidates.

## `sectors`

```ts
Array<{
  name: string;
  state: "tailwind" | "neutral" | "pressure" | "unavail";
  detail: string;        // e.g. "XLK +3.1% · 9/10"
}>
```

Used by Variation C's sector heatmap and feeds into the candidate row sector tag.

## `sources`

```ts
Array<{
  name: string;          // e.g. "SEC EDGAR · Company Facts"
  tier: "official" | "market" | "broker" | "paid-sub" | "rss" | "llm";
  state: "fresh" | "partial" | "stale";
  lastPull: string;      // "2026-05-06 14:24"
  coverage: string;      // "150/150" or "—"
  note: string;          // optional context
}>
```

Used by PanelUniverse. **Tier is a credibility signal** that downstream code uses to weight evidence — bake the tier into the contract.

## `universeBlocked`

```ts
Array<{
  ticker: string;
  reason: string;
  action: string;        // remediation hint
  attempted: string;     // "14:25" — last retry time
}>
```

Tickers that were excluded from the universe with reason + retry status.

## `signals`

```ts
Array<{
  ticker: string;
  kind: string;                // "Insider buying", "Quant rank upgrade", "Technical breakout"
  tier: "confirmed" | "inferred" | "suppressed";
  source: string;              // "SEC Form 4", "Sector ETF"
  impact: "high" | "med" | "low" | "—";
  note: string;                // one-liner
  negative?: boolean;          // true for risk signals (XOM sector pressure etc)
}>
```

The signal log lives in PanelSignals. **`tier` ladder:**
- `confirmed` counts toward evidence-breadth (≥ 2 required to be a candidate)
- `inferred` is context-only (cannot pass the breadth gate alone)
- `suppressed` is logged for audit; visible at 55% opacity in the UI

## `auditLifecycle`

```ts
{
  [ticker: string]: {
    title: string;
    summary: string;
    events: Array<{
      t: string;          // "14:08", "14:30"
      state: string;      // "entered universe", "removed"
      note: string;
      critical?: boolean; // adds red dot + glow
    }>;
  };
}
```

The "why did X happen" trace. The prototype only ships one (NFLX); the real product should produce these on demand for any ticker the user clicks "audit ›" on.

## `policy`

```ts
{
  convictionGates: Array<PolicySlider>;
  portfolioCaps:   Array<PolicySlider>;
  flags:           Array<PolicyFlag>;
}

interface PolicySlider {
  key: string;       // e.g. "long_threshold"
  label: string;     // e.g. "Long threshold (det.)"
  v: number;         // current value
  min: number;
  max: number;
  step: number;
  unit: string;      // "%", " lanes", or ""
}

interface PolicyFlag {
  key: string;       // ALL_CAPS, e.g. "BROKER_SUBMIT_ENABLED"
  label: string;     // human-readable
  v: boolean;
  danger: boolean;   // shows red border when ON
  locked?: boolean;  // cannot be toggled (e.g. LIVE_TRADING in v1)
}
```

**The Policy panel mutates this in the prototype only locally** (via React state). In the real product, it should:
1. Show pending changes (diff vs deployed policy)
2. Require a confirm step ("Apply next cycle")
3. PUT to the agent's config endpoint
4. Show the deployed value vs the staged value

The prototype has none of this — it's a single-user, single-state form. The real product needs proper write semantics.

## `monitorEvents`

```ts
Array<{
  t: string;                            // "14:31:08"
  sev: "info" | "warn" | "block";
  topic: string;                        // "cycle" | "candidate" | "signal" | "source" | "policy" | "regime"
  msg: string;                          // one-line description
}>
```

The continuous stream. **Real product: this should be a server-sent stream**, not a polled array. The UI handles it as a list; the transport is the backend's call.

## Session state (NOT in COCKPIT_DATA)

These live in **React state** in the prototype and reset on reload. The real product needs to persist some of them:

| State | Persistence |
|---|---|
| `phase` (which phase the user is in) | local; reset on cycle change |
| `decisions` (per-ticker approve/defer/reject) | local; reset on cycle change |
| `exits` (per-position close/keep) | local; reset on cycle change |
| `gateOpen` (submit gate armed) | **never persist** — always starts closed |
| `phrase` (confirmation phrase typed) | **never persist** — always starts empty |
| `selected` (which candidate is selected in Variation C) | local; defaults to top |
| Tweak preferences (color, theme, density) | **persist across sessions** (localStorage / Pi config file) |

**[CONFIRM]** — should staged decisions persist across page reload mid-session? The current prototype loses them on reload, but for kiosk reliability (browser crashes, accidental refreshes), persisting them in localStorage + a "do you want to restore your session?" prompt on load is the safe answer.

## Server contract sketch

A pragmatic split:

| Endpoint | Method | Purpose |
|---|---|---|
| `GET /api/cockpit` | GET | One-shot snapshot of everything except monitor events |
| `GET /api/cycle` | GET | Just the cycle + market + engines (cheap poll) |
| `POST /api/decisions` | POST | Submit the manifest. Body: { decisions, exits, phrase } |
| `PUT /api/policy` | PUT | Update policy (gates, caps, flags) |
| `GET /api/monitor/stream` | SSE | Live event stream for PanelMonitor |
| `GET /api/audit/:ticker` | GET | Lifecycle trace on demand |

But the backend shape is **Codex's call** — this is just a sketch for context.
