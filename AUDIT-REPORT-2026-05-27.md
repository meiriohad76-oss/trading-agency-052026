# Trading Agency — Full Operational Audit Report
**Date:** 2026-05-27  
**Audited by:** 5 parallel specialist agents (Product/Flow, Backend Code, UX/Frontend, Schema/Data, QA/Tests)  
**Goal:** Achieve live operational initial full operational capability (IOC) within 5 hours  
**Total findings:** 62 raw → 47 unique after deduplication  
**Format:** Codex-ready — every fix includes exact file, line, and replacement code

---

## SEVERITY LEGEND
- 🔴 **CRITICAL** — System crashes or is completely inoperable without this fix
- 🟠 **HIGH** — Major feature broken or silent data corruption
- 🟡 **MEDIUM** — Noticeable UX or reliability degradation
- 🔵 **LOW** — Minor quality / documentation issue

---

## PART 1: OPERATIONAL BLOCKERS (Fix before starting the server)

These are pre-flight config issues that require operator action, not code changes.

### OPS-1: Config end date is 12 days stale 🔴 CRITICAL
**File:** `research/config/live-refresh.local.json`  
**Problem:** `"end": "2026-05-15"` is 12 days behind today. `load_data_load_status()` checks `config_as_of_verified`; when `False`, it injects a BLOCK blocker into all readiness panels. Every health check, dashboard panel, and cockpit readiness gate will show BLOCKED.  
**Operator action:** Update the file before starting the server:
```json
{
  "end": "2026-05-27"
}
```
**Automation fix** — add to `run_daily_ops.py` or `start_dev.ps1`:
```powershell
# PowerShell: update end date to today
$cfg = Get-Content research\config\live-refresh.local.json | ConvertFrom-Json
$cfg.end = (Get-Date -Format "yyyy-MM-dd")
$cfg | ConvertTo-Json -Depth 10 | Set-Content research\config\live-refresh.local.json -Encoding utf8
```

---

### OPS-2: Scheduler disabled by default in `.env.example` 🔴 CRITICAL
**File:** `.env.example`, `.env`  
**Problem:** `.env.example` ships with `AGENCY_SCHEDULER_ENABLED=false`. Without the scheduler, no lanes auto-refresh, no runtime cycle runs automatically. The system stales out within hours.  
**Operator action:**
```bash
# In .env, change:
AGENCY_SCHEDULER_ENABLED=true
```
**Code hardening** — add startup warning in `src/agency/app.py` inside `_lifespan()` after line 65:
```python
if not _scheduler_enabled_for_app(db_url):
    print(
        "[WARNING] AGENCY_SCHEDULER_ENABLED is false or not set. "
        "No automatic lane refresh or runtime cycles will run. "
        "Set AGENCY_SCHEDULER_ENABLED=true for live operation.",
        flush=True,
    )
```

---

### OPS-3: Postgres must be running — SQLite fallback silently degrades health monitoring 🟠 HIGH
**File:** `src/agency/db.py`  
**Problem:** Without Postgres, the app falls back to SQLite. Source health data is never written to DB, making `runtime_data_source_status()` always return stale artifact-based health. Cycle results aren't persisted for human review.  
**Operator action:** Before starting the server:
```bash
docker compose up -d postgres
# Verify .env has:
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=agency
# DB_USER=<user>
# DB_PASSWORD=<password>
```

---

### OPS-4: Run subscription email login refresh (Seeking Alpha) 🟠 HIGH
**File:** `research/data/manifests/subscription_emails.json`  
**Problem:** `subscription-email-thesis` source is UNAVAILABLE, stale since 2026-05-19 (8 days). Subscription thesis lane only produced 3 signals out of 168 tickers.  
**Operator action:** From the Command page, click **"Open email login refresh"** and complete the Seeking Alpha browser login.

---

### OPS-5: All 168 tickers are BLOCKED/DISABLED — run a fresh cycle after fixing OPS-1 through OPS-4 🟠 HIGH
**Problem:** Last cycle (2026-05-26) shows `execution_state_counts: {"BLOCKED": 148, "DISABLED": 20}`. Zero actionable candidates.  
**Operator action:** After completing OPS-1 through OPS-3:
```bash
python scripts/run_live_runtime_cycle.py \
  --config research/config/live-refresh.local.json \
  --cycle-id manual-2026-05-27 \
  --audit-trigger MANUAL \
  --persist \
  --runtime-universe active
```

---

## PART 2: CRASH BUGS (Code changes — fix immediately)

These cause runtime exceptions that take down entire pages or panels.

---

### BUG-1: `KeyError` crashes entire Command dashboard — `_is_actionable_candidate` 🔴 CRITICAL
**File:** `src/agency/views/_shared.py:495-496`  
**Problem:** Direct subscript access on `candidate["action"]` and `candidate["gate_status"]` raises `KeyError` for any candidate row missing either field, crashing `command_summary()` entirely.

**Current code:**
```python
def _is_actionable_candidate(candidate: Mapping[str, object]) -> bool:
    return str(candidate["action"]) in ACTIONABLE_ACTIONS and candidate["gate_status"] != "BLOCK"
```

**Fix:**
```python
def _is_actionable_candidate(candidate: Mapping[str, object]) -> bool:
    return (
        str(candidate.get("action", "")) in ACTIONABLE_ACTIONS
        and candidate.get("gate_status") != "BLOCK"
    )
```

---

### BUG-2: Second `KeyError` crash in `command_summary()` blocked count 🔴 CRITICAL
**File:** `src/agency/views/command.py:283-284`  
**Problem:** Second direct subscript `candidate["gate_status"]` in the same function.

**Current code:**
```python
blocked_candidate_count = sum(
    1 for candidate in candidates if candidate["gate_status"] == "BLOCK"
)
```

**Fix:**
```python
blocked_candidate_count = sum(
    1 for candidate in candidates if candidate.get("gate_status") == "BLOCK"
)
```

---

### BUG-3: `KeyError` crashes data health panel on any transient lane state 🔴 CRITICAL
**File:** `src/agency/runtime/lane_state.py:448-451`  
**Problem:** `STATE_LABELS[state]` is a bare dict lookup with no fallback. Any lane state not in the 7-key dict (e.g., `"running"`, `"pending"`, `"planned"`) raises `KeyError`, crashing `build_lane_states()` and returning HTTP 500 from the dashboard health endpoint. Independently confirmed by two agents.

**Current code:**
```python
def _status_label_for_lane(state: str, lane_kind: str) -> str:
    if state == "needs_refresh" and lane_kind == "raw_acquisition":
        return "Lane proof needs refresh"
    return STATE_LABELS[state]
```

**Fix:**
```python
def _status_label_for_lane(state: str, lane_kind: str) -> str:
    if state == "needs_refresh" and lane_kind == "raw_acquisition":
        return "Lane proof needs refresh"
    return STATE_LABELS.get(state, state.replace("_", " ").title())
```

---

### BUG-4: `meter()` function scoped inside one IIFE, called from two others — `ReferenceError` 🔴 CRITICAL
**File:** `src/agency/static/data-refresh-progress.js:715, 1093, 1264`  
**Problem:** `meter()` is defined inside the `data-load-panel` IIFE (starts ~line 1219) but called at lines 715 and 1093 inside separate IIFEs. JavaScript lexical scoping makes `meter` undefined in those outer scopes → `ReferenceError` → Massive lane progress panel and scheduler lane table render blank.

**Fix:** Move `meter()` to module scope **before** the first IIFE (before line 1), then remove the duplicate definition at line 1264:
```javascript
// ADD at top of file, before all IIFEs:
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

// REMOVE the duplicate definition at line ~1264 inside the data-load-panel IIFE
```

---

### BUG-5: `KeyError` crashes source status panel on degraded provider 🟠 HIGH
**File:** `src/agency/views/command.py:450-461`  
**Problem:** `source_status_rows()` uses direct subscript on all four fields. Fails exactly when most critical — when a provider is degraded and the row is partial.

**Current code:**
```python
raw_status = str(source["status"])
raw_freshness = str(source["freshness"])
# ...
"source": str(source["source"]),
"checked_at": str(source["checked_at"]),
```

**Fix:**
```python
raw_status = str(source.get("status", "unknown"))
raw_freshness = str(source.get("freshness", "unknown"))
# ...
"source": str(source.get("source", "")),
"checked_at": str(source.get("checked_at", "")),
```

---

### BUG-6: `KeyError` in `_source_is_degraded()` — crashes degraded-source count 🟠 HIGH
**File:** `src/agency/views/_shared.py:566-570`

**Current code:**
```python
def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source["status"]) in DEGRADED_SOURCE_STATUSES
        or str(source["freshness"]) in DEGRADED_FRESHNESS
    )
```

**Fix:**
```python
def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source.get("status", "")) in DEGRADED_SOURCE_STATUSES
        or str(source.get("freshness", "")) in DEGRADED_FRESHNESS
    )
```

---

### BUG-7: `KeyError` in `_human_review_summary()` — crashes paper review queue 🟠 HIGH
**File:** `src/agency/views/_shared.py:556-563`

**Current code:**
```python
status = str(event["status"])
return {
    ...
    "reason": str(event["reason"]),
    "event_time": str(event["event_time"]),
}
```

**Fix:**
```python
status = str(event.get("status", "unknown"))
return {
    ...
    "reason": str(event.get("reason", "")),
    "event_time": str(event.get("event_time", "")),
}
```

---

### BUG-8: `_list_field()` / `_mapping_field()` raise on missing keys — kills entire view builder 🟠 HIGH
**File:** `src/agency/views/_shared.py:697-707`  
**Problem:** Both helpers use `payload[key]` (not `.get()`). Any partial runtime payload crashes the entire view builder chain for `data_load_status_view()`, `full_live_readiness_view()`, and `scheduler_work_queue_view()`.

**Current code:**
```python
def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]          # KeyError if missing
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value

def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]          # KeyError if missing
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)
```

**Fix:**
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

---

## PART 3: DATA INTEGRITY BUGS

---

### DATA-1: Wrong source health lookup for options/premarket lanes — health appears OK when source is down 🟠 HIGH
**File:** `src/agency/runtime/lane_state.py:597-600`  
**Problem:** `_source_for_raw_lane()` returns `"massive-stock-trades"` for all non-daily-bars lanes, including `massive_options_flow`. The options source health entry uses a different name, so options lanes always show healthy even when the actual source is down.

**Current code:**
```python
def _source_for_raw_lane(lane_id: str) -> str:
    if lane_id == "massive_daily_bars":
        return "daily-market-bars"
    return "massive-stock-trades"
```

**Fix:**
```python
_LANE_SOURCE_MAP: dict[str, str] = {
    "massive_daily_bars": "daily-market-bars",
    "massive_live_trade_slices": "massive-stock-trades",
    "massive_premarket_trade_slices": "massive-stock-trades",
    "massive_block_trade_feed": "massive-stock-trades",
    "massive_options_flow": "massive-options-flow",
    "massive_backtest_trade_tape": "massive-stock-trades",
}

def _source_for_raw_lane(lane_id: str) -> str:
    return _LANE_SOURCE_MAP.get(lane_id, "massive-stock-trades")
```

---

### DATA-2: `DETERMINISTIC_ACTION` lifecycle emits `BLOCKED` for BUY/SELL actions — audit trail inverted 🟠 HIGH
**File:** `src/agency/services/deterministic_selection.py:58`  
**Problem:** The status logic `status = "ACTIONABLE" if final_action == "WATCH" else "BLOCKED"` marks every BUY/SELL/HOLD action as BLOCKED in the lifecycle audit trail. `selection_events.py` already has the correct `status_for_action()` function.

**Current code:**
```python
status = "ACTIONABLE" if final_action == "WATCH" else "BLOCKED"
```

**Fix:**
```python
from agency.services.selection_events import status_for_action

deterministic = _mapping_field(report, "deterministic")
status = status_for_action(str(report.get("final_action", "NO_TRADE")), deterministic)
```

---

### DATA-3: `schema_version` stuck at `"0.1.0"` — `trailing_stop_pct`/`position_pct` never written 🟠 HIGH
**Files:** `src/agency/services/deterministic_selection.py:33`, `src/agency/services/final_selection.py:140`, `src/agency/services/demo_cycle.py:128`  
**Problem:** All three code paths hard-code `"schema_version": "0.1.0"`. Schema 0.2.0 was bumped specifically to track `trailing_stop_pct` and `position_pct`, but these fields are never populated and the version never emitted as 0.2.0.

**Fix in `src/agency/services/paper_trade_promotion.py` `_promoted_report()` function:**
```python
# After building trade_plan, populate 0.2.0 fields from policy:
if trade_plan is not None:
    trade_plan["trailing_stop_pct"] = policy.trailing_stop_pct / 100.0
    trade_plan["position_pct"] = policy.default_position_pct / 100.0
    schema_version = "0.2.0"
else:
    schema_version = "0.1.0"

# In the returned dict, replace hardcoded "0.1.0":
return {
    ...
    "schema_version": schema_version,
    ...
}
```
Apply the same pattern in `deterministic_selection.py` and `final_selection.py`.

---

### DATA-4: `missing_source_count` float-vs-int check silently skips risk BLOCK 🟠 HIGH
**File:** `src/agency/services/risk.py:499-501`  
**Problem:** `isinstance(3.0, int)` is `False` in Python. If `missing_source_count` is a float (e.g., from JSON deserialization), the missing-source BLOCK is silently skipped — a BLOCK becomes ALLOW.

**Current code:**
```python
missing_value = source_health_summary.get("missing_source_count", 0)
missing_count = missing_value if isinstance(missing_value, int) else 0
```

**Fix:**
```python
missing_value = source_health_summary.get("missing_source_count", 0)
missing_count = (
    int(missing_value)
    if isinstance(missing_value, (int, float)) and not isinstance(missing_value, bool)
    else 0
)
```

---

### DATA-5: `broker_submit_enabled` / `allow_short_trades` silently default to `False` — DB values always discarded 🟠 HIGH
**File:** `src/agency/services/risk.py:128-129`  
**Problem:** `_env_bool(values.get("AGENCY_BROKER_SUBMIT_ENABLED"))` omits the `default=` kwarg. If env var is absent, defaults to `False`, silently overriding any DB-stored value. An operator setting `allow_short_trades=True` in the DB will be silently surprised.

**Fix:**
```python
broker_submit_enabled=_env_bool(
    values.get("AGENCY_BROKER_SUBMIT_ENABLED"),
    default=defaults.broker_submit_enabled,  # False — env always supersedes DB for safety controls
),
allow_short_trades=_env_bool(
    values.get("AGENCY_ALLOW_SHORT_TRADES"),
    default=defaults.allow_short_trades,  # False — env always supersedes DB for safety controls
),
```

---

### DATA-6: `selection_reports` API endpoint silently skips schema validation 🟡 MEDIUM
**File:** `src/agency/api/reports.py:38, 54`  
**Problem:** Both public GET endpoints call `runtime_selection_reports(..., validate_payloads=False)`. Contrast with `api/risk.py` which uses `validate_payloads=True`. Malformed or forward-schema payloads are returned to the frontend silently.

**Fix:** Remove `validate_payloads=False` from both calls at lines 38 and 54 to use the default `validate_payloads=True`.

---

### DATA-7: `demo_cycle.py` writes `position_size: 0.0` for non-BUY trade plans 🟡 MEDIUM
**File:** `src/agency/services/demo_cycle.py:187-194`  
**Problem:** `"position_size": 10.0 if final_action == "BUY" else 0.0` — a 0.0 position on a SELL/COVER plan is semantically wrong and pollutes conviction-weighted analytics.

**Fix:**
```python
"position_size": 10.0 if final_action == "BUY" else None,
```

---

### DATA-8: `_prefer_newer_artifact_payloads` sets `runtime_storage_superseded: True` on malformed DB timestamps 🟡 MEDIUM
**File:** `src/agency/api/risk.py:318-322`, `src/agency/api/reports.py:161-165`  
**Problem:** When a DB row has an unparseable `generated_at` (e.g., `"UNKNOWN"` string), `_payload_timestamp` returns `datetime.min`. The artifact (with a real timestamp) then always appears newer, incorrectly setting `runtime_storage_superseded=True`.

**Fix:** In `_payload_timestamp`, add a check: if both timestamps resolve to `datetime.min`, treat as equal (do not prefer artifact):
```python
def _prefer_newer_artifact_payloads(
    artifact_payloads: list[dict], db_payloads: list[dict]
) -> tuple[list[dict], bool]:
    artifact_ts = _latest_payload_timestamp(artifact_payloads)
    db_ts = _latest_payload_timestamp(db_payloads)
    # Only prefer artifact if it is genuinely newer (not if both are unknown/min)
    if artifact_ts == datetime.min.replace(tzinfo=UTC) or db_ts == datetime.min.replace(tzinfo=UTC):
        superseded = False  # Cannot determine; do not claim superseded
        return db_payloads if db_payloads else artifact_payloads, superseded
    superseded = artifact_ts > db_ts
    return (artifact_payloads if superseded else db_payloads), superseded
```

---

## PART 4: SCHEDULER / ORCHESTRATION BUGS

---

### SCHED-1: `_register_phase_jobs()` is defined but never called — phase-gated refresh timers are dead code 🟠 HIGH
**File:** `src/agency/runtime/scheduler_runner.py` (~line 147-167)  
**Problem:** `build_scheduler()` only calls `_register_work_queue_jobs(scheduler)`. The `_register_phase_jobs(scheduler)` function, which registers phase-aware interval timers for `prices_daily` (15min pre-market), `news_rss` (30min), `subscription_emails` (10-15min), `sec_form4` (180min), is **never called**. All phase-based scheduling is dead.

**Fix option A** (enable phase jobs):
```python
def build_scheduler(db_url: str | None = None) -> BackgroundScheduler:
    scheduler = _build_apscheduler()
    _register_work_queue_jobs(scheduler)
    _register_phase_jobs(scheduler)  # ADD THIS LINE
    return scheduler
```
**Fix option B** (document as intentional):
```python
def build_scheduler(db_url: str | None = None) -> BackgroundScheduler:
    scheduler = _build_apscheduler()
    _register_work_queue_jobs(scheduler)
    # NOTE: _register_phase_jobs() is intentionally disabled.
    # All scheduling flows through the work queue tick exclusively.
    # Phase jobs are kept as dead code for future use.
    return scheduler
```
**Recommendation:** Verify if the work queue tick alone provides sufficient scheduling coverage. If yes, use Fix B and add a comment. If not, use Fix A.

---

### SCHED-2: `_run_work_queue_tick` is sync but calls `asyncio.get_running_loop()` — may always fall back to file-based queue 🟡 MEDIUM
**File:** `src/agency/runtime/scheduler_runner.py` (~line 189)  
**Problem:** APScheduler's `AsyncIOScheduler` runs sync functions in a thread pool. Inside a thread, `asyncio.get_running_loop()` may raise `RuntimeError`, causing `_load_live_scheduler_work_queue()` to always use the file-based fallback path, never the live async DB path.

**Fix:** Make intent explicit with a flag:
```python
# In _load_live_scheduler_work_queue():
def _load_live_scheduler_work_queue() -> list[dict]:
    # This function is called from a thread (APScheduler), not from the event loop.
    # Always use the synchronous file-based queue path here.
    return scheduler_work_queue_file_context()
```

---

## PART 5: UX / FRONTEND BUGS

---

### UX-1: Signal and Monitor filter chips have no event handlers — dead controls 🟠 HIGH
**File:** `src/agency/templates/_cockpit_panels.html:135-139, 247-251`, `src/agency/static/cockpit.js`  
**Problem:** Filter chips with `data-signal-filter` and `data-monitor-filter` have zero JS event listeners. Clicking does nothing.  
**Also:** The signal `<article>` elements have no `signal-confirmed` / `signal-inferred` CSS classes, so filtering would be inert even after wiring.

**Fix — add to `cockpit.js`** after existing event registration blocks:
```javascript
// Signal evidence filter chips
document.querySelectorAll("[data-signal-filter]").forEach((chip) => {
  chip.addEventListener("click", () => {
    const filter = chip.getAttribute("data-signal-filter");
    document.querySelectorAll("[data-signal-filter]").forEach((c) =>
      c.classList.toggle("active", c === chip)
    );
    document.querySelectorAll(".cockpit-signal-log article").forEach((item) => {
      item.hidden = filter !== "all" && !item.classList.contains(`signal-${filter}`);
    });
  });
});

// Monitor events filter chips
document.querySelectorAll("[data-monitor-filter]").forEach((chip) => {
  chip.addEventListener("click", () => {
    const filter = chip.getAttribute("data-monitor-filter");
    document.querySelectorAll("[data-monitor-filter]").forEach((c) =>
      c.classList.toggle("active", c === chip)
    );
    document.querySelectorAll(".cockpit-monitor-list article").forEach((item) => {
      item.hidden = filter !== "all" && !item.classList.contains(`monitor-${filter}`);
    });
  });
});
```

**Fix — add CSS class to signal articles in `_cockpit_panels.html`:**
```html
<!-- Change from: -->
<article class="cockpit-signal-item">
<!-- To: -->
<article class="cockpit-signal-item signal-{{ signal.status | lower }}">
```

---

### UX-2: `candidate|tojson` in single-quoted HTML attribute — apostrophe breaks JSON parse 🟠 HIGH
**File:** `src/agency/templates/cockpit.html:308, 351`  
**Problem:** `data-cockpit-ticker-payload='{{ candidate|tojson }}'` — any apostrophe in a string value (company name, sector) breaks the attribute. Also, without `|safe`, Jinja2 HTML-escapes double quotes to `&quot;`, which breaks `JSON.parse` in JS.

**Fix:**
```html
<!-- Change from: -->
data-cockpit-ticker-payload='{{ candidate|tojson }}'
<!-- To: -->
data-cockpit-ticker-payload="{{ candidate|tojson|safe }}"
```

---

### UX-3: `data-cockpit-ready="true"` hardcoded in template — defeats JS initialization guard 🟠 HIGH
**File:** `src/agency/templates/cockpit.html:18`  
**Problem:** The attribute is set in HTML before JS runs. If JS fails (e.g., from BUG-4 `meter()` crash), the shell still appears "ready". Any CSS/logic gated on this attribute fires prematurely.

**Fix:** Remove from HTML; let JS set it exclusively:
```html
<!-- Change: -->
<div class="cockpit-shell" data-cockpit-ready="true" data-cockpit-cycle="{{ cycle.id }}">
<!-- To: -->
<div class="cockpit-shell" data-cockpit-cycle="{{ cycle.id }}">
```

---

### UX-4: `window.confirm()` fires as blocking system dialog on page load 🟠 HIGH
**File:** `src/agency/static/cockpit.js:195`  
**Problem:** Fires a native browser modal on page load when localStorage has saved decisions. Operator can accidentally discard all staged planning markers with a single Enter key press.

**Fix:** Replace with in-page non-blocking notice:
```javascript
// Replace window.confirm(...) call with:
function _showRestoreNotice(onRestore, onDiscard) {
  const notice = document.createElement("div");
  notice.className = "cockpit-restore-notice";
  notice.setAttribute("role", "alert");
  notice.innerHTML = `
    <p>Restore local planning markers from your last session?</p>
    <button class="button button-secondary" data-restore>Restore</button>
    <button class="button button-secondary" data-discard>Discard</button>
  `;
  const rail = document.querySelector(".cockpit-phase-rail");
  if (rail) rail.insertAdjacentElement("afterend", notice);
  else document.body.prepend(notice);
  notice.querySelector("[data-restore]").onclick = () => { onRestore(); notice.remove(); };
  notice.querySelector("[data-discard]").onclick = () => { onDiscard(); notice.remove(); };
}
// Then call _showRestoreNotice(restoreCallback, discardCallback) instead of window.confirm
```

---

### UX-5: `cockpit submit` sends `FormData` with duplicate field names for multi-ticker clearance 🟠 HIGH
**File:** `src/agency/static/cockpit.js:160-165`, `src/agency/dashboard.py:304`  
**Problem:** When multiple manifest rows are in the clearance form, `FormData` serializes all hidden inputs (same `name` attributes), potentially only submitting the first ticker's data.

**Fix:** Verify `/cockpit/submit` route handler uses `Form(...)` with `List[str]` type annotations. If not, refactor each clearance row to have its own `<form>` and submit button, or build a JSON payload from all rows:
```javascript
// In cockpit.js submit handler, replace FormData with explicit JSON:
const tickers = [...form.querySelectorAll("[name='ticker']")].map(el => el.value);
const payload = { cycle_id: form.querySelector("[name='cycle_id']").value, tickers };
fetch("/cockpit/submit", {
  method: "POST",
  headers: { "Content-Type": "application/json", "Accept": "application/json" },
  body: JSON.stringify(payload),
});
```

---

### UX-6: Phase rail buttons have active class flicker on load — hardcoded `active` in template 🟡 MEDIUM
**File:** `src/agency/templates/cockpit.html:203`  
**Problem:** The first phase button has `class="cockpit-phase-cell active"` hardcoded. When JS restores a different phase from localStorage, the wrong button briefly appears active.

**Fix:**
```html
<!-- Change: -->
<button type="button" class="cockpit-phase-cell active" data-cockpit-phase-target="candidates">
<!-- To: -->
<button type="button" class="cockpit-phase-cell" data-cockpit-phase-target="candidates">
```

---

### UX-7: Firefox < 121 CSS `:has()` selector not supported — topbar duplicate on cockpit 🔵 LOW
**File:** `src/agency/static/v3-screens.css:185-188`  
**Problem:** `.page-frame:has(.cockpit-shell) .topbar { display: none }` uses CSS Level 4, unsupported in Firefox < 121. Duplicate navigation bars appear.

**Fix — add to `cockpit.js` after shell is confirmed:**
```javascript
// CSS :has() fallback for Firefox < 121
if (document.querySelector(".cockpit-shell")) {
  document.querySelector(".topbar")?.setAttribute("hidden", "");
  document.querySelector(".v3-phase-rail")?.setAttribute("hidden", "");
}
```

---

### UX-8: Brand logo always links to `/cockpit` — reloads and discards state when already on cockpit 🔵 LOW
**File:** `src/agency/templates/base.html:13`  
**Fix:**
```html
<!-- Change href to the operational home: -->
<a href="/command" class="brand-link">
```

---

### UX-9: Review approve/defer/reject forms cause full page reload — no HTMX or JS submission 🟡 MEDIUM
**File:** `src/agency/templates/dashboard.html:245-261`, `src/agency/templates/cockpit.html:311-326`  
**Problem:** Plain `<form method="post">` with no `hx-*` attributes. Every review action reloads the entire data-heavy Command page, losing scroll position.

**Fix (option A — minimal):** Add `<meta name="turbo-method" content="post">` and Turbo frames if Turbo is available. 
**Fix (option B — JS):**
```javascript
// Convert review forms to fetch-based submission:
document.querySelectorAll(".review-action-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const res = await fetch(form.action, { method: "POST", body: new FormData(form) });
    if (res.ok) {
      const card = form.closest(".review-card");
      card?.classList.add("review-submitted");
      // Update card status label without full reload
      const statusEl = card?.querySelector(".review-status");
      if (statusEl) statusEl.textContent = form.dataset.actionLabel || "Submitted";
    }
  });
});
```

---

## PART 6: DATABASE MODEL GAPS

---

### DB-1: `risk_decisions` table missing `final_action` and `final_conviction` queryable columns 🟠 HIGH
**File:** `src/agency/persistence/models.py:59-76`  
**Problem:** These fields exist in `payload` JSON but are not indexed columns. Filtering risk decisions by action or ordering by conviction requires full JSON scan.

**Fix — add to `models.py` `risk_decisions` table definition:**
```python
from sqlalchemy import Column as Col, Float, Index, String, Table

# In risk_decisions table, add after "decision" column:
Col("final_action", String(length=40), nullable=False, server_default="UNKNOWN"),
Col("final_conviction", Float, nullable=False, server_default="0.0"),
```
**Also add index:**
```python
Index("ix_risk_decisions_final_action", risk_decisions.c.final_action),
```
**Update `risk_decision_row_values()` in `src/agency/runtime/risk_decisions.py`:**
```python
def risk_decision_row_values(decision: dict) -> dict:
    return {
        ...
        "final_action": str(decision.get("final_action", "UNKNOWN")),
        "final_conviction": float(decision.get("final_conviction", 0.0)),
    }
```
**Requires a DB migration.**

---

## PART 7: QA / TEST FIXES

---

### TEST-1: Schema contract tests missing for modified schemas 🔴 CRITICAL
**File:** `tests/unit/` (new file: `test_contract_schemas.py`)  
**Problem:** Both `schemas/risk-decision.schema.json` and `schemas/selection-report.schema.json` are modified (git status M) with no tests guarding enum values or required field contracts.

**Fix — create `tests/unit/test_contract_schemas.py`:**
```python
"""Guard tests: verify schema enum values match what the application produces."""
from agency.contracts import load_contract_schema  # adjust import path


def test_risk_decision_schema_version_is_current() -> None:
    schema = load_contract_schema("risk-decision")
    assert schema["properties"]["schema_version"]["const"] == "0.1.0"


def test_selection_report_schema_accepts_both_versions() -> None:
    schema = load_contract_schema("selection-report")
    allowed = set(schema["properties"]["schema_version"]["enum"])
    assert "0.1.0" in allowed
    assert "0.2.0" in allowed


def test_risk_decision_runtime_origin_enum_matches_api_output() -> None:
    schema = load_contract_schema("risk-decision")
    enum_values = set(schema["properties"]["runtime_origin"]["enum"])
    assert enum_values == {"runtime_artifact_fallback", "runtime_artifact_selected"}


def test_policy_update_cannot_accept_broker_submit_field() -> None:
    from agency.api.risk import PolicyUpdate
    fields = set(PolicyUpdate.model_fields.keys())
    assert "broker_submit_enabled" not in fields
    assert "allow_short_trades" not in fields
```

---

### TEST-2: `tests/flow/` is empty — no operator workflow E2E test 🔴 CRITICAL
**File:** `tests/flow/test_operator_review_flow.py` (new file)  
**Problem:** The complete operator workflow has zero automated tests. A regression in any of the 5 handoff points ships undetected.

**Fix — create `tests/flow/test_operator_review_flow.py`:**
```python
"""E2E operator flow: data load → cockpit queue → approve → execution preview ready."""
import pytest
from agency.services.demo_cycle import build_demo_runtime_seed
from agency.services.risk import build_risk_decision, PortfolioPolicy
from agency.services.execution_preview import build_execution_preview


def test_operator_can_review_and_advance_watch_candidate_to_execution() -> None:
    seed = build_demo_runtime_seed()
    watch_reports = [r for r in seed.selection_reports if r["final_action"] in ("WATCH", "BUY")]
    assert watch_reports, "Demo seed must produce at least one WATCH/BUY candidate"

    policy = PortfolioPolicy()
    source_summary = {"source_count": 3, "degraded_source_count": 0, "missing_source_count": 0}
    risk_decisions = [
        build_risk_decision(r, source_summary, generated_at=r["generated_at"])
        for r in watch_reports[:3]  # Test first 3
    ]

    allow_decisions = [rd for rd in risk_decisions if rd.decision == "ALLOW"]
    assert allow_decisions, "At least one WATCH candidate must get ALLOW risk decision"

    previews = [build_execution_preview(rd, policy=policy) for rd in allow_decisions]
    assert any(p.get("preview_state") == "READY" for p in previews), (
        "At least one ALLOW decision must produce a READY execution preview"
    )


def test_cockpit_context_json_serializable() -> None:
    """Regression guard: cockpit context must be fully JSON-serializable."""
    import json
    from tests.unit.test_cockpit_contract import _sample_sources  # reuse fixture
    from agency.views.cockpit import cockpit_context_from_sources

    context = cockpit_context_from_sources(_sample_sources())
    try:
        serialized = json.dumps(context)
    except (TypeError, ValueError) as exc:
        pytest.fail(f"cockpit_context_from_sources() produced non-JSON-serializable data: {exc}")
    assert isinstance(json.loads(serialized), dict)
```

---

### TEST-3: CWD-relative template/CSS paths break non-root test invocation 🟠 HIGH
**Files:** `tests/unit/test_cockpit_candidates.py:14-15`, `tests/unit/test_cockpit_lane_state.py:8-9`

**Current code:**
```python
TEMPLATE = Path("src/agency/templates/cockpit.html")
```

**Fix:**
```python
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # tests/unit/test_*.py -> project root
TEMPLATE = PROJECT_ROOT / "src/agency/templates/cockpit.html"
STYLES = PROJECT_ROOT / "src/agency/static/styles.css"
```

---

### TEST-4: `service_fixtures.selection_report()` not schema-validated — silent fixture drift 🟡 MEDIUM
**File:** `tests/unit/service_fixtures.py`

**Fix — add validated wrapper:**
```python
from agency.contracts import validate_contract

def selection_report_validated(**kwargs) -> dict:
    """Returns a contract-validated selection report. Use this in tests."""
    report = selection_report(**kwargs)
    validate_contract("selection-report", report)
    return report
```

---

### TEST-5: Flaky timeout tests — use assertion on structure not wall clock 🟠 HIGH
**File:** `tests/unit/test_cockpit_routes.py:323-349, 353-408, 492-517`  
**Problem:** Wall-clock budget assertions fail on loaded CI runners.

**Fix:** Replace `assert elapsed < 0.10` with structural assertion:
```python
# Instead of timing:
assert elapsed < 0.10

# Assert on the timeout-path structure:
assert context["portfolio_phase"]["status_label"] in (
    "Portfolio Check Delayed", "Check Skipped"
)
```

---

### TEST-6: Missing tests for new `health.py` helper functions 🟠 HIGH
**File:** `tests/unit/test_fastapi_app.py` (add near existing health unit tests)

**Fix:**
```python
def test_valid_iso_datetime_rejects_sentinel_strings() -> None:
    from agency.api.health import _valid_iso_datetime
    assert _valid_iso_datetime("not checked") is None
    assert _valid_iso_datetime("not recorded") is None
    assert _valid_iso_datetime(None) is None
    assert _valid_iso_datetime("garbage-string") is None
    assert _valid_iso_datetime("2026-05-22T14:00:00+00:00") == "2026-05-22T14:00:00+00:00"


def test_latest_iso_datetime_returns_most_recent() -> None:
    from agency.api.health import _latest_iso_datetime
    assert _latest_iso_datetime(None, "2026-05-22T14:00:00+00:00") == "2026-05-22T14:00:00+00:00"
    assert _latest_iso_datetime("2026-05-21T00:00:00+00:00", "2026-05-22T00:00:00+00:00") == "2026-05-22T00:00:00+00:00"
    assert _latest_iso_datetime("2026-05-23T00:00:00+00:00", "2026-05-22T00:00:00+00:00") == "2026-05-23T00:00:00+00:00"
```

---

### TEST-7: Missing negative test for corrupt manifest graceful handling 🟡 MEDIUM
**File:** `tests/unit/test_data_load_status.py` (add at end)

**Fix:**
```python
def test_data_load_status_handles_corrupt_manifest_gracefully(tmp_path, monkeypatch):
    paths = _fixtures(tmp_path, monkeypatch)
    (paths["manifest_root"] / "prices_daily.json").write_text("{invalid json}", encoding="utf-8")
    status = load_data_load_status(config_path=paths["config"])
    assert status.get("state") in {"blocked", "attention", "error", "missing"}
    # Must not raise; must report degraded state
```

---

## PART 8: MINOR FIXES (LOW PRIORITY)

---

### MINOR-1: Duplicate `_humanize_seconds_in_text` / `_duration_label` in `command.py` 🟡 MEDIUM
**File:** `src/agency/views/command.py:1382-1410`  
**Problem:** Exact duplicates of functions already in `_shared.py`. Future bug fixes to `_shared.py` won't apply to `command.py`.  
**Fix:** Remove the duplicate definitions from `command.py` and add to the existing import from `_shared.py`.

---

### MINOR-2: Background cache done-callback can overwrite newer cache entry 🔵 LOW
**File:** `src/agency/views/cockpit.py:134-146`  
**Fix:** Add timestamp guard before writing to cache:
```python
existing = _cockpit_context_cache.get(key)
new_ts = monotonic()
if existing is None or existing[0] < new_ts:
    _cockpit_context_cache[key] = (new_ts, deepcopy(context))
```

---

### MINOR-3: `/universe` route has no nav link 🔵 LOW
**File:** `src/agency/templates/base.html`  
**Problem:** `dashboard.py:1617` registers `/universe` but it's not linked from any navigation.  
**Fix:** Either add a nav link or add `# NOTE: /universe is an internal/debug-only route` comment to `dashboard.py:1617`.

---

### MINOR-4: `execution_preview` anchor fragment `#focused-preview-{{ row.ticker }}` points to non-existent element 🔵 LOW
**File:** `src/agency/templates/execution_preview.html:23`  
**Fix:** Either add `id="focused-preview-{{ ticker }}"` to the relevant heading in `candidate_detail.html`, or remove the fragment.

---

### MINOR-5: Heartbeat polling runs on all pages, including non-trading pages 🔵 LOW
**File:** `src/agency/templates/base.html:147`, `src/agency/static/data-refresh-progress.js`  
**Fix:** Add `data-enable-heartbeat` attribute only on cockpit/command/execution-preview pages, and add check in heartbeat IIFE:
```javascript
if (!document.querySelector("[data-enable-heartbeat]")) return;
```

---

## IMPLEMENTATION PRIORITY GUIDE FOR CODEX

### Sprint 1 — First 30 minutes (blockers before server start)
1. **OPS-1** — Update config end date (`research/config/live-refresh.local.json`)
2. **OPS-2** — Enable scheduler in `.env`
3. **OPS-3** — Start Postgres

### Sprint 2 — Crash bug fixes (code changes, 1-2 hours)
4. **BUG-1** — `_is_actionable_candidate` KeyError (`_shared.py:495`)
5. **BUG-2** — `command_summary` blocked count KeyError (`command.py:283`)
6. **BUG-3** — `STATE_LABELS` bare dict lookup (`lane_state.py:451`)
7. **BUG-4** — `meter()` IIFE scope crash (`data-refresh-progress.js`)
8. **BUG-5** — `source_status_rows` KeyError (`command.py:450`)
9. **BUG-6** — `_source_is_degraded` KeyError (`_shared.py:566`)
10. **BUG-7** — `_human_review_summary` KeyError (`_shared.py:556`)
11. **BUG-8** — `_list_field` / `_mapping_field` hard errors (`_shared.py:697`)

### Sprint 3 — Data integrity (1 hour)
12. **DATA-1** — `_source_for_raw_lane` wrong mapping (`lane_state.py:597`)
13. **DATA-2** — `DETERMINISTIC_ACTION` lifecycle status inverted (`deterministic_selection.py:58`)
14. **DATA-4** — `missing_source_count` float/int BLOCK bypass (`risk.py:499`)
15. **DATA-5** — `broker_submit_enabled` explicit default (`risk.py:128`)

### Sprint 4 — UX fixes (1 hour)
16. **UX-1** — Wire signal/monitor filter chips
17. **UX-2** — `candidate|tojson|safe` single-quote fix
18. **UX-3** — Remove hardcoded `data-cockpit-ready="true"`
19. **UX-4** — Replace `window.confirm()` with in-page notice
20. **SCHED-1** — Resolve `_register_phase_jobs()` (enable or document as dead)

### Sprint 5 — Tests (remaining time)
21. **TEST-1** — Schema contract guard tests (new file)
22. **TEST-2** — E2E operator flow test (new file)
23. **TEST-3** — Fix CWD-relative template paths
24. **TEST-5** — Fix flaky timeout tests

---

## APPENDIX: FINDINGS BY FILE

| File | Finding IDs |
|------|------------|
| `research/config/live-refresh.local.json` | OPS-1 |
| `.env` / `.env.example` | OPS-2 |
| `src/agency/app.py` | OPS-2 (startup warning) |
| `src/agency/views/_shared.py` | BUG-1, BUG-6, BUG-7, BUG-8 |
| `src/agency/views/command.py` | BUG-2, BUG-5, MINOR-1 |
| `src/agency/runtime/lane_state.py` | BUG-3, DATA-1 |
| `src/agency/static/data-refresh-progress.js` | BUG-4 |
| `src/agency/services/deterministic_selection.py` | DATA-2, DATA-3 |
| `src/agency/services/final_selection.py` | DATA-3 |
| `src/agency/services/paper_trade_promotion.py` | DATA-3 |
| `src/agency/services/demo_cycle.py` | DATA-7 |
| `src/agency/services/risk.py` | DATA-4, DATA-5 |
| `src/agency/api/risk.py` | DATA-8 |
| `src/agency/api/reports.py` | DATA-6, DATA-8 |
| `src/agency/persistence/models.py` | DB-1 |
| `src/agency/runtime/risk_decisions.py` | DB-1 |
| `src/agency/runtime/scheduler_runner.py` | SCHED-1, SCHED-2 |
| `src/agency/views/cockpit.py` | MINOR-2 |
| `src/agency/static/cockpit.js` | UX-1, UX-4, UX-5, UX-7 |
| `src/agency/templates/cockpit.html` | UX-2, UX-3, UX-6 |
| `src/agency/templates/_cockpit_panels.html` | UX-1 |
| `src/agency/templates/dashboard.html` | UX-9 |
| `src/agency/templates/base.html` | UX-7, UX-8, MINOR-5 |
| `src/agency/static/v3-screens.css` | UX-7 |
| `src/agency/templates/execution_preview.html` | MINOR-4 |
| `tests/unit/test_cockpit_candidates.py` | TEST-3 |
| `tests/unit/test_cockpit_lane_state.py` | TEST-3 |
| `tests/unit/test_cockpit_routes.py` | TEST-5 |
| `tests/unit/test_fastapi_app.py` | TEST-6 |
| `tests/unit/test_data_load_status.py` | TEST-7 |
| `tests/unit/service_fixtures.py` | TEST-4 |
| `tests/flow/test_operator_review_flow.py` *(new)* | TEST-2 |
| `tests/unit/test_contract_schemas.py` *(new)* | TEST-1 |
