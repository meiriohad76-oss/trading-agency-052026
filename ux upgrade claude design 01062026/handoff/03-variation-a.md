# 03 · Variation A — Pre-Flight Cockpit

**Aesthetic:** instrument cluster — half-circle gauges, 7-segment readouts, dark slate background, amber accent. Reads like a small-aircraft panel.

**Layout pattern:** **sequential**. One phase visible at a time. The phase rail at the top shows you where you are. You complete Phase 1 (Candidates) before seeing Phase 2 (Portfolio), and so on.

**When to choose A over C:**
- User likes to focus on one thing at a time
- Touchscreen-friendly (taps don't have to be tiny)
- Easier to follow on first use — the linear flow teaches itself
- Better for users who don't have constant context-switching needs

**File:** `Variation A.html` (standalone) · `cockpit/variation-a-preflight.jsx` (source)

## Anatomy (top to bottom)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  TOPBAR     [logo] AGENCY · COCKPIT v2.1   ●6/7 engines  cycle C-14:32  │ ← strip
│             next-in 12:43  [PAPER mode badge]                            │
├─────────────────────────────────────────────────────────────────────────┤
│  INSTRUMENT CLUSTER (gauges + digital readouts)                          │ ← always
│   ◐ Market    ◐ Gross     ◐ Cash      ◐ Concentration  | $28K BP        │   visible
│     BAL         84%         18%         14%             | 3/9 Ready      │
│                                                          | +0.7% WTD     │
├─────────────────────────────────────────────────────────────────────────┤
│  ENGINES · ● Universe ● Fundamentals ● Regime ● Signals ● Det. ● LLM ◐13F│
├─────────────────────────────────────────────────────────────────────────┤
│  INSTRUMENTS › [Universe] [Signals] [Audit] [Policy] [Monitor]           │ ← nav
├─────────────────────────────────────────────────────────────────────────┤
│  PHASE RAIL   01 Candidates    02 Portfolio   03 Clearance   04 Cleared │ ← progress
│               ◀ active ▶          locked         locked         locked   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ACTIVE PHASE CONTENT                                                    │ ← swaps by
│  (candidates table / portfolio review / clearance gate / cleared state) │   phase
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## The four phases

### Phase 1 — Candidates

The big content. A ranked table of the agent's top candidates.

**Header:**
- BLUF headline: *"3 trades ready. Approve what you want to ship today."* (adapts to state)
- Subline: cycle context (*"Cycle C-14:32 scanned 152 tickers..."*)
- Right side: **Advance to Portfolio →** button (disabled until ≥1 approval)

**Table columns:**
| # | Ticker · sector | Conviction | Why (evidence) | Risk | Status | Decision |
|---|---|---|---|---|---|---|
| 01 | **NVDA** Technology | ◐ 0.78 (green) | "CFO bought 4,200 sh..." | "Valuation P/E..." | READY (amber) | [Approve] [Defer] [Reject] |

- **Conviction column** shows a small **half-dial needle** (green/amber/red) + the score number in monospace.
- **Status chip** is a small bordered pill colored by state.
- Clicking a row toggles inline expansion: full evidence pack, LLM rationale (in italic), risk concerns, and order preview side-by-side.
- Clicking the ticker (not the row) opens the **Ticker Detail** overlay (full factor breakdown).

### Phase 2 — Portfolio

Two-column layout: **positions table (left, 2/3)** + **capacity check (right, 1/3)**.

**Positions:** 5 rows. Each shows ticker · days held · P/L · stop distance · setup tag · thesis · keep/close decision (only for non-HOLD).

**Capacity check:** stacked horizontal bars showing current → post-trade vs cap, for:
- Gross exposure
- Per-sector exposures (top 3)
- Cash reserve (with floor inversion — lower bar = more concerning)

Below the bars: an amber heads-up paragraph when caps are tight.

**Buttons:** ← Back · Advance to Clearance → (disabled until all non-HOLD positions have a keep/close decision).

### Phase 3 — Clearance

Two-column: **order manifest (left, 1.4/1)** + **gate panel (right, 1/1)**.

**Order manifest:**
- "Exits first" section if any closes were staged
- One row per staged buy: ticker · qty · limit · notional · stop · target
- Empty state if nothing approved

**Gate panel:**
- Big status dot: red (closed) / green (open)
- Checkbox "I want to open the submit gate"
- Text input "Type to confirm" → required phrase `submit paper orders`
- Submit button — locked until both above are true; activates with a glow
- Footer flags: BROKER_SUBMIT_ENABLED · SHORTS_ENABLED · BRACKET_ORDERS · etc.

### Phase 4 — Cleared (post-submit)

Centered success state. Big check mark in a green ring. "{n} paper orders submitted." Then a horizontal strip of one card per submitted order: ticker · BUY {qty} @ {price} · order ID. Total notional + next cycle countdown below.

`[Start over]` button at the bottom (resets to Phase 1).

## The instrument cluster (top, always visible)

Four arc gauges + a column of three 7-segment displays:

**Arc gauges** — half-circle, -90° to +90°, zoned by color, with a needle that animates to position on first paint:
1. **Market Regime** — 0..1 score; zones: red 0-0.40, amber 0.40-0.62, green 0.62-1; reads "BAL"
2. **Gross Exposure** — `grossPostTrade / grossCap`; zones: green 0-70%, amber 70-90%, red 90%+
3. **Cash Reserve** — `cash / 30%`; zones: red 0-33%, amber 33-50%, green 50%+
4. **Concentration** — `largestName / largestNameCap`; zones: green 0-60%, amber 60-85%, red 85%+

Each gauge has a "?" marker (`<WhyMark>`) that explains the threshold on hover. **Keep these tooltips** — they're how the user learns what the gauges mean.

**7-segment displays** (right column, mono-amber/cyan on near-black):
- **Buying Power** ($28K, cyan)
- **Ready to Trade** (3/9, amber — count of approved / total candidates)
- **P/L Week** (+0.7% WTD, green)

## The engine strip

Single horizontal row, just below the cluster. Lists every engine with a status dot + name + age:

```
ENGINES   ● Universe registry · 6m   ● Fundamentals · 8m   ● Market regime · 2m
          ● Signals · 1m   ● Deterministic · 4m   ● LLM (gpt-5.4-mini) · 4m
          ◐ Institutional 13F · 19h
```

- ●  green = live
- ◐  amber = stale (data exists but is old)
- ●  red = down (blocks selection)

If any engine is **down**, the **outage** scenario triggers — full-bleed message, no candidates, retry countdown. Stale engines do NOT block, they just show amber.

## The instruments nav

Five buttons, just below the engine strip:
| Universe | Signals | Audit | Policy | Monitor |
|---|---|---|---|---|
| 150/152 | 12 live | NFLX trace | 6 caps | live stream |

Each opens an overlay (see `05-components.md → CockpitOverlay`) with that instrument's full content. The overlay is modal but does NOT block the underlying screen visually — it sits on top with a backdrop blur.

## The phase rail

Four cells, 1/4 width each, gridlined. Active phase has:
- Amber phase number
- Bright white title
- Amber underline (1px, 8px glow)
- Background slightly lighter (`#0f1c2f`)

Completed phases: green checkmark, dim title.
Locked phases: `◌` symbol, 42% opacity, "LOCKED" badge.

**Visual rule:** you can see all four phases at all times. They form a horizon — the user always knows where they are in the flow.

## Animations

- **Arc gauges**: needle eases to position on mount (700ms cubic ease-out)
- **Conviction needles** in the candidate table: same (700ms)
- **Phase transitions**: instant (no slide). The active underline fades in via CSS only.
- **Countdown** in topbar: amber, pulses (1.6s) when ≤ 1 min
- **Status dots**: no animation by default. The "cockpit-pulse" class is reserved for the engine strip's stale indicators (and the live indicator in Monitor).
- **Hover states**: 120ms color transition only — no scale, no translate.

## Touch / kiosk considerations

- All buttons ≥ 36px tall
- Decision buttons (Approve/Defer/Reject) are smaller (24px) — but they cluster — Codex should bump these to 40px+ for touch
- Tooltips appear on hover; on touch, they appear on tap-and-hold (300ms)
- No drag-to-reorder, no swipe gestures — every action is a discrete tap

## Variation A's strength + weakness

**Strength:** **focus.** One phase fills the screen. The user is not asked to think about portfolio while approving candidates. The phase rail teaches the workflow.

**Weakness:** **back-tracking.** If the user is in Phase 2 and realizes they want to reject a candidate they approved, they have to go back. The phase rail allows this (the active cell has a < Back button in Phase 2 and 3) but it's an extra click.

If the user is the kind who wants to see everything at once, build Variation C instead.
