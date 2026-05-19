# MVP Execution Plan — First End-to-End Paper Trade
**Date:** 2026-05-16  
**Goal:** Submit one verified Alpaca paper order through the normal UI review flow  
**Strategy:** Three phases — infrastructure baseline, proof-of-path bypass, then real promotion chain

---

## Phase 1 — SQLite Fallback (unblock everything local)

**Objective:** `python -m uvicorn src.agency.app:app --port 8000` starts and serves all routes without Docker or Supabase credentials.

**Why first:** Every P0 item requires a working DB session. The WATCH→ALLOW promotion, paper review event persistence, and policy toggle all silently fail without it. This is the foundation.

---

### Step 1.1 — Add aiosqlite dependency

**File:** `pyproject.toml` (or `requirements.txt` if that's what this project uses)

Add to dependencies:
```
aiosqlite>=0.19.0
```

Verify SQLAlchemy async SQLite driver is available:
```
sqlalchemy[asyncio]>=2.0
```

---

### Step 1.2 — SQLite fallback in database module

**File:** `src/agency/database.py`

Find where `DATABASE_URL` is read from env and `AsyncEngine` / `AsyncSession` are created. Add a fallback:

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

_raw_url = os.getenv("DATABASE_URL", "")
if not _raw_url:
    _DATABASE_URL = "sqlite+aiosqlite:///./trading_agency_local.db"
elif _raw_url.startswith("postgresql://"):
    # SQLAlchemy async requires postgresql+asyncpg://
    _DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    _DATABASE_URL = _raw_url

_connect_args = {"check_same_thread": False} if "sqlite" in _DATABASE_URL else {}

engine = create_async_engine(_DATABASE_URL, connect_args=_connect_args, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

---

### Step 1.3 — Alembic SQLite compatibility

**File:** `alembic/env.py`

SQLite does not support `ALTER COLUMN` or `DROP CONSTRAINT`. Alembic must run in batch mode for SQLite. In `run_migrations_online()`:

```python
from sqlalchemy import engine_from_config
from alembic import context

def run_migrations_online():
    connectable = engine_from_config(...)
    
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,  # required for SQLite ALTER support
        )
        with context.begin_transaction():
            context.run_migrations()
```

Also update `alembic.ini` so `sqlalchemy.url` reads from env:
```ini
sqlalchemy.url = %(DATABASE_URL)s
```
And in `env.py` set it before config is read:
```python
import os
config.set_main_option("sqlalchemy.url", 
    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./trading_agency_local.db"))
```

---

### Step 1.4 — Run migrations on startup (app lifespan)

**File:** `src/agency/app.py`

In the lifespan context manager, run Alembic migrations programmatically before the scheduler starts:

```python
from alembic.config import Config
from alembic import command

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migrations on every startup (idempotent)
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    
    # ... existing scheduler startup ...
    yield
    # ... existing shutdown ...
```

This ensures the SQLite DB has all tables even on first run.

---

### Step 1.5 — Add lightweight dev start script

**File:** `scripts/start_dev.ps1` (new file)

```powershell
# Minimal local dev startup — no Docker required
# Uses SQLite for local state

$env:DATABASE_URL = "sqlite+aiosqlite:///./trading_agency_local.db"

# Optional: LLM review (set your key if you have one)
# $env:AGENCY_ENABLE_LLM_REVIEW = "true"
# $env:OPENAI_API_KEY = "sk-..."

# Broker submit stays disabled until manually enabled
$env:AGENCY_BROKER_SUBMIT_ENABLED = "false"

Write-Host "Starting agency on http://localhost:8000 (SQLite mode)"
python -m uvicorn src.agency.app:app --host 0.0.0.0 --port 8000 --reload
```

---

### Phase 1 Acceptance Test

```powershell
# Terminal 1
.\scripts\start_dev.ps1

# Terminal 2 (after server starts)
Invoke-WebRequest http://localhost:8000/health  # expects 200
Invoke-WebRequest http://localhost:8000/        # expects 200 (dashboard loads)
Invoke-WebRequest http://localhost:8000/execution-preview  # expects 200
```

All three return 200 with no DB connection error in logs. The trading_agency_local.db file is created in the project root.

---

## Phase 2 — Prove the Alpaca Paper Path Works

**Objective:** One Alpaca paper order is submitted and confirmed, bypassing the normal UI flow entirely.

**Why before implementing P0-A:** The WATCH→ALLOW promotion is complex to implement. Before building it, confirm that when everything else is correct, Alpaca actually receives orders. Discover infrastructure issues (API key format, order parameters, market hours behavior) before they're hidden inside a larger feature.

**Tool:** `scripts/run_paper_broker_validation.py --trade-test` already exists and has the bypass path.

---

### Step 2.1 — Configure Alpaca credentials

Ensure `.env` (or PowerShell env) has:
```
ALPACA_API_KEY=<your paper key>
ALPACA_API_SECRET=<your paper secret>
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

Verify with:
```powershell
python -c "
from src.agency.broker.alpaca import AlpacaBroker
import asyncio
b = AlpacaBroker()
print(asyncio.run(b.get_account()))
"
```
Expect: account object with `equity`, `cash`, `status=ACTIVE`.

---

### Step 2.2 — Run the existing trade test

```powershell
python scripts/run_paper_broker_validation.py --trade-test
```

Expected behaviors:
- **During market hours (9:30–16:00 ET):** Places a BUY for 1 share of a test ticker, waits for fill, places offsetting SELL, confirms no open position remains
- **Outside market hours:** Places BUY (queued), immediately cancels, confirms no open order remains

Review the output report at `research/results/alpaca-paper-validation/`. The report should contain `order_submitted: true` and `order_cleaned_up: true`.

**If this step fails:** Fix Alpaca connectivity before continuing. Common issues — wrong base URL (must be paper, not live), wrong key format, account not activated.

---

### Step 2.3 — Document what the submission call looks like

Read the trade-test section of `run_paper_broker_validation.py` and record:
- Which `AlpacaBroker` method is called (e.g., `submit_order(symbol, qty, side)`)
- What parameters it takes
- What response object it returns

This is the exact call that Phase 3's submission endpoint will use. Write it down as a comment in `src/agency/services/broker_audit.py` for Phase 3 reference.

---

### Phase 2 Acceptance Test

Report at `research/results/alpaca-paper-validation/` exists and contains:
```json
{
  "order_submitted": true,
  "order_cleaned_up": true,
  "final_open_orders": 0
}
```
Alpaca paper account dashboard (paper.alpaca.markets) shows the order in activity history.

---

## Phase 3 — WATCH→ALLOW Promotion Chain

**Objective:** A human approving a WATCH candidate in the dashboard causes its execution preview to become `submit_enabled=True` and enables paper order submission.

**Architecture decision:** Use a side-table override rather than re-running the full risk pipeline. The current cycle's selection report and risk decisions are immutable artifacts. The promotion is a separate record that the execution preview layer reads.

---

### Step 3.1 — Add approved_watch_promotions table

**File:** New Alembic migration

```python
# alembic/versions/xxxx_add_watch_promotion.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        "approved_watch_promotions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("cycle_id", sa.String(128), nullable=False),
        sa.Column("approved_at", sa.DateTime, nullable=False),
        sa.Column("approved_by", sa.String(64), nullable=True),  # "human" for now
        sa.Column("approval_event_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("ticker", "cycle_id", name="uq_watch_promotion_per_cycle"),
    )

def downgrade():
    op.drop_table("approved_watch_promotions")
```

Run: `alembic upgrade head`

---

### Step 3.2 — Write the promotion repository function

**File:** `src/agency/services/human_review.py` (or a new `src/agency/services/watch_promotion.py`)

```python
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert

async def record_watch_promotion(
    session: AsyncSession,
    ticker: str,
    cycle_id: str,
    approval_event_hash: str,
) -> None:
    stmt = insert(ApprovedWatchPromotion).values(
        ticker=ticker,
        cycle_id=cycle_id,
        approved_at=datetime.now(timezone.utc),
        approved_by="human",
        approval_event_hash=approval_event_hash,
    ).on_conflict_do_nothing(constraint="uq_watch_promotion_per_cycle")
    await session.execute(stmt)
    await session.commit()

async def is_watch_promoted(
    session: AsyncSession,
    ticker: str,
    cycle_id: str,
) -> bool:
    stmt = select(ApprovedWatchPromotion).where(
        ApprovedWatchPromotion.ticker == ticker,
        ApprovedWatchPromotion.cycle_id == cycle_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None
```

---

### Step 3.3 — Call record_watch_promotion from the APPROVE handler

**File:** `src/agency/api/dashboard.py` or `src/agency/views/candidates.py` — wherever the `POST /candidates/{ticker}` review action is handled.

Find the APPROVE branch:
```python
# Existing code records a candidate lifecycle event
await record_review_event(session, ticker, cycle_id, action="APPROVE", ...)
```

Add immediately after:
```python
from src.agency.services.watch_promotion import record_watch_promotion
from src.agency.services.human_review import build_order_approval_event

# If the candidate's selection action was WATCH, promote it
if selection_action == "WATCH":
    event = build_order_approval_event(ticker, cycle_id, ...)
    await record_watch_promotion(
        session, ticker, cycle_id, 
        approval_event_hash=event["hash"]
    )
```

The `build_order_approval_event()` function already exists in `human_review.py` — use it to generate the hash.

---

### Step 3.4 — Modify execution preview to honor WATCH promotions

**File:** `src/agency/services/execution_preview.py`

The function that builds previews currently calls `_preview_state(risk_state, side)`. Modify the caller to pass promotion status:

```python
async def build_execution_previews_for_cycle(
    session: AsyncSession,
    cycle_id: str,
    selection_reports: list,
    risk_decisions: dict,
    policy: PortfolioPolicy,
) -> list[ExecutionPreview]:
    previews = []
    for report in selection_reports:
        ticker = report.ticker
        risk_decision = risk_decisions.get(ticker, "BLOCK")
        
        # Override WARN→ALLOW for approved WATCH promotions
        if risk_decision == "WARN" and report.action == "WATCH":
            if await is_watch_promoted(session, ticker, cycle_id):
                risk_decision = "ALLOW"
        
        preview = _build_single_preview(report, risk_decision, policy)
        previews.append(preview)
    return previews
```

This is the minimal change: only WARN decisions from WATCH actions are promotable; BLOCK decisions (from policy/conviction failures) stay blocked.

---

### Step 3.5 — Add the paper submission endpoint

**File:** `src/agency/views/execution.py` (or wherever execution_preview routes live)

```python
@router.post("/execution-preview/{ticker}/submit")
async def submit_paper_order(
    ticker: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    cycle_id = get_latest_cycle_id()  # same function used elsewhere
    
    # Guard 1: must have a WATCH promotion on record
    if not await is_watch_promoted(session, ticker, cycle_id):
        raise HTTPException(400, "No approved promotion on record for this ticker")
    
    # Guard 2: policy must allow broker submit
    policy = await load_portfolio_policy(session)
    if not policy.broker_submit_enabled:
        raise HTTPException(403, "broker_submit_enabled is False in policy")
    
    # Build the order from the current execution preview
    preview = await load_execution_preview(ticker, cycle_id)
    if preview.preview_state != "READY":
        raise HTTPException(409, f"Preview is {preview.preview_state}, not READY")
    
    # Submit to Alpaca paper
    broker = AlpacaBroker()
    order_result = await broker.submit_order(
        symbol=ticker,
        qty=preview.quantity,
        side=preview.side.lower(),  # "buy" or "sell"
        order_type="market",
        time_in_force="day",
    )
    
    # Persist the submission event
    await record_execution_event(session, ticker, cycle_id, order_result)
    
    return RedirectResponse(
        url=f"/candidates/{ticker}?submitted=true", 
        status_code=303
    )
```

---

### Step 3.6 — Add Submit button to execution preview template

**File:** `src/agency/templates/execution_preview.html`

For rows where `preview.submit_enabled == True`, add:
```html
<form method="post" action="/execution-preview/{{ preview.ticker }}/submit">
  <button type="submit" class="mini-button mini-button-primary"
          onclick="return confirm('Submit paper order for {{ preview.ticker }}?')">
    Submit paper order
  </button>
</form>
```

For rows where `submit_enabled == False`:
```html
<span class="tag tag-block">Not submittable</span>
```

---

### Step 3.7 — Add policy toggle for broker_submit_enabled

**File:** `src/agency/api/dashboard.py` (policy POST handler) and `src/agency/templates/policy.html`

The policy page already has the three-tier taxonomy (from T149). Add a toggle for `broker_submit_enabled` in the Adjustable tier:

In `policy.html`:
```html
<div class="ops-check-row">
  <span class="tag {% if policy.broker_submit_enabled %}tag-pass{% else %}tag-warn{% endif %}">
    Broker submit
  </span>
  <span class="ops-check-label">Paper order submission</span>
  <form method="post" action="/api/policy/broker-submit" style="display:inline">
    <input type="hidden" name="enabled" 
           value="{{ 'false' if policy.broker_submit_enabled else 'true' }}">
    <button type="submit" class="mini-button">
      {{ 'Disable' if policy.broker_submit_enabled else 'Enable' }}
    </button>
  </form>
</div>
```

Add the matching POST handler in dashboard API:
```python
@router.post("/api/policy/broker-submit")
async def toggle_broker_submit(
    enabled: bool = Form(...),
    session: AsyncSession = Depends(get_db_session),
):
    await update_policy_field(session, "broker_submit_enabled", enabled)
    return RedirectResponse(url="/policy", status_code=303)
```

---

### Phase 3 Acceptance Test (end-to-end)

```
1. Start server: .\scripts\start_dev.ps1
2. Load dashboard: http://localhost:8000/
3. Enable broker submit: POST /api/policy/broker-submit enabled=true
4. Navigate to a WATCH candidate: /candidates/{ticker}
5. Click Approve → APPROVE review event recorded + watch promotion recorded
6. Navigate to /execution-preview
7. Confirm the approved ticker shows preview_state=READY and submit_enabled=True
8. Click "Submit paper order"
9. Confirm redirect to /candidates/{ticker}?submitted=true
10. Check Alpaca paper account — order appears in activity
11. Check /audit — order event logged
```

All 11 steps complete without error. The audit log contains the order event. Alpaca paper account shows the order.

---

## Phase 4 — Stabilize and Document

After the first paper order goes through, do these in any order:

**4.1** — Add `AGENCY_BROKER_SUBMIT_ENABLED` env var override so the policy toggle survives restart without DB persistence (for local testing):

In `src/agency/services/risk.py` where `broker_submit_enabled` is read from policy:
```python
broker_submit_enabled = (
    policy.broker_submit_enabled 
    or os.getenv("AGENCY_BROKER_SUBMIT_ENABLED", "").lower() == "true"
)
```

**4.2** — Add a one-line status indicator to the dashboard showing how many WATCH candidates have active promotions vs. how many are approved-and-submittable.

**4.3** — Write `tests/integration/test_watch_promotion.py`:
- Insert a WATCH selection report and WARN risk decision
- Call `record_watch_promotion()`
- Build execution previews
- Assert `submit_enabled=True` for that ticker

**4.4** — Update `docs/phase-status.md` Phase 4 gate: "Paper order submitted end-to-end via normal review flow" → ✅

---

## Critical Constraints for Codex

1. **Do not modify `risk.py` WATCH→WARN logic.** The design intent (WATCH = review-required, not auto-executable) is correct. The promotion is an additive layer on top, not a change to the risk model.

2. **Do not re-run the cycle to rebuild risk decisions.** The promotion is a read-side override at preview time, not a mutation of the selection report or risk decision artifacts.

3. **The `approved_watch_promotions` table is append-only.** No UPDATE or DELETE. If a user changes their mind, they record a REVOKE event in `candidate_lifecycle_events` and the preview builder checks for revocation before honoring promotion.

4. **broker_submit_enabled=False is the safe default.** The env var override (Phase 4.1) is for local dev only — never set it in production env.

5. **Work through phases sequentially.** Phase 2 (bypass test) must succeed before Phase 3 implementation begins. Discovering Alpaca connectivity issues after implementing the full promotion chain wastes debugging time.
