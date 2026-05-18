# Section 5 Audit Findings - Design System
Agent: D | Date: 2026-05-18 | Status: COMPLETE
Scope: Assigned Section 5 templates, base.html, _data_health.html, signals.html, and styles.css

AUDIT_FINDING
screen: final_selection.html
category: BLUF
severity: P0
finding: Actionable candidate cards hide the decision rationale, policy gates, and plain reason rows behind a collapsed details control.
evidence: src/agency/templates/final_selection.html:57 `<details class="details-panel compact-details">`; src/agency/templates/final_selection.html:93 `<div class="reason-code-list" aria-label="Plain reason list">`
fix: Move the policy gate summary and top three plain reason rows into the always-visible selection card, leaving only raw audit or long rationale text collapsed.
acceptance: Each actionable selection card shows recommendation, conviction, gate status, and three plain reasons before any details element is opened.
END_FINDING

AUDIT_FINDING
screen: portfolio_monitor.html
category: Design System
severity: P1
finding: Portfolio P/L values render as plain table text without green/red P/L semantics or stronger numeric emphasis.
evidence: src/agency/templates/portfolio_monitor.html:214 `<td>{% if position.unrealized_pl is not none %}${{ "%.2f"|format(position.unrealized_pl) }} / {{ "%.2f"|format(position.unrealized_plpc * 100) }}%{% else %}None{% endif %}</td>`
fix: Add a positive/negative/flat P/L class from the view model and style the P/L cell with green for gains, red for losses, neutral for flat, and a stronger numeric type treatment.
acceptance: A positive unrealized P/L cell is green and bold, a negative unrealized P/L cell is red and bold, and both are visually stronger than their table label.
END_FINDING

AUDIT_FINDING
screen: Cross-screen paper mode
category: Design System
severity: P1
finding: Paper-mode messaging is inconsistent because execution uses an unstyled banner while audit marks paper-only execution with the red block tag.
evidence: src/agency/templates/execution_preview.html:72 `<div class="paper-mode-banner" role="alert" aria-live="polite">`; src/agency/templates/audit.html:200 `<span class="tag tag-block">Paper only</span>`
fix: Create one amber/dashed paper-mode visual component and use it for every paper-only or Alpaca paper indicator instead of neutral or block tags.
acceptance: Every paper-mode indicator across execution, audit, portfolio, policy, and the base topbar uses the same amber/dashed treatment and no paper-only label uses `tag-block`.
END_FINDING

AUDIT_FINDING
screen: dashboard.html
category: Design System
severity: P1
finding: The ready-to-review state uses an undefined `tag-urgent` class, so a manual action-required state can fall back to the neutral tag treatment.
evidence: src/agency/templates/dashboard.html:129 `<span class="tag tag-urgent">Ready to review</span>`
fix: Replace `tag-urgent` with the existing warning/attention token or add a defined `.tag-urgent` style that maps to the amber attention system.
acceptance: Ready-to-review candidates render with the same amber attention color as other user-review-required states.
END_FINDING

AUDIT_FINDING
screen: candidate_detail.html
category: Design System
severity: P1
finding: Blocked signals are counted with the blue neutral tag instead of the red blocked/rejected color.
evidence: src/agency/templates/candidate_detail.html:249 `<strong title="Signals blocked by freshness or data-quality gates. They are tracked but have no effect on the decision.">Blocked Signals</strong>`; src/agency/templates/candidate_detail.html:250 `<span class="tag tag-neutral">{{ latest_report.suppressed_signals | length }}</span>`
fix: Render the blocked/suppressed signal count with `tag-block` while keeping advisory/context signals on `tag-warn` and active signals on `tag-pass`.
acceptance: The Blocked Signals count appears red on candidate detail whenever suppressed signals are shown.
END_FINDING

AUDIT_FINDING
screen: base.html
category: Design System
severity: P1
finding: Status types rely on color-only dots and text tags instead of a consistent icon plus color vocabulary for pass, warning, blocked, pending, policy-locked, data, and agent states.
evidence: src/agency/templates/base.html:84 `<span class="status-dot status-dot-warn" data-runtime-dot aria-hidden="true"></span>`; src/agency/static/styles.css:2376 `.status-dot {`
fix: Add a shared icon slot or pseudo-element for each status type and apply it consistently to status dots, status pills, tags, and gate rows.
acceptance: Each required status type has one documented icon and the icon appears with the matching color wherever that status is rendered.
END_FINDING

AUDIT_FINDING
screen: dashboard.html and candidate_detail.html
category: Semi-Auto
severity: P1
finding: Approve, Defer, and Reject controls are text-only and Approve and Defer share the same neutral button style.
evidence: src/agency/templates/dashboard.html:174 `<button class="mini-button" type="submit">Approve</button>`; src/agency/templates/dashboard.html:177 `<button class="mini-button" type="submit">Defer</button>`; src/agency/templates/dashboard.html:180 `<button class="mini-button danger-button" type="submit">Reject</button>`
fix: Give Approve, Defer, and Reject distinct icon-plus-color treatments that map to pass, warn, and block/reject semantics.
acceptance: The three review actions are distinguishable by both icon and color before reading their labels.
END_FINDING

AUDIT_FINDING
screen: Cross-screen agent actions
category: Semi-Auto
severity: P1
finding: Agent-produced outputs and user-required actions share the same tag and button vocabulary without a robot/agent marker or user-action marker.
evidence: src/agency/templates/dashboard.html:418 `<article class="command-status-card command-status-{{ agents_card.status_class }}" data-command-card="agents">`; src/agency/templates/dashboard.html:174 `<button class="mini-button" type="submit">Approve</button>`
fix: Add a consistent visual marker for automated agent outputs and a separate marker for user-required approvals or acknowledgements.
acceptance: A user can identify agent-generated status versus human-required action from icon/color treatment alone on dashboard, final selection, risk, and execution screens.
END_FINDING

AUDIT_FINDING
screen: audit.html
category: Design System
severity: P1
finding: Full LLM rationale is visible by default in the prompt audit table instead of being collapsed behind a details control.
evidence: src/agency/templates/audit.html:255 `<td>{{ prompt.llm_rationale }}</td>`
fix: Show only a short prompt-audit summary in the table and move the full rationale, prompt metadata, and raw audit text into a collapsed details row.
acceptance: Opening Runtime Audit shows no full LLM rationale text until the user expands a prompt-audit details control.
END_FINDING

AUDIT_FINDING
screen: Cross-screen provenance
category: Design System
severity: P1
finding: Long technical provenance strings such as cycle IDs, timestamps, hashes, and model names are visible by default and are not rendered in a monospace technical style.
evidence: src/agency/templates/final_selection.html:26 `<span class="muted-line">Generated {{ row.generated_at_label }} / data as of {{ row.as_of_label }} / cycle {{ row.cycle_id }}</span>`; src/agency/templates/audit.html:104 `<td>{{ run.cycle_id }}</td>`; src/agency/templates/execution_preview.html:61 `<p class="microcopy">Intent hash {{ row.order_intent_hash_label }}; approval expires if the computed order changes.</p>`
fix: Move raw cycle, timestamp, hash, and model values into collapsed details and render remaining technical identifiers with a shared monospace class.
acceptance: Cycle IDs, hashes, raw timestamps, and model names are hidden by default or shown in monospace inside an expanded details section.
END_FINDING

AUDIT_FINDING
screen: Cross-screen details
category: Design System
severity: P1
finding: Expand/collapse controls use multiple component classes with different visual treatments instead of one consistent details pattern.
evidence: src/agency/static/styles.css:3321 `.data-load-details,`; src/agency/static/styles.css:3777 `.signal-inspector {`; src/agency/static/styles.css:4081 `.sector-inspector {`; src/agency/static/styles.css:4354 `.nested-audit {`
fix: Consolidate details, data-load details, signal inspector, sector inspector, and nested audit styling into one shared disclosure component with consistent summary affordance.
acceptance: All collapsed sections use the same summary styling, chevron affordance, open spacing, and focus treatment.
END_FINDING

AUDIT_FINDING
screen: base.html
category: Yellow Brick Road
severity: P1
finding: The left nav does not represent the core Candidates to Portfolio to Execute sequence as a grouped path or progress indicator.
evidence: src/agency/templates/base.html:36 `<span class="nav-section">Decide</span>`; src/agency/templates/base.html:50 `<span class="nav-section">Execute</span>`; src/agency/templates/base.html:51 `<a class="nav-link {% if active_nav == 'execution' %}active{% endif %}" href="/execution-preview">`; src/agency/templates/base.html:55 `<a class="nav-link {% if active_nav == 'portfolio' %}active{% endif %}" href="/portfolio-monitor">`
fix: Add a dedicated yellow-brick-road nav group or progress strip that orders Candidates, Portfolio, and Execute as the primary workflow.
acceptance: The nav visually presents Candidates, Portfolio, and Execute as one ordered workflow distinct from secondary screens.
END_FINDING

AUDIT_FINDING
screen: candidate_detail.html
category: Yellow Brick Road
severity: P1
finding: Candidate detail lacks a breadcrumb or back-link to the parent candidate list.
evidence: src/agency/templates/candidate_detail.html:31 `<a class="text-link" href="#paper-review-heading">Jump to review</a>`
fix: Add a consistent breadcrumb or back-link near the top of the detail page that returns to Final Selection or the candidate queue.
acceptance: The candidate detail first viewport contains a visible link back to the parent candidate list.
END_FINDING

AUDIT_FINDING
screen: Cross-screen details
category: Design System
severity: P2
finding: Summary labels vary between rationale names, inspect verbs, show verbs, and instructional copy, so collapsed sections do not read as one system.
evidence: src/agency/templates/final_selection.html:58 `<summary>Decision Rationale and Policy Gates</summary>`; src/agency/templates/dashboard.html:338 `<summary>Inspect operational detail</summary>`; src/agency/templates/market_regime.html:205 `<summary>How to use this</summary>`
fix: Standardize disclosure labels to one pattern such as `Show details: <section name>` and reserve specific section names for the text after the shared prefix.
acceptance: Every summary label begins with the same disclosure verb pattern across the assigned templates.
END_FINDING

AUDIT_FINDING
screen: base.html
category: Yellow Brick Road
severity: P2
finding: Placeholder or secondary screens named in the checklist are rendered as normal active nav items with the same hover and active affordances as core workflow screens.
evidence: src/agency/templates/base.html:27 `<a class="nav-link {% if active_nav == 'market' %}active{% endif %}" href="/market-regime">`; src/agency/templates/base.html:31 `<a class="nav-link {% if active_nav == 'signals' %}active{% endif %}" href="/signals">`; src/agency/templates/base.html:61 `<a class="nav-link {% if active_nav == 'learning' %}active{% endif %}" href="/learning">`
fix: Mark Universe, Signals, and Learning as secondary or disabled/planned when applicable using muted text, disabled hover behavior, and non-primary grouping.
acceptance: Placeholder or secondary nav items are visually muted compared with Candidates, Portfolio, and Execute.
END_FINDING
