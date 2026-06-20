# Trading Agency v3 — UX & Product Audit
**Date:** 2026-05-29  
**Reviewer:** Claude (PM / UX / Code review)  
**Scope:** Full dashboard UX, data labeling, data pipeline clarity, actionability, and walkthrough flow  
**Targets for implementation:** Codex

---

## Executive Summary

The application has a well-designed backend pipeline and strong data integrity guarantees, but the operator-facing UX fails on three critical dimensions:

1. **No guided workflow** — The user is dropped into a dense ops dashboard with no clear "here's what to do today" path. The app has a well-defined 4-phase workflow (Review → Risk → Select → Execute) but nothing surfaces that flow as a primary affordance.
2. **Label overload** — Internal pipeline terminology (`lane`, `massive lane`, `operationability`, `paper_promotion_status`, `execution_freshness_gate`, `BLUF`) bleeds into the UI. A trader operating this system daily should not need to learn internal architecture vocabulary.
3. **Data density without hierarchy** — Every dashboard packs maximum information onto a single screen without a priority ordering. The review queue (the most time-sensitive operator action) is buried beneath system diagnostics.

**Impact:** An operator with no familiarity with the codebase cannot reliably know (a) whether the system is ready to use, (b) what action to take next, or (c) when they are done for the day.

---

## Audit Findings by Area

### A. Navigation & Information Architecture

**Finding A-1: Two ambiguous "home" pages**  
`/cockpit` (V3 Cockpit) and `/command` (Ops Status) both serve as potential starting points. The root `/` redirects to `/cockpit`. The sidebar shows both with numbers `01` and `02`. Their purposes overlap: both show data health, system status, and candidate-related state. The operator cannot determine which one is "the place to be."

**Finding A-2: Numbered nav items without meaning**  
Numbers 01–11 in the sidebar convey no status. Number 03 ("Candidates") links to `/final-selection` — the route name and the nav label are different (`/final-selection` vs "Candidates"). Number 05 ("Execute") links to `/execution-preview`. This inconsistency between URL semantics, page titles, and nav labels creates disorientation.

**Finding A-3: Workflow phases in Cockpit don't align with nav**  
The Cockpit has phases 01–04 (Candidates, Portfolio, Clearance, Cleared). The nav has items 01–11. These numbering systems are independent but visually indistinguishable, so an operator reading "Phase 01" in the cockpit can confuse it with nav item `01`.

**Finding A-4: "Research" section buried below actionable workflow**  
Market regime, Signals — both are inputs to the candidate review decision — sit below Execute in the nav. They should logically precede or inform the workflow, not trail it.

---

### B. Data Labels & Terminology

**Finding B-1: Internal terms exposed as UI labels**

| Exposed term | Where used | Plain-language replacement |
|---|---|---|
| `lane` / `massive lane` | Command dashboard, scheduler tables | "Data pipeline" / "Large dataset refresh" |
| `operationability` | Cockpit data-state strip | "Readiness gaps" or "Action required" |
| `BLUF` (Bottom Line Up Front) | Cockpit portfolio phase | Remove — use plain headline text |
| `paper_promotion_status` | Execution preview card | "Eligibility status" |
| `execution_freshness_gate` | Status API / execution preview | "Data currency check" |
| `live-critical due` | Scheduler panel | "Urgent refresh due" |
| `repair due` | Scheduler panel | "Coverage backfill pending" |
| `support due` | Scheduler panel | "Context refresh pending" |
| `order_intent_hash` | Execution card | Never show hash in UI; confirm via visual match |
| `client_order_id` | Execution broker status | "Broker order reference" |
| `cycle_id` | Multiple places | Show as "Cycle [date]" not raw UUID |
| `as_of` | Multiple places | "Data as of [human date]" |
| `Massive data lanes` | Command dashboard | "Dataset coverage" |
| `tier N` (ticker tiers) | Scheduler | "Priority group" |
| `inferred` / `suppressed` evidence tiers | Cockpit | These are OK if tooltips explain them |
| `conviction` | All candidate cards | OK term but must have tooltip explaining scoring |

**Finding B-2: Status vocabulary is inconsistent**  
The system uses at minimum five distinct status systems simultaneously:

- CSS classes: `pass`, `warn`, `block`, `neutral`
- Template values: `"PASS"`, `"BLOCK"`, `"BLOCKED"`, `"NO_TRADE"`, `"READY"`, `"DISABLED"`, `"NONE"`
- Risk decision values: `"APPROVE"`, `"BLOCK"`, `"NO_TRADE"`, `"HOLD"`
- Human review decisions: `"PENDING"`, `"APPROVE"`, `"DEFER"`, `"REJECT"`
- Execution states: `"READY"`, `"DISABLED"`, `"FILLED"`, `"CANCELED"`, `"REJECTED"`, `"EXPIRED"`

The same word `BLOCK` means "data pipeline issue" in the scheduler context and "risk decision" in the candidate context. This creates ambiguity that is never explained in the UI.

**Finding B-3: Conviction score unexplained**  
`conviction` appears as a percentage (e.g., `74%`) across every candidate view, but no tooltip or legend explains what it represents, how it's computed, or what threshold is meaningful for action.

**Finding B-4: Evidence tier labels lack persistent context**  
The cockpit shows `confirmed`, `inferred`, `suppressed` evidence tier chips. A one-line legend appears in the cockpit but is absent from every other view that shows evidence. The candidate detail page uses evidence without any tier legend.

---

### C. Command Dashboard (`/command`)

This is the most problematic view. It attempts to show everything on one page, resulting in a page that is ~2,500 lines of HTML with at least 8 distinct sections, 4 collapsed `<details>` areas, and 3 nested tables hidden two levels deep.

**Finding C-1: KPI grid is flat — 9 tiles, equal visual weight**  
The nine KPI tiles ("Portfolio exposure", "Needs Review", "Candidates", "Agency Mode", "Hard Blockers", "Provider Connections", "Source Health", "Lane Refresh", "Contracts") are rendered at identical visual weight. "Needs Review" is the only time-sensitive operational metric; it sits beside "Contracts" (a static schema count). The user cannot determine priority from visual hierarchy.

**Finding C-2: Review queue buried three viewport-heights down**  
The primary operator task — reviewing candidates — lives in a `panel` section preceded by: the Next Action card → Email/Article progress panel → Operator Briefing (with 4 status cells + 3 queue items + 2 CTAs) → LLM status banner → Action ribbon → KPI grid. The queue itself is the 6th visible section on a standard monitor.

**Finding C-3: Email pipeline section appears twice**  
The email login alert appears at the top of the page (as a `command-email-login-alert`), then the full email pipeline progress section appears as the second visible panel. If there is no active email analysis run, the email panel takes full-page real estate to say "No email article run recorded."

**Finding C-4: System diagnostics consume 70% of the page**  
Hidden behind a "Inspect operational detail" `<details>` tag are: Agency Readiness Mode (full panel), Agency Data Readiness (full panel with 3 sub-tables), Automation & Refresh Queue (with Massive lanes table, Next Jobs table, Tier Manager, and 2 nested `<details>`), Operational Readiness Gate, Lane Refresh (with Trade Pull card and another nested `<details>`), Live Config (with full check table), Provider Readiness (with provider cards), and Latest Cycle Review Readiness. These are all valuable diagnostic tools but they are currently equal in visual weight to the review queue.

**Finding C-5: No "you're done for the day" state**  
When all candidates are reviewed and no action remains, the command dashboard still shows all the diagnostic sections at full visibility. There is no "Today's workflow is complete" terminal state.

**Finding C-6: Multiple duplicate progress summaries**  
The command dashboard shows loading progress in at least 4 places: the `operator-briefing-grid` (ETA and progress cell), the `kpi-grid` (Lane Refresh tile), the `system-process-table` (Refresh Progress row), and the full `progress-panel` section. Each shows slightly different facets of the same underlying data.

---

### D. Cockpit (`/cockpit`)

The Cockpit is significantly better structured than the Command dashboard. The 4-phase flow is the right pattern. The following issues remain:

**Finding D-1: Static headline regardless of state**  
`{% block page_title %}Pre-flight briefing is ready{% endblock %}` and the cockpit BLUF headline `{{ scenario.headline }}` are populated from the scenario object, but the page title in the HTML `<title>` is always "Pre-Flight Cockpit - Trading Agency." This means browser tab shows no status to an operator with multiple tabs open.

**Finding D-2: Data State strip uses opaque compound labels**  
`{{ data_review.label }} / {{ data_paper.label }}` renders as e.g. "Review open / Paper execution gated." The forward slash separator looks like a percentage or ratio, not a two-item status pair. The sub-labels ("Review", "Paper execution", "Overall loaded", "Critical lanes") are not explained without reading the source or the tooltip.

**Finding D-3: Candidate rows have 5 distinct action states without explanation**  
A candidate row can show: "Review manifest" + "Open ticker detail" (actionable), OR "Review order intent" (order_reviewable), OR "Approve Research" + "Defer" + "Reject" (reviewable), OR just "Open audit" (non-actionable). There is no legend, no tooltip, no state explanation visible to the operator. The operator must infer from context.

**Finding D-4: Phase navigation is ambiguous about state**  
Phase buttons (01 Candidates, 02 Portfolio, 03 Clearance, 04 Cleared) show "Active" / "Review next" / "Paper gate" / "After submit" as subtitles. These are fine but there is no visual distinction between "completed," "active," and "blocked" phase states. A completed Phase 1 and a skipped Phase 1 look identical.

**Finding D-5: "Operationability gaps" is jargon**  
The data state strip uses `operationability_gaps` as both internal key and visible label. It should be "What's blocking today's session."

**Finding D-6: Clearance form phrase confirmation UX**  
The operator must type "submit paper orders" exactly to submit. This is an intentional safety gate, which is fine, but the `<label>` says "Type submit paper orders" which could be misread as an instruction. The field itself has no `placeholder` attribute, no real-time match feedback (only disabled button), and the error is silent (button stays disabled).

---

### E. Candidate Detail (`/candidates/{ticker}`)

**Finding E-1: Page title is generic**  
`{% block page_title %}{{ ticker }} is ready for evidence review{% endblock %}` — this ignores the actual agent decision. If the agent says REJECT, the title still says "is ready for evidence review." The page title should reflect the agent's recommendation (e.g., "AAPL — Agent recommends BUY").

**Finding E-2: Sticky review bar missing context**  
The sticky bar shows `[ticker] · Review: [decision]` + three action buttons. An operator who scrolls down to read evidence and then scrolls back up sees the buttons without the supporting evidence. The bar needs the conviction score and top reason inline.

**Finding E-3: No visible "what changed since last review" indicator**  
If a candidate was previously DEFERRED and has now been re-submitted with new evidence, there is no "updated evidence" indicator. The operator might re-approve the same thesis without noticing new (negative) signals.

---

### F. Execution Preview (`/execution-preview`)

**Finding F-1: "Paper Promotion" label is unexplained**  
`paper_promotion_status_label` appears as "Paper Promotion" in the execution card metrics. It means the candidate has passed all gates to be submitted as a paper trade, but the label implies the system is "promoting" something, which sounds like an internal operation.

**Finding F-2: Order intent hash shown as metadata**  
`order_intent_hash` is shown in the execution card as a hash string. This is a security/anti-tampering mechanism. It should not be surfaced as a visible metric — it reads as noise to operators and is meaningless without documentation.

**Finding F-3: "Operator advance" action has no visible affordance**  
The `/execution-preview/operator-advance` route exists and allows manual override, but this action is not visible in the normal execution preview flow. An operator needing to override must know to look for it or read the URL structure.

---

### G. Data Pipeline Between Modules

**Finding G-1: Cache TTLs are inconsistent and not surfaced to operators**

| Route/Feature | Cache TTL | Shown to user? |
|---|---|---|
| Cockpit context | 2s (fresh) – 120s (stale) | "Monitor proof: [time]" — but this measures scheduler events, not cache age |
| Command dashboard | 15s | Not shown |
| Execution preview | 60s | Not shown |
| Final selection | 60s | Not shown |
| Broker status | No cache (always fresh) | "Checking broker" pill |

An operator seeing "data as of 2 minutes ago" in the cockpit but "data as of 10 seconds ago" in the execution preview cannot reconcile these differences without understanding the caching strategy.

**Finding G-2: Selection report → Risk decision → Final selection → Execution chain is not visible**  
The data pipeline flows: `evidence_pack` → `deterministic_rules` → `llm_review` → `final_selection` → `risk_decision` → `execution_preview`. The operator sees individual outputs of each stage but never sees the chain. If a candidate is blocked at execution, the operator must manually trace back through 5 pages to understand why.

**Finding G-3: Signal evidence freshness is not shown at point of decision**  
On the candidate detail page, evidence items show tier and source text but not the `as_of` timestamp for each signal. An operator approving a candidate based on insider trading data from 3 days ago cannot detect staleness from the current UI.

**Finding G-4: Scheduler state is disconnected from candidate readiness**  
The command dashboard shows scheduler state (lane refresh, datasets) in a separate section from candidate readiness. An operator seeing "3 candidates ready to review" and separately "data refresh running" does not know whether the refresh will change the candidate list before review is complete.

---

## Implementation Tickets

Organized by priority (P0 = critical path, P1 = major impact, P2 = improvement).

---

### EPIC 1 — Guided Workflow ("Walk-Me")

#### T-UX-01 [P0] — Add "Today's Operator Checklist" widget to Command Dashboard
**Problem:** No single-screen summary of what the operator needs to do today.  
**Solution:** Add a sticky `checklist-card` at the top of `/command` (before all other content) that computes and renders:
```
☐ System ready? [pass/warn badge] → Link to diagnostic
☐ N candidates need review → Link to review queue  
☐ Execution preview open? [pass/warn] → Link to execution  
☐ Orders to submit? [count] → Link to cockpit clearance
```
This replaces the current "Next Action" card and the "Operator Briefing" section as the single authoritative entry point.

**Data already available:** `full_live_readiness`, `review_progress`, `execution_preview` context, `final_selection` summary.  
**File changes:** `dashboard.html`, `views/command.py` (add `operator_checklist_context` function).  
**Acceptance:** Checklist renders before the fold on a 1080p screen. Each item links to the correct page/anchor.

---

#### T-UX-02 [P0] — Redirect root `/` to today's first actionable page
**Problem:** `/` redirects to `/cockpit` which is the pre-flight clearance view. Operators opening the app at 9AM should see what to do, not the cockpit.  
**Solution:** Change root redirect logic: if review queue has pending items → `/command#review-queue-heading`; else if execution preview has orders → `/execution-preview`; else → `/command`.  
**File changes:** `dashboard.py` `dashboard()` route.  
**Acceptance:** Opening the app during market hours routes to the most actionable page.

---

#### T-UX-03 [P1] — Add workflow phase progress indicator to sidebar
**Problem:** The sidebar nav shows 11 numbered items with no state. The user cannot tell where they are in today's cycle.  
**Solution:** In `base.html`, inject a compact workflow breadcrumb below the nav:
```
Today's cycle:  Review (3/5) → Risk → Clear
```
Built from `review_progress`, `final_selection_summary`, `execution_preview_summary`. Each segment links to the relevant page.  
**File changes:** `base.html`, new `views/_shared.py` `workflow_phase_summary()` helper.  
**Acceptance:** Breadcrumb appears on all pages. Completed phases show checkmark. Active phase is bolded.

---

#### T-UX-04 [P1] — Candidate detail: show "what changed" delta badge
**Problem:** Operators cannot tell if evidence has changed since a previous review decision.  
**Solution:** In `candidate_detail.html`, if the candidate has a prior review decision (not `PENDING`) and new evidence has arrived since that decision's timestamp, show a "New evidence since [time]" badge in the decision brief section.  
**Data:** Compare `review.event_time` with signal evidence `as_of` timestamps from `candidate_email_evidence` and `candidate_news_evidence`.  
**File changes:** `candidate_detail.html`, `views/candidates.py` (add `evidence_delta_since_review` field to context).  
**Acceptance:** Badge appears when evidence is newer than last review. Not shown if no prior review.

---

### EPIC 2 — Data Labels & Terminology

#### T-UX-05 [P0] — Replace all internal/jargon terms with operator vocabulary
**Problem:** Internal terms exposed in UI (see Finding B-1).  
**Solution:** Global label replacement across all templates. Create a label mapping and apply consistently.

Specific replacements (all templates):

| Find (exact text) | Replace with |
|---|---|
| `lane` (standalone) | "data pipeline" |
| `Massive data lanes` / `Massive Lanes` | "Dataset coverage" |
| `Operationability gaps` | "Action required" |
| `operationability` | "readiness" |
| `paper_promotion_status` | Eligibility |
| `Live-Critical Due` | "Urgent refresh due" |
| `Repair Due` | "Backfill pending" |
| `Support Due` | "Context refresh pending" |
| `BLUF` | Remove — just use the text |
| `client_order_id` | "Broker order ref" |
| `cycle_id` display | Show as "Cycle [YYYY-MM-DD]" |
| `as_of` display | "Data as of [human date]" |
| `Massive orchestrator` | "Coverage coordinator" |
| `ticker_tier` | "Priority group" |
| `Repair jobs` | "Backfill jobs" |

**File changes:** All templates. Also `_operator_text()` in `views/_shared.py` can be extended to perform these substitutions.  
**Acceptance:** No instance of jargon terms in any operator-visible template.

---

#### T-UX-06 [P0] — Standardize status vocabulary across all views
**Problem:** `BLOCK`, `BLOCKED`, `block`, `NO_TRADE`, `REJECTED`, `DISABLED` all mean "not actionable" but carry different semantic meaning in different contexts (Finding B-2).  
**Solution:**

Define a canonical 4-state vocabulary for operator display:
- `ready` / green — action can proceed
- `attention` / yellow — action can proceed with caution  
- `blocked` / red — action cannot proceed, explicit reason required
- `inactive` / grey — not in scope for current session

Map all existing status values to this vocabulary at the view layer. The underlying domain terms (`BLOCK`, `NO_TRADE`, etc.) remain in the data model.

**File changes:** `views/_shared.py` — add `operator_status_label(raw_status: str) -> tuple[str, str]` returning `(label, css_class)`. Apply in all view constructors.  
**Acceptance:** Template search for `"tag-block"` shows only truly blocked states. `"tag-warn"` shows only attention states.

---

#### T-UX-07 [P1] — Add conviction score tooltip everywhere it appears
**Problem:** Conviction % has no explanation (Finding B-3).  
**Solution:** In every template where `conviction_pct` or `final_conviction` appears, wrap the label with a `<span class="info-tip">` carrying the same tooltip text:
```
"Conviction combines the deterministic rules score (signals passing 
threshold rules) and LLM alignment score. 100% = full model agreement 
with positive evidence. Thresholds: ≥70% eligible for approval, 
<40% typically below action threshold."
```
**File changes:** `cockpit.html`, `final_selection.html`, `candidate_detail.html`, `dashboard.html`.  
**Acceptance:** Every conviction% display has an accessible tooltip.

---

#### T-UX-08 [P1] — Add evidence tier legend to every page that shows evidence
**Problem:** Evidence tier labels (`confirmed`, `inferred`, `suppressed`) only have a one-line legend in the cockpit (Finding B-4).  
**Solution:** Create a reusable `_evidence_legend.html` macro. Include it in: cockpit candidate rows, candidate detail page, final selection page.

Legend text:
- **Confirmed** — Signal derived from a verified primary source (SEC filing, direct feed). Can drive decisions.
- **Inferred** — Signal inferred from price/volume model. Provides context but does not independently confirm.
- **Suppressed** — Signal is recorded for audit but cannot influence decisions due to age, conflict, or policy.

**File changes:** New `_evidence_legend.html` macro, included in `cockpit.html`, `candidate_detail.html`, `final_selection.html`.

---

### EPIC 3 — Command Dashboard Simplification

#### T-UX-09 [P0] — Collapse Command Dashboard to two zones: Act + Diagnose
**Problem:** ~2,500 lines of HTML, equal visual weight for operational and diagnostic content (Findings C-1 through C-6).  
**Solution:** Restructure `dashboard.html` into two clearly separated zones:

**Zone 1: Act (always visible, max 60% of viewport height)**
- `operator_checklist_context` card (from T-UX-01) — full width, top
- Review Queue — full width, directly below checklist
- No other content before the fold

**Zone 2: Diagnose (below fold, default collapsed)**
- System diagnostics panel (collapsible)
  - KPI grid (condensed to 4 tiles: Needs Review, Hard Blockers, Data Coverage, Trade Eligibility)
  - Process health table
  - Email pipeline status (only if email analysis is active or has recent results)
  - Lane refresh progress
- Advanced detail (always collapsed by default)
  - Full Live Readiness
  - Data Load Status
  - Scheduler panels

**File changes:** `dashboard.html` — major restructure. `views/command.py` — no logic changes needed.  
**Acceptance:** On 1080p screen, Zone 1 is visible without scrolling. Diagnostic zone requires intentional scroll or expand.

---

#### T-UX-10 [P0] — Reduce KPI grid to 4 prioritized tiles
**Problem:** 9 equal-weight KPI tiles (Finding C-1).  
**Solution:** Retain only:
1. **Needs Review** — pending review count, links to queue
2. **System Status** — pass/attention/blocked with one-line explanation
3. **Data Coverage** — % of data ready (from `data_load_status.overall_percent`)
4. **Trade Gate** — paper execution eligibility (open/gated)

Remove from KPI grid: Contracts (move to Policy page), Agency Mode (fold into System Status), Provider Connections (fold into System Status), Source Health (fold into Data Coverage), Lane Refresh (fold into Data Coverage).

**File changes:** `dashboard.html` (remove 5 KPI articles), `views/command.py` (keep all data, just don't render the removed tiles).

---

#### T-UX-11 [P1] — Consolidate email pipeline into a single dismissible alert
**Problem:** Email status appears twice and takes prime real estate when inactive (Finding C-3).  
**Solution:**
- If `email_status.login_required > 0` OR `email_status.linked_content_processing > 0` → show compact inline alert banner (one row, dismissible, with action button)
- If email pipeline is idle → hide entirely
- The full email progress panel (with all 8 metrics) is only shown when email analysis is actively running

**File changes:** `dashboard.html` — replace `command-email-login-alert` section and `subscription-pipeline` section with single conditional alert bar.

---

### EPIC 4 — Cockpit Improvements

#### T-UX-12 [P1] — Dynamic page title reflecting actual workflow state
**Problem:** Cockpit always says "Pre-flight briefing is ready" regardless of state (Finding D-1).  
**Solution:**
- Scenario `outage` → title: "⛔ Pre-Flight Blocked — [reason]"
- Scenario `no-actionable` → title: "⚪ No Actionable Candidates Today"
- Scenario `submitted` → title: "✅ Orders Submitted — [cycle date]"
- Default (candidates pending review) → title: "📋 [N] Candidates Need Review"

Also update `<title>` block to include the scenario headline.

**File changes:** `cockpit.html` — `{% block title %}` and `{% block page_title %}`.

---

#### T-UX-13 [P1] — Replace "Operationability gaps" with "What's blocking today"
**Problem:** "Operationability" is jargon (Finding D-5).  
**Solution:**
```html
<!-- Replace: -->
<strong>Operationability gaps</strong>
<!-- With: -->
<strong>What's blocking today</strong>
<span class="info-tip" title="These are the current barriers to starting candidate review or paper execution. Resolve them in order before proceeding.">?</span>
```
Also rename the `cockpit_data_state_gaps` section heading from "Data State" to "Session Readiness."

**File changes:** `cockpit.html`.

---

#### T-UX-14 [P1] — Phase buttons: add visual state (complete / active / pending)
**Problem:** Phase buttons look identical whether complete, active, or blocked (Finding D-4).  
**Solution:** Compute phase state in `views/cockpit.py`:
- `phase_state.candidates`: `"complete"` if all candidates reviewed, `"active"` if in-progress, `"pending"` if data not ready
- `phase_state.portfolio`: `"complete"` if user has made keep/close decisions, `"active"`, `"pending"`
- `phase_state.clearance`: `"complete"` if orders submitted, `"active"`, `"pending"`

Render phase buttons with `data-phase-state="complete|active|pending"` attribute and CSS accordingly (e.g., checkmark on complete, arrow on active, lock icon on pending).

**File changes:** `cockpit.html`, `views/cockpit.py` (add `phase_states` to context).

---

#### T-UX-15 [P2] — Clearance phrase field: add real-time match feedback
**Problem:** The submit phrase field silently keeps the button disabled (Finding D-6).  
**Solution:**
- Add `placeholder="type: submit paper orders"` to the phrase input
- Add `data-cockpit-submit-phrase-feedback` span that shows ✓ (match) or typed chars vs expected on keystroke
- Submit button tooltip when disabled: "Check the checkbox above and type the exact phrase to enable."
- Button text changes from "Submit paper orders" to "Confirm & Submit Paper Orders" for clarity.

**File changes:** `cockpit.html`, `cockpit.js` (add input event listener for phrase validation feedback).

---

### EPIC 5 — Candidate Detail Improvements

#### T-UX-16 [P1] — Lead with agent recommendation in page title and decision brief
**Problem:** Page title always says "ready for evidence review" (Finding E-1).  
**Solution:**
- `{% block page_title %}{{ ticker }}: Agent recommends {{ decision_brief.action_label }}{% endblock %}`
- `{% block title %}{{ ticker }} — {{ decision_brief.action_label }} | Trading Agency{% endblock %}`
- Decision brief hero background color already reflects state via `decision-brief-{{ decision_brief.state_class }}` — ensure the state class maps to meaningful colors (BUY = green-tinted, SELL = amber-tinted, REJECT = red-tinted).

**File changes:** `candidate_detail.html`.

---

#### T-UX-17 [P1] — Sticky review bar: add conviction + top reason inline
**Problem:** Review bar shows ticker + action buttons without supporting context (Finding E-2).  
**Solution:**
```html
<!-- Current: -->
<span class="metric-label">{{ ticker }} · Review: {{ review.decision }}</span>
<!-- Replace with: -->
<span class="metric-label">
  {{ ticker }} · {{ decision_brief.conviction_pct }}% conviction
  · {{ decision_brief.action_label }}
  · {{ decision_brief.top_reason_brief }}
</span>
```
Where `top_reason_brief` is the first reason from `decision_brief.signal_counts` (already computed in context).

**File changes:** `candidate_detail.html`.

---

#### T-UX-18 [P1] — Add signal `as_of` timestamps to candidate evidence items
**Problem:** Evidence items don't show their data freshness (Finding G-3).  
**Solution:** In each evidence section (news evidence, email evidence, signals), add a `<small>Data as of {{ item.as_of_label }}</small>` below the item text.  
**Data:** The `as_of` field already exists in signal result objects via `signal_adapters.py`.  
**File changes:** `candidate_detail.html`, `views/candidates.py` — ensure `as_of_label` is forwarded in evidence items.

---

### EPIC 6 — Execution Preview Improvements

#### T-UX-19 [P1] — Remove `order_intent_hash` from operator-visible metrics
**Problem:** Hash is shown as a UI metric (Finding F-2).  
**Solution:** The `order_intent_hash` field in execution preview cards should not appear as a visible metric row. It should remain as a hidden form field for anti-tampering validation only. If the operator needs to verify intent integrity, show: "Order verified ✓" (when hash matches) or "⚠ Order hash mismatch — refresh required."

**File changes:** `execution_preview.html` — remove `order_intent_hash_label` from visible metrics grid; add "Order verified" indicator driven by `order_intent_hash` comparison.

---

#### T-UX-20 [P1] — Rename "Paper Promotion" to "Eligibility Status"
**Problem:** "Paper Promotion" is internal jargon (Finding F-1).  
**Solution:**
- Template label: `Paper Promotion` → `Eligibility`
- `paper_promotion_status_label` values: rename in `views/execution.py` view model
  - `"Eligible for paper trade"` (was: some promotion pass label)
  - `"Awaiting research approval"` (was: promotion pending)
  - `"Not eligible"` (was: promotion blocked)

**File changes:** `execution_preview.html`, `views/execution.py`.

---

### EPIC 7 — Data Freshness & Staleness Indicators

#### T-UX-21 [P0] — Show data cache age next to every major data section
**Problem:** Operators cannot tell how stale displayed data is (Finding G-1).  
**Solution:** Add a `data-freshness-label` attribute and visible `<span class="data-freshness">As of [time]</span>` to:
- Cockpit instrument cluster header → "Cockpit data as of [cache_age_seconds]s ago"
- Command dashboard → "Updated [timestamp]"
- Final selection → "Selection data as of [cycle_as_of]"
- Execution preview → "Preview data as of [timestamp]"

The cockpit already has `monitor.last_update` — extend it to show the actual context cache age (expose from `cockpit_context()` as `context_freshness_label`).

**File changes:** `cockpit.html`, `dashboard.html`, `final_selection.html`, `execution_preview.html`. `views/cockpit.py` — add `context_freshness_label` to context.

---

#### T-UX-22 [P1] — Add pipeline chain view: Why is this candidate at this state?
**Problem:** When a candidate is blocked in execution, the operator must trace 5 pages manually (Finding G-2).  
**Solution:** On the execution preview card, add a collapsible "Trace" section that renders the pipeline chain for that candidate:

```
Evidence pack assembled ✓ [cycle date]
↓ Deterministic rules: PASS (score: 0.74)
↓ LLM review: APPROVE (confidence: 81%)
↓ Final selection: BUY
↓ Risk decision: APPROVE
↓ Paper eligibility: Awaiting order approval ← CURRENT
```

**Data:** All this information is already available in the execution context row. The view needs to format it as a sequential chain.  
**File changes:** `execution_preview.html`, `views/execution.py` (add `pipeline_chain` to row context).

---

### EPIC 8 — Navigation Cleanup

#### T-UX-23 [P1] — Rename navigation items to action-oriented labels

Current → Replacement:

| # | Current label | Replacement |
|---|---|---|
| 01 | V3 Cockpit | Today's Cockpit |
| 02 | Ops status | System Status |
| 03 | Candidates | Review Candidates |
| 04 | Portfolio | Portfolio |
| 05 | Execute | Submit Orders |
| 06 | Universe & market | Market & Universe |
| 07 | Signals | Signal Analysis |
| 08 | Risk | Risk Rules |
| 09 | Policy | Trading Policy |
| 10 | Learning | Learning Log |
| 11 | Audit | Audit Trail |

**File changes:** `base.html`.

---

#### T-UX-24 [P2] — Align Cockpit phase numbers with nav position
**Problem:** Cockpit phases 01–04 and nav items 01–11 use the same numbering but are unrelated (Finding A-3).  
**Solution:** Remove numeric labels from cockpit phase buttons. Use descriptive labels only:
- "Candidates" (was "01 Candidates")
- "Portfolio Review" (was "02 Portfolio")
- "Clearance" (was "03 Clearance")
- "Cleared" (was "04 Cleared")

**File changes:** `cockpit.html`.

---

#### T-UX-25 [P2] — Move "Research" nav section above "Core workflow"
**Problem:** Market regime and Signals are inputs to candidate review but sit below Execute in the nav (Finding A-4).  
**Solution:** Reorder nav sections:
1. Operate (Cockpit, System Status)
2. Research (Market & Universe, Signal Analysis)
3. Core workflow (Review Candidates, Portfolio, Submit Orders)
4. Controls (Risk Rules, Trading Policy)
5. Trust (Learning Log, Audit Trail)

**File changes:** `base.html`.

---

### EPIC 9 — Tooltip System Completion

#### T-UX-26 [P2] — Audit and complete all `info-tip` tooltips in dashboard.html
**Problem:** Tooltips exist inconsistently. Some labels have them, many don't.  
**Solution:** Audit every `<strong>`, `<span class="metric-label">`, and KPI `<article>` in `dashboard.html`. Add `info-tip` where missing with standardized tooltip text.

Priority labels needing tooltips (currently missing or incomplete):
- "Trade Eligibility" — what opens/closes this gate
- "Coverage" (source health KPI) — what percentage means "ready"
- "Reviewed" / "Pending" in review queue progress — does pending include deferred?
- "Open Risk" in readiness panel — distinct from blocked risk?
- "Confirmed signals" — vs total signals

**File changes:** `dashboard.html`. Create a `TOOLTIP_REGISTRY.md` doc with standard tooltip text for reuse.

---

### EPIC 10 — Data Pipeline Transparency (For Operators)

#### T-UX-27 [P2] — Scheduler state: add "how does this affect my candidates?" summary
**Problem:** Scheduler section shows technical lane data with no connection to candidate readiness (Finding G-4).  
**Solution:** At the top of the Automation & Refresh Queue section, add a one-line operator impact summary:
```
"[N] candidates may update when the current refresh completes (ETA: [time])."
```
Or if idle:
```
"Data is current. No active refresh affects today's candidate list."
```
**Data:** Cross-reference `scheduler.next_job_rows` with `candidates` tickers.  
**File changes:** `dashboard.html`, `views/command.py` (add `refresh_candidate_impact` to scheduler context).

---

## Summary: Ticket Priority Matrix

| Ticket | Priority | Epic | Est. effort |
|---|---|---|---|
| T-UX-01 Operator checklist widget | P0 | Guided Workflow | M |
| T-UX-02 Smart root redirect | P0 | Guided Workflow | S |
| T-UX-05 Replace jargon labels | P0 | Labels | M |
| T-UX-06 Standardize status vocab | P0 | Labels | L |
| T-UX-09 Command dashboard restructure | P0 | Command Dashboard | L |
| T-UX-10 Reduce KPI grid to 4 tiles | P0 | Command Dashboard | S |
| T-UX-21 Data freshness indicators | P0 | Freshness | M |
| T-UX-03 Workflow phase breadcrumb | P1 | Guided Workflow | M |
| T-UX-04 "What changed" delta badge | P1 | Guided Workflow | M |
| T-UX-07 Conviction score tooltip everywhere | P1 | Labels | S |
| T-UX-08 Evidence tier legend macro | P1 | Labels | S |
| T-UX-11 Email pipeline consolidation | P1 | Command Dashboard | S |
| T-UX-12 Dynamic cockpit page title | P1 | Cockpit | S |
| T-UX-13 "Operationability" → "What's blocking today" | P1 | Cockpit | S |
| T-UX-14 Phase button state (complete/active/pending) | P1 | Cockpit | M |
| T-UX-15 Clearance phrase field feedback | P1 | Cockpit | S |
| T-UX-16 Candidate detail page title | P1 | Candidate Detail | S |
| T-UX-17 Sticky bar conviction + reason | P1 | Candidate Detail | S |
| T-UX-18 Signal `as_of` timestamps | P1 | Candidate Detail | S |
| T-UX-19 Remove hash from visible metrics | P1 | Execution | S |
| T-UX-20 Paper Promotion → Eligibility | P1 | Execution | S |
| T-UX-22 Pipeline chain trace | P1 | Execution | M |
| T-UX-23 Rename nav items | P1 | Navigation | S |
| T-UX-24 Remove numeric phase labels | P2 | Navigation | S |
| T-UX-25 Reorder nav sections | P2 | Navigation | S |
| T-UX-26 Complete tooltip audit | P2 | Tooltips | M |
| T-UX-27 Scheduler → candidate impact summary | P2 | Pipeline | M |

---

## Recommended Implementation Order for Codex

**Sprint 1 (Foundation — highest operator impact):**
T-UX-09 → T-UX-10 → T-UX-01 → T-UX-05 → T-UX-06 → T-UX-21

**Sprint 2 (Workflow guidance):**
T-UX-02 → T-UX-03 → T-UX-12 → T-UX-13 → T-UX-14 → T-UX-23

**Sprint 3 (Candidate & execution clarity):**
T-UX-16 → T-UX-17 → T-UX-18 → T-UX-19 → T-UX-20 → T-UX-22

**Sprint 4 (Polish):**
T-UX-04 → T-UX-07 → T-UX-08 → T-UX-11 → T-UX-15 → T-UX-24 → T-UX-25 → T-UX-26 → T-UX-27
