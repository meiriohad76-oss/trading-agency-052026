why not # Trading Agency v2 UX Specialist Brief

Date captured: 2026-05-09  
Local app used for screenshots: `http://127.0.0.1:8000/`  
Current product mode: paper trading, review-only

## Product Summary

Trading Agency v2 is a local paper-trading research and review console. It collects market, SEC, RSS, and subscription-email evidence, converts that evidence into signal lanes, builds candidate selection reports, applies risk gates, and presents watch candidates for human review. The current UX is functional and data-rich, but it needs refinement so users can understand decisions faster and trust what the agency is doing.

## User Goals

- Know whether the agency is operational and what needs attention.
- See which stocks are selected, rejected, or blocked, and why.
- Inspect each candidate in plain English before approving, deferring, or rejecting paper review.
- Understand whether email/article evidence was analyzed or only matched as a headline.
- Confirm that data sources, provider keys, risk gates, execution preview, audit, and policy controls are behaving safely.

## Current Information Architecture

The app uses a fixed left navigation with a work-surface on the right. Active pages are:

- Command
- Final selection
- Risk
- Execution preview
- Portfolio monitor
- Learning
- Audit
- Policy

Universe and Signals appear in navigation but are currently disabled. The main routes are implemented in `src/agency/dashboard.py`, `src/agency/audit_dashboard.py`, and API routes under `src/agency/api/`.

## Core Modules

| Module | Purpose | Current UX Role |
| --- | --- | --- |
| Data/provider readiness | Checks API keys, live config, source health, and data refresh state. | Command dashboard operational gate. |
| Data loading/progress | Shows active/completed data refresh status, progress, current dataset, and ETA. | Helps the user know whether data is still loading. |
| PIT data layer | Point-in-time parquet/manifests for prices, SEC facts, Form 4, 13F, RSS, subscription emails, and stock trades. | Mostly invisible; surfaced as source health and evidence freshness. |
| Subscription email agents | Ingest Gmail/local `.eml`, identify SA/Zacks/TradeVision evidence, open allowed links, summarize article thesis. | Candidate detail `Subscription Intelligence`. |
| Signal lanes | Converts raw evidence into actionable/context/suppressed signals: fundamentals, insider, institutional, abnormal volume, sector momentum, news, subscription thesis, market-flow lanes. | Candidate scoring and explanation. |
| Runtime cycle | Builds latest paper cycle: evidence packs, selection reports, risk decisions, execution previews, audit rows. | Drives Command, Candidate, Final selection, Risk, and Execution pages. |
| Selection | Produces final `WATCH` / `NO_TRADE` reports and conviction. | Final selection dashboard and candidate cards. |
| Risk | Blocks or warns candidates according to paper-trading safety rules. | Risk dashboard and review queue state. |
| Execution preview | Shows what would happen if execution were enabled. Current mode blocks order submission. | Execution preview dashboard. |
| Portfolio monitor | Placeholder/read-only view for future position monitoring. | Empty-state dashboard. |
| Learning | Shows whether enough reviewed outcomes exist for learning/tuning. | Empty/premature-state dashboard. |
| Audit | Shows agent runs, risk snapshots, execution states, and prompt audits. | Traceability and trust. |
| Policy | Read-only portfolio/risk policy display. | Safety and governance. |

## Dashboard Screens

### 1. Command Dashboard

Purpose: the operational landing page. It answers: "Can I trust the agency right now, what needs attention, and what candidates should I review?"

Current design:

- Hero status banner with headline.
- Action ribbon with shortcuts.
- Summary metrics grid.
- Operational checklist with pass/warn rows.
- Data Loading progress panel.
- Live Config, Provider Readiness, Live Readiness, Review Queue, Candidates, Data Sources, Contracts.

Screenshot:

![Command dashboard desktop](ux-review-assets/command-desktop.png)

Mobile:

![Command dashboard mobile](ux-review-assets/command-mobile.png)

UX opportunities:

- The page is long and dense; the hierarchy after the first three panels can feel like a status dump.
- The action ribbon labels are clear, but it could better guide the user's next single action.
- Provider/data/config/readiness panels have overlapping meanings.
- Candidate review cards need stronger visual distinction between "reviewable", "blocked", and "pending human decision".

### 2. Candidate Detail

Purpose: the main decision explanation page for one ticker. It answers: "Why is this stock here, what supports it, what could be wrong, what did the email/article agents learn, and what should I do?"

Current design:

- Decision brief with action and conviction.
- Metric strip for actionable/context/suppressed/email evidence.
- "Why This Stock Is Here" explanation cards.
- Signal support and caution panels.
- Subscription Intelligence panel.
- Human Review actions.
- Collapsed technical/audit details.

Screenshot:

![AAPL candidate detail desktop](ux-review-assets/candidate-aapl-desktop.png)

Mobile:

![AAPL candidate detail mobile](ux-review-assets/candidate-aapl-mobile.png)

UX opportunities:

- This page is much improved, but still mixes decision explanation, email pipeline audit, and technical details.
- Subscription Intelligence needs clearer separation between: matched email, opened article, article summary, and whether it affects the agency score.
- "Headline Only", "Limit Reached", and "Evidence Row" are accurate but may need friendlier language.
- Human review controls should probably remain sticky or repeat near the top after enough confidence is built.

### 3. Final Selection

Purpose: shows all selection reports and final deterministic/LLM actions.

Screenshot:

![Final selection dashboard](ux-review-assets/final-selection-desktop.png)

UX opportunities:

- Needs a stronger summary of "selected vs rejected vs blocked".
- Could group reports by action and risk state instead of one long table/list.

### 4. Risk

Purpose: explains risk decisions and gate details for current candidates.

Screenshot:

![Risk dashboard](ux-review-assets/risk-desktop.png)

UX opportunities:

- Good place for a visual risk matrix.
- Current risk states could be more legible if grouped into "can review", "blocked by policy", and "needs data".

### 5. Execution Preview

Purpose: shows whether any paper order preview is ready and why order submission is disabled/blocked.

Screenshot:

![Execution preview dashboard](ux-review-assets/execution-preview-desktop.png)

UX opportunities:

- This page should clearly say "No real orders can be sent" in paper mode.
- Future UX should separate order preview details from execution safety gates.

### 6. Portfolio Monitor

Purpose: future position monitoring page. Current state is an empty/read-only placeholder.

Screenshot:

![Portfolio monitor dashboard](ux-review-assets/portfolio-monitor-desktop.png)

UX opportunities:

- Empty state should explain what will appear here after paper positions exist.
- Future cards should prioritize position risk, thesis drift, stop/exit status, and review urgency.

### 7. Learning

Purpose: shows whether the agency has enough reviewed outcomes to learn or tune recommendations.

Screenshot:

![Learning dashboard](ux-review-assets/learning-desktop.png)

UX opportunities:

- Needs an explanatory model of what "learning" means and what it will never do automatically.
- Good candidate for a timeline/progress-to-sample-size visual.

### 8. Audit

Purpose: traceability page for agent runs, prompts, risk snapshots, and execution states.

Screenshot:

![Audit dashboard](ux-review-assets/audit-desktop.png)

UX opportunities:

- Strong trust feature, but dense.
- Should support filtering by ticker/cycle/status/event type.
- Could use expandable event detail rows instead of full visible payload density.

### 9. Policy

Purpose: read-only safety and portfolio policy reference.

Screenshot:

![Policy dashboard](ux-review-assets/policy-desktop.png)

UX opportunities:

- This page should be visually calmer and more reference-like.
- Important hard constraints should be scannable as "never", "requires confirmation", and "paper-only".

## Current Visual System

- Layout: fixed sidebar plus page content area.
- Tone: operational SaaS dashboard, compact and status-heavy.
- Components: hero banners, summary metric tiles, cards, tables, status pills, tags, progress bar, collapsible details.
- Status colors:
  - Green/pass: ready, healthy, confirmed, online.
  - Yellow/warn: attention, pending, review needed.
  - Red/block: blocked, rejected, policy stops.
  - Blue/neutral: informational, disabled, planned.
- Typography: clear but dense; many uppercase labels; high information density.
- Interaction style: mostly read-only navigation, with forms for human review actions.

## UX Problems To Explore

1. **Decision hierarchy:** Users need the top reason and next action before supporting data.
2. **Panel overlap:** Live Config, Provider Readiness, Live Readiness, Data Sources, and Operational Checklist may feel redundant.
3. **Email evidence semantics:** The difference between mailbox match, linked article analysis, normalized feed row, and subscription thesis lane still needs clearer language.
4. **Review queue affordance:** Approve/Defer/Reject are available, but the page should help the user understand when a candidate is actually reviewable vs blocked.
5. **Dense technical vocabulary:** Terms like `source_count`, `freshness`, `timestamp_as_of`, `selection_report`, and `risk_decision` may need product-language labels.
6. **Progressive disclosure:** Technical details are partly collapsed, but dashboards still show many operational internals before user meaning.
7. **Mobile:** Core pages render, but long cards and dense tables need mobile-first hierarchy and fewer columns.

## Suggested UX Deliverables

- Revised information architecture and navigation labels.
- Candidate decision page wireframe focused on "why / confidence / risks / evidence / action".
- Command dashboard wireframe with one primary next action.
- Subscription Intelligence component redesign.
- Status taxonomy and copywriting guide.
- Responsive table/card patterns for mobile.
- Empty-state designs for Portfolio Monitor and Learning.
- Audit filtering and event detail pattern.

## Implementation References

- Templates: `src/agency/templates/`
- Styling: `src/agency/static/styles.css`
- Dashboard view models: `src/agency/dashboard.py`
- Audit dashboard: `src/agency/audit_dashboard.py`
- Runtime/evidence services: `src/agency/services.py`
- Email-agent documentation: `docs/subscription-email-agents.md`
- First-version testing notes: `docs/testing-first-version.md`
