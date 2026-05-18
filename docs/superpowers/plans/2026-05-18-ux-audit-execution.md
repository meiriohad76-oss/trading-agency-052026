# UX & Product Audit — Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a workflow-first UX audit of Trading Agency v2, produce `docs/audit-findings.md` with structured Codex-ready findings, then generate `docs/audit-implementation-plan.md` as the input for UX improvement work.

**Architecture:** Four parallel audit agents each read a defined set of template/service files and emit `AUDIT_FINDING` blocks. A consolidation agent merges them into a single ordered finding log. An implementation plan agent converts that log into a Codex task list grouped by file.

**Tech Stack:** Jinja2 templates (`src/agency/templates/`), CSS (`src/agency/static/styles.css`), Python services (`src/agency/services/`), FastAPI routes (`src/agency/dashboard.py`).

---

## Rubric Reference (carry into every audit task)

### Four dimensions

**BLUF:** Does the screen answer the user's core question in ≤ 3 seconds? Is the most important data visually dominant? Is secondary/diagnostic data hidden behind progressive disclosure?

**Yellow Brick Road:** Does the screen have one clear next step? Is navigation between the 3 core steps (Candidates → Portfolio → Execute) obvious? Are dead ends eliminated?

**Semi-Auto:** Is every manual step reducible to approve/acknowledge? Are agent outputs surfaced as ready-to-confirm decisions, not raw data?

**Design System:** Green = healthy/pass/actionable/profit. Red = blocked/rejected/loss. Yellow = attention/pending. Blue = informational/neutral. Icons self-explanatory. Typography hierarchy clear.

### Severity

- `P0` — blocks the workflow entirely
- `P1` — degrades UX significantly, user can proceed but it's painful
- `P2` — polish, nice to have for MVP

### Finding format (emit one block per failing checklist item)

```
AUDIT_FINDING
screen: <screen name>
category: <BLUF|Yellow Brick Road|Semi-Auto|Design System>
severity: <P0|P1|P2>
finding: <one sentence, specific and concrete>
evidence: <file:line or CSS class or route>
fix: <specific instruction — what to move, add, remove, or change>
acceptance: <one testable condition>
END_FINDING
```

**Rule:** For every checklist item that fails, write one `AUDIT_FINDING` block. For items that pass, write nothing. Be specific about `file:line`.

---

## Task 1 — Setup: Verify Source Files and Create Output Stubs

**Files:**
- Read: `src/agency/templates/` (verify 13 files present)
- Create: `docs/audit-findings-s2.md`, `docs/audit-findings-s3.md`, `docs/audit-findings-s4.md`, `docs/audit-findings-s5.md`

- [ ] **Step 1.1: Verify all source files exist**

Run:
```powershell
Get-ChildItem src/agency/templates/*.html | Select-Object Name
Get-Item src/agency/static/styles.css
Get-Item src/agency/services/risk.py
Get-Item src/agency/services/execution_preview.py
```

Expected: 13 `.html` files listed; styles.css, risk.py, execution_preview.py all found. If any are missing, stop and report.

- [ ] **Step 1.2: Create output stub files**

Create `docs/audit-findings-s2.md`:
```markdown
# Section 2 Audit Findings — Candidates Flow
Agent: A | Date: 2026-05-18 | Status: IN PROGRESS
Screens: Command dashboard · Final Selection · Candidate Detail
```

Create `docs/audit-findings-s3.md`:
```markdown
# Section 3 Audit Findings — Portfolio
Agent: B | Date: 2026-05-18 | Status: IN PROGRESS
Screens: Portfolio Monitor · cross-screen context
```

Create `docs/audit-findings-s4.md`:
```markdown
# Section 4 Audit Findings — Confirm Orders
Agent: C | Date: 2026-05-18 | Status: IN PROGRESS
Screens: Risk dashboard · Execution Preview · LLM recommendation
```

Create `docs/audit-findings-s5.md`:
```markdown
# Section 5 Audit Findings — Design System
Agent: D | Date: 2026-05-18 | Status: IN PROGRESS
Scope: All 8 templates · styles.css · base.html
```

- [ ] **Step 1.3: Commit stubs**

```bash
git add docs/audit-findings-s2.md docs/audit-findings-s3.md docs/audit-findings-s4.md docs/audit-findings-s5.md
git commit -m "audit: create finding stubs for sections 2-5"
```

---

## Tasks 2–5 — Parallel Audit Agents

> **Run Tasks 2, 3, 4, and 5 simultaneously.** They read non-overlapping files and write to separate output files. Dispatch all four before waiting for any to complete.
> If an agent finds zero failing checklist items for its section, it writes "No findings." to its stub file and commits. That is a valid, expected result.

---

## Task 2 — Agent A: Audit Section 2 — Candidates Flow

**Files:**
- Read: `src/agency/templates/dashboard.html`
- Read: `src/agency/templates/final_selection.html`
- Read: `src/agency/templates/candidate_detail.html`
- Read: `src/agency/dashboard.py` (route context)
- Write: `docs/audit-findings-s2.md`

- [ ] **Step 2.1: Read and map dashboard.html**

Read the full file. Identify:
- Line number where the review queue / candidate list begins
- Line number where each readiness panel begins (Live Config, Provider Readiness, Live Readiness, Data Sources, Operational Checklist)
- Line number of the hero/banner section
- Any call-to-action buttons and their labels

- [ ] **Step 2.2: Audit dashboard.html against checklist 2A**

Check each item. For every failure, append one `AUDIT_FINDING` block to `docs/audit-findings-s2.md`.

Checklist 2A:
1. Is the review queue above the fold (before any readiness panels in DOM order)?
2. Is there a single primary CTA ("Review X candidates") that renders first visually?
3. Are the 5 readiness panels collapsed by default (inside `<details>` or hidden with CSS)?
4. Do candidate cards have distinct visual treatment for "Reviewable", "Blocked", "Already decided" — using both color class AND icon, not text labels alone?
5. Is there a link/button labeled for the next yellow brick road step (Portfolio or Execute)?
6. When LLM is disabled, is there an explicit banner/indicator (not blank columns)?

Example finding for a failing item:
```
AUDIT_FINDING
screen: Command dashboard
category: BLUF
severity: P0
finding: Review queue section renders after 4 readiness panels; user must scroll past 300px of status data before seeing candidates
evidence: src/agency/templates/dashboard.html:142 — div.review-queue rendered after div.provider-readiness
fix: Move the review-queue div to immediately after the hero banner (before any readiness panel). Wrap all 5 readiness panels in a single <details> element with summary="System Status — all checks passed" collapsed by default.
acceptance: Opening http://localhost:8000/ on a 1080p screen shows candidate cards without scrolling.
END_FINDING
```

- [ ] **Step 2.3: Read and audit final_selection.html against checklist 2B**

Read the full file. Check each item:

1. Is there a 3-number summary row at the top (Selected count / Blocked count / No-Trade count)?
2. Are candidates visually grouped by action — WATCH section first (green), NO_TRADE second (grey), BLOCKED last (red)?
3. Does each candidate card/row show only: ticker + conviction score + top reason by default (no raw signal data visible)?
4. Is there a direct link from each candidate row to `/candidates/<ticker>`?
5. Does the action column/badge use color (not just text) to encode WATCH/BLOCKED/NO_TRADE?

For every failure, append an `AUDIT_FINDING` block to `docs/audit-findings-s2.md`.

- [ ] **Step 2.4: Read and audit candidate_detail.html against checklist 2C**

Read the full file. Check each item:

1. Is the recommendation (WATCH / NO_TRADE) and conviction score the first and largest element in the `<main>` or content area (check font-size class and DOM position)?
2. Are Approve / Defer / Reject buttons either (a) sticky-positioned or (b) visible without scrolling on a 1080p screen?
3. Is signal evidence split into two tiers — a short "Why it's here" summary (≤5 items, always visible) and a "Supporting detail" section in a `<details>` element?
4. Is the Subscription Intelligence section labeled "Email/article evidence" with subheadings: Matched → Opened → Summarized → Score impact — in that order?
5. Are ALL of these fields inside a collapsed `<details>` element by default: `timestamp_as_of`, `source_count`, `verification_level`, `run_id`, `input_snapshot_id`?
6. Is there a "Back to candidates" link or "Next candidate" navigation element?

For every failure, append an `AUDIT_FINDING` block to `docs/audit-findings-s2.md`.

- [ ] **Step 2.5: Update stub header to COMPLETE**

Edit the first line of `docs/audit-findings-s2.md` to change `Status: IN PROGRESS` to `Status: COMPLETE`.

- [ ] **Step 2.6: Commit**

```bash
git add docs/audit-findings-s2.md
git commit -m "audit: Section 2 findings — candidates flow (Agent A)"
```

---

## Task 3 — Agent B: Audit Section 3 — Portfolio Monitor

**Files:**
- Read: `src/agency/templates/portfolio_monitor.html`
- Read: `src/agency/templates/candidate_detail.html` (for cross-screen badge check)
- Read: `src/agency/templates/dashboard.html` (for exposure warning check)
- Read: `src/agency/services/portfolio_monitor.py` (if exists; check for exit recommendation logic)
- Write: `docs/audit-findings-s3.md`

- [ ] **Step 3.1: Read portfolio_monitor.html and map its structure**

Read the full file. Identify:
- Is there any content beyond the empty-state placeholder?
- What text/copy is used in the empty state?
- Is there any link or CTA in the empty state?
- Is there any position display, exposure panel, or exit recommendation panel?

- [ ] **Step 3.2: Audit empty state (checklist 3A)**

Check each item. Append `AUDIT_FINDING` blocks for failures to `docs/audit-findings-s3.md`:

1. Does the empty state copy explicitly explain *why* it's empty — e.g., "No paper positions yet — approve your first candidate to see positions here" — rather than a generic "No data" or blank?
2. Does the empty state include a direct CTA linking to Candidates (e.g., "Go to Candidates →")?
3. Is the empty state visually calm — no red/amber colours, no error-style iconography?

- [ ] **Step 3.3: Audit MVP position view gap (checklist 3B — target state)**

These items audit what is MISSING from the template, not what is broken. Each missing element is a P1 finding.

Check whether the template contains:

1. An exposure summary section showing 3 numbers: total exposure %, cash available, max allowed. If absent → P1 finding.
2. Position cards with: ticker, entry price, P&L (with green/red colouring), thesis-validity indicator, stop distance. If absent → P1 finding.
3. A trailing-stop proximity alert (highlight when stop is within 5% of triggering). If absent → P1 finding.
4. A single policy compliance status indicator ("Within limits" / "Over exposure"). If absent → P1 finding.

- [ ] **Step 3.4: Audit exit recommendations panel (checklist 3C)**

Check whether the template contains an agent-generated exit recommendation panel:

1. A named "Exit Recommendations" section or panel. If absent → P0 finding (this is the core semi-auto feature for Step 2).
2. Per-recommendation fields: ticker, plain-English reason, exposure freed, urgency (Now/Soon/Optional). If absent → P0 finding.
3. A single confirm button per recommendation. If absent → P0 finding.
4. A downstream effect line ("Exiting X frees Y% → allows 1 new position"). If absent → P1 finding.
5. A "no exits needed" state copy. If absent → P1 finding.

- [ ] **Step 3.5: Audit cross-screen context (checklist 3D)**

Check candidate_detail.html for:
1. A "Currently holding X shares" badge or indicator when ticker is in portfolio. If absent → P1 finding. Evidence: `src/agency/templates/candidate_detail.html`.

Check dashboard.html for:
2. An exposure warning element that appears when exposure is near policy limit. If absent → P1 finding. Evidence: `src/agency/templates/dashboard.html`.

Check portfolio_monitor.html for:
3. A link to the Execution Preview screen for managing existing positions. If absent → P1 finding.

- [ ] **Step 3.6: Update stub and commit**

Edit `docs/audit-findings-s3.md` first line: `Status: IN PROGRESS` → `Status: COMPLETE`.

```bash
git add docs/audit-findings-s3.md
git commit -m "audit: Section 3 findings — portfolio monitor (Agent B)"
```

---

## Task 4 — Agent C: Audit Section 4 — Confirm Orders + LLM

**Files:**
- Read: `src/agency/templates/risk.html`
- Read: `src/agency/templates/execution_preview.html`
- Read: `src/agency/services/risk.py` (lines 330–420 — risk decision logic)
- Read: `src/agency/services/execution_preview.py` (lines 180–200 — preview state logic)
- Read: `src/agency/services/llm_review.py` (lines 110–130 — env gate)
- Write: `docs/audit-findings-s4.md`

- [ ] **Step 4.1: Read risk.html and map structure**

Read the full file. Identify:
- How candidates are grouped or listed (flat table vs. grouped sections)
- What information is shown per-candidate by default
- Whether risk block reasons are human-readable or code values (e.g., "WARN" vs. "Exposure would exceed 20% limit")
- Whether there is a one-click path to Execution Preview

- [ ] **Step 4.2: Audit risk.html (checklist 4A)**

Append `AUDIT_FINDING` blocks to `docs/audit-findings-s4.md` for failures:

1. Are candidates grouped into 3 visual tiers (Ready to review / Blocked by policy / Needs data) with distinct visual treatment (border color or background tint)? If a flat list → P1.
2. Does each blocked candidate show a plain-English block reason (not a status code)? Check the template for any display of `risk_decision`, `risk_state`, or `action` values — if they render raw enum values without human-readable labels → P1.
3. Is there a visual risk matrix (candidate × dimension) available behind a drill-down? If absent → P2.
4. Is there a direct link from each "Ready to review" candidate to its Execution Preview row? If absent → P1.
5. Are agent-resolved risk checks shown as "Agent checked — OK" (suppressing detail)? If all checks render at full detail → P1.

- [ ] **Step 4.3: Read execution_preview.html and services/execution_preview.py**

From `execution_preview.py`, read lines 120–200 to understand:
- Where `submit_enabled` is set
- What `preview_state` values exist (READY / BLOCKED / etc.)
- Where the paper-mode banner copy comes from

From `execution_preview.html`, identify:
- Location and text of the paper-mode safety banner
- How `submit_enabled=False` rows are rendered (greyed button? explanatory text?)
- Whether a Submit button exists for `submit_enabled=True` rows
- Whether a bulk "Submit all ready" action exists
- Whether post-submission confirmation renders inline or redirects

- [ ] **Step 4.4: Audit execution_preview.html (checklist 4B)**

Append `AUDIT_FINDING` blocks for failures:

1. Does the paper-mode banner use reassuring language ("Running in paper mode — no real money at risk") vs. alarming or bureaucratic language? Copy the exact current text from the template into the finding's `evidence` field.
2. Is each order row human-readable ("Buy 12 shares of AAPL at market · Est. cost $2,340 · 3.1% of portfolio") or does it show raw field values (qty, symbol, notional separately)? If raw → P1.
3. Does each `submit_enabled=False` row include a per-row explanation of *why* (not just a greyed button)? If absent → P1.
4. When a row could be `submit_enabled=True` (after WATCH→ALLOW promotion), is there a clearly styled green "Submit" button? Check whether the template has a conditional block for `submit_enabled=True`. If absent → P0.
5. Is there a "Submit all ready orders" button for bulk confirm? If absent → P2.
6. After submission, does the template show inline confirmation (not just redirect)? If absent → P1.

- [ ] **Step 4.5: Audit approval flow end-to-end (checklist 4C)**

Read `src/agency/services/risk.py` lines 335–417 and `src/agency/services/execution_preview.py` lines 185–200.

Check:
1. Is there a `promote_watch_to_allow()` function or equivalent that upgrades WATCH→ALLOW on human APPROVE? If absent in risk.py → P0 finding (evidence: `risk.py:415`).
2. Does the execution preview builder check for a promotion record when computing `submit_enabled`? If absent in execution_preview.py → P0 finding.
3. After approval, does any template show a state-change confirmation ("Approved — execution preview updated")? Check candidate_detail.html and execution_preview.html for a success banner or toast on POST. If absent → P1.
4. Count the clicks from "I want to approve this" to "order placed": Approve button click → (redirect?) → Execution Preview → Submit click = 2–3 clicks. If the flow requires more navigation steps → P1.

- [ ] **Step 4.6: Audit LLM recommendation display (checklist 4D)**

Read `src/agency/services/llm_review.py` lines 110–130 for the env gate and stub return.

Check risk.html and execution_preview.html for:
1. An inline LLM recommendation per candidate row (WATCH/NO_TRADE/NO_REVIEW + one-line rationale). If absent → P1.
2. A side-by-side display of deterministic score vs. LLM recommendation. If absent → P1.
3. A conflict indicator (amber icon/badge) when deterministic and LLM disagree. If absent → P1.
4. A per-row "LLM review unavailable — rules-only" text when LLM is disabled. If absent (blank column) → P1.
5. LLM rationale in a collapsible element (summary visible, detail hidden). If always fully expanded → P2.
6. A page-level LLM system status indicator. If absent → P2.

- [ ] **Step 4.7: Update stub and commit**

Edit `docs/audit-findings-s4.md` first line: `Status: IN PROGRESS` → `Status: COMPLETE`.

```bash
git add docs/audit-findings-s4.md
git commit -m "audit: Section 4 findings — confirm orders + LLM (Agent C)"
```

---

## Task 5 — Agent D: Audit Section 5 — Design System

**Files:**
- Read: ALL of: `src/agency/templates/dashboard.html`, `final_selection.html`, `candidate_detail.html`, `portfolio_monitor.html`, `risk.html`, `execution_preview.html`, `audit.html`, `policy.html`, `learning.html`, `market_regime.html`, `base.html`, `_data_health.html`
- Read: `src/agency/static/styles.css`
- Write: `docs/audit-findings-s5.md`

- [ ] **Step 5.1: Extract the colour class inventory from styles.css**

Read styles.css. List every CSS class that sets a `color`, `background-color`, or `border-color` property. Group them by semantic meaning:
- Classes that appear to mean "pass/healthy/good"
- Classes that appear to mean "blocked/rejected/error"
- Classes that appear to mean "warning/attention/pending"
- Classes that appear to mean "informational/neutral"

If any class name's meaning is ambiguous (e.g., `.tag-primary` could mean either action or info), note it.

- [ ] **Step 5.2: Audit color semantics across all 8 templates (checklist 5A)**

For each template, grep for every colour class and check:
1. Is green used for non-green meanings (e.g., green badge on a disabled item)? → P1.
2. Is red used for warnings rather than errors/blocks? → P1.
3. Is the same colour used for two different semantic meanings on the same screen? → P1.
4. Do P&L values always use green for positive and red for negative in every template that shows them? → P1 if not.
5. Are paper-mode elements consistently marked with a distinct visual treatment (e.g., amber/dashed border) vs. live elements? → P1 if not.

Append `AUDIT_FINDING` blocks to `docs/audit-findings-s5.md` for every violation found. Include the template name and CSS class name in `evidence`.

- [ ] **Step 5.3: Audit icon and symbol usage (checklist 5B)**

Search all templates for icon/symbol usage: `<i class`, `<svg`, emoji characters, Unicode symbols (✅ ⚠️ 🚫 etc.).

Check:
1. Is each status type represented by the same icon/symbol across all templates (not different icons per screen)? List which icon is used for each status type on each screen. Flag inconsistencies → P1.
2. Are icons always accompanied by a colour (not just shape-only)? → P1 if shape-only.
3. Are Approve / Defer / Reject action buttons distinguished by both icon and colour? → P1 if text-only.
4. Is there a visual distinction between agent-automated actions and user-required actions? → P1 if absent.

- [ ] **Step 5.4: Audit typography hierarchy (checklist 5C)**

For each template, identify the CSS classes applied to:
- The primary answer/recommendation element
- Supporting labels and secondary text
- Key numeric values (conviction, P&L, order size)
- Technical strings (IDs, timestamps)

Check:
1. Is there one clearly largest/boldest element per screen (the headline answer)? → P1 if every element has the same visual weight.
2. Are uppercase small labels reserved for secondary context only — not used on primary data? → P2 if used on primary data.
3. Are numeric values (conviction score, P&L, order size) in a larger or bolder style than their labels? → P1 if same size/weight.
4. Are at least 3 distinct type sizes in use across the page? → P2 if only 1–2.
5. Are long technical strings always in a monospace class and always inside a `<details>` element? → P1 if visible by default.

- [ ] **Step 5.5: Audit progressive disclosure consistency (checklist 5D)**

Search all templates for `<details>`, `<summary>`, and any JS-toggle patterns (classes like `collapsible`, `expandable`, `hidden`).

Check:
1. Is the same expand/collapse pattern used everywhere, or is it a mix of `<details>`, custom JS toggle, and CSS hidden? → P1 if mixed (creates inconsistent UX).
2. In every template: are provenance fields (`timestamp_as_of`, `source_count`, `verification_level`) inside `<details>` or equivalent collapse? → P1 per template where they're always visible.
3. In every template: are agent run metadata fields (`run_id`, `input_snapshot_id`) always collapsed? → P1 per template if visible by default.
4. In every template: are recommendation, conviction score, top 3 reasons, risk decision, and order size always visible without expanding? → P0 per template if any of these are collapsed by default.
5. Is the `<summary>` text consistent across collapsed sections (e.g., always "▶ Show details", not sometimes "More", sometimes "Details", sometimes a chevron icon)? → P2 if inconsistent.

- [ ] **Step 5.6: Audit navigation and wayfinding (checklist 5E)**

Read `base.html` fully (this defines the left nav).

Check:
1. Does the active nav item have a visually strong indicator (background fill, bold text, left border) — not just a subtle colour change? → P1 if subtle.
2. Is the yellow brick road sequence (Candidates → Portfolio → Execute) represented as a visual group or progress indicator in the nav? → P1 if the 3 steps are scattered among 8 nav items with equal visual weight.
3. Are placeholder/disabled screens (Universe, Signals, Learning) visually muted (greyed text, no hover effect) vs. active screens? → P2 if they look identical to active screens.
4. Do drill-down pages (candidate_detail.html) have a breadcrumb or back-link to the parent list? → P1 if absent.
5. Does the mobile media query (at 768px breakpoint from T150) maintain a usable nav? Check for the responsive breakpoint in styles.css or base.html. → P1 if nav is unusable on mobile.

- [ ] **Step 5.7: Update stub and commit**

Edit `docs/audit-findings-s5.md` first line: `Status: IN PROGRESS` → `Status: COMPLETE`.

```bash
git add docs/audit-findings-s5.md
git commit -m "audit: Section 5 findings — design system (Agent D)"
```

---

## Task 6 — Consolidation: Merge Findings into `docs/audit-findings.md`

**Files:**
- Read: `docs/audit-findings-s2.md`, `docs/audit-findings-s3.md`, `docs/audit-findings-s4.md`, `docs/audit-findings-s5.md`
- Create: `docs/audit-findings.md`

- [ ] **Step 6.1: Parse all AUDIT_FINDING blocks from the four section files**

Read all four section files. Extract every `AUDIT_FINDING ... END_FINDING` block. Parse each block into fields:
- screen, category, severity, finding, evidence, fix, acceptance

- [ ] **Step 6.2: Deduplicate cross-screen findings**

If two blocks from different agents describe the same issue (same `evidence` file:line or same `finding` text), merge them into one block. Keep the higher severity. Note both agents in a comment.

- [ ] **Step 6.3: Assign finding IDs and sort**

Assign sequential IDs: `F001`, `F002`, ...

Sort order:
1. P0 findings first
2. Within P0: Step 1 screens (Command, Final Selection, Candidate Detail) → Step 2 (Portfolio) → Step 3 (Risk, Execution Preview) → Design System
3. P1 findings, same order
4. P2 findings, same order
5. Within each severity+step: group findings that share the same template file so Codex batches edits

- [ ] **Step 6.4: Write `docs/audit-findings.md`**

```markdown
# Trading Agency v2 — UX & Product Audit Findings
Date: 2026-05-18
Spec: docs/superpowers/specs/2026-05-18-ux-audit-design.md

## Summary

| Severity | Count |
|----------|-------|
| P0 — blocks workflow | X |
| P1 — degrades UX | X |
| P2 — polish | X |
| **Total** | **X** |

> Note: X values above are filled in by the consolidation agent at runtime — they cannot be pre-determined before the audit runs.

## Implementation Order

1. [F001] <title> (P0 — <screen>)
2. [F002] <title> (P0 — <screen>)
...

---

## P0 Findings

### [F001] <One-line title>
- **Screen:** <name>
- **Category:** <category>
- **Severity:** P0
- **Finding:** <finding>
- **Evidence:** `<evidence>`
- **Fix:** <fix>
- **Acceptance:** <acceptance>

[repeat for each P0]

---

## P1 Findings

[repeat pattern]

---

## P2 Findings

[repeat pattern]
```

- [ ] **Step 6.5: Commit**

```bash
git add docs/audit-findings.md
git commit -m "audit: consolidated finding log — F001-FXXX (sections 2-5)"
```

---

## Task 7 — Generate `docs/audit-implementation-plan.md`

**Files:**
- Read: `docs/audit-findings.md`
- Create: `docs/audit-implementation-plan.md`

- [ ] **Step 7.1: Group findings by template file**

From `docs/audit-findings.md`, group all findings by the primary template file in their `evidence` field:
- `dashboard.html` findings
- `final_selection.html` findings
- `candidate_detail.html` findings
- `portfolio_monitor.html` findings
- `risk.html` findings
- `execution_preview.html` findings
- `styles.css` / `base.html` findings (design system)
- Cross-file / service findings (risk.py, execution_preview.py)

Within each group, sort P0 before P1 before P2.

- [ ] **Step 7.2: Write `docs/audit-implementation-plan.md`**

For each file group, write one implementation task. Each task:
- Lists the findings it addresses (F-IDs)
- Specifies the exact file and line range
- Describes the change in a single clear instruction
- States the acceptance test

Format:

```markdown
# Trading Agency v2 — UX Audit Implementation Plan
Source: docs/audit-findings.md
Date: 2026-05-18

> This plan is the direct input for Codex UX improvement work.
> Execute tasks in order. Each task references the audit finding(s) it resolves.

---

## T001 — <File>: <Change summary>
**Resolves:** F001, F003
**File:** `src/agency/templates/dashboard.html`
**Change:** <Specific instruction — what to move, add, remove, or change>
**Acceptance:** <Testable condition>

---

## T002 — ...
```

- [ ] **Step 7.3: Verify every finding is covered**

After writing the plan, scan `docs/audit-findings.md` for every F-ID. Confirm each appears in at least one implementation task. If any F-ID has no task, add a task for it.

- [ ] **Step 7.4: Commit and report**

```bash
git add docs/audit-implementation-plan.md
git commit -m "audit: generate UX implementation plan from consolidated findings"
```

Report the final counts:
- Total findings: X (P0: X, P1: X, P2: X)
- Implementation tasks: X
- Files to be modified: X
