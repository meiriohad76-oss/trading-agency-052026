# Section 2 Audit Findings - Candidates Flow
Agent: A | Date: 2026-05-18 | Status: COMPLETE
Screens: Command dashboard | Final Selection | Candidate Detail

AUDIT_FINDING
screen: Command dashboard
category: Yellow Brick Road
severity: P1
finding: The hero primary CTA reviews only the top ticker instead of the full pending candidate queue.
evidence: src/agency/templates/dashboard.html:29 - <a class="primary-action" href="{{ review_queue[0].candidate_href }}">Review {{ review_queue[0].ticker }}</a>
fix: Change the hero primary CTA to Review {{ review_progress.pending_count }} candidates and link it to #review-queue-heading while keeping per-ticker review links inside candidate cards.
acceptance: With three pending candidates, the first primary action reads Review 3 candidates and jumps to the Review Queue.
END_FINDING

AUDIT_FINDING
screen: Command dashboard
category: BLUF
severity: P1
finding: Data Sources remains an always-visible readiness panel instead of being collapsed with the other readiness diagnostics.
evidence: src/agency/templates/dashboard.html:1428 - <section class="panel" aria-labelledby="source-heading">
fix: Move Data Sources into the collapsed operational details group or wrap it in a collapsed <details> section by default.
acceptance: Loading the Command dashboard shows no Data Sources table until the user expands readiness details.
END_FINDING

AUDIT_FINDING
screen: Command dashboard
category: Design System
severity: P2
finding: Review cards distinguish reviewable, blocked, and decided states with color and text but no icon.
evidence: src/agency/templates/dashboard.html:129 - <span class="tag tag-urgent">Ready to review</span>
fix: Add a state icon to each Ready to review, Blocked by risk, and recorded-review branch while preserving the existing color classes.
acceptance: Each review card state has both a color-coded class and an icon that differs across ready, blocked, and decided states.
END_FINDING

AUDIT_FINDING
screen: Command dashboard
category: Yellow Brick Road
severity: P1
finding: Candidate cards offer Candidate, Risk, and Selection links but no contextual Portfolio or Execute next-step link.
evidence: src/agency/templates/dashboard.html:187 - <a class="text-link" href="{{ item.candidate_href }}">Candidate</a>
fix: Add a clearly labeled Portfolio or Execute next-step link in the queue area after review actions are shown.
acceptance: A review card or queue-level action contains a visible link to /portfolio-monitor or /execution-preview.
END_FINDING

AUDIT_FINDING
screen: Command dashboard
category: BLUF
severity: P1
finding: The dashboard template has no explicit LLM-disabled banner in the primary content path.
evidence: src/agency/templates/dashboard.html:12 - <section class="next-action {{ summary.hero_class }}" aria-label="Recommended next action">
fix: Render a visible warning or neutral banner in the hero or queue area when LLM review is disabled or unavailable.
acceptance: With LLM disabled, the Command dashboard displays an above-the-fold indicator that says LLM review is disabled or unavailable.
END_FINDING

AUDIT_FINDING
screen: Final Selection
category: BLUF
severity: P1
finding: The top KPI row does not provide the required Selected, Blocked, and No-Trade three-number summary.
evidence: src/agency/templates/final_selection.html:130 - <section class="kpi-grid kpi-grid-compact" aria-label="Final selection metrics">
fix: Replace the Reports, Actionable, Blocked, and History Hidden KPI set with Selected, Blocked, and No-Trade counts.
acceptance: The first metric row on Final Selection contains exactly Selected, Blocked, and No-Trade counts.
END_FINDING

AUDIT_FINDING
screen: Final Selection
category: Yellow Brick Road
severity: P1
finding: Candidates are grouped into Actionable Review Queue and Rejected/Blocked Traceability instead of WATCH, NO_TRADE, and BLOCKED action sections.
evidence: src/agency/templates/final_selection.html:155 - <section class="panel" aria-labelledby="final-heading">
fix: Render explicit WATCH, NO_TRADE, and BLOCKED sections in that order with section-level colors matching the action meaning.
acceptance: Final Selection displays WATCH first, NO_TRADE second, and BLOCKED last regardless of conviction ordering.
END_FINDING

AUDIT_FINDING
screen: Final Selection
category: BLUF
severity: P1
finding: Candidate rows expose deterministic, LLM, evidence, risk, human review, timestamps, and multiple badges by default instead of only ticker, conviction, and top reason.
evidence: src/agency/templates/final_selection.html:35 - <div class="selection-facts">
fix: Collapse secondary facts into details and keep the default row surface to ticker, conviction score, and one top reason.
acceptance: A default candidate row shows no deterministic, LLM, evidence, risk, timestamp, or human-review fields until expanded.
END_FINDING

AUDIT_FINDING
screen: Final Selection
category: Design System
severity: P1
finding: The action badge is always neutral, so WATCH, BLOCKED, and NO_TRADE are not color-encoded by action.
evidence: src/agency/templates/final_selection.html:16 - <span class="tag tag-neutral">{{ row.action }}</span>
fix: Map row.action to action-specific tag classes such as pass for WATCH, neutral for NO_TRADE, and block for BLOCKED.
acceptance: WATCH, NO_TRADE, and BLOCKED badges render with distinct action-specific colors.
END_FINDING

AUDIT_FINDING
screen: Candidate Detail
category: BLUF
severity: P1
finding: The largest first-row element is the ticker, while the recommendation chip and conviction score are secondary.
evidence: src/agency/templates/candidate_detail.html:39 - <h2>{{ ticker }}</h2>
fix: Make the recommendation and conviction score the dominant first content in the decision brief and demote the ticker to supporting context.
acceptance: The first decision brief row visually prioritizes WATCH or NO_TRADE and the conviction percent over the ticker symbol.
END_FINDING

AUDIT_FINDING
screen: Candidate Detail
category: BLUF
severity: P1
finding: Supporting signal evidence is expanded by default instead of being collapsed behind a Supporting detail section.
evidence: src/agency/templates/candidate_detail.html:157 - <section class="panel signal-evidence-panel" aria-labelledby="signal-evidence-heading">
fix: Keep Why This Stock Is Here as the always-visible summary and move Primary Signal Evidence into a collapsed <details> section labeled Supporting detail.
acceptance: Opening a candidate page shows no Active Signals, Advisory Signals, or Blocked Signals lists until Supporting detail is expanded.
END_FINDING

AUDIT_FINDING
screen: Candidate Detail
category: Design System
severity: P2
finding: The subscription evidence section uses a different label and ends its pipeline with Scored instead of Score impact.
evidence: src/agency/templates/candidate_detail.html:409 - <h2 id="email-evidence-heading">Supplementary Subscription Intelligence</h2>
fix: Rename the section to Email/article evidence and rename the fourth pipeline step to Score impact while preserving the Matched, Opened, Summarized order.
acceptance: The section heading reads Email/article evidence and the pipeline labels are Matched, Opened, Summarized, and Score impact in that order.
END_FINDING

AUDIT_FINDING
screen: Candidate Detail
category: BLUF
severity: P1
finding: Raw provenance-derived values are visible outside collapsed details.
evidence: src/agency/templates/candidate_detail.html:61 - <span class="metric-label">Sources</span>
fix: Move timestamp_as_of, source_count, verification_level, run_id, and input_snapshot_id into a collapsed technical provenance details section.
acceptance: Those five provenance fields are not visible on initial page load and appear only after expanding technical provenance.
END_FINDING

AUDIT_FINDING
screen: Candidate Detail
category: Yellow Brick Road
severity: P1
finding: The candidate detail template has review jump links but no Back to candidates or Next candidate navigation.
evidence: src/agency/templates/candidate_detail.html:31 - <a class="text-link" href="#paper-review-heading">Jump to review</a>
fix: Add a Back to candidates link to /final-selection or a Next candidate navigation control near the top review actions.
acceptance: The top of Candidate Detail includes a visible Back to candidates link or Next candidate control.
END_FINDING
