# 06 · States & Scenarios

The cockpit must handle four scenarios in addition to the happy path. The prototype's Tweaks panel exposes them under "Scenario" — try each:

| Scenario | When it happens | What the user sees |
|---|---|---|
| `normal` | The expected daily case | Full cockpit, candidates available, normal flow |
| `no-actionable` | Agent ran but nothing met the bar | Single-screen empty state, skip-to-portfolio shortcut |
| `outage` | Critical engines are down | Full-bleed alert, no candidates, retry countdown |
| `submitted` | Already cleared this cycle | Post-submit success state |

All four must be implemented. None of them are "rare" — `no-actionable` happens roughly 1-2 days a week in normal market conditions, and `outage` is the safety case the user trusts the cockpit on.

## `normal` — the happy path

This is everything in `02-user-workflow.md`. The default state. The prototype starts here.

**Initial decisions** (for demoability): NVDA + HD pre-approved. UNH ready to approve. XOM marked for close in portfolio. This is a reasonable mid-session state — the user has started but hasn't finished.

For the real product: **initial decisions should be empty.** The user starts fresh each cycle. Persistence is per-cycle, not across cycles. (See `07-data-schema.md → session state`.)

## `no-actionable` — low-conviction day

The agent ran the full funnel and **nothing cleared the bar.** This is normal, healthy behaviour — not a bug. The cockpit needs to communicate this clearly.

### Variation A's `no-actionable`

Single-screen replacement of Phase 1 content (instrument cluster + engines + nav + phase rail still visible):

- **Headline:** "Nothing actionable today. Skip ahead — the agent already filtered."
- **Sub:** "Scanned 152 tickers. 10 reached final review. None met the conviction bar..."
- **Right-side button:** "Skip to Portfolio →"
- **Below:** a 3-card explanation of the closest candidates and why each fell short (e.g. "AAPL · LLM DEMOTED · reviewer cited thin earnings revision evidence")
- **Bottom:** "Agent note ›" — a calm paragraph confirming this is expected for a balanced day

**Visual tone:** not alarming. The agent did its job. The user's job is short today.

### Variation C's `no-actionable`

All three columns still visible, but Stage 01 (Candidates) shows the empty state:

- Stage 01 column: amber-tinted card — "● NO ACTIONABLE · Funnel completed. Bar not cleared." Below: same 3-card explanation
- Stage 02 column: unchanged — portfolio is still active, the user still reviews positions
- Stage 03 column: empty manifest state — "◯ Manifest empty. No orders staged this cycle. The clearance gate stays closed." + cyan note explaining low-conviction days are normal

## `outage` — engines down

Critical engines (MARKET_DATA, FUNDAMENTALS) are offline. The agent has tripped its circuit breaker and refuses to surface candidates. **This is a safety feature, not a failure to communicate to the user.**

### Variation A's `outage`

Full-bleed replacement (only TopBar remains):

- **Banner:** "◉ SELECTION BLOCKED · CYCLE C-14:32" (red)
- **Headline:** "Two critical engines are down. No candidates can be cleared this cycle."
- **Body:** "The agent will retry automatically. You can leave the cockpit and come back — there's nothing to action right now."
- **Two engine cards:** Market data + Fundamentals API, each with red dot, "OFFLINE" label, detail
- **Bottom strip:** auto-retry countdown (amber) + last successful cycle time

### Variation C's `outage`

Two-column replacement (telemetry strip remains):

- **Left:** the BLUF — red banner, headline, retry / last-good-cycle info
- **Right:** engine telemetry table — every engine with a state code (CONN_LOST / UPSTREAM_5XX / BLOCKED / OK). Includes LIVE engines (POLICY, RISK_MONITOR, AUDIT_LOG) to communicate that the system itself is healthy — just the data feeds are out.

**Visual tone:** calm, not panicked. The cockpit is *informing*, not alarming. **Specifically, do NOT use blinking, sirens, sound, or shake animations.** This is a "the agent has it" moment.

## `submitted` — post-clearance

Orders have been sent to the broker. The user could close the cockpit; they should also see confirmation first.

### Variation A's `submitted`

Phase 4 (Cleared) state — see `03-variation-a.md`. Big green check, "{n} orders submitted." Order cards strip, total notional, next cycle reminder. `[Start over]` button.

### Variation C's `submitted`

Clearance column switches to the "submitted pane." All three columns visible, but Candidates + Portfolio are **dimmed to 42% opacity** (greyscale-saturated). Clearance stays bright.

The submitted pane: centered ring check, "▸ TRANSMITTED" label, count + brackets-attached confirmation, then one card per accepted order (ticker · ACCEPTED chip · broker ID · BUY {qty} @ {price}).

**No "start over" button in C** — the next cycle takes care of it. The cockpit will refresh on its own. (For implementation: when a new cycle starts, the dim clears and Candidates becomes active again.)

## State transitions in the real product

The prototype lets the user click between scenarios via the Tweaks panel. In the real product, scenario is **determined by the backend**:

- The agent emits a `cycle` payload with a `scenarioHint` field
- The cockpit renders accordingly
- The hint can change mid-session if engines go down — the cockpit must handle live transitions (e.g. user is in Phase 2 portfolio when the data feed dies → cockpit transitions to outage)

**[CONFIRM]** with the human: what happens to staged decisions if an outage hits mid-session? Cleanest answer: **decisions persist locally** (they're not committed yet), the cockpit shows outage, when feeds recover the user returns to their pre-outage state. But this needs product confirmation.

## Edge cases the prototype doesn't show

- **All candidates approved.** Variation A: the "Advance" button just says "Advance" (no special copy). Variation C: the Stage 01 header reads e.g. "3/3 cleared".
- **Portfolio with zero positions** (fresh account). Skip Phase 2 entirely? Or show an empty state? **[CONFIRM]** — currently both variations would show 0 rows and the capacity check would show all zeros.
- **Submitted state when only exits, no buys** (selling, not buying). The clearance manifest shows the exits section but no buys. Submit button text should adapt: `▸ TRANSMIT · 1 EXIT · $0K` → `▸ TRANSMIT · 1 SELL ORDER`.
- **Mixed approved + blocked** — what if the user approves a candidate that then gets blocked by a policy change? Decisions become invalid. **[CONFIRM]** — likely: revalidate at submit time, show a warning, let the user re-approve.

## Visual state checklist (for QA)

For each variation, every scenario should be visually checked:
- [ ] `normal` — phase 1 candidates
- [ ] `normal` — phase 2 portfolio
- [ ] `normal` — phase 3 clearance, gate closed
- [ ] `normal` — phase 3 clearance, gate open, phrase not yet typed
- [ ] `normal` — phase 3 clearance, gate open, phrase correct, submit ready
- [ ] `normal` — phase 4 / submitted
- [ ] `no-actionable` — main view
- [ ] `outage` — main view
- [ ] `submitted` — main view (post-clearance)
- [ ] All 6 instrument panels open / close

Plus density modes (full / calm) and color presets (amber / duotone / saturated) × theme presets (dark / accent / light). That's 18 × 3 × 3 = 162 visual permutations, but many compose — verify by spot-check.
