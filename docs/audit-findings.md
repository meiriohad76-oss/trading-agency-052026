# Trading Agency v2 - UX & Product Audit Findings
Date: 2026-05-18
Spec: docs/superpowers/specs/2026-05-18-ux-audit-design.md

## Summary

| Severity | Count |
|----------|------:|
| P0 - blocks workflow | 6 |
| P1 - degrades UX | 42 |
| P2 - polish | 9 |
| **Total** | **57** |

Deduplication note: candidate-detail parent navigation and portfolio P/L position-card findings were merged across agents because they described the same actionable gap.

## Implementation Order

1. [F001] Actionable candidate cards hide the decision rationale, policy gates, and plain... (P0 - final_selection.html)
2. [F002] Exit recommendations have no single confirm action for the user to approve an exit (P0 - Portfolio Monitor)
3. [F003] The core agent-generated Exit Recommendations panel is missing (P0 - Portfolio Monitor)
4. [F004] The exit review rows do not show recommendation urgency or exposure freed, so t... (P0 - Portfolio Monitor)
5. [F005] Execution Preview submit_enabled does not check a human approval or promotion r... (P0 - Approval flow)
6. [F006] Risk logic has no WATCH-to-ALLOW promotion path on human approval (P0 - Approval flow)
7. [F007] Candidate Detail lacks a breadcrumb, Back to candidates link, or Next candidate... (P1 - Candidate Detail)
8. [F008] Raw provenance-derived values are visible outside collapsed details (P1 - Candidate Detail)
9. [F009] Supporting signal evidence is expanded by default instead of being collapsed be... (P1 - Candidate Detail)
10. [F010] The largest first-row element is the ticker, while the recommendation chip and... (P1 - Candidate Detail)
11. [F011] Blocked signals are counted with the blue neutral tag instead of the red blocke... (P1 - candidate_detail.html)
12. [F012] Candidate cards offer Candidate, Risk, and Selection links but no contextual Po... (P1 - Command dashboard)
13. [F013] Data Sources remains an always-visible readiness panel instead of being collaps... (P1 - Command dashboard)
14. [F014] The dashboard template has no explicit LLM-disabled banner in the primary conte... (P1 - Command dashboard)
15. [F015] The hero primary CTA reviews only the top ticker instead of the full pending ca... (P1 - Command dashboard)
16. [F016] Agent-produced outputs and user-required actions share the same tag and button... (P1 - Cross-screen agent actions)
17. [F017] The ready-to-review state uses an undefined `tag-urgent` class, so a manual act... (P1 - dashboard.html)
18. [F018] Approve, Defer, and Reject controls are text-only and Approve and Defer share t... (P1 - dashboard.html and candidate_detail.html)
19. [F019] Candidate rows expose deterministic, LLM, evidence, risk, human review, timesta... (P1 - Final Selection)
20. [F020] Candidates are grouped into Actionable Review Queue and Rejected/Blocked Tracea... (P1 - Final Selection)
21. [F021] The action badge is always neutral, so WATCH, BLOCKED, and NO_TRADE are not col... (P1 - Final Selection)
22. [F022] The top KPI row does not provide the required Selected, Blocked, and No-Trade t... (P1 - Final Selection)
23. [F023] The monitor only flags a trailing stop after it is breached, not when it is wit... (P1 - Portfolio Monitor)
24. [F024] The left nav does not represent the core Candidates to Portfolio to Execute seq... (P1 - base.html)
25. [F025] Candidate Detail does not show whether the candidate is already held in the por... (P1 - Candidate Detail)
26. [F026] The Command dashboard does not warn about portfolio exposure near policy limit... (P1 - Command dashboard)
27. [F027] Portfolio Monitor does not provide a clear path from existing positions to the... (P1 - Portfolio Monitor)
28. [F028] Position Review renders dense table rows with unstyled P/L instead of position... (P1 - Portfolio Monitor)
29. [F029] The empty portfolio state does not include a direct Candidates CTA, so the user... (P1 - Portfolio Monitor)
30. [F030] The monitor does not explain what capacity is freed by an exit recommendation (P1 - Portfolio Monitor)
31. [F031] The screen has no explicit "no exits needed" state when the portfolio is within... (P1 - Portfolio Monitor)
32. [F032] The screen lacks a single policy compliance indicator that tells the user wheth... (P1 - Portfolio Monitor)
33. [F033] The top portfolio summary does not present total exposure, cash available, and... (P1 - Portfolio Monitor)
34. [F034] The per-row LLM disabled state is not rendered even though the service returns... (P1 - Risk dashboard and Execution Preview)
35. [F035] Approval does not show a clear state-change confirmation that execution preview... (P1 - Approval flow)
36. [F036] The approval-to-order path requires more than three user actions because execut... (P1 - Approval flow)
37. [F037] Paper-mode messaging is inconsistent because execution uses an unstyled banner... (P1 - Cross-screen paper mode)
38. [F038] The submit flow has a POST form but no inline post-submission confirmation stat... (P1 - Execution Preview)
39. [F039] LLM/rules conflicts are not visually flagged with an amber indicator (P1 - Risk dashboard and Execution Preview)
40. [F040] Long technical provenance strings such as cycle IDs, timestamps, hashes, and mo... (P1 - Cross-screen provenance)
41. [F041] Agent-resolved risk checks are exposed as full criteria and next-step detail in... (P1 - Risk dashboard)
42. [F042] Ready candidates do not have a direct per-row link to their Execution Preview row (P1 - Risk dashboard)
43. [F043] The Risk dashboard does not group candidates into the required Ready to review,... (P1 - Risk dashboard)
44. [F044] Candidate rows do not show an inline LLM recommendation with one-line rationale (P1 - Risk dashboard and Execution Preview)
45. [F045] Deterministic score and LLM recommendation are not displayed side by side (P1 - Risk dashboard and Execution Preview)
46. [F046] Expand/collapse controls use multiple component classes with different visual t... (P1 - Cross-screen details)
47. [F047] Full LLM rationale is visible by default in the prompt audit table instead of b... (P1 - audit.html)
48. [F048] Status types rely on color-only dots and text tags instead of a consistent icon... (P1 - base.html)
49. [F049] The subscription evidence section uses a different label and ends its pipeline... (P2 - Candidate Detail)
50. [F050] Review cards distinguish reviewable, blocked, and decided states with color and... (P2 - Command dashboard)
51. [F051] Summary labels vary between rationale names, inspect verbs, show verbs, and ins... (P2 - Cross-screen details)
52. [F052] The zero-position table empty state is generic and does not explain that positi... (P2 - Portfolio Monitor)
53. [F053] LLM rationale is not shown as a one-line summary with expandable full reasoning (P2 - Risk dashboard and Execution Preview)
54. [F054] There is no bulk action to submit all ready orders (P2 - Execution Preview)
55. [F055] Neither page shows a page-level LLM system status indicator before review (P2 - Risk dashboard and Execution Preview)
56. [F056] The Risk dashboard has drill-down gate details but no candidate-by-dimension ri... (P2 - Risk dashboard)
57. [F057] Placeholder or secondary screens named in the checklist are rendered as normal... (P2 - base.html)

---

## P0 Findings

### [F001] Actionable candidate cards hide the decision rationale, policy gates, and plain...
- **Screen:** final_selection.html
- **Category:** BLUF
- **Severity:** P0
- **Finding:** Actionable candidate cards hide the decision rationale, policy gates, and plain reason rows behind a collapsed details control.
- **Evidence:** `src/agency/templates/final_selection.html:57 '<details class="details-panel compact-details">'; src/agency/templates/final_selection.html:93 '<div class="reason-code-list" aria-label="Plain reason list">'`
- **Fix:** Move the policy gate summary and top three plain reason rows into the always-visible selection card, leaving only raw audit or long rationale text collapsed.
- **Acceptance:** Each actionable selection card shows recommendation, conviction, gate status, and three plain reasons before any details element is opened.

### [F002] Exit recommendations have no single confirm action for the user to approve an exit
- **Screen:** Portfolio Monitor
- **Category:** Semi-Auto
- **Severity:** P0
- **Finding:** Exit recommendations have no single confirm action for the user to approve an exit.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:216 - '<td>{{ position.exit_reason }}</td>' renders guidance text as the row action, and the row contains no '<form>' or '<button>'.`
- **Fix:** Add one confirm exit button per recommendation that submits the appropriate close-review or exit action.
- **Acceptance:** Every rendered exit recommendation includes exactly one primary confirmation button.

### [F003] The core agent-generated Exit Recommendations panel is missing
- **Screen:** Portfolio Monitor
- **Category:** Semi-Auto
- **Severity:** P0
- **Finding:** The core agent-generated Exit Recommendations panel is missing.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:176 - '<h2 id="positions-heading">Position Review</h2>' is the only exit-related section title, with no "Exit Recommendations" panel in the template.`
- **Fix:** Add a dedicated "Exit Recommendations" panel generated from close candidates or exit-rule output.
- **Acceptance:** The portfolio page renders a named "Exit Recommendations" section whenever exit recommendation data is available.

### [F004] The exit review rows do not show recommendation urgency or exposure freed, so t...
- **Screen:** Portfolio Monitor
- **Category:** Semi-Auto
- **Severity:** P0
- **Finding:** The exit review rows do not show recommendation urgency or exposure freed, so they are not actionable semi-auto recommendations.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:183 - '<th>Ticker</th>' starts a table whose headers are Ticker, State, Exit Signal, Current Thesis, Position, Unrealized P/L, Rule Trigger, and What To Do.`
- **Fix:** Model and render per-recommendation ticker, plain-English reason, exposure freed, and urgency values.
- **Acceptance:** Each exit recommendation row or card contains ticker, reason, exposure freed, and urgency labeled Now, Soon, or Optional.

### [F005] Execution Preview submit_enabled does not check a human approval or promotion r...
- **Screen:** Approval flow
- **Category:** Semi-Auto
- **Severity:** P0
- **Finding:** Execution Preview submit_enabled does not check a human approval or promotion record.
- **Evidence:** `src/agency/services/execution_preview.py:120 sets submit_enabled from policy, READY state, side, size, broker account, and order conflict only.`
- **Fix:** Include the human approval or WATCH-to-ALLOW promotion record in the submit_enabled calculation.
- **Acceptance:** A READY preview without the required approval record has submit_enabled False, and the same preview with the approval record has submit_enabled True.

### [F006] Risk logic has no WATCH-to-ALLOW promotion path on human approval
- **Screen:** Approval flow
- **Category:** Semi-Auto
- **Severity:** P0
- **Finding:** Risk logic has no WATCH-to-ALLOW promotion path on human approval.
- **Evidence:** `src/agency/services/risk.py:409 returns review actions through _review_only_caution_check and src/agency/services/risk.py:419 returns "WATCH is review-only" as WARN.`
- **Fix:** Add a promotion function or equivalent risk decision path that turns an approved WATCH candidate into ALLOW when paper-trade promotion requirements are satisfied.
- **Acceptance:** A unit test with a human-approved WATCH report produces a risk decision with decision "ALLOW".


---

## P1 Findings

### [F007] Candidate Detail lacks a breadcrumb, Back to candidates link, or Next candidate...
- **Screen:** Candidate Detail
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Candidate Detail lacks a breadcrumb, Back to candidates link, or Next candidate control to return the user to the parent list.
- **Evidence:** `src/agency/templates/candidate_detail.html:31 - <a class="text-link" href="#paper-review-heading">Jump to review</a>; src/agency/templates/candidate_detail.html:31 '<a class="text-link" href="#paper-review-heading">Jump to review</a>'`
- **Fix:** Add a consistent breadcrumb or Back to candidates link near the top of Candidate Detail that returns to Final Selection or the review queue, and keep any Next candidate control in the same navigation cluster.
- **Acceptance:** The Candidate Detail first viewport contains a visible link back to the parent candidate list or a Next candidate control.
<!-- Sources: Agent A, Agent D -->

### [F008] Raw provenance-derived values are visible outside collapsed details
- **Screen:** Candidate Detail
- **Category:** BLUF
- **Severity:** P1
- **Finding:** Raw provenance-derived values are visible outside collapsed details.
- **Evidence:** `src/agency/templates/candidate_detail.html:61 - <span class="metric-label">Sources</span>`
- **Fix:** Move timestamp_as_of, source_count, verification_level, run_id, and input_snapshot_id into a collapsed technical provenance details section.
- **Acceptance:** Those five provenance fields are not visible on initial page load and appear only after expanding technical provenance.

### [F009] Supporting signal evidence is expanded by default instead of being collapsed be...
- **Screen:** Candidate Detail
- **Category:** BLUF
- **Severity:** P1
- **Finding:** Supporting signal evidence is expanded by default instead of being collapsed behind a Supporting detail section.
- **Evidence:** `src/agency/templates/candidate_detail.html:157 - <section class="panel signal-evidence-panel" aria-labelledby="signal-evidence-heading">`
- **Fix:** Keep Why This Stock Is Here as the always-visible summary and move Primary Signal Evidence into a collapsed <details> section labeled Supporting detail.
- **Acceptance:** Opening a candidate page shows no Active Signals, Advisory Signals, or Blocked Signals lists until Supporting detail is expanded.

### [F010] The largest first-row element is the ticker, while the recommendation chip and...
- **Screen:** Candidate Detail
- **Category:** BLUF
- **Severity:** P1
- **Finding:** The largest first-row element is the ticker, while the recommendation chip and conviction score are secondary.
- **Evidence:** `src/agency/templates/candidate_detail.html:39 - <h2>{{ ticker }}</h2>`
- **Fix:** Make the recommendation and conviction score the dominant first content in the decision brief and demote the ticker to supporting context.
- **Acceptance:** The first decision brief row visually prioritizes WATCH or NO_TRADE and the conviction percent over the ticker symbol.

### [F011] Blocked signals are counted with the blue neutral tag instead of the red blocke...
- **Screen:** candidate_detail.html
- **Category:** Design System
- **Severity:** P1
- **Finding:** Blocked signals are counted with the blue neutral tag instead of the red blocked/rejected color.
- **Evidence:** `src/agency/templates/candidate_detail.html:249 '<strong title="Signals blocked by freshness or data-quality gates. They are tracked but have no effect on the decision.">Blocked Signals</strong>'; src/agency/templates/candidate_detail.html:250 '<span class="tag tag-neutral">{{ latest_report.suppressed_signals | length }}</span>'`
- **Fix:** Render the blocked/suppressed signal count with 'tag-block' while keeping advisory/context signals on 'tag-warn' and active signals on 'tag-pass'.
- **Acceptance:** The Blocked Signals count appears red on candidate detail whenever suppressed signals are shown.

### [F012] Candidate cards offer Candidate, Risk, and Selection links but no contextual Po...
- **Screen:** Command dashboard
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Candidate cards offer Candidate, Risk, and Selection links but no contextual Portfolio or Execute next-step link.
- **Evidence:** `src/agency/templates/dashboard.html:187 - <a class="text-link" href="{{ item.candidate_href }}">Candidate</a>`
- **Fix:** Add a clearly labeled Portfolio or Execute next-step link in the queue area after review actions are shown.
- **Acceptance:** A review card or queue-level action contains a visible link to /portfolio-monitor or /execution-preview.

### [F013] Data Sources remains an always-visible readiness panel instead of being collaps...
- **Screen:** Command dashboard
- **Category:** BLUF
- **Severity:** P1
- **Finding:** Data Sources remains an always-visible readiness panel instead of being collapsed with the other readiness diagnostics.
- **Evidence:** `src/agency/templates/dashboard.html:1428 - <section class="panel" aria-labelledby="source-heading">`
- **Fix:** Move Data Sources into the collapsed operational details group or wrap it in a collapsed <details> section by default.
- **Acceptance:** Loading the Command dashboard shows no Data Sources table until the user expands readiness details.

### [F014] The dashboard template has no explicit LLM-disabled banner in the primary conte...
- **Screen:** Command dashboard
- **Category:** BLUF
- **Severity:** P1
- **Finding:** The dashboard template has no explicit LLM-disabled banner in the primary content path.
- **Evidence:** `src/agency/templates/dashboard.html:12 - <section class="next-action {{ summary.hero_class }}" aria-label="Recommended next action">`
- **Fix:** Render a visible warning or neutral banner in the hero or queue area when LLM review is disabled or unavailable.
- **Acceptance:** With LLM disabled, the Command dashboard displays an above-the-fold indicator that says LLM review is disabled or unavailable.

### [F015] The hero primary CTA reviews only the top ticker instead of the full pending ca...
- **Screen:** Command dashboard
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** The hero primary CTA reviews only the top ticker instead of the full pending candidate queue.
- **Evidence:** `src/agency/templates/dashboard.html:29 - <a class="primary-action" href="{{ review_queue[0].candidate_href }}">Review {{ review_queue[0].ticker }}</a>`
- **Fix:** Change the hero primary CTA to Review {{ review_progress.pending_count }} candidates and link it to #review-queue-heading while keeping per-ticker review links inside candidate cards.
- **Acceptance:** With three pending candidates, the first primary action reads Review 3 candidates and jumps to the Review Queue.

### [F016] Agent-produced outputs and user-required actions share the same tag and button...
- **Screen:** Cross-screen agent actions
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** Agent-produced outputs and user-required actions share the same tag and button vocabulary without a robot/agent marker or user-action marker.
- **Evidence:** `src/agency/templates/dashboard.html:418 '<article class="command-status-card command-status-{{ agents_card.status_class }}" data-command-card="agents">'; src/agency/templates/dashboard.html:174 '<button class="mini-button" type="submit">Approve</button>'`
- **Fix:** Add a consistent visual marker for automated agent outputs and a separate marker for user-required approvals or acknowledgements.
- **Acceptance:** A user can identify agent-generated status versus human-required action from icon/color treatment alone on dashboard, final selection, risk, and execution screens.

### [F017] The ready-to-review state uses an undefined `tag-urgent` class, so a manual act...
- **Screen:** dashboard.html
- **Category:** Design System
- **Severity:** P1
- **Finding:** The ready-to-review state uses an undefined `tag-urgent` class, so a manual action-required state can fall back to the neutral tag treatment.
- **Evidence:** `src/agency/templates/dashboard.html:129 '<span class="tag tag-urgent">Ready to review</span>'`
- **Fix:** Replace 'tag-urgent' with the existing warning/attention token or add a defined '.tag-urgent' style that maps to the amber attention system.
- **Acceptance:** Ready-to-review candidates render with the same amber attention color as other user-review-required states.

### [F018] Approve, Defer, and Reject controls are text-only and Approve and Defer share t...
- **Screen:** dashboard.html and candidate_detail.html
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** Approve, Defer, and Reject controls are text-only and Approve and Defer share the same neutral button style.
- **Evidence:** `src/agency/templates/dashboard.html:174 '<button class="mini-button" type="submit">Approve</button>'; src/agency/templates/dashboard.html:177 '<button class="mini-button" type="submit">Defer</button>'; src/agency/templates/dashboard.html:180 '<button class="mini-button danger-button" type="submit">Reject</button>'`
- **Fix:** Give Approve, Defer, and Reject distinct icon-plus-color treatments that map to pass, warn, and block/reject semantics.
- **Acceptance:** The three review actions are distinguishable by both icon and color before reading their labels.

### [F019] Candidate rows expose deterministic, LLM, evidence, risk, human review, timesta...
- **Screen:** Final Selection
- **Category:** BLUF
- **Severity:** P1
- **Finding:** Candidate rows expose deterministic, LLM, evidence, risk, human review, timestamps, and multiple badges by default instead of only ticker, conviction, and top reason.
- **Evidence:** `src/agency/templates/final_selection.html:35 - <div class="selection-facts">`
- **Fix:** Collapse secondary facts into details and keep the default row surface to ticker, conviction score, and one top reason.
- **Acceptance:** A default candidate row shows no deterministic, LLM, evidence, risk, timestamp, or human-review fields until expanded.

### [F020] Candidates are grouped into Actionable Review Queue and Rejected/Blocked Tracea...
- **Screen:** Final Selection
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Candidates are grouped into Actionable Review Queue and Rejected/Blocked Traceability instead of WATCH, NO_TRADE, and BLOCKED action sections.
- **Evidence:** `src/agency/templates/final_selection.html:155 - <section class="panel" aria-labelledby="final-heading">`
- **Fix:** Render explicit WATCH, NO_TRADE, and BLOCKED sections in that order with section-level colors matching the action meaning.
- **Acceptance:** Final Selection displays WATCH first, NO_TRADE second, and BLOCKED last regardless of conviction ordering.

### [F021] The action badge is always neutral, so WATCH, BLOCKED, and NO_TRADE are not col...
- **Screen:** Final Selection
- **Category:** Design System
- **Severity:** P1
- **Finding:** The action badge is always neutral, so WATCH, BLOCKED, and NO_TRADE are not color-encoded by action.
- **Evidence:** `src/agency/templates/final_selection.html:16 - <span class="tag tag-neutral">{{ row.action }}</span>`
- **Fix:** Map row.action to action-specific tag classes such as pass for WATCH, neutral for NO_TRADE, and block for BLOCKED.
- **Acceptance:** WATCH, NO_TRADE, and BLOCKED badges render with distinct action-specific colors.

### [F022] The top KPI row does not provide the required Selected, Blocked, and No-Trade t...
- **Screen:** Final Selection
- **Category:** BLUF
- **Severity:** P1
- **Finding:** The top KPI row does not provide the required Selected, Blocked, and No-Trade three-number summary.
- **Evidence:** `src/agency/templates/final_selection.html:130 - <section class="kpi-grid kpi-grid-compact" aria-label="Final selection metrics">`
- **Fix:** Replace the Reports, Actionable, Blocked, and History Hidden KPI set with Selected, Blocked, and No-Trade counts.
- **Acceptance:** The first metric row on Final Selection contains exactly Selected, Blocked, and No-Trade counts.

### [F023] The monitor only flags a trailing stop after it is breached, not when it is wit...
- **Screen:** Portfolio Monitor
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** The monitor only flags a trailing stop after it is breached, not when it is within 5% of triggering.
- **Evidence:** `src/agency/services/portfolio_monitor.py:248 - 'and (high_water_mark - pnl_pct) >= policy.trailing_stop_pct'`
- **Fix:** Add a proximity calculation for positions within 5 percentage points of the trailing-stop threshold and expose a warning flag to the template.
- **Acceptance:** A position whose drawdown is within 5 percentage points of the trailing-stop threshold renders a red or amber trailing-stop proximity alert.

### [F024] The left nav does not represent the core Candidates to Portfolio to Execute seq...
- **Screen:** base.html
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** The left nav does not represent the core Candidates to Portfolio to Execute sequence as a grouped path or progress indicator.
- **Evidence:** `src/agency/templates/base.html:36 '<span class="nav-section">Decide</span>'; src/agency/templates/base.html:50 '<span class="nav-section">Execute</span>'; src/agency/templates/base.html:51 '<a class="nav-link {% if active_nav == 'execution' %}active{% endif %}" href="/execution-preview">'; src/agency/templates/base.html:55 '<a class="nav-link {% if active_nav == 'portfolio' %}active{% endif %}" href="/portfolio-monitor">'`
- **Fix:** Add a dedicated yellow-brick-road nav group or progress strip that orders Candidates, Portfolio, and Execute as the primary workflow.
- **Acceptance:** The nav visually presents Candidates, Portfolio, and Execute as one ordered workflow distinct from secondary screens.

### [F025] Candidate Detail does not show whether the candidate is already held in the por...
- **Screen:** Candidate Detail
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Candidate Detail does not show whether the candidate is already held in the portfolio.
- **Evidence:** `src/agency/templates/candidate_detail.html:38 - '<div class="brief-title-row">' renders the ticker and action chip only, with no current-holding badge or portfolio branch in the file.`
- **Fix:** Pass current holding context into Candidate Detail and render a "Currently holding X shares" badge near the ticker when applicable.
- **Acceptance:** For a candidate ticker that exists in portfolio positions, Candidate Detail shows a visible current-holding badge with share quantity.

### [F026] The Command dashboard does not warn about portfolio exposure near policy limit...
- **Screen:** Command dashboard
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** The Command dashboard does not warn about portfolio exposure near policy limit before candidate review.
- **Evidence:** `src/agency/templates/dashboard.html:44 - '<section class="kpi-grid" aria-label="Current metrics">' renders review and readiness KPIs, and no exposure or portfolio limit warning branch appears in the dashboard template.`
- **Fix:** Add an exposure-warning element above or beside the review queue when gross exposure is near the policy maximum.
- **Acceptance:** When exposure is within the configured warning band of the limit, the dashboard shows a visible exposure warning before the review queue.

### [F027] Portfolio Monitor does not provide a clear path from existing positions to the...
- **Screen:** Portfolio Monitor
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Portfolio Monitor does not provide a clear path from existing positions to the Execution Preview screen.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:174 - '<section class="panel" aria-labelledby="positions-heading">' renders the Position Review section without any execution preview link.`
- **Fix:** Add a visible link from the Position Review or Exit Recommendations area to the Execution Preview route for managing existing positions.
- **Acceptance:** The Portfolio Monitor page contains a visible "Execution Preview" or "Execute" link whose 'href' opens the execution preview screen.

### [F028] Position Review renders dense table rows with unstyled P/L instead of position...
- **Screen:** Portfolio Monitor
- **Category:** Design System
- **Severity:** P1
- **Finding:** Position Review renders dense table rows with unstyled P/L instead of position cards with entry price, green/red P/L, thesis validity, and stop distance.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:180 - '<table>' under Position Review is the default position display, and src/agency/templates/portfolio_monitor.html:214 - '<td>{% if position.unrealized_pl is not none %}${{ "%.2f"|format(position.unrealized_pl) }} / {{ "%.2f"|format(position.unrealized_plpc * 100) }}%{% else %}None{% endif %}</td>' renders P/L without a profit/loss color class.; src/agency/templates/portfolio_monitor.html:214 '<td>{% if position.unrealized_pl is not none %}${{ "%.2f"|format(position.unrealized_pl) }} / {{ "%.2f"|format(position.unrealized_plpc * 100) }}%{% else %}None{% endif %}</td>'`
- **Fix:** Replace or supplement the table with position cards and style P/L with green for gains, red for losses, neutral for flat, and stronger numeric emphasis.
- **Acceptance:** For one sample position, the monitor renders a card containing ticker, entry price, thesis validity, stop distance, and P/L styling that changes for positive versus negative values.
<!-- Sources: Agent B, Agent D -->

### [F029] The empty portfolio state does not include a direct Candidates CTA, so the user...
- **Screen:** Portfolio Monitor
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** The empty portfolio state does not include a direct Candidates CTA, so the user is stranded after learning there is nothing to monitor.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:58 - '<section class="panel empty-state-panel" aria-label="No portfolio data">' contains only explanatory copy before the '{% endif %}' at line 68.`
- **Fix:** Add a visible link or button in the empty-state panel to the canonical Candidates screen with text like "Go to Candidates".
- **Acceptance:** With no portfolio data, the empty-state panel renders one visible CTA whose 'href' opens the candidate review list.

### [F030] The monitor does not explain what capacity is freed by an exit recommendation
- **Screen:** Portfolio Monitor
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** The monitor does not explain what capacity is freed by an exit recommendation.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:215 - '<td>{{ position.reason }}</td>' and src/agency/templates/portfolio_monitor.html:216 - '<td>{{ position.exit_reason }}</td>' render rule text without an "exiting X frees Y% -> allows Z" effect line.`
- **Fix:** Add a downstream-effect line to each recommendation showing exposure freed and the number of new positions enabled.
- **Acceptance:** Each recommendation includes text matching the structure "Exiting [ticker] frees [percent] exposure -> allows [count] new position(s)."

### [F031] The screen has no explicit "no exits needed" state when the portfolio is within...
- **Screen:** Portfolio Monitor
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** The screen has no explicit "no exits needed" state when the portfolio is within policy.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:177 - '<span class="tag tag-neutral">No auto-close</span>'`
- **Fix:** Render "Portfolio within policy - no exits needed" when there are positions but no exit recommendations.
- **Acceptance:** With positions present and no exit recommendations, the Exit Recommendations panel displays the no-exits-needed copy.

### [F032] The screen lacks a single policy compliance indicator that tells the user wheth...
- **Screen:** Portfolio Monitor
- **Category:** BLUF
- **Severity:** P1
- **Finding:** The screen lacks a single policy compliance indicator that tells the user whether the portfolio is within limits or over exposure.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:43 - '<article class="kpi kpi-urgent">' displays Exposure, but no "Within limits" or "Over exposure" status is rendered in the metrics section.`
- **Fix:** Add one policy compliance status component driven by gross exposure versus max allowed exposure.
- **Acceptance:** When gross exposure is below the limit the monitor shows "Within limits", and when above the limit it shows "Over exposure".

### [F033] The top portfolio summary does not present total exposure, cash available, and...
- **Screen:** Portfolio Monitor
- **Category:** BLUF
- **Severity:** P1
- **Finding:** The top portfolio summary does not present total exposure, cash available, and max allowed as a single dominant three-number exposure summary.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:21 - '<section class="kpi-grid kpi-grid-compact" aria-label="Portfolio monitor metrics">' renders portfolio metrics, while cash appears later at line 114 and no max-allowed value is rendered.`
- **Fix:** Add a top exposure summary panel with total exposure percent, cash available, and max allowed pulled from policy and account data.
- **Acceptance:** Opening Portfolio Monitor shows those three numbers together above rules, broker, snapshot, and position sections.

### [F034] The per-row LLM disabled state is not rendered even though the service returns...
- **Screen:** Risk dashboard and Execution Preview
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** The per-row LLM disabled state is not rendered even though the service returns a disabled stub.
- **Evidence:** `src/agency/services/llm_review.py:130 returns build_llm_review_stub when LLM review is disabled and src/agency/services/llm_review.py:252 sets rationale "LLM review is not enabled for this run."`
- **Fix:** Surface disabled LLM review state on every candidate row as "LLM review unavailable - rules-only".
- **Acceptance:** With AGENCY_ENABLE_LLM_REVIEW unset, every row shows "LLM review unavailable - rules-only" instead of a blank or missing LLM field.

### [F035] Approval does not show a clear state-change confirmation that execution preview...
- **Screen:** Approval flow
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Approval does not show a clear state-change confirmation that execution preview was updated.
- **Evidence:** `src/agency/templates/candidate_detail.html:302 renders the approve form and src/agency/templates/execution_preview.html:42 renders review metadata, but neither template renders a success banner such as "Approved - execution preview updated".`
- **Fix:** Add a POST-result success banner or toast on Candidate Detail and/or Execution Preview after approval records a state change.
- **Acceptance:** After approving a candidate, the next rendered page shows "Approved - execution preview updated" or equivalent confirmation.

### [F036] The approval-to-order path requires more than three user actions because execut...
- **Screen:** Approval flow
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** The approval-to-order path requires more than three user actions because execution still requires separate navigation, order intent approval, and submit.
- **Evidence:** `src/agency/templates/candidate_detail.html:310 renders "Approve Research" and src/agency/templates/execution_preview.html:59 renders "Approve order intent" before src/agency/templates/execution_preview.html:65 renders the submit button.`
- **Fix:** After research approval, route directly to the ready execution row and collapse order-intent approval into the final submit confirmation when safe.
- **Acceptance:** Starting from Candidate Detail, a user can approve and place the paper order in no more than three clicks.

### [F037] Paper-mode messaging is inconsistent because execution uses an unstyled banner...
- **Screen:** Cross-screen paper mode
- **Category:** Design System
- **Severity:** P1
- **Finding:** Paper-mode messaging is inconsistent because execution uses an unstyled banner while audit marks paper-only execution with the red block tag.
- **Evidence:** `src/agency/templates/execution_preview.html:72 '<div class="paper-mode-banner" role="alert" aria-live="polite">'; src/agency/templates/audit.html:200 '<span class="tag tag-block">Paper only</span>'`
- **Fix:** Create one amber/dashed paper-mode visual component and use it for every paper-only or Alpaca paper indicator instead of neutral or block tags.
- **Acceptance:** Every paper-mode indicator across execution, audit, portfolio, policy, and the base topbar uses the same amber/dashed treatment and no paper-only label uses 'tag-block'.

### [F038] The submit flow has a POST form but no inline post-submission confirmation stat...
- **Screen:** Execution Preview
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** The submit flow has a POST form but no inline post-submission confirmation state in the template.
- **Evidence:** `src/agency/templates/execution_preview.html:63 renders the submit_enabled form and src/agency/templates/execution_preview.html:65 renders the submit button without any adjacent success banner or submitted-order state.`
- **Fix:** Render an inline confirmation banner or row state after submission showing the ticker, paper order id, and timestamp.
- **Acceptance:** After a successful paper submit POST, the same Execution Preview page shows an inline confirmation for the submitted row.

### [F039] LLM/rules conflicts are not visually flagged with an amber indicator
- **Screen:** Risk dashboard and Execution Preview
- **Category:** Design System
- **Severity:** P1
- **Finding:** LLM/rules conflicts are not visually flagged with an amber indicator.
- **Evidence:** `src/agency/templates/execution_preview.html:20 renders row metrics for Order Value, Sizing, Approval, Risk, and Paper Promotion with no conflict badge or amber indicator.`
- **Fix:** Add a conflict flag field and render an amber badge/icon when deterministic rules and LLM recommendation disagree.
- **Acceptance:** A row with conflicting deterministic and LLM recommendations displays an amber conflict indicator.

### [F040] Long technical provenance strings such as cycle IDs, timestamps, hashes, and mo...
- **Screen:** Cross-screen provenance
- **Category:** Design System
- **Severity:** P1
- **Finding:** Long technical provenance strings such as cycle IDs, timestamps, hashes, and model names are visible by default and are not rendered in a monospace technical style.
- **Evidence:** `src/agency/templates/final_selection.html:26 '<span class="muted-line">Generated {{ row.generated_at_label }} / data as of {{ row.as_of_label }} / cycle {{ row.cycle_id }}</span>'; src/agency/templates/audit.html:104 '<td>{{ run.cycle_id }}</td>'; src/agency/templates/execution_preview.html:61 '<p class="microcopy">Intent hash {{ row.order_intent_hash_label }}; approval expires if the computed order changes.</p>'`
- **Fix:** Move raw cycle, timestamp, hash, and model values into collapsed details and render remaining technical identifiers with a shared monospace class.
- **Acceptance:** Cycle IDs, hashes, raw timestamps, and model names are hidden by default or shown in monospace inside an expanded details section.

### [F041] Agent-resolved risk checks are exposed as full criteria and next-step detail in...
- **Screen:** Risk dashboard
- **Category:** Semi-Auto
- **Severity:** P1
- **Finding:** Agent-resolved risk checks are exposed as full criteria and next-step detail instead of a simple Agent checked OK summary.
- **Evidence:** `src/agency/templates/risk.html:212 iterates row.checks and src/agency/templates/risk.html:217 renders "{{ check.meaning }} Criteria: {{ check.criteria }} Next: {{ check.next_step }}".`
- **Fix:** Collapse passing agent-resolved checks into an "Agent checked - OK" summary and reveal criteria only on explicit expansion.
- **Acceptance:** A fully passing risk check row initially displays "Agent checked - OK" and hides criteria text until expanded.

### [F042] Ready candidates do not have a direct per-row link to their Execution Preview row
- **Screen:** Risk dashboard
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** Ready candidates do not have a direct per-row link to their Execution Preview row.
- **Evidence:** `src/agency/templates/risk.html:87 links allow rows to "/candidates/{{ row.ticker }}" and src/agency/templates/risk.html:20 only provides a generic "/execution-preview" page link.`
- **Fix:** Add an Execution Preview row link or anchor action on each Ready to review candidate card.
- **Acceptance:** Each ready candidate card includes a link that lands on that ticker's execution preview row.

### [F043] The Risk dashboard does not group candidates into the required Ready to review,...
- **Screen:** Risk dashboard
- **Category:** Yellow Brick Road
- **Severity:** P1
- **Finding:** The Risk dashboard does not group candidates into the required Ready to review, Blocked by policy, and Needs data visual tiers.
- **Evidence:** `src/agency/templates/risk.html:76 shows section "Risk focus queues" with Orderable Risk Queue and WARN Review Queue, while src/agency/templates/risk.html:166 shows a separate "Blocked Archive" section.`
- **Fix:** Replace the current allow/warn/archive grouping with three candidate tiers named Ready to review, Blocked by policy, and Needs data, with distinct green, red, and amber/grey treatments.
- **Acceptance:** Rendering one WATCH approval-pending row, one policy-blocked row, and one data-blocked row shows all three required tiers in that order.

### [F044] Candidate rows do not show an inline LLM recommendation with one-line rationale
- **Screen:** Risk dashboard and Execution Preview
- **Category:** BLUF
- **Severity:** P1
- **Finding:** Candidate rows do not show an inline LLM recommendation with one-line rationale.
- **Evidence:** `src/agency/templates/risk.html:136 lists table headers Ticker, Decision, Action, Conviction, Projected Gross, Meaning, and User Action, while src/agency/templates/execution_preview.html:20 renders row metrics without any LLM recommendation field.`
- **Fix:** Add per-candidate LLM action and one-line rationale fields to both Risk dashboard rows and Execution Preview cards.
- **Acceptance:** Every rendered candidate row on both screens shows an LLM action and one-line rationale.

### [F045] Deterministic score and LLM recommendation are not displayed side by side
- **Screen:** Risk dashboard and Execution Preview
- **Category:** BLUF
- **Severity:** P1
- **Finding:** Deterministic score and LLM recommendation are not displayed side by side.
- **Evidence:** `src/agency/templates/risk.html:151 renders only "{{ row.conviction_pct }}%" and src/agency/templates/execution_preview.html:20 renders card metrics without deterministic-vs-LLM comparison.`
- **Fix:** Add a paired deterministic score and LLM recommendation display to each candidate row/card.
- **Acceptance:** Each row shows deterministic score and LLM recommendation in adjacent cells or adjacent card metrics.

### [F046] Expand/collapse controls use multiple component classes with different visual t...
- **Screen:** Cross-screen details
- **Category:** Design System
- **Severity:** P1
- **Finding:** Expand/collapse controls use multiple component classes with different visual treatments instead of one consistent details pattern.
- **Evidence:** `src/agency/static/styles.css:3321 '.data-load-details,'; src/agency/static/styles.css:3777 '.signal-inspector {'; src/agency/static/styles.css:4081 '.sector-inspector {'; src/agency/static/styles.css:4354 '.nested-audit {'`
- **Fix:** Consolidate details, data-load details, signal inspector, sector inspector, and nested audit styling into one shared disclosure component with consistent summary affordance.
- **Acceptance:** All collapsed sections use the same summary styling, chevron affordance, open spacing, and focus treatment.

### [F047] Full LLM rationale is visible by default in the prompt audit table instead of b...
- **Screen:** audit.html
- **Category:** Design System
- **Severity:** P1
- **Finding:** Full LLM rationale is visible by default in the prompt audit table instead of being collapsed behind a details control.
- **Evidence:** `src/agency/templates/audit.html:255 '<td>{{ prompt.llm_rationale }}</td>'`
- **Fix:** Show only a short prompt-audit summary in the table and move the full rationale, prompt metadata, and raw audit text into a collapsed details row.
- **Acceptance:** Opening Runtime Audit shows no full LLM rationale text until the user expands a prompt-audit details control.

### [F048] Status types rely on color-only dots and text tags instead of a consistent icon...
- **Screen:** base.html
- **Category:** Design System
- **Severity:** P1
- **Finding:** Status types rely on color-only dots and text tags instead of a consistent icon plus color vocabulary for pass, warning, blocked, pending, policy-locked, data, and agent states.
- **Evidence:** `src/agency/templates/base.html:84 '<span class="status-dot status-dot-warn" data-runtime-dot aria-hidden="true"></span>'; src/agency/static/styles.css:2376 '.status-dot {'`
- **Fix:** Add a shared icon slot or pseudo-element for each status type and apply it consistently to status dots, status pills, tags, and gate rows.
- **Acceptance:** Each required status type has one documented icon and the icon appears with the matching color wherever that status is rendered.


---

## P2 Findings

### [F049] The subscription evidence section uses a different label and ends its pipeline...
- **Screen:** Candidate Detail
- **Category:** Design System
- **Severity:** P2
- **Finding:** The subscription evidence section uses a different label and ends its pipeline with Scored instead of Score impact.
- **Evidence:** `src/agency/templates/candidate_detail.html:409 - <h2 id="email-evidence-heading">Supplementary Subscription Intelligence</h2>`
- **Fix:** Rename the section to Email/article evidence and rename the fourth pipeline step to Score impact while preserving the Matched, Opened, Summarized order.
- **Acceptance:** The section heading reads Email/article evidence and the pipeline labels are Matched, Opened, Summarized, and Score impact in that order.

### [F050] Review cards distinguish reviewable, blocked, and decided states with color and...
- **Screen:** Command dashboard
- **Category:** Design System
- **Severity:** P2
- **Finding:** Review cards distinguish reviewable, blocked, and decided states with color and text but no icon.
- **Evidence:** `src/agency/templates/dashboard.html:129 - <span class="tag tag-urgent">Ready to review</span>`
- **Fix:** Add a state icon to each Ready to review, Blocked by risk, and recorded-review branch while preserving the existing color classes.
- **Acceptance:** Each review card state has both a color-coded class and an icon that differs across ready, blocked, and decided states.

### [F051] Summary labels vary between rationale names, inspect verbs, show verbs, and ins...
- **Screen:** Cross-screen details
- **Category:** Design System
- **Severity:** P2
- **Finding:** Summary labels vary between rationale names, inspect verbs, show verbs, and instructional copy, so collapsed sections do not read as one system.
- **Evidence:** `src/agency/templates/final_selection.html:58 '<summary>Decision Rationale and Policy Gates</summary>'; src/agency/templates/dashboard.html:338 '<summary>Inspect operational detail</summary>'; src/agency/templates/market_regime.html:205 '<summary>How to use this</summary>'`
- **Fix:** Standardize disclosure labels to one pattern such as 'Show details: <section name>' and reserve specific section names for the text after the shared prefix.
- **Acceptance:** Every summary label begins with the same disclosure verb pattern across the assigned templates.

### [F052] The zero-position table empty state is generic and does not explain that positi...
- **Screen:** Portfolio Monitor
- **Category:** BLUF
- **Severity:** P2
- **Finding:** The zero-position table empty state is generic and does not explain that positions appear after approving or executing candidates.
- **Evidence:** `src/agency/templates/portfolio_monitor.html:220 - '<td class="empty-row" colspan="8">No portfolio positions are tracked yet</td>'`
- **Fix:** Replace the empty row copy with explicit cause-and-next-step text such as "No paper positions yet - approve a candidate and run execution to see positions here."
- **Acceptance:** With 'positions=[]', the Position Review empty row explains why no positions exist and mentions the candidate or execution prerequisite.

### [F053] LLM rationale is not shown as a one-line summary with expandable full reasoning
- **Screen:** Risk dashboard and Execution Preview
- **Category:** BLUF
- **Severity:** P2
- **Finding:** LLM rationale is not shown as a one-line summary with expandable full reasoning.
- **Evidence:** `src/agency/services/llm_review.py:332 normalizes an LLM rationale field, but src/agency/templates/execution_preview.html:20 renders row metrics without any LLM rationale details element.`
- **Fix:** Render a one-line LLM rationale per row and place full rationale, supporting factors, and concerns inside a collapsed details element.
- **Acceptance:** Each row shows a one-line LLM rationale and expands to show full LLM reasoning.

### [F054] There is no bulk action to submit all ready orders
- **Screen:** Execution Preview
- **Category:** Semi-Auto
- **Severity:** P2
- **Finding:** There is no bulk action to submit all ready orders.
- **Evidence:** `src/agency/templates/execution_preview.html:147 renders "Orderable Paper Orders" and src/agency/templates/execution_preview.html:155 renders orderable rows with no "Submit all ready orders" form or button.`
- **Fix:** Add a bulk "Submit all ready orders" action that appears only when more than one approved ready order is available.
- **Acceptance:** With two approved ready rows, the Execution Preview page shows one bulk submit action for all ready orders.

### [F055] Neither page shows a page-level LLM system status indicator before review
- **Screen:** Risk dashboard and Execution Preview
- **Category:** Semi-Auto
- **Severity:** P2
- **Finding:** Neither page shows a page-level LLM system status indicator before review.
- **Evidence:** `src/agency/templates/execution_preview.html:83 renders the Execution state section and src/agency/templates/risk.html:12 renders the Risk state section without any LLM status indicator.`
- **Fix:** Add a page-level LLM status tag to both pages showing enabled, disabled, or provider error state.
- **Acceptance:** Loading either page shows an LLM status indicator before the candidate list.

### [F056] The Risk dashboard has drill-down gate details but no candidate-by-dimension ri...
- **Screen:** Risk dashboard
- **Category:** BLUF
- **Severity:** P2
- **Finding:** The Risk dashboard has drill-down gate details but no candidate-by-dimension risk matrix.
- **Evidence:** `src/agency/templates/risk.html:195 renders section "Risk Gate Detail" and src/agency/templates/risk.html:204 renders one details panel per row instead of a matrix.`
- **Fix:** Add a collapsed drill-down matrix with candidates as rows and risk dimensions as columns while keeping the default page focused on the tiered action queues.
- **Acceptance:** A user can expand one drill-down and see a candidate-by-risk-dimension matrix without the matrix appearing by default.

### [F057] Placeholder or secondary screens named in the checklist are rendered as normal...
- **Screen:** base.html
- **Category:** Yellow Brick Road
- **Severity:** P2
- **Finding:** Placeholder or secondary screens named in the checklist are rendered as normal active nav items with the same hover and active affordances as core workflow screens.
- **Evidence:** `src/agency/templates/base.html:27 '<a class="nav-link {% if active_nav == 'market' %}active{% endif %}" href="/market-regime">'; src/agency/templates/base.html:31 '<a class="nav-link {% if active_nav == 'signals' %}active{% endif %}" href="/signals">'; src/agency/templates/base.html:61 '<a class="nav-link {% if active_nav == 'learning' %}active{% endif %}" href="/learning">'`
- **Fix:** Mark Universe, Signals, and Learning as secondary or disabled/planned when applicable using muted text, disabled hover behavior, and non-primary grouping.
- **Acceptance:** Placeholder or secondary nav items are visually muted compared with Candidates, Portfolio, and Execute.
