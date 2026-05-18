# Section 4 Audit Findings - Confirm Orders
Agent: C | Date: 2026-05-18 | Status: COMPLETE
Screens: Risk dashboard - Execution Preview - LLM recommendation
AUDIT_FINDING
screen: Risk dashboard
category: Yellow Brick Road
severity: P1
finding: The Risk dashboard does not group candidates into the required Ready to review, Blocked by policy, and Needs data visual tiers.
evidence: src/agency/templates/risk.html:76 shows section "Risk focus queues" with Orderable Risk Queue and WARN Review Queue, while src/agency/templates/risk.html:166 shows a separate "Blocked Archive" section.
fix: Replace the current allow/warn/archive grouping with three candidate tiers named Ready to review, Blocked by policy, and Needs data, with distinct green, red, and amber/grey treatments.
acceptance: Rendering one WATCH approval-pending row, one policy-blocked row, and one data-blocked row shows all three required tiers in that order.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard
category: BLUF
severity: P2
finding: The Risk dashboard has drill-down gate details but no candidate-by-dimension risk matrix.
evidence: src/agency/templates/risk.html:195 renders section "Risk Gate Detail" and src/agency/templates/risk.html:204 renders one details panel per row instead of a matrix.
fix: Add a collapsed drill-down matrix with candidates as rows and risk dimensions as columns while keeping the default page focused on the tiered action queues.
acceptance: A user can expand one drill-down and see a candidate-by-risk-dimension matrix without the matrix appearing by default.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard
category: Yellow Brick Road
severity: P1
finding: Ready candidates do not have a direct per-row link to their Execution Preview row.
evidence: src/agency/templates/risk.html:87 links allow rows to "/candidates/{{ row.ticker }}" and src/agency/templates/risk.html:20 only provides a generic "/execution-preview" page link.
fix: Add an Execution Preview row link or anchor action on each Ready to review candidate card.
acceptance: Each ready candidate card includes a link that lands on that ticker's execution preview row.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard
category: Semi-Auto
severity: P1
finding: Agent-resolved risk checks are exposed as full criteria and next-step detail instead of a simple Agent checked OK summary.
evidence: src/agency/templates/risk.html:212 iterates row.checks and src/agency/templates/risk.html:217 renders "{{ check.meaning }} Criteria: {{ check.criteria }} Next: {{ check.next_step }}".
fix: Collapse passing agent-resolved checks into an "Agent checked - OK" summary and reveal criteria only on explicit expansion.
acceptance: A fully passing risk check row initially displays "Agent checked - OK" and hides criteria text until expanded.
END_FINDING
AUDIT_FINDING
screen: Execution Preview
category: Semi-Auto
severity: P2
finding: There is no bulk action to submit all ready orders.
evidence: src/agency/templates/execution_preview.html:147 renders "Orderable Paper Orders" and src/agency/templates/execution_preview.html:155 renders orderable rows with no "Submit all ready orders" form or button.
fix: Add a bulk "Submit all ready orders" action that appears only when more than one approved ready order is available.
acceptance: With two approved ready rows, the Execution Preview page shows one bulk submit action for all ready orders.
END_FINDING
AUDIT_FINDING
screen: Execution Preview
category: Semi-Auto
severity: P1
finding: The submit flow has a POST form but no inline post-submission confirmation state in the template.
evidence: src/agency/templates/execution_preview.html:63 renders the submit_enabled form and src/agency/templates/execution_preview.html:65 renders the submit button without any adjacent success banner or submitted-order state.
fix: Render an inline confirmation banner or row state after submission showing the ticker, paper order id, and timestamp.
acceptance: After a successful paper submit POST, the same Execution Preview page shows an inline confirmation for the submitted row.
END_FINDING
AUDIT_FINDING
screen: Approval flow
category: Semi-Auto
severity: P0
finding: Risk logic has no WATCH-to-ALLOW promotion path on human approval.
evidence: src/agency/services/risk.py:409 returns review actions through _review_only_caution_check and src/agency/services/risk.py:419 returns "WATCH is review-only" as WARN.
fix: Add a promotion function or equivalent risk decision path that turns an approved WATCH candidate into ALLOW when paper-trade promotion requirements are satisfied.
acceptance: A unit test with a human-approved WATCH report produces a risk decision with decision "ALLOW".
END_FINDING
AUDIT_FINDING
screen: Approval flow
category: Semi-Auto
severity: P0
finding: Execution Preview submit_enabled does not check a human approval or promotion record.
evidence: src/agency/services/execution_preview.py:120 sets submit_enabled from policy, READY state, side, size, broker account, and order conflict only.
fix: Include the human approval or WATCH-to-ALLOW promotion record in the submit_enabled calculation.
acceptance: A READY preview without the required approval record has submit_enabled False, and the same preview with the approval record has submit_enabled True.
END_FINDING
AUDIT_FINDING
screen: Approval flow
category: Yellow Brick Road
severity: P1
finding: Approval does not show a clear state-change confirmation that execution preview was updated.
evidence: src/agency/templates/candidate_detail.html:302 renders the approve form and src/agency/templates/execution_preview.html:42 renders review metadata, but neither template renders a success banner such as "Approved - execution preview updated".
fix: Add a POST-result success banner or toast on Candidate Detail and/or Execution Preview after approval records a state change.
acceptance: After approving a candidate, the next rendered page shows "Approved - execution preview updated" or equivalent confirmation.
END_FINDING
AUDIT_FINDING
screen: Approval flow
category: Yellow Brick Road
severity: P1
finding: The approval-to-order path requires more than three user actions because execution still requires separate navigation, order intent approval, and submit.
evidence: src/agency/templates/candidate_detail.html:310 renders "Approve Research" and src/agency/templates/execution_preview.html:59 renders "Approve order intent" before src/agency/templates/execution_preview.html:65 renders the submit button.
fix: After research approval, route directly to the ready execution row and collapse order-intent approval into the final submit confirmation when safe.
acceptance: Starting from Candidate Detail, a user can approve and place the paper order in no more than three clicks.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard and Execution Preview
category: BLUF
severity: P1
finding: Candidate rows do not show an inline LLM recommendation with one-line rationale.
evidence: src/agency/templates/risk.html:136 lists table headers Ticker, Decision, Action, Conviction, Projected Gross, Meaning, and User Action, while src/agency/templates/execution_preview.html:20 renders row metrics without any LLM recommendation field.
fix: Add per-candidate LLM action and one-line rationale fields to both Risk dashboard rows and Execution Preview cards.
acceptance: Every rendered candidate row on both screens shows an LLM action and one-line rationale.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard and Execution Preview
category: BLUF
severity: P1
finding: Deterministic score and LLM recommendation are not displayed side by side.
evidence: src/agency/templates/risk.html:151 renders only "{{ row.conviction_pct }}%" and src/agency/templates/execution_preview.html:20 renders card metrics without deterministic-vs-LLM comparison.
fix: Add a paired deterministic score and LLM recommendation display to each candidate row/card.
acceptance: Each row shows deterministic score and LLM recommendation in adjacent cells or adjacent card metrics.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard and Execution Preview
category: Design System
severity: P1
finding: LLM/rules conflicts are not visually flagged with an amber indicator.
evidence: src/agency/templates/execution_preview.html:20 renders row metrics for Order Value, Sizing, Approval, Risk, and Paper Promotion with no conflict badge or amber indicator.
fix: Add a conflict flag field and render an amber badge/icon when deterministic rules and LLM recommendation disagree.
acceptance: A row with conflicting deterministic and LLM recommendations displays an amber conflict indicator.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard and Execution Preview
category: Semi-Auto
severity: P1
finding: The per-row LLM disabled state is not rendered even though the service returns a disabled stub.
evidence: src/agency/services/llm_review.py:130 returns build_llm_review_stub when LLM review is disabled and src/agency/services/llm_review.py:252 sets rationale "LLM review is not enabled for this run."
fix: Surface disabled LLM review state on every candidate row as "LLM review unavailable - rules-only".
acceptance: With AGENCY_ENABLE_LLM_REVIEW unset, every row shows "LLM review unavailable - rules-only" instead of a blank or missing LLM field.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard and Execution Preview
category: BLUF
severity: P2
finding: LLM rationale is not shown as a one-line summary with expandable full reasoning.
evidence: src/agency/services/llm_review.py:332 normalizes an LLM rationale field, but src/agency/templates/execution_preview.html:20 renders row metrics without any LLM rationale details element.
fix: Render a one-line LLM rationale per row and place full rationale, supporting factors, and concerns inside a collapsed details element.
acceptance: Each row shows a one-line LLM rationale and expands to show full LLM reasoning.
END_FINDING
AUDIT_FINDING
screen: Risk dashboard and Execution Preview
category: Semi-Auto
severity: P2
finding: Neither page shows a page-level LLM system status indicator before review.
evidence: src/agency/templates/execution_preview.html:83 renders the Execution state section and src/agency/templates/risk.html:12 renders the Risk state section without any LLM status indicator.
fix: Add a page-level LLM status tag to both pages showing enabled, disabled, or provider error state.
acceptance: Loading either page shows an LLM status indicator before the candidate list.
END_FINDING
