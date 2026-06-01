# 04 · Variation C — Mission Control

**Aesthetic:** NASA mission control / launch console — three columns, dense telemetry strip on top, status grid on bottom. Amber on near-black, with cyan secondary. Reads like a launch director's console.

**Layout pattern:** **parallel**. All three phases (Candidates · Portfolio · Clearance) are visible simultaneously as three columns. The user works left-to-right but can see consequences immediately on the right.

**When to choose C over A:**
- User is comfortable with dense interfaces (or this is their second tool, not their first)
- They want to see "what will happen if I approve this" without clicking through phases
- The visual feedback (fly-to-manifest chip) is a delightful pay-off for the denser layout
- Better for the "ambient" use case — the cockpit as a standing dashboard between cycles

**File:** `Variation C.html` (standalone) · `cockpit/variation-c-mission.jsx` (source)

## Anatomy

```
┌─────────────────────────────────────────────────────────────────────────┐
│  TELEMETRY STRIP                                                         │
│  ◎ AGENCY MISSION CTRL  | SPY+2.4% VIX 14.8 Breadth 62% Gross 67→84% ...│ ← live
│  t-C-14:32 next-12:43   |              [Approved: 3] [To exit: 1]       │   data
│                          | [U][S][A][P][M]  [PAPER]                      │   nav
├─────────────────────────┬─────────────────────┬─────────────────────────┤
│ STAGE/01 · CANDIDATES   │ STAGE/02 · PORTFOLIO│ STAGE/03 · CLEARANCE    │
│ ─────────────────────── │ ─────────────────── │ ─────────────────────── │
│ Funnel crumbs · ranked  │ Mini-meters: gross / │ Status: gate · CLOSED  │
│ list · selection detail │ cash / sector caps   │ Manifest preview        │
│ pane                    │                      │ Submit gate             │
│                         │ 5 position rows      │                         │
│ ▸ NVDA  0.78 ●          │ ─────────────────── │ EXITS · FIRST           │
│   HD    0.69 ●          │ Sector heatmap       │ ▼ SELL · XOM            │
│   UNH   0.65 ●          │ (11 sectors)         │                         │
│   ...                   │                      │ STAGED · BUY            │
│                         │                      │ NVDA · HD · UNH         │
│ ┌─ selected ────────┐   │                      │                         │
│ │ NVDA   det/llm •• │   │                      │ [open gate ☐]           │
│ │ evidence pack     │   │                      │ [type: submit paper..] │
│ │ risk flags        │   │                      │ [▸ TRANSMIT 3 ORDERS]  │
│ │ [reject][defer][✓]│   │                      │                         │
│ └───────────────────┘   │                      │                         │
├─────────────────────────┴─────────────────────┴─────────────────────────┤
│ RUNTIME ENGINE STRIP  ● UNIVERSE ● FUND ● REGIME ● SIGNALS ◐ 13F · ...  │
└─────────────────────────────────────────────────────────────────────────┘
```

## The three columns

Each column has the same anatomy:
- **Header strip** with stage label (`STAGE/01` mono), title, summary
- **Body** — the column's content
- **Active state** — the active column gets a brighter background, amber underline, and full opacity
- **Dimmed state** — non-active columns are at 42% saturation when something is mid-flight (after submission, the candidates + portfolio columns dim out and clearance stays bright)

### Stage 01 — Candidates

**Header:** stage label · "Candidates" · "{approved}/{actionable} cleared" · funnel crumbs strip

**Body split** (320px top / rest bottom):
- **Top: ranked list** — compact rows with index, ticker, conviction bar (vertical), one-line evidence, status dot. Click selects.
- **Bottom: detail pane** — the selected candidate's full breakdown:
  - Ticker · sector · price · earnings days · DET/LLM dots
  - Det score chip / LLM score chip
  - Evidence rows (CONF / INF badges)
  - Risk flags (if any)
  - LLM rationale (cyan-tinted, italic)
  - Three decision buttons: Reject / Defer / Approve · stage

**Selection:** clicking any row in the list updates the detail pane. The selection state persists across scenarios.

### Stage 02 — Portfolio

**Header:** stage label · "Portfolio" · "5 pos · {n} exit" · three mini-meters (Gross / Cash / Tech sector)

**Body:**
- **Position rows** (5) — each has ticker · status tag · P/L · thesis · keep/close buttons (only for non-HOLD)
- **Sector heatmap** — 2-column grid showing all 11 sectors, color-coded:
  - Green = tailwind
  - Red = pressure
  - Grey = neutral
  - Faded = unavailable

The heatmap is **important context** — it's why the agent is tagging some positions REVIEW or CLOSE. Don't hide it.

### Stage 03 — Clearance

**Header:** stage label · "Clearance" · gate status · order count + total notional

**Body** (top to bottom):
- **Exits first** (if any closes staged) — red-tinted block listing SELL orders
- **Staged orders · BUY** — one row per approved candidate (ticker · BUY {qty} @ {price} · stop/target · notional)
- **Submit gate** panel — same logic as Variation A's gate, more compact:
  - Section header: "SUBMIT GATE · ARMED?"
  - Open gate checkbox (changes "○ SAFE" to "● ARMED")
  - Confirmation phrase input
  - Big TRANSMIT button: `▸ TRANSMIT · 3 ORDERS · $19K`
  - Flags footer

After submission: switch to the **submitted pane** — centered check mark, "▸ TRANSMITTED", one card per accepted order with broker ID.

## The telemetry strip (top, always visible)

Four-column grid: brand · live metrics · approval counters · panel nav.

**Brand block (left):**
- Crosshair logo (SVG) + "AGENCY · MISSION CTRL"
- Sub-line: `t-C-14:32 · next-12:43 · 2026-05-22` (cycle id + countdown + date)

**Live metrics (center, wraps if needed):**
- SPY 20d (e.g. +2.4%, green)
- VIX (14.8)
- Breadth (62%, green)
- Gross (67 → 84%, amber if approaching cap) — with `?` tooltip
- Cash (18%) — with tooltip
- Open ord. (2/5)

**Approval counters (right):**
- Approved (3, green, big-styled chip)
- To exit (1, red if > 0, big-styled chip)

**Panel nav (far right):**
- 5 single-letter buttons: U / S / A / P / M (Universe / Signals / Audit / Policy / Monitor) — each ≤ 26px square
- PAPER mode badge

The whole strip is dense by design. It's the **standing context** the user references between micro-decisions. **Calm mode hides the middle metrics block** — keeps only brand + counters + nav. (See `08-tweaks.md → density`.)

## The footer engine strip

Single horizontal row at the very bottom, listing every engine as a tiny chip:
```
● UNIVERSE REGISTR  ● FUNDAMENTALS  ● MARKET REGIME  ● SIGNALS  ● DETERMINISTIC
● LLM (GPT-5.4-MIN  ◐ INSTITUTIONAL  …                           RUNTIME_OK · 6/7
```

Engine names are uppercased and truncated to 14 chars. The aesthetic is "telemetry banner" — same energy as the bottom of a launch console. **Calm mode hides this row.**

## The signature animation: fly-to-manifest

When the user approves a candidate, a **flying chip** spawns from the click position and animates toward the right column (clearance), landing in the manifest area.

- Chip is green with the ticker symbol: `▸ NVDA`
- 700ms animation: translate + scale-down + fade-out
- The chip is **on top of the layout** (z 60) and doesn't affect layout
- Cleared 750ms after spawn

This animation is **the payoff** of the three-column design. It makes the cause→effect visible. Don't cut it — it's small in code (single CSS keyframe) and worth a lot in feel.

## Auto-advance behaviour

The active column auto-advances based on user activity:
- Start: Stage 01 active
- First approval → Stage 02 active (or Stage 03 if exits were also staged)
- Clicking inside a column makes it active

This is **subtle navigation** — the user doesn't have to manage stages, but the visual cue (brighter background, amber underline) tells them where the system thinks they are.

Submitted state: all three columns dim except clearance (which goes to the success pane).

## Variation C's strength + weakness

**Strength:** **simultaneity.** The user sees the consequence of every decision in real-time. Approve NVDA → it appears in the clearance column → the telemetry strip's "Approved" counter ticks up → the portfolio mini-meter ticks up → if it would breach a cap, the meter turns amber. The whole system breathes together.

**Weakness:** **density.** First-time users may feel overwhelmed. There's no progressive disclosure — it's all there at once. The calm-mode density toggle is partial mitigation, but Variation C is not the right choice if the audience needs hand-holding.
