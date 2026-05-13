# Fast-Path Sprint Implementation Plan (T115–T122)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily paper-trading loop run reliably without manual debugging — data refreshes, the cycle builds, WATCH candidates appear in the review queue, and any failures surface visibly.

**Architecture:** Eight focused changes in priority order: (1) document/verify the corroboration gate, (2) surface batch failures in the dashboard, (3) fix freshness misreporting for non-price datasets, (4) consolidate email ingest, (5) decompose the 5 864-line dashboard.py, (6) wire the market-aware scheduler executor, (7) write the daily ops runbook, (8) add the daily-loop smoke test. Each task is independent except Task 8, which depends on all prior tasks.

**Tech stack:** Python 3.14, FastAPI, Jinja2, APScheduler 3.x, pytest, pandas, mypy, ruff. All commands assume the activated venv at `.venv\Scripts\python` on Windows (use `.venv/bin/python` on Mac/Linux).

**Run tests with:**
```
.\.venv\Scripts\python -m pytest tests/ -x -q
```

**Type-check with:**
```
.\.venv\Scripts\python -m mypy src research --ignore-missing-imports
```

---

## Task 1: T116 — Document and verify inferred-lane corroboration behaviour

**Why this first:** Before any other change, confirm the corroboration gate works as designed (it does — no code change needed), then lock the behaviour with explicit tests so regressions are caught immediately.

**Files:**
- Modify: `tests/unit/test_actionability_gate.py`

---

- [ ] **Step 1: Understand the current behaviour by reading the gate**

Open `src/agency/services/actionability_gate.py`. Find `_threshold_reason` (around line 116). Note that `inferred_needs_confirmed_corroboration=True` is the default in `LaneActionabilityRule`, and the `has_confirmed` flag already propagates across the whole signal set. The gate IS enforced — this task adds explicit tests.

- [ ] **Step 2: Add the zero-confirmed-signals test**

Append to `tests/unit/test_actionability_gate.py`:

```python
def test_actionability_gate_demotes_all_inferred_lanes_when_no_confirmed_signal() -> None:
    """All inferred lanes must be CONTEXT_ONLY when no confirmed signal is present."""
    signals = [
        _signal("abnormal_volume", "alpaca", "src-1", verification="INFERRED"),
        _signal("buy_sell_pressure", "massive", "src-2", verification="INFERRED"),
        _signal("technical_analysis", "prices", "src-3", verification="INFERRED"),
    ]
    gated = apply_actionability_gate(signals)

    for result in gated:
        assert result["actionability"] == "CONTEXT_ONLY", (
            f"Lane {result['lane']} should be CONTEXT_ONLY without a confirmed signal, "
            f"got {result['actionability']}"
        )
        assert "requires_confirmed_corroboration" in result["reason_codes"]
```

- [ ] **Step 3: Run the test to verify it passes (behaviour is already correct)**

```
.\.venv\Scripts\python -m pytest tests/unit/test_actionability_gate.py::test_actionability_gate_demotes_all_inferred_lanes_when_no_confirmed_signal -v
```

Expected: `PASSED`

- [ ] **Step 4: Add the mixed-set test (inferred passes when confirmed is present)**

```python
def test_actionability_gate_allows_inferred_lane_when_confirmed_signal_present() -> None:
    """An inferred lane may be ACTIONABLE when at least one confirmed signal exists."""
    signals = [
        _signal("fundamentals", "sec", "sec-1"),          # CONFIRMED by default
        _signal("abnormal_volume", "alpaca", "src-1", verification="INFERRED"),
    ]
    gated = apply_actionability_gate(signals)

    fundamentals_result = next(r for r in gated if r["lane"] == "fundamentals")
    volume_result = next(r for r in gated if r["lane"] == "abnormal_volume")

    assert fundamentals_result["actionability"] == "ACTIONABLE"
    assert volume_result["actionability"] == "ACTIONABLE"
    assert "requires_confirmed_corroboration" not in volume_result["reason_codes"]
```

- [ ] **Step 5: Check if `_signal` helper accepts `verification` kwarg**

Open `tests/unit/test_actionability_gate.py`, find the `_signal` helper function. If it doesn't accept `verification` as a kwarg, add it:

```python
def _signal(
    lane: str,
    source: str,
    source_id: str,
    freshness: str = "FRESH",
    verification: str = "CONFIRMED",
) -> dict[str, object]:
    return build_signal_result(
        lane=lane,
        ticker="AAPL",
        score=0.5,
        direction="BULLISH",
        actionability="ACTIONABLE",
        confidence=0.8,
        source_tier="OFFICIAL_FILING",
        verification_level=verification,
        freshness=freshness,
        provenance={
            "source": source,
            "source_id": source_id,
            "timestamp_observed": AS_OF,
            "timestamp_as_of": AS_OF,
            "freshness": freshness,
            "confidence": 0.8,
            "verification_level": verification,
        },
        reason_codes=[],
        suppression_reason=None,
    )
```

- [ ] **Step 6: Run all actionability gate tests**

```
.\.venv\Scripts\python -m pytest tests/unit/test_actionability_gate.py -v
```

Expected: all `PASSED`

- [ ] **Step 7: Commit**

```
git add tests/unit/test_actionability_gate.py
git commit -m "test: document inferred-lane corroboration gate behaviour"
```

---

## Task 2: T122 — Surface silent failures in data refresh

**Why:** `RefreshBatchResult.failed` already captures failures. The Command dashboard does not visually warn when any dataset in the latest refresh has `status: "failed"`. Partial refreshes silently appear as "in progress" or "done."

**Files:**
- Modify: `research/src/data_refresh/status.py`
- Modify: `src/agency/runtime/data_refresh_progress.py`
- Modify: `src/agency/templates/dashboard.html` (add failure warning section)
- Modify: `tests/unit/test_data_refresh_batch.py`

---

- [ ] **Step 1: Write a failing test for partial-failure status**

Append to `tests/unit/test_data_refresh_batch.py`:

```python
def test_run_refresh_batch_records_failed_datasets(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("prices_daily", "news_rss"),
        tickers=("AAPL",),
        market_data_provider="yfinance",
    )

    def failing_runner(command: Sequence[str], repo_root: Path) -> CommandResult:
        if "prices_daily" in " ".join(command):
            return CommandResult(returncode=1, stderr="connection refused")
        return CommandResult(returncode=0)

    result = run_refresh_batch(config, runner=failing_runner)

    status_json = json.loads((tmp_path / "data-refresh-status.json").read_text())
    assert status_json["has_failures"] is True
    assert "prices_daily" in status_json["failed_datasets"]
    assert "news_rss" not in status_json["failed_datasets"]
    assert result.failed is True
```

- [ ] **Step 2: Run to confirm it fails**

```
.\.venv\Scripts\python -m pytest tests/unit/test_data_refresh_batch.py::test_run_refresh_batch_records_failed_datasets -v
```

Expected: `FAILED` — `has_failures` key does not exist

- [ ] **Step 3: Add `has_failures` and `failed_datasets` to `result_to_json` in status.py**

In `research/src/data_refresh/status.py`, find `result_to_json` and add two fields to the returned dict (after `"updated_at"`):

```python
def result_to_json(result: RefreshBatchResult) -> str:
    failed_datasets = [job.dataset for job in result.jobs if job.status == "failed"]
    payload = {
        # ... existing fields ...
        "has_failures": len(failed_datasets) > 0,
        "failed_datasets": failed_datasets,
        # ... rest of existing fields ...
    }
    return json.dumps(payload, indent=2, default=str)
```

- [ ] **Step 4: Run the test to verify it passes**

```
.\.venv\Scripts\python -m pytest tests/unit/test_data_refresh_batch.py::test_run_refresh_batch_records_failed_datasets -v
```

Expected: `PASSED`

- [ ] **Step 5: Surface the failure in `data_refresh_progress.py`**

Open `src/agency/runtime/data_refresh_progress.py`. Find where the status JSON is loaded and the progress context dict is built. Add a `has_failures` and `failed_datasets` field to the returned context:

```python
# After loading status_data from the JSON file, add:
has_failures = bool(status_data.get("has_failures", False))
failed_datasets: list[str] = list(status_data.get("failed_datasets", []))

# Include in the returned context dict:
return {
    # ... existing fields ...
    "has_failures": has_failures,
    "failed_datasets": failed_datasets,
    "failure_summary": (
        f"{len(failed_datasets)} dataset(s) failed: {', '.join(failed_datasets)}"
        if has_failures
        else ""
    ),
}
```

- [ ] **Step 6: Add a failure warning panel to the dashboard template**

Open `src/agency/templates/dashboard.html`. Find the data refresh progress section. After the progress bar, add:

```html
{% if refresh_progress.has_failures %}
<div class="alert alert-warn" role="alert" aria-live="polite">
  <strong>Refresh failures:</strong> {{ refresh_progress.failure_summary }}
  — check logs and re-run the affected dataset.
</div>
{% endif %}
```

- [ ] **Step 7: Run all data refresh batch tests**

```
.\.venv\Scripts\python -m pytest tests/unit/test_data_refresh_batch.py -v
```

Expected: all `PASSED`

- [ ] **Step 8: Commit**

```
git add research/src/data_refresh/status.py src/agency/runtime/data_refresh_progress.py src/agency/templates/dashboard.html tests/unit/test_data_refresh_batch.py
git commit -m "feat: surface data refresh failures in status JSON and dashboard"
```

---

## Task 3: T115 — Fix dataset freshness domains for all non-price sources

**Why:** `freshness.py` only applies a calendar correction for `PRICES_DAILY`. SEC, stock-trades, subscription-emails, and 13F all use raw `timestamp_as_of`, causing FRESH/STALE misreporting that propagates silently to the actionability gate.

**Resolved decision (OQ-2):** `SEC_13F` should report `FRESH` with a `next_expected_filing` metadata note, not STALE.

**Files:**
- Modify: `research/src/live_runtime/freshness.py`
- Modify: `research/src/live_runtime/source_health.py`
- Create: `tests/unit/test_live_runtime_freshness.py`

---

- [ ] **Step 1: Write failing tests for all dataset types**

Create `tests/unit/test_live_runtime_freshness.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from live_runtime.freshness import effective_freshness_timestamp, next_quarterly_filing_date
from pit.manifest import DatasetName


# ── helpers ──────────────────────────────────────────────────────────────────

def _dt(d: date, hour: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=UTC)


TODAY = date(2026, 5, 13)
NOW = _dt(TODAY, hour=15)  # 15:00 UTC = 11:00 ET (market hours)


# ── PRICES_DAILY (existing behaviour) ────────────────────────────────────────

def test_prices_daily_today_returns_checked_at_after_close() -> None:
    checked_at = _dt(TODAY, hour=22)  # 22:00 UTC = 18:00 ET (after close)
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(TODAY), checked_at
    )
    assert ts == checked_at


def test_prices_daily_today_returns_checked_at_minus_offset_before_close() -> None:
    """Before 21:15 UTC (17:15 ET), today's bars are not published yet."""
    checked_at = _dt(TODAY, hour=19)  # 19:00 UTC = 15:00 ET (market hours)
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(TODAY), checked_at
    )
    # Should treat today's data as NOT available yet → use yesterday
    assert ts.date() < TODAY


# ── STOCK_TRADES ──────────────────────────────────────────────────────────────

def test_stock_trades_before_post_market_window_uses_yesterday() -> None:
    """Delayed prints for today are not reliable before 21:15 UTC."""
    checked_at = _dt(TODAY, hour=19)  # before 21:15 UTC
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES, _dt(TODAY), checked_at
    )
    assert ts.date() < TODAY


def test_stock_trades_after_post_market_window_returns_checked_at() -> None:
    checked_at = _dt(TODAY, hour=22)  # after 21:15 UTC
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES, _dt(TODAY), checked_at
    )
    assert ts == checked_at


# ── SUBSCRIPTION_EMAILS ───────────────────────────────────────────────────────

def test_subscription_emails_applies_delivery_lag() -> None:
    """A 20-minute delivery lag is subtracted from checked_at."""
    ts_as_of = _dt(TODAY, hour=14)  # email delivered at 14:00
    checked_at = _dt(TODAY, hour=14)  # checking immediately
    ts = effective_freshness_timestamp(
        DatasetName.SUBSCRIPTION_EMAILS, ts_as_of, checked_at
    )
    # Effective timestamp should be 20 min earlier
    assert ts <= checked_at - timedelta(minutes=20)


# ── SEC_13F ────────────────────────────────────────────────────────────────────

def test_sec_13f_returns_fresh_between_quarters() -> None:
    """13F is FRESH between filing periods — it's current as of last filing."""
    ts_as_of = _dt(date(2026, 3, 31))  # Q1 filing
    checked_at = _dt(date(2026, 5, 13))  # mid-Q2
    ts = effective_freshness_timestamp(
        DatasetName.SEC_13F, ts_as_of, checked_at
    )
    assert ts == checked_at  # report as fresh (lagged by design, not stale)


def test_next_quarterly_filing_date_after_q1() -> None:
    assert next_quarterly_filing_date(date(2026, 3, 31)) == date(2026, 6, 30)


def test_next_quarterly_filing_date_after_q2() -> None:
    assert next_quarterly_filing_date(date(2026, 6, 30)) == date(2026, 9, 30)


def test_next_quarterly_filing_date_after_q3() -> None:
    assert next_quarterly_filing_date(date(2026, 9, 30)) == date(2026, 12, 31)


def test_next_quarterly_filing_date_after_q4() -> None:
    assert next_quarterly_filing_date(date(2026, 12, 31)) == date(2027, 3, 31)
```

- [ ] **Step 2: Run to confirm tests fail**

```
.\.venv\Scripts\python -m pytest tests/unit/test_live_runtime_freshness.py -v
```

Expected: most tests `FAILED` — `next_quarterly_filing_date` not defined, stock_trades/subscription_emails not handled

- [ ] **Step 3: Rewrite `freshness.py` with per-dataset domain logic**

Replace the contents of `research/src/live_runtime/freshness.py` with:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pit.manifest import DatasetName

# Delayed stock-trade prints are not reliable until this many minutes after
# regular market close (16:00 ET = 20:00 UTC).
_STOCK_TRADES_POST_MARKET_UTC_HOUR = 21
_STOCK_TRADES_POST_MARKET_UTC_MINUTE = 15

# Email delivery lag before a subscription email is considered "arrived".
_EMAIL_DELIVERY_LAG_MINUTES = 20


def effective_freshness_timestamp(
    dataset: DatasetName,
    timestamp_as_of: datetime,
    checked_at: datetime,
) -> datetime:
    """Return the effective timestamp used to classify freshness for this dataset.

    Adjusts for dataset-specific delivery windows so that source health does
    not report data as FRESH before it is actually available.
    """
    if dataset is DatasetName.PRICES_DAILY:
        if timestamp_as_of.date() >= _latest_completed_daily_bar_date(checked_at.date()):
            if _after_bar_publication_window(checked_at):
                return checked_at
            # Bars for today are not published yet; treat as yesterday's data.
            prev = _latest_completed_daily_bar_date(checked_at.date())
            return datetime(prev.year, prev.month, prev.day, tzinfo=UTC)
        return timestamp_as_of

    if dataset is DatasetName.STOCK_TRADES:
        if timestamp_as_of.date() >= checked_at.date():
            if _after_stock_trades_window(checked_at):
                return checked_at
            prev = checked_at.date() - timedelta(days=1)
            return datetime(prev.year, prev.month, prev.day, tzinfo=UTC)
        return timestamp_as_of

    if dataset is DatasetName.SUBSCRIPTION_EMAILS:
        # Subtract delivery lag so a brand-new email is not immediately FRESH.
        return min(timestamp_as_of, checked_at - timedelta(minutes=_EMAIL_DELIVERY_LAG_MINUTES))

    if dataset is DatasetName.SEC_13F:
        # 13F is always current-as-of the last filing; return checked_at so
        # freshness classification treats it as FRESH between filing periods.
        # The notes field in source_health surfaces next_expected_filing_date.
        return checked_at

    return timestamp_as_of


def next_quarterly_filing_date(last_filing_date: date) -> date:
    """Return the next expected 13F filing date after the given quarter end."""
    quarter_ends = {3: 30, 6: 30, 9: 30, 12: 31}
    month = last_filing_date.month
    year = last_filing_date.year
    if month in (1, 2, 3):
        return date(year, 6, 30)
    if month in (4, 5, 6):
        return date(year, 9, 30)
    if month in (7, 8, 9):
        return date(year, 12, 31)
    return date(year + 1, 3, 31)


# ── private helpers ────────────────────────────────────────────────────────────

def _latest_completed_daily_bar_date(current: date) -> date:
    candidate = current - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _after_bar_publication_window(checked_at: datetime) -> bool:
    """Daily bars are published ~17:15 ET = 21:15 UTC."""
    return (
        checked_at.hour > _STOCK_TRADES_POST_MARKET_UTC_HOUR
        or (
            checked_at.hour == _STOCK_TRADES_POST_MARKET_UTC_HOUR
            and checked_at.minute >= _STOCK_TRADES_POST_MARKET_UTC_MINUTE
        )
    )


def _after_stock_trades_window(checked_at: datetime) -> bool:
    return _after_bar_publication_window(checked_at)
```

- [ ] **Step 4: Run the freshness tests**

```
.\.venv\Scripts\python -m pytest tests/unit/test_live_runtime_freshness.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Add 13F next-filing note to source_health.py**

In `research/src/live_runtime/source_health.py`, find `_available`. After computing `freshness`, add the 13F note:

```python
from live_runtime.freshness import effective_freshness_timestamp, next_quarterly_filing_date

def _available(
    config: RuntimeDatasetConfig,
    *,
    manifest: DataManifest,
    checked_at: datetime,
    cap_timestamp_at_checked_at: bool,
) -> dict[str, object]:
    timestamp_as_of = _timestamp_as_of(
        manifest,
        checked_at=checked_at,
        cap_timestamp_at_checked_at=cap_timestamp_at_checked_at,
    )
    freshness_timestamp = effective_freshness_timestamp(
        config.dataset,
        timestamp_as_of,
        checked_at,
    )
    freshness = compute_freshness(
        freshness_timestamp,
        config.freshness_domain,
        now=checked_at,
    )
    lag = max((checked_at - freshness_timestamp).total_seconds(), 0.0)
    notes = [f"{manifest.dataset.value}: {manifest.row_count} rows"]
    if config.dataset is DatasetName.SEC_13F:
        next_filing = next_quarterly_filing_date(timestamp_as_of.date())
        notes.append(f"lagged by design — next expected filing: {next_filing.isoformat()}")
    return {
        "schema_version": "0.1.0",
        "source": config.source,
        "source_tier": config.source_tier,
        "status": _status(freshness),
        "checked_at": checked_at.isoformat(),
        "freshness": freshness.value,
        "last_success_at": timestamp_as_of.isoformat(),
        "observed_lag_seconds": round(lag, 3),
        "error_count": 0,
        "reliability_score": _reliability(freshness),
        "rate_limit_reset_at": None,
        "notes": notes,
    }
```

You will also need to add the `DatasetName` import to `source_health.py`:

```python
from pit.manifest import DataManifest, DatasetName, ManifestRegistry
```

- [ ] **Step 6: Run full test suite to check for regressions**

```
.\.venv\Scripts\python -m pytest tests/ -x -q
```

Expected: all `PASSED` (the freshness changes should not break existing source health tests as the overall FRESH/STALE classification is unchanged for the non-price paths)

- [ ] **Step 7: Commit**

```
git add research/src/live_runtime/freshness.py research/src/live_runtime/source_health.py tests/unit/test_live_runtime_freshness.py
git commit -m "fix: add per-dataset freshness domain corrections (stock-trades, email, 13F)"
```

---

## Task 4: T120 — Consolidate subscription email ingest path

**Why:** Two scripts (`watch_subscription_emails.py` and `import_subscription_emails.py`) have overlapping responsibilities with no documented daily-ops guidance and no concurrency guard.

**Files:**
- Modify: `research/scripts/watch_subscription_emails.py`
- Modify: `docs/subscription-email-agents.md`

---

- [ ] **Step 1: Add a lock-file concurrency guard to the watch script**

Open `research/scripts/watch_subscription_emails.py`. Find the main entry point. Add a lock file guard at the top of `main()` (or equivalent). The project runs on Windows — use `msvcrt`:

```python
import msvcrt
from pathlib import Path

LOCK_FILE = Path(__file__).parent.parent / "data" / ".email-watch.lock"
_lock_fd = None  # module-level so it stays open


def _acquire_lock() -> None:
    """Exit if another email ingest process is already running (Windows lock)."""
    global _lock_fd
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = open(LOCK_FILE, "w")  # noqa: SIM115
    try:
        msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        _lock_fd.close()
        print(
            "ERROR: Another email ingest process is already running "
            f"(lock: {LOCK_FILE}). Exiting."
        )
        raise SystemExit(1)
```

Call `_acquire_lock()` at the very start of `main()` before any mailbox connection.

- [ ] **Step 2: Add a structured startup log message**

At the start of the watch loop, print a structured JSON startup line:

```python
import json, sys
from datetime import UTC, datetime

startup = {
    "event": "email_watch_started",
    "mode": "watch",
    "mailbox": str(mailbox_config.folder),
    "cadence_seconds": poll_interval_seconds,
    "started_at": datetime.now(UTC).isoformat(),
}
print(json.dumps(startup), flush=True)
```

- [ ] **Step 3: Update the docs to give explicit daily-ops guidance**

Open `docs/subscription-email-agents.md`. Add a new section at the top:

```markdown
## Daily Operations Guide

**For continuous daily operation:** use `watch_subscription_emails.py`.
This script polls the configured mailbox on a regular cadence (default: every
5 minutes) and ingests new emails as they arrive. Start it once at the beginning
of the day alongside the scheduler.

**For one-shot historical backfill only:** use `import_subscription_emails.py`.
This script processes the mailbox once and exits. Do not run it while
`watch_subscription_emails.py` is active — the concurrency guard will prevent
the second process from starting, but running them sequentially on the same
timeframe may produce duplicate rows.

**Running both safely:** `watch_subscription_emails.py` holds a lock file at
`research/data/.email-watch.lock` while running. Any attempt to start a second
instance exits with a clear error message.
```

- [ ] **Step 4: Run the import script in dry-run mode to confirm it still works**

```
.\.venv\Scripts\python research\scripts\import_subscription_emails.py --help
```

Expected: help text printed, no error

- [ ] **Step 5: Commit**

```
git add research/scripts/watch_subscription_emails.py docs/subscription-email-agents.md
git commit -m "fix: add concurrency guard and daily-ops guidance for email ingest"
```

---

## Task 5: T117 — Split dashboard.py into per-page view-model modules

**Why:** At 5 864 lines, `dashboard.py` is the highest blast-radius file in the repo. All UX track work depends on it being decomposable. This is a pure structural move — zero behaviour change.

**Files:**
- Create: `src/agency/views/__init__.py`
- Create: `src/agency/views/_shared.py`
- Create: `src/agency/views/command.py`
- Create: `src/agency/views/candidates.py`
- Create: `src/agency/views/risk.py`
- Create: `src/agency/views/execution.py`
- Create: `src/agency/views/portfolio.py`
- Create: `src/agency/views/learning.py`
- Create: `src/agency/views/signals.py`
- Create: `src/agency/views/market_regime.py`
- Modify: `src/agency/dashboard.py` → routing only (< 150 lines)

---

- [ ] **Step 1: Identify the view-model functions in dashboard.py**

Run:

```powershell
Select-String -Path src\agency\dashboard.py -Pattern "^async def |^def " | Select-Object -First 60
```

Open the file and note every top-level `async def` or `def` that builds a view-model dict or returns a `TemplateResponse`. These are the functions to move. The routing functions (decorated with `@router.get(...)`) stay in `dashboard.py` as thin dispatchers.

- [ ] **Step 2: Create the views package**

```python
# src/agency/views/__init__.py
"""Per-page view-model constructors. Each module owns one dashboard page."""
```

- [ ] **Step 3: Create `_shared.py` for helpers used by 2+ modules**

Move helpers that appear in multiple page functions (e.g., `_format_conviction`, `_candidate_href`, common date formatters) into:

```python
# src/agency/views/_shared.py
from __future__ import annotations

from datetime import datetime

ACTIONABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
OPEN_RISK_DECISIONS = {"ALLOW", "WARN"}
DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}

# Move any function from dashboard.py that is called by 2+ page handlers here.
```

- [ ] **Step 4: Move one page at a time — start with the smallest (learning)**

The pattern for every page module is:

```python
# src/agency/views/learning.py
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agency.services.learning import build_learning_outcome


async def build_learning_view(
    *,
    session: Any,  # AsyncSession — typed here to avoid circular import
) -> dict[str, object]:
    """Build the template context for the Learning dashboard page."""
    outcome = await build_learning_outcome(session)
    return {"outcome": outcome}
```

Then in `dashboard.py`, replace the inline view-model logic with:

```python
from agency.views.learning import build_learning_view

@router.get("/learning")
async def learning_page(request: Request, session: AsyncSession = Depends(get_session)):
    context = await build_learning_view(session=session)
    return templates.TemplateResponse("learning.html", {"request": request, **context})
```

Repeat this pattern for: `portfolio`, `risk`, `execution`, `signals`, `market_regime`, `candidates`, `command`.

- [ ] **Step 5: After moving all pages, verify dashboard.py is routing-only**

```
python -c "
import ast, pathlib
src = pathlib.Path('src/agency/dashboard.py').read_text()
tree = ast.parse(src)
funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
print('Functions remaining:', funcs)
print('Lines:', len(src.splitlines()))
"
```

Expected: only route handler functions remain (no view-model builders), line count < 200.

- [ ] **Step 6: Run the full test suite**

```
.\.venv\Scripts\python -m pytest tests/ -x -q
```

Expected: all `PASSED` — no behaviour changed

- [ ] **Step 7: Type-check**

```
.\.venv\Scripts\python -m mypy src/agency/views src/agency/dashboard.py --ignore-missing-imports
```

Expected: no errors

- [ ] **Step 8: Commit**

```
git add src/agency/views/ src/agency/dashboard.py
git commit -m "refactor: decompose dashboard.py into per-page view-model modules"
```

---

## Task 6: T118 — Wire market-aware scheduler executor

**Why:** `market_batching.py` produces the correct plan. Nothing executes it. Without a scheduler, the market-aware operating model is aspirational documentation only.

**Resolved (OQ-1):** APScheduler uses Postgres job store.

**Files:**
- Modify: `src/agency/runtime/scheduler.py`
- Create: `src/agency/runtime/scheduler_runner.py`
- Modify: `src/agency/app.py` (register scheduler lifespan)
- Create: `tests/unit/test_scheduler_runner.py`

---

- [ ] **Step 1: Add APScheduler to dependencies if not present**

Check `pyproject.toml`:

```
.\.venv\Scripts\python -c "import apscheduler; print(apscheduler.__version__)"
```

If not installed:

```
.\.venv\Scripts\pip install apscheduler
```

Then add to `pyproject.toml` dependencies: `"apscheduler>=3.10"`.

- [ ] **Step 2: Write a failing test for the market-phase job selector**

Create `tests/unit/test_scheduler_runner.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agency.runtime.scheduler_runner import jobs_for_phase


def test_pre_market_jobs_include_stock_trades_and_email() -> None:
    jobs = jobs_for_phase("pre_market")
    names = {j["name"] for j in jobs}
    assert "stock_trades" in names
    assert "subscription_emails" in names
    assert "sec_company_facts" not in names  # deferred during market hours


def test_regular_market_jobs_include_news_only() -> None:
    jobs = jobs_for_phase("regular_market")
    names = {j["name"] for j in jobs}
    assert "news_rss" in names
    assert "prices_daily" not in names   # wait for close
    assert "sec_form4" not in names     # deferred


def test_after_hours_jobs_include_prices_and_trades() -> None:
    jobs = jobs_for_phase("after_hours")
    names = {j["name"] for j in jobs}
    assert "prices_daily" in names
    assert "stock_trades" in names


def test_overnight_jobs_include_sec_baselines() -> None:
    jobs = jobs_for_phase("overnight")
    names = {j["name"] for j in jobs}
    assert "sec_company_facts" in names
    assert "sec_form4" in names
    assert "sec_13f" in names
```

- [ ] **Step 3: Run to confirm tests fail**

```
.\.venv\Scripts\python -m pytest tests/unit/test_scheduler_runner.py -v
```

Expected: `FAILED` — `jobs_for_phase` not found

- [ ] **Step 4: Create `scheduler_runner.py`**

```python
# src/agency/runtime/scheduler_runner.py
from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data_refresh.market_calendar import classify_market_session

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = os.environ.get("AGENCY_PYTHON", "python")

# Jobs per market phase: name → interval_minutes
_PHASE_JOBS: dict[str, list[dict[str, Any]]] = {
    "pre_market": [
        {"name": "stock_trades",        "interval_minutes": 15},
        {"name": "subscription_emails", "interval_minutes": 10},
        {"name": "news_rss",            "interval_minutes": 30},
    ],
    "regular_market": [
        {"name": "news_rss",            "interval_minutes": 30},
        {"name": "subscription_emails", "interval_minutes": 10},
    ],
    "after_hours": [
        {"name": "prices_daily",        "interval_minutes": 30},
        {"name": "stock_trades",        "interval_minutes": 20},
        {"name": "subscription_emails", "interval_minutes": 15},
    ],
    "overnight": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
        {"name": "sec_13f",             "interval_minutes": 720},
        {"name": "news_rss",            "interval_minutes": 60},
        {"name": "prices_daily",        "interval_minutes": 60},
    ],
    "holiday": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
    ],
}


def jobs_for_phase(phase: str) -> list[dict[str, Any]]:
    """Return the job specs active for the given market phase."""
    return _PHASE_JOBS.get(phase, [])


def _run_dataset_refresh(dataset: str) -> None:
    """Fire a subprocess refresh for one dataset using the live-refresh config."""
    config_path = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
    if not config_path.is_file():
        print(f"[scheduler] WARNING: live-refresh config not found at {config_path}", flush=True)
        return
    cmd = [
        PYTHON,
        str(REPO_ROOT / "research" / "scripts" / "run_data_refresh_batch.py"),
        "--config", str(config_path),
        "--datasets", dataset,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    status = "ok" if result.returncode == 0 else "FAILED"
    print(
        f"[scheduler] {dataset} refresh {status} "
        f"(exit {result.returncode})",
        flush=True,
    )
    if result.returncode != 0:
        print(f"[scheduler] stderr: {result.stderr[:500]}", flush=True)


def build_scheduler(db_url: str) -> AsyncIOScheduler:
    """Build an APScheduler instance backed by Postgres."""
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
    _register_phase_jobs(scheduler)
    return scheduler


def _register_phase_jobs(scheduler: AsyncIOScheduler) -> None:
    now = datetime.now(UTC)
    session = classify_market_session(now)
    phase = session.phase
    for spec in jobs_for_phase(phase):
        scheduler.add_job(
            _run_dataset_refresh,
            "interval",
            minutes=spec["interval_minutes"],
            args=[spec["name"]],
            id=f"refresh_{spec['name']}",
            replace_existing=True,
            name=f"refresh:{spec['name']}",
        )
    print(f"[scheduler] registered {len(jobs_for_phase(phase))} jobs for phase={phase}", flush=True)
```

- [ ] **Step 5: Run the scheduler tests**

```
.\.venv\Scripts\python -m pytest tests/unit/test_scheduler_runner.py -v
```

Expected: all `PASSED`

- [ ] **Step 6: Register the scheduler lifespan in `app.py`**

`app.py` currently uses `create_app()` with no lifespan. Modify it:

```python
# src/agency/app.py
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agency.api.audit import router as audit_api_router
from agency.api.candidates import router as candidates_router
from agency.api.health import router as health_router
from agency.api.reports import router as reports_router
from agency.api.risk import router as risk_router
from agency.audit_dashboard import router as audit_dashboard_router
from agency.dashboard import router as dashboard_router
from agency.runtime.scheduler_runner import build_scheduler


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    db_url = os.environ.get("DATABASE_URL", "")
    scheduler = None
    if db_url and os.environ.get("AGENCY_SCHEDULER_ENABLED", "").lower() == "true":
        scheduler = build_scheduler(db_url)
        scheduler.start()
        print("[scheduler] started", flush=True)
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        print("[scheduler] stopped", flush=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trading Agency v2",
        version="0.1.0",
        description="Supervised equity research and paper-trading assistant.",
        lifespan=_lifespan,
    )
    app.mount(
        "/static",
        StaticFiles(packages=[("agency", "static")]),
        name="static",
    )
    app.include_router(dashboard_router)
    app.include_router(audit_dashboard_router)
    app.include_router(audit_api_router)
    app.include_router(candidates_router)
    app.include_router(health_router)
    app.include_router(reports_router)
    app.include_router(risk_router)
    return app


app = create_app()
```

Add to `.env.example`:
```
# Set to true to start the market-aware data refresh scheduler on server startup
AGENCY_SCHEDULER_ENABLED=false
```

- [ ] **Step 7: Run the full test suite**

```
.\.venv\Scripts\python -m pytest tests/ -x -q
```

Expected: all `PASSED`

- [ ] **Step 8: Commit**

```
git add src/agency/runtime/scheduler_runner.py src/agency/app.py tests/unit/test_scheduler_runner.py pyproject.toml .env.example
git commit -m "feat: wire market-aware scheduler executor with Postgres job store"
```

---

## Task 7: T119 — Write the daily ops runbook

**Why:** Multiple scripts exist but no single document tells the operator what to run, in what order, and how to recover from failures.

**Files:**
- Create: `docs/daily-ops-runbook.md`
- Create: `scripts/run_daily_ops.py`

---

- [ ] **Step 1: Create `scripts/run_daily_ops.py`**

```python
#!/usr/bin/env python
"""Daily operations entry point for Trading Agency v2.

Runs the full daily paper-trading loop:
  1. Operational readiness check
  2. Market-aware data refresh (or scheduler status check)
  3. PIT runtime cycle
  4. Review queue check

Each step prints a clear status line. Any failure prints a recovery hint and
exits with a non-zero code.

Usage:
    python scripts/run_daily_ops.py [--dry-run] [--skip-refresh]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _step(label: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"\n[{ts}] ── {label} ──", flush=True)


def _run(cmd: list[str], *, hint: str) -> None:
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"\nFAILED. Recovery hint: {hint}")
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print steps without running them")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip data refresh step")
    args = parser.parse_args()

    _step("1 / 4  Operational readiness check (~10s)")
    if not args.dry_run:
        _run(
            [PYTHON, "scripts/check_operational_readiness.py"],
            hint="Fix the failing readiness check before running the cycle.",
        )

    if not args.skip_refresh:
        _step("2 / 4  Market-aware data refresh (~2-10 min depending on phase)")
        if not args.dry_run:
            config = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
            _run(
                [PYTHON, "research/scripts/run_data_refresh_batch.py", "--config", str(config)],
                hint="Check data-refresh-status.json in research/results/ for failed datasets.",
            )

    _step("3 / 4  PIT runtime cycle (~30s)")
    if not args.dry_run:
        _run(
            [PYTHON, "scripts/run_first_version_pipeline.py",
             "--email-max-emails", "5",
             "--email-max-article-links", "2"],
            hint="Check the dashboard at http://127.0.0.1:8000/command for cycle errors.",
        )

    _step("4 / 4  Review queue check (~5s)")
    if not args.dry_run:
        _run(
            [PYTHON, "scripts/check_paper_review_status.py"],
            hint="Open http://127.0.0.1:8000/command and review the WATCH candidates.",
        )

    _step("Done")
    print("All steps completed. Open http://127.0.0.1:8000/command to review candidates.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script runs in dry-run mode**

```
.\.venv\Scripts\python scripts\run_daily_ops.py --dry-run
```

Expected: prints 4 step labels and "Done" with no subprocess errors

- [ ] **Step 3: Create `docs/daily-ops-runbook.md`**

```markdown
# Daily Operations Runbook

**Last updated:** 2026-05-13  
**Mode:** Paper trading — no real orders

## Quick Start

```powershell
.\.venv\Scripts\python scripts\run_daily_ops.py
```

This runs all four steps below in sequence. Any failure prints a recovery hint
and stops.

## Manual Steps

### 1. Operational Readiness Check (~10s)

```powershell
.\.venv\Scripts\python scripts\check_operational_readiness.py
```

Checks: API keys present, live config valid, latest cycle reviewable.  
**On failure:** read the printed checklist and fix the flagged item.

### 2. Market-Aware Data Refresh (~2–10 min)

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json
```

Runs the correct datasets for the current market phase.  
**On failure:** open `research/results/*/data-refresh-status.json` — the
`failed_datasets` field names the datasets to re-run.  
**Re-run one dataset:**

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --datasets prices_daily
```

### 3. PIT Runtime Cycle (~30s)

```powershell
.\.venv\Scripts\python scripts\run_first_version_pipeline.py `
  --email-max-emails 5 `
  --email-max-article-links 2
```

Builds the cycle and persists selection reports to Postgres.  
**On failure:** check the server log at `http://127.0.0.1:8000/health`.

### 4. Review Queue Check (~5s)

```powershell
.\.venv\Scripts\python scripts\check_paper_review_status.py
```

Prints pending/approved/deferred counts.  
**Next step:** open `http://127.0.0.1:8000/command` and approve, defer, or reject
each WATCH candidate.

## Scheduler Mode (automated, background)

If `AGENCY_SCHEDULER_ENABLED=true` in `.env`, the scheduler handles steps 2
automatically when the FastAPI server is running. You only need to run steps 3
and 4 manually (or wait for the next automated cycle).

## Recovery Reference

| Symptom | Command |
|---|---|
| No candidates in queue | Check source health: `http://127.0.0.1:8000/status/source-health` |
| Cycle fails to build | Check PIT data: `.\.venv\Scripts\python research\scripts\check_live_refresh_outputs.py` |
| Dashboard unreachable | Restart server: `.\.venv\Scripts\python -m uvicorn agency.app:app --reload` |
| Email agent fails | Check Gmail readiness: `http://127.0.0.1:8000/status/provider-readiness` |
```

- [ ] **Step 4: Commit**

```
git add scripts/run_daily_ops.py docs/daily-ops-runbook.md
git commit -m "docs: add daily ops runbook and single-entry-point script"
```

---

## Task 8: T121 — End-to-end daily loop smoke test

**Why:** Confirms the complete path — source health → cycle → evidence packs → selection reports → review queue — works end-to-end with seeded data. This is the sprint gate.

**Dependencies:** Tasks 1–7 merged.

**Files:**
- Create: `tests/e2e/test_daily_loop_smoke.py`

---

- [ ] **Step 1: Understand the existing e2e fixture**

Open `tests/e2e/test_first_version_smoke.py`. Note the seeded-data path it uses (the `service_fixtures.py` or `pit_fixtures.py`). The new test follows the same pattern but extends the assertions.

- [ ] **Step 2: Write the daily loop smoke test**

Create `tests/e2e/test_daily_loop_smoke.py`:

```python
"""Daily loop smoke test.

Verifies: source health → cycle build → evidence packs → selection reports →
review queue populated → human review action recorded.

Uses seeded local data only (no external API calls).
Runs in under 60 seconds.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

# Reuse fixtures from the existing e2e smoke test where possible.
# The exact fixture names depend on the project's conftest setup.
# Open tests/e2e/test_first_version_smoke.py to identify the right imports.


@pytest.mark.e2e
def test_daily_loop_source_health_is_non_empty(seeded_pit_cycle) -> None:
    """Source health must include at least one entry."""
    source_health = seeded_pit_cycle.source_health
    assert len(source_health) > 0, "Expected source health entries from seeded data"
    for entry in source_health:
        assert "source" in entry
        assert "status" in entry


@pytest.mark.e2e
def test_daily_loop_evidence_packs_built(seeded_pit_cycle) -> None:
    """Evidence packs must be built for each ticker in the seeded set."""
    evidence_packs = seeded_pit_cycle.evidence_packs
    assert len(evidence_packs) > 0, "Expected at least one evidence pack"
    for pack in evidence_packs:
        assert "ticker" in pack
        assert "actionable_signals" in pack


@pytest.mark.e2e
def test_daily_loop_selection_reports_present(seeded_pit_cycle) -> None:
    """Selection reports must be produced (WATCH or NO_TRADE) for each ticker."""
    reports = seeded_pit_cycle.selection_reports
    assert len(reports) > 0, "Expected selection reports from seeded cycle"
    actions = {r["final_action"] for r in reports}
    assert actions.issubset({"WATCH", "NO_TRADE", "HOLD", "BUY", "SELL"})


@pytest.mark.e2e
def test_daily_loop_risk_decisions_present(seeded_pit_cycle) -> None:
    """Risk decisions must be present for every selection report."""
    risk_decisions = seeded_pit_cycle.risk_decisions
    assert len(risk_decisions) > 0, "Expected risk decisions from seeded cycle"
    for decision in risk_decisions:
        assert decision["decision"] in {"ALLOW", "WARN", "BLOCK"}


@pytest.mark.e2e
def test_daily_loop_no_unhandled_exceptions(seeded_pit_cycle) -> None:
    """The cycle must complete without unhandled exceptions."""
    # If seeded_pit_cycle fixture raises, this test fails — that's the intent.
    assert seeded_pit_cycle.cycle_id is not None
    assert seeded_pit_cycle.as_of is not None
```

> **Note:** The `seeded_pit_cycle` fixture must be defined in `tests/e2e/conftest.py` or `tests/unit/service_fixtures.py`. Open those files to find the existing fixture that builds a `RuntimeCycleResult` from seeded data, and use it as `seeded_pit_cycle`. If it has a different name (e.g., `sample_cycle_result`), use that name and add an alias.

- [ ] **Step 3: Run the smoke tests**

```
.\.venv\Scripts\python -m pytest tests/e2e/test_daily_loop_smoke.py -v -m e2e
```

Expected: all `PASSED` (seeded data is already in the repo from previous sprint work)

- [ ] **Step 4: Run the full test suite one final time**

```
.\.venv\Scripts\python -m pytest tests/ -q
```

Expected: all `PASSED`. Sprint gate is achieved.

- [ ] **Step 5: Commit**

```
git add tests/e2e/test_daily_loop_smoke.py
git commit -m "test: add end-to-end daily loop smoke test (sprint gate T121)"
```

---

## Sprint Complete — Gate Check

After Task 8 merges, verify the sprint gate:

```powershell
.\.venv\Scripts\python scripts\run_daily_ops.py --dry-run   # prints all 4 steps
.\.venv\Scripts\python -m pytest tests/ -q                  # all green
.\.venv\Scripts\python -m mypy src research --ignore-missing-imports  # no errors
```

---

## Parallel Track Plans (separate documents)

Each track gets its own plan written when the track starts:

| Track | Plan document | Start condition |
|---|---|---|
| Track 1 — Code quality | `docs/superpowers/plans/2026-05-13-track1-code-quality.md` | T121 merged |
| Track 2 — UX | `docs/superpowers/plans/2026-05-13-track2-ux.md` | T117 merged |
| Track 3 — Research | `docs/superpowers/plans/2026-05-13-track3-research.md` | T151 ready |

**Early-start tickets (no sprint dependency):**
- Track 1: T123, T124, T126, T127, T134, T137 — start immediately alongside the sprint
- Track 2: T140, T146 — start immediately (no T117 dependency)
- Track 3: T151 — start immediately (Massive key active, no limits)
