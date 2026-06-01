# 05 · Components

Shared components used by both variations. Source files in `cockpit/shell.jsx` and `cockpit/panels.jsx`. The prototype implementations are correct visually — read them as-is, but feel free to refactor.

## Shell components (`cockpit/shell.jsx`)

### `useCockpitCountdown(initialSeconds)` — hook

Returns `{ mm, ss, total }` and ticks every second. When it hits zero, it loops back to 13 minutes (the cycle interval). The prototype's loop behaviour is fine for the kiosk — when the cycle clock changes for real, replace with backend-driven `total` and derive mm/ss locally.

### `useAnimatedValue(target, duration, deps)` — hook

Ease-out cubic animation from 0 to `target` over `duration` ms. Used for the arc-gauge needles and the conviction bars. Re-fires on `deps` change.

### `<CockpitTip tip side="top|bottom" />`

Hover tooltip. Black background, narrow (220px), positioned above or below the trigger. **No arrow** — the offset (6px) is the only spatial cue.

### `<WhyMark tip="..." />`

Tiny circular "?" badge next to a label. Uses `<CockpitTip>` internally. **Use liberally** — every threshold, every cap, every cryptic abbreviation should have one. This is provenance principle #2 made tangible.

### `<CockpitOverlay open onClose title sub badge children width accent />`

Modal overlay used by all five instrument panels. Anatomy:
- Backdrop: `rgba(0,0,0,.55)` + 2px blur
- Centered card, max-height 80vh, scrolls if content exceeds
- Header: badge (small uppercase pill) · title · sub · close button (top-right, "Close · Esc")
- Body: padded 22px, scrolls
- Esc key closes
- Click-outside closes

The overlay is **modal but not loud**. The backdrop is dim, not black. The user can still see the cockpit underneath. This is intentional — it's a "peek into the instrument," not a navigation away.

## Panel components (`cockpit/panels.jsx`)

Six panels live inside `<CockpitOverlay>` and are reused by both variations. Each is self-contained.

### `<PanelUniverse />` — Data sources & freshness

**Top:** 4-up stat grid — Universe (152) · Ready (150) · Blocked (2) · Refreshed (14:30).

**Body:** two-column.
- **Left (1.6fr):** "Data sources · 9 connected" — table with columns Source / Tier / State / Coverage. Each source has a freshness dot (fresh=green, partial=amber, stale=red), last-pull time, and an optional note.
- **Right (1fr):** "Blocked tickers" cards (red-bordered) + "PIT integrity" status card (green-bordered).

**Purpose:** the user wants to know what data the agent saw. This is the answer.

### `<PanelSignals />` — Evidence log

**Top:** filter chips (all / confirmed / inferred / suppressed) with counts.

**Middle:** two side-by-side rule cards explaining how evidence is treated and the breadth requirement.

**Bottom:** "Signal log · this cycle" — a table of every signal this cycle, with tier badges (CONF green / INF amber / SUPPRESSED grey).

**Purpose:** when the user asks "why is NVDA scored 0.78?" the answer lives here.

### `<PanelTickerDetail ticker="NVDA" />` — Deep-dive

Three sections:
- **Hero:** big ticker · name · sector · price · DET/LLM/Final score blocks (with thresholds)
- **Order preview** (if approved): qty, limit, notional, stop, target, earnings days, bracket type
- **Factor breakdown** (left, 1fr): table of 6 fundamental factors with threshold / value / pass-or-warn chip
- **Evidence pack** (right, 1fr): each evidence item as a card (tier-colored left border) + LLM rationale block (cyan-tinted, italic)
- **Policy gates** (bottom, 3-up grid): every gate evaluated, green if pass, red if fail

**Purpose:** the deepest single-candidate view. The user opens this from a ticker click in any variation.

### `<PanelAudit ticker="NFLX" />` — Decision lifecycle trace

**Top:** amber-bordered card with the ticker, status badge ("removed mid-cycle"), title ("Why NFLX disappeared at 14:30"), and summary.

**Middle:** vertical timeline. Each event has a timestamp, state label, note. Critical events get a red dot with a glow. Timeline rail is a 1px vertical line on the left.

**Bottom:** reproducibility note — cycle ID, evidence pack hash, "all state transitions are deterministic given the same input pack."

**Purpose:** when a candidate doesn't appear (or disappears mid-cycle), the user can ask why. The audit is the agent's answer.

### `<PanelPolicy />` — Policy editor

Two-column at top:
- **Conviction gates** (left): sliders for long_threshold, min_final_conv, agreement_bonus, evidence_breadth
- **Portfolio caps** (right): sliders for gross_cap, cash_floor, sector_cap, single_name_cap, max_positions, new_per_cycle

Below: **Operational flags** — 2-column grid of toggle switches:
- BROKER_SUBMIT_ENABLED (safe)
- SHORTS_ENABLED (danger — red border when on)
- LIVE_TRADING (danger + locked off — cannot be enabled in v1)
- BRACKET_ORDERS (safe)
- LLM_REVIEW (safe)

Bottom: amber heads-up — "Policy changes apply next cycle."

**Purpose:** the operator's control over the agent's behaviour. **Editing here doesn't mutate live state in the prototype** — only the slider position changes. In the real product, this writes to the agent's config.

### `<PanelMonitor />` — Event stream

**Top:** filter chips (all / info / warn / block) + live pulse indicator + "live stream · {countdown}".

**Body:** chronological event list — each row has timestamp · severity dot · message · topic chip. Tinted backgrounds for warn (amber) and block (red).

**Purpose:** between-cycle ambient awareness. The user can leave this open and glance at it.

## Variation-specific primitives

### Variation A — `<ArcGauge>`

Half-circle gauge, 160×100 SVG. Zones colored per config. Needle rotates from -90° to +90° based on value (0..1). Below the SVG: big mono number with unit, label (uppercase letterspaced), sub-line (small grey).

Mount animation: needle eases from 0 to value (700ms).

### Variation A — `<ConvictionDial>`

Same family as ArcGauge but compact (64×40). Used in the candidates table — one per row. Color tracks the score threshold.

### Variation A — `<SegDisplay>`

Faux-7-segment display: dark slab, monospace number with a subtle text-shadow glow, small label above. Used for the three digital readouts (Buying Power, Ready to Trade, P/L Week).

### Variation A — `<PhaseRail>`

Four equal cells with phase number, title, sub, locked-or-active state. Active gets amber underline + glow. Locked at 42% opacity with "◌ LOCKED" badge.

### Variation C — `<MCColumn>`

Generic column wrapper with header strip, body. Handles active / dimmed states.

### Variation C — `<ConvictionBar>`

Tiny 14×14 vertical bar (fill grows from bottom) + the mono score number. Used in the compact candidate list.

### Variation C — `<Telem>`

Telemetry strip element: small uppercase label · mono value (colored by sign). Optional "big" variant for the approval counters.

### Variation C — `<MiniMeter>`

Tiny cap meter for the portfolio column header: label · "cur → post" · thin progress bar.

### Variation C — `<SectorRadar>`

11-cell grid with sector name + sub-line, color-coded by state. **The "radar" name is aspirational** — it's not actually a polar plot, just a heatmap grid. We tried a polar version; the grid is more legible at small sizes.

## Decision buttons

Both variations use a Approve / Defer / Reject trio. Three tones:
- **Approve** — green outline, green fill on active (`bg: rgba(95,228,157,.18)`)
- **Defer** — neutral grey outline
- **Reject** — red outline, red fill on active

Size: `6px 10px` padding, 11px font. Bump to `10px 16px` and 13px for touch deployment on the Pi.

## Status chips

Small bordered pills, 9px font, letterspaced uppercase:
- READY (amber)
- YOU APPROVED (green)
- DEFERRED (grey)
- YOU REJECTED (red)
- LLM DEMOTED (amber)
- BLOCKED (red)
- BELOW THRESHOLD (grey)

Border + text color match. No fill. (Filled chips exist as a variant — used for the "removed mid-cycle" badge in PanelAudit.)

## Color usage rules

1. **Amber = attention** — primary brand, used for the active phase, the "READY" state, the "Advance" button, hover, focus rings
2. **Green = positive / cleared** — approved, fresh, pos PnL, gauge in good zone
3. **Red = blocked / danger** — rejected, stale (down), neg PnL, gauge in danger zone, SUBMIT gate closed
4. **Cyan / acc = LLM voice** — the rationale block is cyan-tinted; the "Buying Power" segdisplay is cyan; the audit panel's reproducibility note has a cyan accent.
5. **Grey (tx-2/tx-3) = recede** — labels, captions, dim states, locked phases

**Do not invent a sixth color.** If you find yourself reaching for one, you're solving the wrong problem.

## Iconography rules

The prototype uses **almost no icons.** Status is communicated by:
- Color
- Position
- Typography weight
- Small geometric shapes (dots, half-circles, arrows ▸ ▼ ▲)

The few SVGs in the codebase are:
- The brand logo (a stylized circle-and-diamond in topbar / crosshair logo in Mission Control)
- The arc gauge needles + tracks
- The conviction bars + dials

**Do not add icons** (no font-awesome, no lucide, no material). If the design needs visual differentiation, use a color + position cue.

## Typography rules

- **Sans:** `-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`
- **Mono:** `ui-monospace, "JetBrains Mono", "SF Mono", "Roboto Mono", Menlo, Consolas, monospace`
- **Serif:** declared but not used — keep the variable for future.

**Rules:**
- All numbers in mono (`.mono` class, with `font-variant-numeric: tabular-nums`)
- Labels and category tags: small (9–11px), letterspaced (`.14em–.18em`), uppercase, faded (`var(--tx-3)`)
- Body copy: 12–13px, regular weight, `var(--tx-2)`
- BLUF headlines: 22–28px, weight 500, slight negative letterspacing (-.2 to -.4)
- The instrument cluster's gauge numbers: 24px mono, weight 500

**Never** use a third typeface. **Never** use a script / decorative font.

## Spacing rules

Use multiples of 4. Common values: 4, 8, 10, 12, 14, 16, 18, 22, 24, 32. The prototype is consistent on this; preserve it.

## Borders

- Hairline: `1px solid var(--bd)` (color `#1d2c40` in dark theme)
- Slightly bolder: `var(--bd-2)` (`#2a3d57`)
- Dashed for placeholder / empty states
- Dotted in compact tables (`1px dotted var(--bd)` for low-priority row separators)
- **Avoid border-radius > 4px.** The aesthetic is sharp. Pills can use 2-3px.
