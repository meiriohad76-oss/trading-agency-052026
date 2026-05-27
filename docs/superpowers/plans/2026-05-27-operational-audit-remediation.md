# Operational Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `AUDIT-REPORT-2026-05-27.md` into a verified, operationally safer Trading Agency build with crash guards, truthful data health, working cockpit controls, and regression coverage.

**Architecture:** Treat the audit as a remediation backlog, but verify each finding against current code before editing because the worktree already contains uncommitted fixes. Fix runtime-crash and data-integrity issues first, then UX/control issues, then DB/query improvements and broad QA. Preserve the lane/work-queue operating model: do not reintroduce broad direct batches or duplicate scheduler paths.

**Tech Stack:** FastAPI, Jinja templates, vanilla JS, SQLAlchemy/Alembic, pytest, Ruff, Node `--check`, Playwright/browser QA where UI behavior changes.

---

## Current Repo Cross-Check

The audit report is present at `AUDIT-REPORT-2026-05-27.md` and is currently untracked. The repo is dirty from the previous cockpit/lane-health pass, and `main` is ahead of `origin/main` by two commits.

Important live observations from the current tree:

- Still open: `BUG-1`, `BUG-2`, `BUG-3`, `BUG-4`, `BUG-5`, `BUG-6`, `BUG-7`, `BUG-8`.
- Still open: `DATA-1`, `DATA-2`, `DATA-4`, `DATA-5`, `DATA-6`, `DATA-8`.
- Still open: `UX-1`, `UX-2`, `UX-3`, `UX-4`, `UX-6`; `UX-5` needs a proof test before changing because `/cockpit/submit` currently parses repeated fields server-side.
- Partially handled before this plan: artifact-origin schema fields now exist in the dirty tree, but `DATA-8` still needs the malformed/unknown timestamp guard.
- High risk: `data-refresh-progress.js` now calls `meter()` before its current IIFE-scoped definition, so `BUG-4` is active in the current dirty tree despite `node --check` passing.

## Execution Rules

- [ ] Before implementation, run `git status --short --branch` and preserve all existing dirty changes.
- [ ] Use `.\.venv\Scripts\python -m pytest`, not bare `pytest`.
- [ ] For every bugfix, add or update a failing regression test first, run it, then implement.
- [ ] After each ticket, run that ticket's focused test and commit only the files for that ticket.
- [ ] Do not claim the agency is operational unless fresh readiness checks and browser QA pass.

---

## Task 0: Safety Checkpoint And Audit Baseline

**Files:**
- Read: `AUDIT-REPORT-2026-05-27.md`
- Read: current dirty files from `git status`
- Create: `docs/handoffs/2026-05-27-operational-audit-start.md`

- [ ] **Step 1: Record starting state**

Run:

```powershell
git status --short --branch
git diff --stat
```

Expected: dirty tree is visible; do not reset it.

- [ ] **Step 2: Write the start handoff**

Create `docs/handoffs/2026-05-27-operational-audit-start.md` containing:

```markdown
# Operational Audit Start Handoff

Source audit: `AUDIT-REPORT-2026-05-27.md`
Branch/status: paste `git status --short --branch`
Dirty diff summary: paste `git diff --stat`
Execution rule: preserve dirty work; use `.\.venv\Scripts\python -m pytest`.
First implementation task: Task 1 crash guards.
```

- [ ] **Step 3: Commit the plan and handoff**

Run:

```powershell
git add docs/superpowers/plans/2026-05-27-operational-audit-remediation.md docs/handoffs/2026-05-27-operational-audit-start.md AUDIT-REPORT-2026-05-27.md
git commit -m "docs: add operational audit remediation plan"
```

Expected: plan and source audit are tracked before code changes.

---

## Task 1: Crash Guards For Shared View Builders

**Audit IDs:** `BUG-1`, `BUG-2`, `BUG-5`, `BUG-6`, `BUG-7`, `BUG-8`  
**Files:**
- Modify: `src/agency/views/_shared.py`
- Modify: `src/agency/views/command.py`
- Test: `tests/unit/test_audit_crash_guards.py` (new)

- [ ] **Step 1: Write failing tests for partial runtime rows**

Create `tests/unit/test_audit_crash_guards.py`:

```python
from __future__ import annotations

import pytest

from agency.views import command as command_view
from agency.views import _shared as shared_view


def test_is_actionable_candidate_tolerates_missing_fields() -> None:
    assert shared_view._is_actionable_candidate({}) is False


def test_source_is_degraded_tolerates_missing_fields() -> None:
    assert shared_view._source_is_degraded({}) is False


def test_human_review_summary_tolerates_partial_event() -> None:
    summary = shared_view._human_review_summary({"payload": {"review_decision": "APPROVE"}})
    assert summary["decision"] == "Approve"
    assert summary["reason"] == ""
    assert summary["event_time"] == ""


def test_list_and_mapping_helpers_return_empty_for_missing_keys() -> None:
    assert shared_view._list_field({}, "missing") == []
    assert shared_view._mapping_field({}, "missing") == {}


def test_command_summary_tolerates_partial_candidate_and_source_rows() -> None:
    summary = command_view.command_summary(
        candidates=[{}],
        data_sources=[{}],
        contracts=[],
        readiness=None,
        review_queue=[],
    )
    assert summary["candidate_count"] == 1
    assert summary["actionable_candidate_count"] == 0
    assert summary["blocked_candidate_count"] == 0
    assert summary["degraded_source_count"] == 0


def test_source_status_rows_tolerates_partial_provider_rows() -> None:
    rows = command_view.source_status_rows([{}])
    assert rows[0]["source"] == ""
    assert rows[0]["raw_status"] == "unknown"
    assert rows[0]["raw_freshness"] == "unknown"
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_audit_crash_guards.py -q
```

Expected: fail on KeyError or missing safe behavior.

- [ ] **Step 3: Implement safe access**

Change `src/agency/views/_shared.py`:

```python
def _is_actionable_candidate(candidate: Mapping[str, object]) -> bool:
    return (
        str(candidate.get("action", "")) in ACTIONABLE_ACTIONS
        and candidate.get("gate_status") != "BLOCK"
    )
```

```python
def _human_review_summary(event: Mapping[str, object] | None) -> dict[str, str]:
    if event is None:
        return {
            "decision": "Pending",
            "status_class": "neutral",
            "reason": "no human review recorded",
            "review_reason": "",
            "notes": "",
            "event_time": "None",
        }
    payload = _mapping_field(event, "payload")
    decision = str(payload.get("review_decision", "RECORDED"))
    status = str(event.get("status", "unknown"))
    return {
        "decision": _label_text(decision),
        "status_class": _human_review_status_class(status),
        "reason": str(event.get("reason", "")),
        "review_reason": _clean_text(payload.get("review_reason")) or "",
        "notes": _clean_text(payload.get("notes")) or "",
        "event_time": str(event.get("event_time", "")),
    }
```

```python
def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source.get("status", "")) in DEGRADED_SOURCE_STATUSES
        or str(source.get("freshness", "")) in DEGRADED_FRESHNESS
    )
```

```python
def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list, got {type(value).__name__}")
    return value


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping, got {type(value).__name__}")
    return cast(Mapping[str, object], value)
```

Change `src/agency/views/command.py`:

```python
blocked_candidate_count = sum(
    1 for candidate in candidates if candidate.get("gate_status") == "BLOCK"
)
```

```python
def source_status_rows(sources: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in sources:
        raw_status = str(source.get("status", "unknown"))
        raw_freshness = str(source.get("freshness", "unknown"))
        rows.append(
            {
                "source": str(source.get("source", "")),
                "status": _source_operator_status(raw_status),
                "freshness": _source_operator_status(raw_freshness),
                "raw_status": raw_status,
                "raw_freshness": raw_freshness,
                "reliability_pct": round(_float_field(source, "reliability_score") * 100),
                "status_class": _source_status_class(source),
                "checked_at": str(source.get("checked_at", "")),
            }
        )
    return rows
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_audit_crash_guards.py tests/unit/test_fastapi_app.py -q
.\.venv\Scripts\python -m ruff check src/agency/views/_shared.py src/agency/views/command.py tests/unit/test_audit_crash_guards.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agency/views/_shared.py src/agency/views/command.py tests/unit/test_audit_crash_guards.py
git commit -m "fix: harden runtime view builders against partial rows"
```

---

## Task 2: Lane-State And JS Runtime Crash Fixes

**Audit IDs:** `BUG-3`, `BUG-4`  
**Files:**
- Modify: `src/agency/runtime/lane_state.py`
- Modify: `src/agency/static/data-refresh-progress.js`
- Test: `tests/unit/test_lane_state.py`
- Test: `tests/unit/test_ux_audit_implementation.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_lane_state.py`:

```python
def test_lane_state_unknown_status_gets_operator_label() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_reference",
                    "label": "Massive Reference",
                    "state": "planned",
                    "required_now": True,
                    "blocks_execution": False,
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[],
        now=NOW,
    )
    lane = _lane(states, "massive_reference")
    assert lane["status_label"] == "Planned"
```

Append to `tests/unit/test_ux_audit_implementation.py`:

```python
def test_data_refresh_meter_is_module_scoped_before_iifes() -> None:
    script = Path("src/agency/static/data-refresh-progress.js").read_text(encoding="utf-8")
    assert "const meter = (percent)" in script
    assert script.index("const meter = (percent)") < script.index("(() => {")
    data_load_section = script.split('const panel = document.querySelector("[data-load-panel]");', 1)[1]
    assert "const meter = (percent)" not in data_load_section
```

- [ ] **Step 2: Run tests and verify red**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_lane_state.py::test_lane_state_unknown_status_gets_operator_label tests/unit/test_ux_audit_implementation.py::test_data_refresh_meter_is_module_scoped_before_iifes -q
```

Expected: fail before implementation.

- [ ] **Step 3: Implement lane label fallback**

In `src/agency/runtime/lane_state.py`:

```python
def _status_label_for_lane(state: str, lane_kind: str) -> str:
    if state == "needs_refresh" and lane_kind == "raw_acquisition":
        return "Lane proof needs refresh"
    return STATE_LABELS.get(state, state.replace("_", " ").title())
```

- [ ] **Step 4: Move `meter()` to module scope**

At the top of `src/agency/static/data-refresh-progress.js`, after `operatorDataHealthText`, add:

```javascript
const meter = (percent) => {
  const wrapper = document.createElement("div");
  const safePercent = Math.max(0, Math.min(Number(percent || 0), 100));
  wrapper.className = "mini-meter";
  wrapper.setAttribute("aria-label", `${safePercent}% coverage`);
  const fill = document.createElement("span");
  fill.style.width = `${safePercent}%`;
  wrapper.appendChild(fill);
  return wrapper;
};
```

Remove the duplicate `const meter = (percent) => { ... }` inside the `data-load-panel` IIFE.

- [ ] **Step 5: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_lane_state.py tests/unit/test_ux_audit_implementation.py -q
node --check src/agency/static/data-refresh-progress.js
```

Expected: all pass; no JS parse errors.

- [ ] **Step 6: Commit**

```powershell
git add src/agency/runtime/lane_state.py src/agency/static/data-refresh-progress.js tests/unit/test_lane_state.py tests/unit/test_ux_audit_implementation.py
git commit -m "fix: prevent lane-state and progress-panel runtime crashes"
```

---

## Task 3: Data Integrity Guardrails

**Audit IDs:** `DATA-1`, `DATA-2`, `DATA-4`, `DATA-5`, `DATA-8`  
**Files:**
- Modify: `src/agency/runtime/lane_state.py`
- Modify: `src/agency/services/deterministic_selection.py`
- Modify: `src/agency/services/risk.py`
- Modify: `src/agency/api/reports.py`
- Modify: `src/agency/api/risk.py`
- Test: `tests/unit/test_lane_state.py`
- Test: `tests/unit/test_deterministic_selection.py` or nearest existing deterministic-selection test file
- Test: `tests/unit/test_risk_service.py` or nearest existing risk test file
- Test: `tests/unit/test_reports_api.py`
- Test: `tests/unit/test_risk_api.py`

- [ ] **Step 1: Add lane-source mapping test**

```python
def test_options_raw_lane_uses_options_source_health() -> None:
    states = build_lane_states(
        data_refresh={
            "massive_lanes": [
                {
                    "lane_id": "massive_options_flow",
                    "label": "Massive Options Flow",
                    "state": "complete",
                    "required_now": True,
                    "blocks_execution": False,
                }
            ]
        },
        dataset_rows=[],
        lane_rows=[],
        source_health_rows=[
            {
                "source": "massive-options-flow",
                "status": "UNAVAILABLE",
                "freshness": "UNAVAILABLE",
            }
        ],
        now=NOW,
    )
    lane = _lane(states, "massive_options_flow")
    assert lane["source_status"] == "UNAVAILABLE"
```

- [ ] **Step 2: Implement lane-source map**

```python
_LANE_SOURCE_MAP: dict[str, str] = {
    "massive_daily_bars": "daily-market-bars",
    "massive_live_trade_slices": "massive-stock-trades",
    "massive_premarket_trade_slices": "massive-stock-trades",
    "massive_block_trade_feed": "massive-stock-trades",
    "massive_backtest_trade_tape": "massive-stock-trades",
    "massive_options_flow": "massive-options-flow",
}


def _source_for_raw_lane(lane_id: str) -> str:
    return _LANE_SOURCE_MAP.get(lane_id, "massive-stock-trades")
```

- [ ] **Step 3: Fix deterministic lifecycle inversion**

Add/adjust test to assert BUY is actionable using `status_for_action`. Then in `src/agency/services/deterministic_selection.py`:

```python
from agency.services.selection_events import status_for_action
```

```python
deterministic = _mapping_field(report, "deterministic")
status = status_for_action(final_action, deterministic)
```

- [ ] **Step 4: Fix risk missing-source and env defaults**

Add test where `missing_source_count` is `3.0` and risk returns BLOCK. Add policy test where DB/default `broker_submit_enabled=True` survives missing env.

Implement:

```python
missing_value = source_health_summary.get("missing_source_count", 0)
missing_count = (
    int(missing_value)
    if isinstance(missing_value, (int, float)) and not isinstance(missing_value, bool)
    else 0
)
```

```python
broker_submit_enabled=_env_bool(
    values.get("AGENCY_BROKER_SUBMIT_ENABLED"),
    default=defaults.broker_submit_enabled,
),
allow_short_trades=_env_bool(
    values.get("AGENCY_ALLOW_SHORT_TRADES"),
    default=defaults.allow_short_trades,
),
```

- [ ] **Step 5: Fix artifact superseded truthfulness**

Add tests in `tests/unit/test_reports_api.py` and `tests/unit/test_risk_api.py` where DB and artifact timestamps are both malformed/unknown. Expected: no `runtime_storage_superseded=True` claim.

Implementation rule:

```python
UNKNOWN_TS = datetime.min.replace(tzinfo=UTC)

def _prefer_newer_artifact_payloads(
    storage_payloads: list[dict[str, object]],
    artifact_payloads: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not artifact_payloads:
        return storage_payloads
    if not storage_payloads:
        return artifact_payloads
    artifact_ts = _latest_payload_timestamp(artifact_payloads)
    storage_ts = _latest_payload_timestamp(storage_payloads)
    if artifact_ts == UNKNOWN_TS or storage_ts == UNKNOWN_TS:
        return storage_payloads
    if artifact_ts > storage_ts:
        return artifact_payloads
    return storage_payloads
```

If provenance stamping needs to know whether storage was superseded, return a small object or pass `runtime_storage_superseded=artifact_ts > storage_ts and storage_ts != UNKNOWN_TS`.

- [ ] **Step 6: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_lane_state.py tests/unit/test_reports_api.py tests/unit/test_risk_api.py -q
.\.venv\Scripts\python -m pytest tests/unit -q
.\.venv\Scripts\python -m ruff check src/agency/runtime/lane_state.py src/agency/services/deterministic_selection.py src/agency/services/risk.py src/agency/api/reports.py src/agency/api/risk.py
```

- [ ] **Step 7: Commit**

```powershell
git add src/agency/runtime/lane_state.py src/agency/services/deterministic_selection.py src/agency/services/risk.py src/agency/api/reports.py src/agency/api/risk.py tests/unit
git commit -m "fix: harden operational data integrity guards"
```

---

## Task 4: Selection Schema 0.2 Trade-Plan Fields

**Audit IDs:** `DATA-3`, `DATA-7`, `TEST-1`, `TEST-4`  
**Files:**
- Modify: `src/agency/services/paper_trade_promotion.py`
- Modify: `src/agency/services/deterministic_selection.py`
- Modify: `src/agency/services/final_selection.py`
- Modify: `src/agency/services/demo_cycle.py`
- Modify: `tests/unit/service_fixtures.py`
- Create: `tests/unit/test_contract_schemas.py`

- [ ] **Step 1: Add schema guard tests**

Create `tests/unit/test_contract_schemas.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agency.api.risk import PolicyUpdate

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_ROOT / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_selection_report_schema_accepts_current_versions() -> None:
    allowed = set(_schema("selection-report")["properties"]["schema_version"]["enum"])
    assert {"0.1.0", "0.2.0"}.issubset(allowed)


def test_runtime_origin_enums_match_api_outputs() -> None:
    assert set(_schema("selection-report")["properties"]["runtime_origin"]["enum"]) == {
        "runtime_artifact_fallback",
        "runtime_artifact_selected",
    }
    assert set(_schema("risk-decision")["properties"]["runtime_origin"]["enum"]) == {
        "runtime_artifact_fallback",
        "runtime_artifact_selected",
    }


def test_policy_update_cannot_toggle_runtime_submit_safety() -> None:
    fields = set(PolicyUpdate.model_fields)
    assert "broker_submit_enabled" not in fields
    assert "allow_short_trades" not in fields
```

- [ ] **Step 2: Add validated fixture wrapper**

In `tests/unit/service_fixtures.py`:

```python
from agency.contracts import validate_contract


def selection_report_validated(**kwargs: object) -> dict[str, object]:
    report = selection_report(**kwargs)
    validate_contract("selection-report", report)
    return report
```

- [ ] **Step 3: Add trade-plan tests**

Add focused tests proving promoted BUY reports emit:

```python
assert report["schema_version"] == "0.2.0"
assert report["trade_plan"]["trailing_stop_pct"] == policy.trailing_stop_pct / 100.0
assert report["trade_plan"]["position_pct"] == policy.default_position_pct / 100.0
```

Add demo-cycle test:

```python
assert sell_or_cover_report["trade_plan"]["position_size"] is None
```

- [ ] **Step 4: Implement minimal schema-version logic**

In report builders, use:

```python
schema_version = "0.2.0" if trade_plan is not None else "0.1.0"
```

Populate:

```python
trade_plan["trailing_stop_pct"] = policy.trailing_stop_pct / 100.0
trade_plan["position_pct"] = policy.default_position_pct / 100.0
```

- [ ] **Step 5: Verify and commit**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_contract_schemas.py tests/unit -q
.\.venv\Scripts\python -m ruff check src/agency/services tests/unit
git add src/agency/services tests/unit
git commit -m "fix: emit current selection trade-plan schema fields"
```

---

## Task 5: Scheduler Intent Clarification

**Audit IDs:** `SCHED-1`, `SCHED-2`  
**Files:**
- Modify: `src/agency/runtime/scheduler_runner.py`
- Test: existing scheduler runner tests or new `tests/unit/test_scheduler_runner.py`

Recommended decision: keep the work queue as the single scheduler authority. Do not enable `_register_phase_jobs()` unless tests prove missing coverage, because duplicate phase jobs would conflict with the lane/work-queue model.

- [ ] **Step 1: Add tests**

```python
def test_scheduler_build_documents_work_queue_as_single_authority() -> None:
    source = Path("src/agency/runtime/scheduler_runner.py").read_text(encoding="utf-8")
    assert "_register_work_queue_jobs(scheduler)" in source
    assert "intentionally disabled" in source
    assert "_register_phase_jobs(scheduler)" not in source.split("def build_scheduler", 1)[1].split("return scheduler", 1)[0]
```

- [ ] **Step 2: Add code comment**

In `build_scheduler()`:

```python
# _register_phase_jobs() is intentionally disabled. The live system routes
# all automatic refresh decisions through the market-aware work queue so each
# lane has one source of priority, cadence, budget, ETA, and status truth.
```

- [ ] **Step 3: Make `_load_live_scheduler_work_queue()` intent explicit**

Replace event-loop guessing with the synchronous file/context path that is valid from APScheduler worker threads. The implementation must clearly state that the function is called outside the app event loop.

- [ ] **Step 4: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_scheduler_runner.py tests/unit/test_fastapi_app.py -q
.\.venv\Scripts\python -m ruff check src/agency/runtime/scheduler_runner.py tests/unit/test_scheduler_runner.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/agency/runtime/scheduler_runner.py tests/unit/test_scheduler_runner.py
git commit -m "fix: document work-queue scheduler authority"
```

---

## Task 6: Cockpit UX Control Fixes

**Audit IDs:** `UX-1`, `UX-2`, `UX-3`, `UX-4`, `UX-6`, `UX-7`  
**Files:**
- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/templates/_cockpit_panels.html`
- Modify: `src/agency/static/cockpit.js`
- Modify: `tests/unit/test_cockpit_views.py`
- Modify: `tests/unit/test_ux_audit_implementation.py`

- [ ] **Step 1: Add static tests**

Assert:

```python
assert 'data-cockpit-ready="true"' not in cockpit_html
assert 'data-cockpit-ticker-payload="{{ candidate|tojson|safe }}"' in cockpit_html
assert 'class="cockpit-phase-cell active"' not in cockpit_html
assert "window.confirm(" not in cockpit_js
assert "data-signal-filter" in cockpit_js
assert "data-monitor-filter" in cockpit_js
assert "signal-{{ signal.status | lower }}" in cockpit_panels_html
```

- [ ] **Step 2: Fix JSON attribute**

In both `data-cockpit-ticker-payload` locations:

```html
data-cockpit-ticker-payload="{{ candidate|tojson|safe }}"
```

- [ ] **Step 3: Remove template-ready and hardcoded active**

Remove `data-cockpit-ready="true"` from the cockpit shell. Remove hardcoded `active` from the first phase button. Let `cockpit.js` set both current phase and readiness.

- [ ] **Step 4: Replace blocking restore confirm**

Add a non-blocking restore notice in `cockpit.js`:

```javascript
function showRestoreNotice(onRestore, onDiscard) {
  const notice = document.createElement("div");
  notice.className = "cockpit-restore-notice";
  notice.setAttribute("role", "alert");
  const text = document.createElement("p");
  text.textContent = "Restore local planning markers from your last session? These are not server approvals.";
  const restore = document.createElement("button");
  restore.className = "button button-secondary";
  restore.type = "button";
  restore.textContent = "Restore";
  restore.addEventListener("click", () => {
    onRestore();
    notice.remove();
  });
  const discard = document.createElement("button");
  discard.className = "button button-secondary";
  discard.type = "button";
  discard.textContent = "Discard";
  discard.addEventListener("click", () => {
    onDiscard();
    notice.remove();
  });
  notice.append(text, restore, discard);
  const rail = document.querySelector(".cockpit-phase-rail");
  if (rail) {
    rail.insertAdjacentElement("afterend", notice);
  } else {
    document.body.prepend(notice);
  }
}
```

- [ ] **Step 5: Wire filters**

Add event handlers for `data-signal-filter` and `data-monitor-filter`. Add CSS classes:

```html
<article class="cockpit-signal-item signal-{{ signal.status | lower }}">
```

and monitor item classes:

```html
<article class="cockpit-monitor-item monitor-{{ event.status_class|default('info', true) }}">
```

- [ ] **Step 6: Add Firefox fallback**

```javascript
if (document.querySelector(".cockpit-shell")) {
  document.querySelector(".topbar")?.setAttribute("hidden", "");
  document.querySelector(".v3-phase-rail")?.setAttribute("hidden", "");
}
```

- [ ] **Step 7: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_cockpit_views.py tests/unit/test_ux_audit_implementation.py -q
node --check src/agency/static/cockpit.js
```

Then use the browser on `http://127.0.0.1:8000/cockpit` if the server is running, checking:

- Signal filters hide/show rows.
- Monitor filters hide/show rows.
- No native browser confirm appears.
- Cockpit shell does not show ready styling if JS fails.

- [ ] **Step 8: Commit**

```powershell
git add src/agency/templates/cockpit.html src/agency/templates/_cockpit_panels.html src/agency/static/cockpit.js tests/unit
git commit -m "fix: make cockpit controls truthful and interactive"
```

---

## Task 7: Operator Workflow And Submit Flow Coverage

**Audit IDs:** `UX-5`, `UX-9`, `TEST-2`, `TEST-5`  
**Files:**
- Modify: `src/agency/static/cockpit.js` only if proof test fails
- Modify: `src/agency/templates/dashboard.html`
- Create: `tests/flow/test_operator_review_flow.py`
- Modify: `tests/unit/test_cockpit_routes.py`

- [ ] **Step 1: Prove multi-ticker cockpit submit behavior before changing it**

Add a route-level test that submits two order rows with duplicate `ticker`, `cycle_id`, `as_of`, and `order_intent_hash` fields. Expected: both rows reach `submit_execution_order`.

If this passes, do not refactor to JSON. If it fails, refactor to explicit JSON payload with a matching FastAPI route handler and tests.

- [ ] **Step 2: Replace fragile wall-clock assertions**

In timeout tests, replace timing-only assertions with structural assertions like:

```python
assert payload["data_health"]["status_label"] == "Detail delayed"
```

or:

```python
assert context["portfolio_phase"]["status_label"] in {
    "Portfolio Check Delayed",
    "Check Skipped",
}
```

- [ ] **Step 3: Add operator flow test**

Create `tests/flow/test_operator_review_flow.py` with a service-level flow:

```python
def test_operator_can_advance_candidate_to_execution_preview() -> None:
    ...
```

The test must cover:

- candidate exists,
- risk decision is ALLOW or WARN,
- execution preview has a clear `preview_state`,
- paper submit remains behind human/order-intent gates.

- [ ] **Step 4: Improve review action forms without broad framework change**

Add `class="review-action-form"` and data labels to review forms. Add fetch-based progressive enhancement only if tests/browser QA confirm it does not break normal POST fallback.

- [ ] **Step 5: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/flow/test_operator_review_flow.py tests/unit/test_cockpit_routes.py -q
node --check src/agency/static/cockpit.js
```

- [ ] **Step 6: Commit**

```powershell
git add src/agency/static/cockpit.js src/agency/templates/dashboard.html tests/flow tests/unit/test_cockpit_routes.py
git commit -m "test: cover operator review to execution workflow"
```

---

## Task 8: Operational Preflight Automation

**Audit IDs:** `OPS-1`, `OPS-2`, `OPS-3`, `OPS-4`, `OPS-5`  
**Files:**
- Modify: `scripts/start_dev.ps1`
- Modify: `src/agency/app.py`
- Create or modify: `scripts/check_operational_preflight.py`
- Test: `tests/unit/test_ops_scripts.py`

- [ ] **Step 1: Add preflight script tests**

Test that preflight reports:

- config `end` before today as BLOCK,
- scheduler disabled as BLOCK,
- DB fallback as WARN unless explicitly allowed,
- subscription email unavailable as WARN with login-refresh action.

- [ ] **Step 2: Add startup warning**

In app lifespan, warn when scheduler is disabled:

```python
if not _scheduler_enabled_for_app(db_url):
    print(
        "[WARNING] AGENCY_SCHEDULER_ENABLED is false or not set. "
        "No automatic lane refresh or runtime cycles will run. "
        "Set AGENCY_SCHEDULER_ENABLED=true for live operation.",
        flush=True,
    )
```

- [ ] **Step 3: Harden `start_dev.ps1`**

Set today’s `research/config/live-refresh.local.json` `end` before server start, but print the change clearly:

```powershell
$cfgPath = "research\config\live-refresh.local.json"
$cfg = Get-Content $cfgPath | ConvertFrom-Json
$today = Get-Date -Format "yyyy-MM-dd"
if ($cfg.end -ne $today) {
  Write-Host "Updating live refresh end date from $($cfg.end) to $today"
  $cfg.end = $today
  $cfg | ConvertTo-Json -Depth 10 | Set-Content $cfgPath -Encoding utf8
}
```

- [ ] **Step 4: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_ops_scripts.py -q
.\.venv\Scripts\python scripts/check_operational_readiness.py --min-queue 1
.\.venv\Scripts\python scripts/check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
```

Expected: no hidden fallback artifact should be treated as proof of full operational readiness.

- [ ] **Step 5: Commit**

```powershell
git add scripts/start_dev.ps1 scripts/check_operational_preflight.py src/agency/app.py tests/unit/test_ops_scripts.py
git commit -m "fix: add live-operation preflight checks"
```

---

## Task 9: DB Query Columns For Risk Decisions

**Audit IDs:** `DB-1`  
**Files:**
- Modify: `src/agency/persistence/models.py`
- Modify: `src/agency/runtime/risk_decisions.py`
- Create: Alembic migration under `migrations/versions/`
- Test: persistence/runtime tests for risk decisions

- [ ] **Step 1: Add failing persistence test**

Persist a risk decision with `final_action="BUY"` and `final_conviction=0.74`; assert the DB row exposes queryable columns with those values.

- [ ] **Step 2: Add model columns and index**

```python
Col("final_action", String(length=40), nullable=False, server_default="UNKNOWN"),
Col("final_conviction", Float, nullable=False, server_default="0.0"),
Index("ix_risk_decisions_final_action", risk_decisions.c.final_action),
```

- [ ] **Step 3: Update row values**

```python
"final_action": str(decision.get("final_action", "UNKNOWN")),
"final_conviction": float(decision.get("final_conviction", 0.0)),
```

- [ ] **Step 4: Add migration**

Migration must use SQLite batch mode compatibility because the repo supports SQLite fallback.

- [ ] **Step 5: Verify**

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_risk_api.py tests/unit/test_policy_persistence.py -q
.\.venv\Scripts\python -m alembic upgrade head
```

- [ ] **Step 6: Commit**

```powershell
git add src/agency/persistence/models.py src/agency/runtime/risk_decisions.py migrations/versions tests/unit
git commit -m "feat: index risk decisions by action and conviction"
```

---

## Task 10: Final QA And Operational Readiness Probe

**Audit IDs:** all  
**Files:** no feature files unless verification finds bugs.

- [ ] **Step 1: Static checks**

```powershell
.\.venv\Scripts\python -m ruff check .
node --check src/agency/static/cockpit.js
node --check src/agency/static/data-refresh-progress.js
git diff --check
```

- [ ] **Step 2: Unit and flow checks**

```powershell
.\.venv\Scripts\python -m pytest tests/unit -q
.\.venv\Scripts\python -m pytest tests/flow -q
```

- [ ] **Step 3: Live/local readiness checks**

```powershell
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
```

- [ ] **Step 4: Browser QA**

With a single server running:

- Command page loads.
- Cockpit page loads.
- Data lane progress meters render.
- Ticker drawer opens without heavy candidate-detail delay.
- Signal and monitor filters work.
- Approve research flow records server approval, not local-only approval.
- Execution preview shows order intent only when policy gates create it.

- [ ] **Step 5: Final handoff**

Create `docs/handoffs/2026-05-27-operational-audit-complete.md`:

```markdown
# Operational Audit Completion Handoff

Implemented tickets:
Fresh verification:
Known residual risks:
How to start server:
What operator should check first:
```

- [ ] **Step 6: Commit**

```powershell
git add docs/handoffs/2026-05-27-operational-audit-complete.md
git commit -m "docs: record operational audit completion handoff"
```

---

## Deferred / Lower-Priority Items

These should be handled after the system is crash-safe and review-to-paper flow is verified:

- `MINOR-1`: deduplicate `_humanize_seconds_in_text` / `_duration_label`.
- `MINOR-2`: cache callback timestamp guard.
- `MINOR-3`: `/universe` nav or internal-route note.
- `MINOR-4`: execution preview fragment anchor.
- `MINOR-5`: heartbeat polling only on operational pages.
- `UX-8`: brand link target decision. Do not change this without product approval because the current product direction has made cockpit the operational home.

## Definition Of Done

The audit remediation is done only when all are true:

- All critical/high crash findings have failing-then-passing tests.
- `data-refresh-progress.js` has no runtime-scope `meter()` issue and passes `node --check`.
- Partial runtime rows cannot crash Command, Cockpit, source health, or data health builders.
- Lane health uses correct provider/source mapping.
- Artifact-selected rows do not falsely claim DB supersession when timestamps are unknown.
- Cockpit controls are interactive and do not imply server approval from localStorage.
- `.\.venv\Scripts\python -m pytest tests/unit -q` passes.
- `.\.venv\Scripts\python -m pytest tests/flow -q` passes or an explicit missing-dependency reason is recorded.
- Ruff, JS syntax, and `git diff --check` pass.
- A final handoff records exact verification commands and results.
