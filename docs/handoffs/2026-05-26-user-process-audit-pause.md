# User Process Audit Pause Handoff - 2026-05-26

## Resolution Update After Resume

This handoff was the pause point before the recovery work resumed. The blocker documented below has since been resolved in the follow-up implementation pass:

- Candidate `?audit=light` pages now render without rich evidence reconstruction and without broker-status calls.
- Focused execution and focused final-selection routes preserve the selected ticker.
- The generic execution page is bounded as a triage view instead of a long full-universe dump.
- Final evidence:
  - all-168 focused execution audit: `failure_count=0`
  - 24-candidate process-flow sample: `failure_count=0`
  - broad unit/UX suite: `288 passed`
  - V3/paper promotion targeted suite: `27 passed`
  - Ruff: `All checks passed`

The historical notes below are retained so the original pause context is not lost.

## Current User Steering Queue

Latest user request:

- "i need to pause for an hour, please generate a clean handoff point, so we can continue later. including my messages in the steer/queue"

Active mission before pause:

- Perform a thorough user-process-oriented behavioral audit and review.
- Cover all 168 stocks and major flow paths.
- Verify no old UX residue remains.
- Verify selected ticker/user-flow data persists between screens.
- Make the agency credible for operator review after repeated UX/process regressions.

Recent user pain points to preserve:

- From Command dashboard, approving/selecting PLTR moved to Execution, but PLTR was not automatically selected and the user had to find it in a long stock list.
- The PLTR execution screen lacked real review data and did not clearly push the stock forward in the process.
- User described this as a bad UX/process regression against the "walk me" theme.
- The user does not want more claims of readiness without broad, evidence-backed checks.

## Repo / Runtime State

- Repo: `C:\Users\meiri\trading_agency`
- Branch: `main`
- Remote tracking: `main...origin/main`
- Worktree: dirty, not committed.
- Server is running at `http://127.0.0.1:8000`.
- Current listener: `127.0.0.1:8000`, owning process observed as `18504`, parent uvicorn process `9404`.
- No `check_user_process_flow_audit.py` process was left running after the pause.
- Server environment used for restart:
  - `PYTHONPATH=C:\Users\meiri\trading_agency\src;C:\Users\meiri\trading_agency\research\src`
  - `DATABASE_URL=sqlite+aiosqlite:///research/results/agency-scheduler.sqlite`
  - `AGENCY_PAPER_TRADE_PROMOTION_ENABLED=true`
  - `AGENCY_PAPER_TRADE_MIN_CONVICTION=0.62`
  - `AGENCY_BROKER_SUBMIT_ENABLED=true`
  - `AGENCY_ALPACA_BROKER_ENABLED=true`

## Files Changed In This Worktree

Existing dirty files now include:

- `src/agency/dashboard.py`
- `src/agency/static/styles.css`
- `src/agency/templates/candidate_detail.html`
- `src/agency/templates/dashboard.html`
- `src/agency/templates/execution_preview.html`
- `src/agency/templates/final_selection.html`
- `src/agency/templates/portfolio_monitor.html`
- `src/agency/views/_shared.py`
- `src/agency/views/candidates.py`
- `src/agency/views/execution.py`
- `src/agency/views/final_selection.py`
- `tests/unit/test_fastapi_app.py`
- `tests/unit/test_ops_scripts.py`
- `tests/unit/test_ux_audit_implementation.py`
- `scripts/check_user_process_flow_audit.py` new
- `docs/user-process-flow-audit-2026-05-25.md` new
- `docs/handoffs/2026-05-26-user-process-audit-pause.md` this file

`git diff --stat` before this handoff file showed 14 changed tracked files, 865 insertions, 59 deletions. There is also a CRLF/LF warning for `src/agency/views/candidates.py`.

## Implemented During This Audit Pass

### Focused execution workflow

- `/execution-preview?ticker=TICKER` now uses a short display cache and derives focus from cached `preview_rows`.
- Focused execution routes no longer render the long full 168-row execution queue below the focused ticker card.
- Focused page now shows the selected ticker card first and a clear "Show full clearance list" path back.
- Candidate approval, manual advance, order intent approval, submit success, and order approval errors preserve ticker focus where applicable.
- `/status/execution-preview` shares the display cache. Submit/approval paths still rebuild and re-check fresh broker/data state.

### Final selection / candidate focus

- `/final-selection?ticker=TICKER#candidate-TICKER` is supported.
- Candidate cards have stable `id="candidate-TICKER"` anchors and focused styling.
- Candidate detail "Back to candidates" returns to the same ticker anchor.
- Final-selection and candidate-detail buttons are explicit:
  - `Approve research for TICKER`
  - `Defer TICKER review`
  - `Reject TICKER candidate`
- Portfolio exit action now points to `/execution-preview?ticker=TICKER#focused-preview-TICKER` and is labeled "Review exit plan for TICKER" instead of "Confirm exit plan".

### Lifecycle/fallback persistence reliability

- `_lifecycle_events_for_reports()` now normalizes ticker case.
- Human review and operator manual advance events merge local lifecycle artifacts even when DB reads succeed but return no event.
- Lifecycle events sort by `event_time`/generated timestamps so later fallback approvals win over older fallback decisions.
- Order approval artifact-only behavior was kept intentionally strict.

### Audit harness

- `scripts/check_user_process_flow_audit.py` was added.
- It audits:
  - V3 shell/build/briefing on key routes.
  - 168 execution status row contracts.
  - focused execution route behavior.
  - Command execute links preserving ticker focus.
  - optional candidate page checks.
  - forbidden old/test UX terms.
  - route budget failures via `--route-budget-seconds`.
- Candidate-page checks were changed to sample mode by default when `--candidate-pages` is used:
  - `--candidate-page-sample-size 24`
  - `0` means all candidate pages.

## Verification Passed

Commands run and passed:

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py -k "final_selection_route_preserves_requested_focus or execution_preview_focused_routes_reuse_cached_base_context or approve_execution_order_records_intent_while_execution_gate_closed or approve_execution_order_does_not_block_immediately_on_broker_failure or submit_execution_order_records_intent_before_broker_submit" -q
```

Result: `5 passed, 184 deselected`

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py -k "lifecycle_events_use_artifact_fallback or human_review_events_merge_artifact_fallback or operator_manual_advance_events_merge_artifact_fallback or order_approval_lookup_ignores_artifact_only" -q
```

Result: `4 passed, 185 deselected`

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_ops_scripts.py -k "user_process_audit" -q
```

Result: `5 passed, 52 deselected`

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py tests/unit/test_ops_scripts.py tests/unit/test_ux_audit_implementation.py -q
```

Result: `268 passed, 2 warnings`

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_v3_ux_rollout.py tests/unit/test_paper_trade_promotion.py -q
```

Result: `27 passed`

```powershell
.\.venv\Scripts\python -m ruff check src/agency/dashboard.py src/agency/views/_shared.py src/agency/views/final_selection.py scripts/check_user_process_flow_audit.py tests/unit/test_fastapi_app.py tests/unit/test_ops_scripts.py tests/unit/test_ux_audit_implementation.py
```

Result: `All checks passed`

Live focused execution full-universe audit:

```powershell
.\.venv\Scripts\python scripts\check_user_process_flow_audit.py --workers 8 --timeout 60 --all-focus-routes --route-budget-seconds 10
```

Result: `failure_count=0`, `execution_focus_route_count=168`, `ticker_count=168`.

Report paths:

- `research/results/user-process-flow-audit/latest/user-process-flow-audit.json`
- `research/results/user-process-flow-audit/latest/user-process-flow-audit.md`

## Current Blocker At Pause

Candidate page sampled audit still fails.

Command run:

```powershell
.\.venv\Scripts\python scripts\check_user_process_flow_audit.py --workers 8 --timeout 60 --focus-route-sample-size 12 --candidate-pages --candidate-page-sample-size 24 --route-budget-seconds 15
```

Result:

- `failure_count=152`
- `candidate_route_count=24`
- Every sampled candidate page returned HTTP 500.
- Failures are cascading because 500 pages do not include V3 shell/data-health/review actions.

Root cause reproduced with TestClient:

```text
jinja2.exceptions.UndefinedError: 'dict object' has no attribute 'event_count'
src/agency/templates/candidate_detail.html:616
```

Cause:

- `candidate_detail_context(..., include_rich_signal_evidence=False)` was added for audit/light mode.
- In that branch, `email_evidence` placeholder is incomplete.
- `candidate_detail.html` expects a full email evidence contract including at least:
  - `event_count`
  - `feed_count`
  - `analyzed_count`
  - `direction_rows`
  - `judgement_summary`
  - `pipeline_summary`
  - `quality_summary`
  - `primary_takeaway`
  - `insight_cards`
  - `paired_rows`
  - `rows`
  - `feed_rows`
  - `latest_at`
  - `status_class`
  - `status_label`
  - `detail`
  - `meaning`

Next fix should add a helper such as `_empty_email_evidence_for_audit(ticker)` that returns the complete contract. Do not just add `event_count`; expect further missing keys if the placeholder stays partial.

## Immediate Next Steps On Resume

1. Fix `candidate_detail_context(..., include_rich_signal_evidence=False)` to return complete placeholder contracts for email/news evidence, or make the template robust with defaults.
2. Add/adjust unit test to render `/candidates/PLTR?audit=light` successfully through `TestClient`.
3. Re-run:

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py -k "candidate_detail_report_rows_can_skip_rich_signal_reconstruction or candidate_detail_report_rows_add_signal_trigger_evidence" -q
.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py tests/unit/test_ops_scripts.py tests/unit/test_ux_audit_implementation.py -q
.\.venv\Scripts\python -m ruff check .
```

4. Restart server.
5. Re-run candidate sampled audit:

```powershell
.\.venv\Scripts\python scripts\check_user_process_flow_audit.py --workers 8 --timeout 60 --focus-route-sample-size 12 --candidate-pages --candidate-page-sample-size 24 --route-budget-seconds 15
```

6. If sampled candidate audit passes, run a deliberately stricter candidate HTML profile separately:

```powershell
.\.venv\Scripts\python scripts\check_user_process_flow_audit.py --workers 4 --timeout 60 --focus-route-sample-size 1 --candidate-pages --candidate-page-sample-size 0 --route-budget-seconds 15
```

Do not claim full candidate-page readiness until that passes or until we replace all-candidate HTML sweeping with a first-class all-candidate JSON/status contract plus sampled HTML.

## Known Residual Risks / Backlog

- Full 168 candidate HTML pages are still not proven within budget.
- Candidate `?audit=light` currently 500s until the placeholder evidence contract is fixed.
- Route budget on key pages showed some pages still near or above several seconds; performance should be monitored.
- The working tree is dirty and not committed; avoid broad refactors before the candidate audit shell is green.
- The latest generated audit report currently reflects the failing sampled candidate run, not the earlier passing 168 focused execution run.

## Suggested Resume Command Sequence

```powershell
cd C:\Users\meiri\trading_agency
git status --short --branch
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py -k "candidate_detail_report_rows_can_skip_rich_signal_reconstruction or candidate_detail_report_rows_add_signal_trigger_evidence" -q
```

Then open:

- `src/agency/views/candidates.py`
- `src/agency/templates/candidate_detail.html`
- `scripts/check_user_process_flow_audit.py`

First implementation target:

- Complete the light/audit evidence placeholder contract.
