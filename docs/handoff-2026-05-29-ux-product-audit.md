# Handoff: UX Product Audit — 2026-05-29

Branch: `feat/ux-product-audit-20260529`  
Date: 2026-05-29  
Author: Meiri / Claude Sonnet 4.6

---

## What this branch is about

A full UX product audit of the operator-facing UI.  
Goal: remove internal sprint jargon, restructure the command dashboard around a clear Act / Diagnose / Archive hierarchy, add operator-language labels, tooltips, and conviction helpers across all key pages.

Driven by a formal spec: `docs/specs/2026-05-29-ux-product-audit.md`  
Implementation notes: `docs/decisions/2026-05-29-ux-product-audit-implementation.md`

---

## Current state

### Committed (108bf89)
The UX audit core implementation is **committed and complete**:

| Area | What was done |
|---|---|
| `base.html` | Sidebar relabeled to operator workflow labels (Today's Cockpit, Review Candidates, Submit Orders, Market & Universe, Signal Analysis, Risk Rules, Trading Policy, Audit Trail). Global phase rail changed to plain words (Review Candidates / Portfolio Check / Order Clearance / Order Audit). Workflow breadcrumb added. Mobile nav (`max-width: 640px`) improved. |
| `dashboard.html` | Act zone (`command-act-zone`) placed first, then Review Queue, then Diagnose zone (`command-diagnose-zone`). 4 prioritized KPIs only: Needs Review, System Status, Data Coverage, Trade Gate. Email progress shown conditionally (not as idle prime real estate). Data freshness visible via `command_freshness_label`. Scheduler candidate impact with `scheduler_candidate_impact` tooltip. |
| `cockpit.html` | Dynamic readiness title (`scenario.browser_title` / `scenario.page_title`). Phase states non-numeric. Candidate action legend ("Why buttons change"). Clearance phrase: `placeholder="type: submit paper orders"` with live match feedback in `cockpit.js`. |
| `candidate_detail.html` | Sticky context bar. Decision-focused title: `decision_brief.action_label`, `decision_brief.top_reason_brief`, `decision_brief.conviction_pct`. `evidence_delta_since_review` shown. Timestamp label as "Data as of {{ signal.timestamp_label }}". |
| `execution_preview.html` | "Eligibility" instead of "Paper Promotion". `order_integrity_label`, `pipeline_chain`. Plain-language archive labels. "Policy-stopped / context-only" and "No transaction / stopped by policy". No "Intent hash". |
| `final_selection.html` | "Context-Only Archive" and "Policy-Gated Archive" labels. Plain description rows. |
| `_evidence_legend.html` | New shared partial: "confirmed direct data" explanation. |
| `views/_shared.py` | `operator_status_label()` function: maps domain states (PASS/ALLOW/WARN/BLOCK/NO_TRADE/DISABLED) to 4 display states (Ready / Attention / Blocked / Inactive). |
| `views/command.py` | Lane-state copy rewritten in operator language. Forbidden phrases removed (Massive lane, Blocking reason, No Massive stock-trades, etc.). |
| `views/candidates.py`, `views/cockpit.py`, `views/execution.py` | Updated to pass new template variables. |
| `static/styles.css` | `.command-act-zone`, `.command-diagnose-zone`, `.operator-checklist-card`, `.operator-state-{ready,attention,blocked,inactive}` CSS classes added. |
| `static/cockpit.js` | Clearance phrase live match + "Phrase matches" / "Type the exact phrase" feedback. |
| `docs/TOOLTIP_REGISTRY.md` | Created with "Trade Eligibility" entry. |
| **Tests** | `test_ux_product_audit_20260529.py` — 18 tests, all passing. |

---

### Uncommitted (working tree — 16 files modified)

A second round of follow-on fixes is staged but **not yet committed**.  
All 18 tests in `test_ux_product_audit_20260529.py` pass on current working tree.

Files modified since 108bf89:

```
schemas/execution-preview.schema.json       (+8)   schema additions
src/agency/services/execution_preview.py    (+2)   service field additions
src/agency/static/data-refresh-progress.js  (~52)  operator language in JS progress copy
src/agency/templates/_cockpit_panels.html   (~12)  operator copy cleanup
src/agency/templates/_data_health.html      (~10)  operator copy cleanup
src/agency/templates/base.html              (~24)  nav/breadcrumb refinements
src/agency/templates/candidate_detail.html  (+4)   minor fix
src/agency/templates/cockpit.html           (~12)  cockpit panel refinements
src/agency/templates/dashboard.html         (~36)  dashboard refinements
src/agency/templates/execution_preview.html (~16)  operator language
src/agency/templates/final_selection.html   (~18)  archive label fixes
src/agency/views/command.py                 (~100)  lane-state operator language (large rewrite)
src/agency/views/execution.py               (+40)  execution view additions
tests/unit/test_cockpit_routes.py           (+34)  new route tests
tests/unit/test_execution_preview_service.py (+13) new service tests
tests/unit/test_ux_product_audit_20260529.py (+87) extended audit tests
```

**Next action: commit these working-tree changes.**  
Suggested commit message:
```
UX audit follow-on: operator language, schema, JS copy, extended tests

- Rewrite lane-state copy in command.py to operator language
- Extend execution preview schema + service fields
- Fix JS progress copy in data-refresh-progress.js
- Operator language cleanup across all modified templates
- +87 lines to UX audit tests (all 18 pass)
- +34 cockpit route tests, +13 execution preview service tests
```

---

## Test coverage

```
tests/unit/test_ux_product_audit_20260529.py  — 18 tests — ALL PASSING
```

Key assertions covered:
- Act zone appears before Review Queue before Diagnose zone
- 4 KPIs only (Needs Review, System Status, Data Coverage, Trade Gate)
- Email progress is conditional
- Data freshness visible
- `operator_status_label()` maps 6 domain statuses to 4 display states
- ~12 forbidden sprint-1 jargon phrases absent from combined templates
- CSS defines all 6 operator classes
- Mobile shell rules present
- Sidebar uses operator workflow labels + breadcrumb
- Global phase rail uses plain words not numeric steps (01/02/03/04)
- Cockpit uses dynamic readiness title + non-numeric phases
- Candidate detail is decision-focused
- Execution preview hides hash, uses traceable operator language
- Final selection uses plain archive labels
- Shared evidence legend + conviction tooltips present in 3 templates
- Cockpit clearance phrase has live JS feedback
- Scheduler impact + TOOLTIP_REGISTRY.md present
- Lane-state copy uses operator language (18 forbidden phrases absent)

---

## Open gaps (from audit spec that may still be pending)

Check `docs/specs/2026-05-29-ux-product-audit.md` for the full audit checklist.  
Items that were deferred or may not yet be implemented:
- Any spec items not covered by the 18 test assertions above
- Manual visual verification of mobile layout at 640px
- TOOLTIP_REGISTRY.md is minimal (one entry); may need to grow as more tooltips are added

---

## How to continue in a new session

1. **Commit the working tree** (16 files) with the message above.
2. Verify all tests still pass: `python -m pytest tests/unit/ -x --tb=short`
3. Check `docs/specs/2026-05-29-ux-product-audit.md` for any unchecked spec items.
4. After all spec items are done, update `docs/phase-status.md` with a "UX audit complete" entry.
5. When ready to merge: `git checkout main && git merge feat/ux-product-audit-20260529`

---

## Key file map

| File | Role |
|---|---|
| `docs/specs/2026-05-29-ux-product-audit.md` | Full audit spec (source of truth) |
| `docs/decisions/2026-05-29-ux-product-audit-implementation.md` | Implementation decisions |
| `docs/TOOLTIP_REGISTRY.md` | Tooltip catalogue |
| `src/agency/views/_shared.py` | `operator_status_label()` helper |
| `tests/unit/test_ux_product_audit_20260529.py` | Audit regression tests |
