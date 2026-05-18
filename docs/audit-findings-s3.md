# Section 3 Audit Findings - Portfolio
Agent: B | Date: 2026-05-18 | Status: COMPLETE
Screens: Portfolio Monitor | cross-screen context
AUDIT_FINDING
screen: Portfolio Monitor
category: BLUF
severity: P2
finding: The zero-position table empty state is generic and does not explain that positions appear after approving or executing candidates.
evidence: src/agency/templates/portfolio_monitor.html:220 - `<td class="empty-row" colspan="8">No portfolio positions are tracked yet</td>`
fix: Replace the empty row copy with explicit cause-and-next-step text such as "No paper positions yet - approve a candidate and run execution to see positions here."
acceptance: With `positions=[]`, the Position Review empty row explains why no positions exist and mentions the candidate or execution prerequisite.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Yellow Brick Road
severity: P1
finding: The empty portfolio state does not include a direct Candidates CTA, so the user is stranded after learning there is nothing to monitor.
evidence: src/agency/templates/portfolio_monitor.html:58 - `<section class="panel empty-state-panel" aria-label="No portfolio data">` contains only explanatory copy before the `{% endif %}` at line 68.
fix: Add a visible link or button in the empty-state panel to the canonical Candidates screen with text like "Go to Candidates".
acceptance: With no portfolio data, the empty-state panel renders one visible CTA whose `href` opens the candidate review list.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: BLUF
severity: P1
finding: The top portfolio summary does not present total exposure, cash available, and max allowed as a single dominant three-number exposure summary.
evidence: src/agency/templates/portfolio_monitor.html:21 - `<section class="kpi-grid kpi-grid-compact" aria-label="Portfolio monitor metrics">` renders portfolio metrics, while cash appears later at line 114 and no max-allowed value is rendered.
fix: Add a top exposure summary panel with total exposure percent, cash available, and max allowed pulled from policy and account data.
acceptance: Opening Portfolio Monitor shows those three numbers together above rules, broker, snapshot, and position sections.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Design System
severity: P1
finding: Positions render as a dense table instead of cards with entry price, color-coded P/L, thesis validity, and stop distance.
evidence: src/agency/templates/portfolio_monitor.html:180 - `<table>` under Position Review is the default position display, and src/agency/templates/portfolio_monitor.html:214 - `<td>{% if position.unrealized_pl is not none %}${{ "%.2f"|format(position.unrealized_pl) }} / {{ "%.2f"|format(position.unrealized_plpc * 100) }}%{% else %}None{% endif %}</td>` renders P/L without a profit/loss color class.
fix: Replace or supplement the table with position cards that show ticker, entry price, green/red current P/L, thesis-validity indicator, and stop distance.
acceptance: For one sample position, the monitor renders a card containing all five required fields and P/L styling changes with positive versus negative values.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Semi-Auto
severity: P1
finding: The monitor only flags a trailing stop after it is breached, not when it is within 5% of triggering.
evidence: src/agency/services/portfolio_monitor.py:248 - `and (high_water_mark - pnl_pct) >= policy.trailing_stop_pct`
fix: Add a proximity calculation for positions within 5 percentage points of the trailing-stop threshold and expose a warning flag to the template.
acceptance: A position whose drawdown is within 5 percentage points of the trailing-stop threshold renders a red or amber trailing-stop proximity alert.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: BLUF
severity: P1
finding: The screen lacks a single policy compliance indicator that tells the user whether the portfolio is within limits or over exposure.
evidence: src/agency/templates/portfolio_monitor.html:43 - `<article class="kpi kpi-urgent">` displays Exposure, but no "Within limits" or "Over exposure" status is rendered in the metrics section.
fix: Add one policy compliance status component driven by gross exposure versus max allowed exposure.
acceptance: When gross exposure is below the limit the monitor shows "Within limits", and when above the limit it shows "Over exposure".
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Semi-Auto
severity: P0
finding: The core agent-generated Exit Recommendations panel is missing.
evidence: src/agency/templates/portfolio_monitor.html:176 - `<h2 id="positions-heading">Position Review</h2>` is the only exit-related section title, with no "Exit Recommendations" panel in the template.
fix: Add a dedicated "Exit Recommendations" panel generated from close candidates or exit-rule output.
acceptance: The portfolio page renders a named "Exit Recommendations" section whenever exit recommendation data is available.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Semi-Auto
severity: P0
finding: The exit review rows do not show recommendation urgency or exposure freed, so they are not actionable semi-auto recommendations.
evidence: src/agency/templates/portfolio_monitor.html:183 - `<th>Ticker</th>` starts a table whose headers are Ticker, State, Exit Signal, Current Thesis, Position, Unrealized P/L, Rule Trigger, and What To Do.
fix: Model and render per-recommendation ticker, plain-English reason, exposure freed, and urgency values.
acceptance: Each exit recommendation row or card contains ticker, reason, exposure freed, and urgency labeled Now, Soon, or Optional.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Semi-Auto
severity: P0
finding: Exit recommendations have no single confirm action for the user to approve an exit.
evidence: src/agency/templates/portfolio_monitor.html:216 - `<td>{{ position.exit_reason }}</td>` renders guidance text as the row action, and the row contains no `<form>` or `<button>`.
fix: Add one confirm exit button per recommendation that submits the appropriate close-review or exit action.
acceptance: Every rendered exit recommendation includes exactly one primary confirmation button.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Semi-Auto
severity: P1
finding: The monitor does not explain what capacity is freed by an exit recommendation.
evidence: src/agency/templates/portfolio_monitor.html:215 - `<td>{{ position.reason }}</td>` and src/agency/templates/portfolio_monitor.html:216 - `<td>{{ position.exit_reason }}</td>` render rule text without an "exiting X frees Y% -> allows Z" effect line.
fix: Add a downstream-effect line to each recommendation showing exposure freed and the number of new positions enabled.
acceptance: Each recommendation includes text matching the structure "Exiting [ticker] frees [percent] exposure -> allows [count] new position(s)."
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Semi-Auto
severity: P1
finding: The screen has no explicit "no exits needed" state when the portfolio is within policy.
evidence: src/agency/templates/portfolio_monitor.html:177 - `<span class="tag tag-neutral">No auto-close</span>`
fix: Render "Portfolio within policy - no exits needed" when there are positions but no exit recommendations.
acceptance: With positions present and no exit recommendations, the Exit Recommendations panel displays the no-exits-needed copy.
END_FINDING
AUDIT_FINDING
screen: Candidate Detail
category: Yellow Brick Road
severity: P1
finding: Candidate Detail does not show whether the candidate is already held in the portfolio.
evidence: src/agency/templates/candidate_detail.html:38 - `<div class="brief-title-row">` renders the ticker and action chip only, with no current-holding badge or portfolio branch in the file.
fix: Pass current holding context into Candidate Detail and render a "Currently holding X shares" badge near the ticker when applicable.
acceptance: For a candidate ticker that exists in portfolio positions, Candidate Detail shows a visible current-holding badge with share quantity.
END_FINDING
AUDIT_FINDING
screen: Command dashboard
category: Yellow Brick Road
severity: P1
finding: The Command dashboard does not warn about portfolio exposure near policy limit before candidate review.
evidence: src/agency/templates/dashboard.html:44 - `<section class="kpi-grid" aria-label="Current metrics">` renders review and readiness KPIs, and no exposure or portfolio limit warning branch appears in the dashboard template.
fix: Add an exposure-warning element above or beside the review queue when gross exposure is near the policy maximum.
acceptance: When exposure is within the configured warning band of the limit, the dashboard shows a visible exposure warning before the review queue.
END_FINDING
AUDIT_FINDING
screen: Portfolio Monitor
category: Yellow Brick Road
severity: P1
finding: Portfolio Monitor does not provide a clear path from existing positions to the Execution Preview screen.
evidence: src/agency/templates/portfolio_monitor.html:174 - `<section class="panel" aria-labelledby="positions-heading">` renders the Position Review section without any execution preview link.
fix: Add a visible link from the Position Review or Exit Recommendations area to the Execution Preview route for managing existing positions.
acceptance: The Portfolio Monitor page contains a visible "Execution Preview" or "Execute" link whose `href` opens the execution preview screen.
END_FINDING
