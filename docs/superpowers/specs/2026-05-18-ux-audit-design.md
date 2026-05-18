# Trading Agency v2 — UX & Product Audit Design
**Date:** 2026-05-18
**Owner:** Ohad Meiri
**Status:** Approved — ready for Codex execution
**Output:** `docs/audit-findings.md` → `docs/audit-implementation-plan.md`

---

## Vision

A workflow-first audit of the Trading Agency v2 UI, structured around the user's 3-step daily workflow:

> **Candidates → Portfolio → Execute**

Every finding is evaluated against this workflow and the "Bottom Lines Up Front" (BLUF) principle: the user should get the answer they need in under 3 seconds per screen, with detail available on demand.

The audit produces a structured finding log (`docs/audit-findings.md`) that Codex uses directly to implement improvements — no interpretation needed.

---

## User Workflow (Yellow Brick Road)

The 3 steps the user takes every morning:

1. **See today's candidates** — What does the agency recommend I look at?
2. **Check current portfolio** — What do I hold, what should I exit to make room, what can I enter?
3. **Confirm orders** — Which orders are ready to place, and what do I need to do to confirm them?

All screens are evaluated by how well they support one of these steps — or how clearly they indicate they are secondary/supporting.

---

## Section 1 — Audit Rubric

### 1A — Four Scoring Dimensions

**BLUF (Bottom Lines Up Front)**
- Does the screen answer the user's core question in the first 3 seconds?
- Is the most important data visually dominant (size, color, position)?
- Is secondary/diagnostic data hidden behind progressive disclosure, not upfront?

**Yellow Brick Road**
- Does the screen have one clear "next step" that guides the user forward?
- Is navigation between the 3 core steps obvious?
- Are dead ends and orphan screens eliminated or deprioritized?

**Semi-Auto Readiness**
- What does the user have to *do* vs. what does the agent do automatically?
- Is every manual step reducible to a single approve/acknowledge action?
- Are agent outputs surfaced as decisions ready to confirm, not as raw data to interpret?

**Design System**
- Green = healthy/pass/actionable/profit · Red = blocked/rejected/loss · Yellow = attention/pending · Blue = informational/neutral
- Are icons and symbols self-explanatory without labels?
- Is typography hierarchy clear (headline → key number → supporting detail)?

### 1B — Severity Levels

| Level | Meaning |
|-------|---------|
| P0 | Blocks the workflow entirely — user cannot proceed |
| P1 | Degrades UX significantly — user can proceed but it's painful or confusing |
| P2 | Polish/improvement — nice to have for MVP |

### 1C — Finding Format

Every finding uses this exact structure:

```
AUDIT_FINDING
screen: <name>
category: <BLUF|Yellow Brick Road|Semi-Auto|Design System>
severity: <P0|P1|P2>
finding: <one sentence, specific and concrete>
evidence: <file:line or CSS class or route>
fix: <specific instruction — what to move, add, remove, or change>
acceptance: <one testable condition>
END_FINDING
```

No narrative. No general observations. Every finding must be actionable.

---

## Section 2 — Step 1: "See Today's Candidates"

**Screens:** Command dashboard · Final Selection · Candidate Detail
**Core question:** *What does the agency recommend I look at today?*

### 2A — Command Dashboard (`src/agency/templates/dashboard.html`)

- [ ] Is the review queue (candidates to approve) above the fold, or buried below status panels?
- [ ] Is there a single primary call-to-action ("Review X candidates") that the eye lands on first?
- [ ] Are the 5 overlapping readiness panels (Live Config, Provider Readiness, Live Readiness, Data Sources, Operational Checklist) consolidated or collapsed by default?
- [ ] Do candidate cards visually distinguish "Reviewable now" vs "Blocked" vs "Already decided" — with color + icon, not just text labels?
- [ ] Is there a visible "next step" link/button that takes the user to Step 2 (Portfolio) or Step 3 (Execute)?
- [ ] Is LLM disabled state surfaced clearly (not just blank columns)?

### 2B — Final Selection (`src/agency/templates/final_selection.html`)

- [ ] Is there a 3-number summary at the top: Selected / Blocked / No-Trade?
- [ ] Are candidates grouped by action (WATCH at top, NO_TRADE below, BLOCKED last)?
- [ ] Does each candidate card show: ticker + conviction score + top reason — nothing else by default?
- [ ] Is there a one-click path from any candidate row to its Candidate Detail page?
- [ ] Is color used to encode action meaning (green=WATCH, red=BLOCKED, grey=NO_TRADE)?

### 2C — Candidate Detail (`src/agency/templates/candidate_detail.html`)

- [ ] Is the recommendation (WATCH / NO_TRADE) and conviction score the largest element on the page?
- [ ] Are Approve / Defer / Reject buttons visible immediately (sticky or above the fold)?
- [ ] Is signal evidence split into two visual tiers: "Why it's here" (3–5 bullets, prominent) vs "Supporting detail" (collapsed)?
- [ ] Is Subscription Intelligence clearly labeled as "Email/article evidence" with: matched → opened → summarized → score impact — in that order?
- [ ] Are raw provenance fields (timestamp_as_of, source_count, verification_level) fully collapsed by default?
- [ ] Is there a clear "Back to candidates" or "Next candidate" navigation affordance?

---

## Section 3 — Step 2: "Check Current Portfolio"

**Screens:** Portfolio Monitor · cross-screen context
**Core question:** *What do I hold, what should I exit to make room, and what can I enter?*

### 3A — Empty State Design (`src/agency/templates/portfolio_monitor.html`)

- [ ] Does the empty state explain *why* it's empty ("No paper positions yet — approve your first candidate to see positions here")?
- [ ] Does the empty state give a direct action ("Go to Candidates →") so the user isn't stranded?
- [ ] Is the empty state visually calm — not alarming?

### 3B — MVP Position View (target state — audit what's missing, not what's broken)

- [ ] Exposure summary at top: Total exposure % · Cash available · Max allowed — 3 numbers, visually dominant
- [ ] Position cards: Ticker · Entry price · Current P&L (green=profit/red=loss) · Thesis still valid? · Stop distance
- [ ] Trailing stop within 5% of triggering → highlighted in red/amber
- [ ] Single policy compliance status: "Within limits" (green) or "Over exposure" (red)

### 3C — Exit Recommendations (semi-auto agent output)

- [ ] Dedicated "Exit Recommendations" panel — agent-generated, not user-derived
- [ ] Each recommendation shows: Ticker · Reason (plain English) · Exposure freed · Urgency (Now / Soon / Optional)
- [ ] Single "Exit" button per recommendation — no form to fill, just confirm
- [ ] Downstream effect shown: "Exiting MSFT frees 4% exposure → allows 1 new position"
- [ ] When no exits needed: "Portfolio within policy — no exits needed" displayed clearly

### 3D — Cross-Screen Context (Yellow Brick Road connections)

- [ ] Candidate Detail shows "Currently holding X shares" badge when ticker is in portfolio
- [ ] Command dashboard shows exposure warning when near policy limit, before user reviews candidates
- [ ] Portfolio Monitor has a clear path → Execute (for managing existing positions)
- [ ] Exit recommendations link back to the relevant Candidate Detail page

---

## Section 4 — Step 3: "Confirm Orders"

**Screens:** Risk dashboard · Execution Preview
**Core question:** *Which orders are ready to place, and what do I need to confirm?*

### 4A — Risk Dashboard (`src/agency/templates/risk.html`)

- [ ] Candidates grouped into 3 visual tiers — not a flat table:
  - "Ready to review" (WATCH + human approval pending) — top, green border
  - "Blocked by policy" — middle, red border
  - "Needs data" — bottom, grey/amber border
- [ ] Each risk card explains the block reason in plain English — not a status code
- [ ] Risk matrix available as a drill-down, not default view
- [ ] One-click path from "Ready to review" candidate directly to its Execution Preview row
- [ ] Agent-resolved risk checks shown as "Agent checked — OK" without burdening the user with detail

### 4B — Execution Preview (`src/agency/templates/execution_preview.html`)

- [ ] Paper-mode safety banner is reassuring ("Running in paper mode — no real money at risk") — not alarming
- [ ] Order summary is human-readable: "Buy 12 shares of AAPL at market · Est. cost $2,340 · 3.1% of portfolio"
- [ ] `submit_enabled=False` state clearly explained per-row — not just a greyed-out button
- [ ] Once approved (WATCH→ALLOW promoted), row visually changes to a clear "Ready — Submit" state with prominent green button
- [ ] Submit button is a single click with inline confirmation — not a separate page or modal
- [ ] "Submit all ready orders" bulk action available when multiple candidates are approved
- [ ] After submission: inline confirmation shown — not just a redirect

### 4C — Approval Flow (end-to-end semi-auto)

- [ ] Candidate Detail → Approve → review event recorded → WATCH promoted to ALLOW
- [ ] ALLOW promotion → Execution Preview row flips to `submit_enabled=True`
- [ ] Submit → Alpaca paper order placed → audit log updated → Portfolio Monitor reflects new position
- [ ] At each step: UI confirms what just happened — no silent state changes
- [ ] Number of clicks from "I want to approve this" to "order is placed" ≤ 3

### 4D — LLM Final Recommendation

- [ ] Each candidate in Execution Preview and Risk dashboard shows LLM recommendation inline with one-line rationale
- [ ] Deterministic score and LLM recommendation shown side by side — agreement or conflict visible at a glance
- [ ] LLM/rules conflict flagged visually (amber icon) — not just text
- [ ] LLM disabled state clearly stated per-row ("LLM review unavailable — rules-only") — not a blank column
- [ ] LLM rationale collapsible: one-line summary visible, full reasoning expandable
- [ ] LLM system status indicator on the page so user knows before reviewing

---

## Section 5 — Design System Audit

**Scope:** All 8 active screens · `src/agency/static/styles.css` · `src/agency/templates/base.html`
**Core question:** *Is the visual language consistent, self-explanatory, and meaningful across every screen?*

### 5A — Color Semantics

- [ ] Green used exclusively for: healthy, pass, actionable, profit
- [ ] Red used exclusively for: blocked, rejected, loss, danger
- [ ] Yellow/amber used exclusively for: attention needed, pending, review required
- [ ] Blue used exclusively for: informational, neutral, disabled, planned
- [ ] No screen uses the same color for two different meanings
- [ ] Positive P&L always green, negative always red — in tables, cards, and status strips
- [ ] "Paper mode only" elements visually distinct (consistent amber/dashed border system)

### 5B — Icons and Symbols

- [ ] Consistent icon for each status type across all screens:
  - ✅ Pass / healthy
  - ⚠️ Warning / attention
  - 🚫 Blocked / rejected
  - ⏳ Pending / loading
  - 🔒 Policy locked / paper-only
  - 📊 Data / evidence
  - 🤖 Agent / automated action
- [ ] Icons paired with color (not just shape) — legible for color-blind users
- [ ] Action buttons (Approve / Defer / Reject) differentiated by both color and icon
- [ ] Visual distinction between "agent did this automatically" vs "user action required here"

### 5C — Typography Hierarchy

- [ ] Every screen has one element that is clearly the largest/boldest — the headline answer
- [ ] Uppercase small labels reserved for secondary context — not used for primary data
- [ ] Conviction scores, P&L numbers, and order sizes displayed in larger font than their labels
- [ ] At least 3 distinct type sizes in use: headline · body · label
- [ ] Long technical strings (cycle_id, timestamps, hash values) always in monospace and always collapsed

### 5D — Progressive Disclosure

- [ ] Consistent expand/collapse pattern across all screens (same chevron, same animation, same label)
- [ ] Always collapsed by default: raw provenance fields · agent run metadata · full signal evidence · LLM prompt/response pairs
- [ ] Always visible by default: recommendation/action · conviction score · top 3 reasons · risk decision · order size and cost
- [ ] Collapsed state visually consistent across all 8 screens

### 5E — Navigation and Wayfinding

- [ ] Left nav highlights active screen clearly — not just a subtle underline
- [ ] Yellow brick road sequence (Candidates → Portfolio → Execute) represented in nav or as a progress indicator
- [ ] Disabled/placeholder screens (Universe, Signals, Learning) visually muted in nav
- [ ] Consistent breadcrumb or back-link pattern for drill-down pages (Candidate Detail)
- [ ] On mobile: nav collapses cleanly and yellow brick road remains followable

---

## Section 6 — Finding Log & Codex Brief

### 6A — Output File Structure (`docs/audit-findings.md`)

> Note: Section 1C defines the raw `AUDIT_FINDING` block format that each parallel agent emits. The consolidation agent (Phase 2) converts those blocks into the human-readable markdown below and writes `docs/audit-findings.md`.

```markdown
# Trading Agency v2 — UX & Product Audit Findings
Date: <date>
Rubric: docs/superpowers/specs/2026-05-18-ux-audit-design.md

## Summary
- P0 findings: X
- P1 findings: X
- P2 findings: X

## Implementation Order
[Ordered list: P0 → P1 by yellow brick road step → P2]

## Findings

### [F001] <One-line title>
- **Screen:** <name>
- **Category:** <BLUF|Yellow Brick Road|Semi-Auto|Design System>
- **Severity:** P0|P1|P2
- **Finding:** <one sentence>
- **Evidence:** `<file:line>`
- **Fix:** <specific Codex instruction>
- **Acceptance:** <one testable condition>
```

### 6B — Grouping and Ordering Rules

1. All P0 findings first, ordered by yellow brick road step (Step 1 → Step 2 → Step 3 → Design System)
2. All P1 findings, same ordering
3. All P2 findings, same ordering
4. Findings that share a template file are adjacent so Codex can batch edits in one pass

### 6C — Codex Execution Plan

```
Phase 1 — Parallel audit agents (run simultaneously):
  Agent A: Section 2 audit — reads dashboard.html, final_selection.html, candidate_detail.html
  Agent B: Section 3 audit — reads portfolio_monitor.html + cross-screen refs
  Agent C: Section 4 audit — reads risk.html, execution_preview.html, services/risk.py, services/execution_preview.py
  Agent D: Section 5 audit — reads all 8 templates + styles.css + base.html

Phase 2 — Consolidation agent (after all 4 complete):
  Reads all 4 agent outputs
  Assigns finding IDs (F001, F002 ...)
  Deduplicates cross-screen findings
  Orders by severity + yellow brick road step
  Writes docs/audit-findings.md

Phase 3 — Implementation plan agent (after consolidation):
  Reads docs/audit-findings.md
  Groups findings by template file
  Writes docs/audit-implementation-plan.md with one Codex task per finding or file batch
```

### 6D — Audit Agent Context

Each agent prompt must include:
- The rubric from Section 1 (4 dimensions + severity levels)
- The checklist for its assigned section
- The actual template file contents
- The finding output format from 1C
- Instruction: *"For every checklist item that fails, write one AUDIT_FINDING block. For items that pass, write nothing. Be specific about file:line."*

---

## Appendix — Screen Inventory

| Screen | Template | Yellow Brick Road role |
|--------|----------|----------------------|
| Command | `dashboard.html` | Step 1 entry point |
| Final Selection | `final_selection.html` | Step 1 candidate list |
| Candidate Detail | `candidate_detail.html` | Step 1 decision page |
| Portfolio Monitor | `portfolio_monitor.html` | Step 2 |
| Risk | `risk.html` | Step 3 |
| Execution Preview | `execution_preview.html` | Step 3 confirmation |
| Audit | `audit.html` | Supporting |
| Policy | `policy.html` | Supporting |
| Learning | `learning.html` | Placeholder |
| Market Regime | `market_regime.html` | Supporting |
