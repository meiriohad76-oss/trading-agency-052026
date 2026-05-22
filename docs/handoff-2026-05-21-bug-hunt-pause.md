# Handoff: 2026-05-21 Bug-Hunt Pause

Timestamp: 2026-05-21 23:20:15 +03:00

## Current Mission

The active mission was another bug-hunt and QA pass on the live agency workflow, with focus on operational readiness, data-load/source-health truthfulness, execution preview, and paper-trade audit visibility.

No Alpaca or paper orders were submitted during this pass.

## What Was Fixed In This Pass

1. Operational readiness and paper-review status now distinguish runtime reader failure from a true no-cycle condition.
2. Operational readiness, paper-review, and execution preview paths now use active-cycle filtering instead of raw recent report ordering.
3. `scripts/check_operational_readiness.py` now fails when runtime and data-load cycle ids disagree.
4. Execution Preview now joins recorded execution audit state back into preview rows.
5. Filled/submitted/terminal execution states disable duplicate order approval and duplicate submit actions.
6. Filled orders can display broker confirmation fields inline: state, reason, event time, client order id, filled quantity, and average fill price.
7. `_record_submitted_order()` no longer forces a generic "submitted" reason, allowing state-specific audit reasons such as filled.
8. Source-health/data-load wording now distinguishes unavailable/data-void sources from old health-proof snapshots.
9. Scheduler refresh-needed rows now include blocking source statuses even when freshness is unknown.
10. During premarket, source-health proof for `massive-stock-trades` now reflects `massive_premarket_trade_slices` instead of regular live slices.
11. Legacy execution audit payload compatibility was fixed: audit rows may store preview data under `execution_preview` instead of `preview`.
12. Health monitor labels no longer treat synthetic unavailable lane rows as missing health-monitor timestamps.

## Subagent Bug-Hunt Findings Covered

Three read-only subagents reported issues in these groups:

1. Runtime readiness/data-load cycle mismatch and runtime reader failure masking.
2. Execution preview filled-state visibility, duplicate submit prevention, and state-specific order reasons.
3. Source-health wording, scheduler refresh rows, and premarket lane proof.

Those reported issues are represented in the current patches and verified by tests listed below.

## Verification Completed

Focused regression slice:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py -k "operational_readiness_context_reports_runtime_fetch_failure or operational_readiness_context_filters_to_active_cycle or execution_preview_rows_show_filled_audit_state_and_disable_resubmit or record_submitted_order_uses_state_specific_reason or source_health_kpi_distinguishes_unavailable" -q
```

Result:

```text
5 passed, 156 deselected in 2.68s
```

Red cases found during broader suite, then fixed:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_risk_and_execution_pages_render_runtime_states tests\unit\test_data_load_status.py::test_data_load_status_health_monitor_uses_source_specific_sla tests\unit\test_data_load_status.py::test_data_load_status_blocks_stale_health_monitor_rows -q
```

Result:

```text
3 passed in 20.23s
```

Full affected suite:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py tests\unit\test_ops_scripts.py tests\unit\test_scheduler_work_queue.py tests\unit\test_data_load_status.py -q
```

Result:

```text
303 passed, 2 warnings in 160.91s
```

Execution/promotion-specific suites:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_execution_preview_service.py tests\unit\test_paper_trade_promotion.py tests\unit\test_paper_broker_validation_script.py -q
```

Result:

```text
49 passed in 3.27s
```

Static checks:

```powershell
.\.venv\Scripts\python -m ruff check --select F,E9 src\agency\views\command.py src\agency\views\execution.py src\agency\views\_shared.py src\agency\runtime\data_load_status.py src\agency\runtime\scheduler_work_queue.py src\agency\dashboard.py scripts\check_operational_readiness.py tests\unit\test_fastapi_app.py tests\unit\test_ops_scripts.py tests\unit\test_scheduler_work_queue.py tests\unit\test_data_load_status.py
```

Result:

```text
All checks passed!
```

Compile check:

```powershell
.\.venv\Scripts\python -m compileall src\agency\views\command.py src\agency\views\execution.py src\agency\views\_shared.py src\agency\runtime\data_load_status.py src\agency\runtime\scheduler_work_queue.py src\agency\dashboard.py scripts\check_operational_readiness.py
```

Result: exit code 0.

Whitespace check:

```powershell
git diff --check
```

Result: exit code 0.

## Current Git State

Branch: `main`

Modified files:

```text
scripts/check_operational_readiness.py
scripts/start_dev.ps1
src/agency/dashboard.py
src/agency/runtime/data_load_status.py
src/agency/runtime/scheduler_work_queue.py
src/agency/static/styles.css
src/agency/templates/execution_preview.html
src/agency/views/_shared.py
src/agency/views/command.py
src/agency/views/execution.py
tests/unit/test_data_load_status.py
tests/unit/test_fastapi_app.py
tests/unit/test_ops_scripts.py
tests/unit/test_scheduler_work_queue.py
docs/handoff-2026-05-21-bug-hunt-pause.md
```

Diff size before this handoff file:

```text
14 files changed, 1556 insertions(+), 134 deletions(-)
```

There were already dirty files before this pass. Do not revert unrelated edits without explicit user approval.

## Not Completed Before Pause

1. Live endpoint probes were not completed after the final fixes.
2. The FastAPI server was not restarted as part of this pause handoff.
3. CodeRabbit CLI review did not run because `coderabbit` is not installed in this shell. A `bash` check also failed because `/bin/bash` is unavailable through WSL here.
4. No commit was created. This is an intentional pause handoff, not a repo checkpoint commit.

## Resume Here

Start with fresh verification before making any operational claim:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py tests\unit\test_ops_scripts.py tests\unit\test_scheduler_work_queue.py tests\unit\test_data_load_status.py -q
.\.venv\Scripts\python -m pytest tests\unit\test_execution_preview_service.py tests\unit\test_paper_trade_promotion.py tests\unit\test_paper_broker_validation_script.py -q
.\.venv\Scripts\python -m ruff check --select F,E9 src\agency\views\command.py src\agency\views\execution.py src\agency\views\_shared.py src\agency\runtime\data_load_status.py src\agency\runtime\scheduler_work_queue.py src\agency\dashboard.py scripts\check_operational_readiness.py tests\unit\test_fastapi_app.py tests\unit\test_ops_scripts.py tests\unit\test_scheduler_work_queue.py tests\unit\test_data_load_status.py
git diff --check
```

Then restart/probe the app before operator testing:

```powershell
.\scripts\start_dev.ps1
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/status/operational-readiness' -TimeoutSec 20 | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/status/execution-preview' -TimeoutSec 30 | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/audit/execution-states?ticker=XEL&limit=1' -TimeoutSec 10 | ConvertTo-Json -Depth 8
```

Only after those probes pass should the next operator review claim that the system is ready for workflow testing.

