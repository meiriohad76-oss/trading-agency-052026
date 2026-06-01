# 02 · User Workflow

A typical session in plain English. This is the journey both variations support; they differ in *how they lay it out*, not *what happens*.

## When the user shows up

Time: typically 9:00–10:30 local time, near US market open. The agent has been running cycles in the background; the current cycle (e.g. `C-14:32` UTC) has just produced its candidate set. The countdown shows ~13 minutes to the next cycle.

The user has a coffee. They sit down at the Pi. The cockpit is already open (kiosk mode).

## Phase 0: orient (5 seconds)

User looks at the top of the screen. They see:
- **Cycle ID + countdown** to next cycle
- **Mode badge**: `PAPER` (always, for v1)
- **Engine health**: e.g. "6 of 7 engines live" — they note the one stale engine but don't worry about it (the agent already wouldn't ship if a critical engine were down)
- **Market regime gauge**: BAL (balanced) — neutral day; no top-down edge

They form a one-sentence mental model: *"Balanced day, agent is healthy, let's see what it found."*

## Phase 1: candidates (60–120 seconds)

User scrolls the candidate list. Both variations rank by final conviction, top-down.

For each actionable candidate (status: `approved` by the agent), the user sees:
- **Ticker · sector**
- **Conviction needle** (visual) + score (number)
- **One-line evidence** ("CFO bought 4,200 sh @ $812.40 on 2026-05-02")
- **One-line risk** ("Valuation P/E at 90th percentile")
- **Status chip**: READY
- **Three buttons**: Approve · Defer · Reject

For each non-actionable candidate (demoted, blocked, rejected by policy):
- Same row, but greyed
- **Status chip** explains: LLM DEMOTED, BLOCKED, BELOW THRESHOLD
- **`audit ›`** link opens the lifecycle trace

**Typical user action:**
- Skim the top 3–5 rows
- For the first READY candidate: read the headline evidence, check the conviction needle is green, click **Approve**
- For the second: same. Maybe click the ticker to open the deep-dive panel (factor breakdown, LLM rationale, every policy gate). Approve.
- For a demoted one: curious why — click `audit ›`, read the timeline ("LLM cited thin earnings-rev evidence"), close. Move on.
- After 2–3 approvals: click **Advance to Portfolio**.

In Variation C (Mission Control), there is no "advance" button — the right column is already showing the staged manifest. Approving a candidate triggers a flying chip animation that visually moves it into the right column.

## Phase 2: portfolio (30–60 seconds)

User reviews existing positions. Five open positions. The agent has tagged each:

- **HOLD** (green) — setup intact, no action needed
- **REVIEW** (amber) — thesis softening; user should glance at it
- **CLOSE CANDIDATE** (red) — setup flipped; agent recommends exit

For HOLD positions: nothing to do.
For REVIEW: read the one-line thesis update, leave alone or mark KEEP / CLOSE.
For CLOSE CANDIDATE: read the agent's reason ("Setup flipped to NO_TRADE · Energy pressure now active"), click **Close** to confirm or **Keep** to override.

To the right, a **capacity check** shows how the staged trades + exits affect:
- Gross exposure (current → post-trade / cap)
- Per-sector exposure (with cap)
- Cash reserve (with floor)

If any cap or floor would be breached, the user sees an amber heads-up: *"Approving all 3 takes Tech to its 30% cap. No more Tech entries this week."*

## Phase 3: clearance (15–30 seconds)

The user reviews the staged manifest one last time. They see:
- **Exits first** (sells) — if any close decisions were made in Phase 2
- **Staged buys** — one row per approved candidate: ticker, qty, limit, notional, stop, target
- **Submit gate** panel

To submit:
1. Tick **"I want to open the submit gate"** → status flips from CLOSED (red) to OPEN (amber)
2. Type the phrase `submit paper orders` in the confirmation field
3. The **Submit** button becomes active (green, with a glow)
4. Click it. Orders go to the broker (paper account).

After submission:
- A "Cleared" / "Transmitted" success state
- Order IDs displayed (one per ticker)
- Confirmation that brackets (stop + target, OCO) are attached
- Reminder: next cycle in ~13 min

## After clearance

User walks away. The cockpit stays open in kiosk mode. Between cycles:
- The countdown ticks down
- The agent runs the next cycle in the background
- Positions update as fills land (the Portfolio Monitor panel shows the event stream)

The user can come back any time to check the Portfolio Monitor (continuous monitor / event log) — that's the "ambient" mode of the cockpit, and it's why `density=calm` exists. Between cycles, calm mode strips the loud chrome so the cockpit is a comfortable thing to glance at.

## The four scenarios

The "happy path" above is the **`normal`** scenario. Three others must also work — see `06-states.md`. Briefly:

- **`no-actionable`** — the agent ran but nothing cleared the bar. User skips Phase 1, glances at portfolio, done. (15 seconds total.)
- **`outage`** — engines are down. User sees a calm "selection blocked, no action possible" screen. They close the cockpit and come back later.
- **`submitted`** — already cleared this cycle. User sees the post-submit state.

The cockpit must handle these gracefully, not just the happy path. **Especially the outage case** — bad data should never reach the user as a stale-looking "ready" candidate. The agent breaks the circuit; the cockpit reflects that loudly.

## What this means for engineering

- **Session is short.** Total interaction time per cycle: 1–3 minutes. Optimize for that, not for 8-hour sessions.
- **The user is not multitasking.** They are giving the cockpit their full attention for a brief window. The interface can be dense.
- **Between cycles, the cockpit is wallpaper.** It must be visually quiet by default (calm mode) when no decision is pending.
- **Idempotency matters.** If the user reloads mid-session, their staged approvals should persist. The submit gate should not. (Detailed in `07-data-schema.md`.)
- **Network is local.** The agent runs on the same Pi. API latency is sub-10ms. Don't design for a slow network — but DO design for the *engine* being slow (LLM calls, broker handshake).
