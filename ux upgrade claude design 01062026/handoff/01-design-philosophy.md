# 01 · Design Philosophy

This is the lens. Every visual choice, every interaction, every word of copy traces back to one of the principles below. When you find yourself adding a button, removing a label, picking a color, or wiring an animation — check this doc.

## The user

**A single human operator running a paper-trading agent on a Raspberry Pi at home.** They are not a high-frequency trader. They are not glued to the screen. They open the cockpit **once or twice a day** — typically near the market open — to review what the agent wants to do and approve or reject it. Then they close it.

This is **not Bloomberg.** This is not a real-time monitoring station. It is a **briefing room**: the agent has done the work, the operator reviews, decides, signs off.

## The core idea: agent does the work, human signs the order

The agent (running on the Pi, between cycles) ingests data, ranks candidates, applies policy, drafts a manifest. **When the human shows up, the work is already done.** Their job is to:

1. **Audit** — was the reasoning sound? Is the evidence credible?
2. **Decide** — approve / defer / reject each candidate
3. **Clear** — sign off on the manifest as a final, considered act

Every screen serves this loop. We are not building a trading terminal where the user constructs trades. We are building **a cockpit where the user clears a pre-flight checklist the agent prepared.**

## Five principles

### 1. BLUF — Bottom Line Up Front

Every screen opens with a single declarative sentence stating the decision in front of the user. Not a header. Not a category. A sentence.

- ✅ "3 trades ready. Approve what you want to ship today."
- ✅ "Nothing actionable today. Skip ahead — the agent already filtered."
- ❌ "Candidates" *(label, not a decision)*
- ❌ "Daily Review Dashboard" *(named the screen, not the situation)*

If the user reads only the headline and then walks away, they should know what the situation is and what their next move is.

### 2. Provenance is the product

The agent's value proposition is **trust through transparency.** Every recommendation must be traceable to the evidence that produced it. Every block must cite the policy rule that triggered it. Every score must come with the inputs that drove it.

This means:
- Confirmed evidence (filings, paid subs, sector ETFs) is visually distinct from inferred evidence (volume bars, options flow).
- Every candidate row exposes a one-line evidence summary in the resting state, and a full evidence pack on expand.
- Policy blocks state the rule and the value: "Financials sector exposure at 30% cap." Not "Blocked."
- Audit panel is one click away, always.

The visual rhythm of the design is **claim → evidence → score.** Never just "score."

### 3. Gated, not blocked

The submit gate is a **deliberate friction surface**. It is not security theater — it's the design saying "this is the moment that matters; slow down."

The pattern: **checkbox to arm, type a phrase to confirm, then submit becomes possible.** Three small actions, none of them difficult, but together they make accidental submission essentially impossible.

This pattern should appear nowhere else in the app. **Friction must be rare to be meaningful.** Every other action is one click.

### 4. Calm dense, not anxious dense

The aesthetic is **instrument-cluster dense**: lots of numbers, lots of state, all at once, but the user is not meant to feel anxious. They're meant to feel *informed.* Compare to a pilot's panel — there's a lot on it, but a pilot doesn't feel panicked when they look at it.

How we achieve this:
- **Monospace for all numbers** (tabular alignment; no jitter as values change)
- **One amber accent** carries attention; everything else recedes
- **Status by color, not just by label** (green/amber/red/dim grey)
- **No animations except where they encode change** (countdowns, value transitions, the fly-to-manifest chip in Variation C)
- **No motion ambient noise** (no spinning gradients, no breathing logos, no parallax)

The "calm" density mode (`density=calm`) strips chrome further — drops the gauges, kills glows, hides the engine strip. It's for users who want to keep the cockpit open in the background between cycles without ambient visual load.

### 5. Reversibility before irreversibility

Anything that can be undone is one click. **Submission cannot be undone**, so it gets three steps (gate / phrase / button). Everything else — approve, defer, reject, mark-for-close, mark-for-keep — is a single click and reversible until clearance.

Approvals are *staged*, not committed, until the submit gate opens. The right column / right panel always shows the current state of the staged manifest. Nothing crosses the line into "the broker received this" until the gate is open and the button is pressed.

## What's *not* in this design (and why)

- **No charts.** The agent is the analyst. The user is not staring at candles. If the user finds themselves wishing for a chart, the evidence pack failed.
- **No watchlists, no custom screens, no "set up your own dashboard."** The agent decides what the user sees. Customization is a distraction.
- **No social features.** Not a trading community.
- **No news feed.** News enters through the signal lane (provenance-rated), not as ambient scroll.
- **No real-time tick streams during review.** The ticker tape in earlier mocks was removed — it adds anxiety without informing the decision. Prices are quoted point-in-time at cycle start.
- **No live trading.** Paper only. The `LIVE_TRADING` flag is locked off in the policy panel and **must stay that way** for v1.

## Negotiable vs not

**Not negotiable** (these are the design):
- The 3-phase workflow (Candidates → Portfolio → Clearance) — both variations express it
- The gated submit pattern (checkbox + phrase + button)
- Provenance hierarchy (confirmed > inferred > suppressed)
- BLUF headlines on every primary screen
- Amber as the primary accent
- Monospace for all numbers
- Paper-only for v1

**Negotiable** (use judgment, ask if unsure):
- Exact pixel spacing — match the prototype within reason
- Exact copy — preserve voice (terse, direct, never cute), tighten if better
- Animation timings — feel matters more than the exact ms
- Component implementation (CSS-in-JS vs CSS modules vs Tailwind) — pick one and stay consistent
- Whether the Tweaks panel ships in-app or as a settings screen — prototype has it floating; product can have it elsewhere

## When you have to choose

If you find yourself adding a feature the prototype doesn't show: **don't.** The prototype is the scope. If the agent's behaviour requires a UI affordance that isn't there, raise it as a question — don't quietly invent.

If you find yourself removing something the prototype shows: **also don't.** Everything is load-bearing. The dense telemetry strip in Mission Control is not decoration; it's the standing context that frames every decision. The conviction needle next to each candidate is not redundant with the score number; it's the at-a-glance read for skim-scanning.

When in doubt: **preserve the prototype, ask the human.**
