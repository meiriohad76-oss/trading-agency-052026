# Codex Implementation Plan — Paper Trade MVP
**Date:** 2026-05-16  
**Repo root:** `c:\Users\meiri\trading_agency`

---

## Situation (read before touching anything)

The entire paper-trade execution chain is **already fully implemented**. These routes and services exist and work:

| Component | File | Status |
|---|---|---|
| WATCH→BUY promotion | `src/agency/services/paper_trade_promotion.py` | ✅ complete |
| Execution preview pipeline | `src/agency/views/execution.py` | ✅ complete |
| Order approval endpoint | `src/agency/dashboard.py:230–270` | ✅ complete |
| Paper order submission endpoint | `src/agency/dashboard.py:273–360` | ✅ complete |
| `broker_submit_enabled` env gate | `src/agency/services/risk.py:129` | ✅ reads `AGENCY_BROKER_SUBMIT_ENABLED` |
| Alpaca paper broker client | `src/agency/broker/alpaca.py` | ✅ complete |

**The only blocker is the database layer.** `src/agency/db.py` requires five Postgres env vars (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`). When they are absent it throws `MissingDatabaseConfigurationError` before any session can be opened, which makes review-event persistence, order-approval persistence, and order-audit persistence all fail. Without a working DB, the UI review actions fail with 503 and the full paper-trade flow cannot complete.

**Three code changes required. Nothing else.**

---

## Task 1 — Add `aiosqlite` dependency

**File:** `pyproject.toml`

In the `dependencies` list (currently ends with `"apscheduler>=3.10"`), add one line:

```toml
  "aiosqlite>=0.19",
```

Full context for the edit — insert after the `asyncpg` line:

```toml
dependencies = [
  "alembic>=1.16",
  "aiosqlite>=0.19",        # ← add this line
  "asyncpg>=0.30",
  ...
```

After editing, run:
```powershell
pip install aiosqlite
```

**Verify:** `python -c "import aiosqlite; print('ok')"` prints `ok`.

---

## Task 2 — SQLite fallback in `src/agency/db.py`

**Goal:** When `DB_HOST` is not set, fall back to `DATABASE_URL` env var, then to `sqlite+aiosqlite:///./agency_local.db`. Postgres behaviour is unchanged when the five DB_ vars are present.

**Current file:** `src/agency/db.py` (read it fully before editing)

### 2a — Add import and helper function

After the existing imports block (line 18 ends with `from sqlalchemy.pool import NullPool`), add:

```python
SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///./agency_local.db"


def _effective_database_url() -> str:
    """Return the async DB URL to use.

    Priority:
      1. DATABASE_URL env var (normalises postgresql:// → postgresql+asyncpg://)
      2. Individual DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD vars
      3. SQLite local fallback (no configuration needed)
    """
    load_dotenv()
    explicit = os.environ.get("DATABASE_URL", "").strip()
    if explicit:
        if explicit.startswith("postgresql://"):
            return explicit.replace("postgresql://", "postgresql+asyncpg://", 1)
        return explicit
    if os.environ.get("DB_HOST", "").strip():
        try:
            return build_database_url(DatabaseSettings.from_env()).render_as_string(
                hide_password=False
            )
        except MissingDatabaseConfigurationError:
            pass
    return SQLITE_FALLBACK_URL
```

### 2b — Replace `create_engine`

The current `create_engine` function (lines 84–92) passes asyncpg-specific `connect_args={"timeout": ...}` which raises a `TypeError` with aiosqlite. Replace the entire function:

**Old** (lines 84–92):
```python
def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    db_settings = DatabaseSettings.from_env() if settings is None else settings
    return create_async_engine(
        build_database_url(db_settings),
        echo=db_settings.echo,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"timeout": db_settings.connect_timeout_seconds},
    )
```

**New:**
```python
def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    if settings is not None:
        # Explicit Postgres settings (legacy / test path)
        return create_async_engine(
            build_database_url(settings),
            echo=settings.echo,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"timeout": settings.connect_timeout_seconds},
        )
    url = _effective_database_url()
    if url.startswith("sqlite"):
        return create_async_engine(
            url,
            connect_args={"check_same_thread": False},
        )
    # Postgres path via DATABASE_URL or DB_* vars
    try:
        pg = DatabaseSettings.from_env()
        return create_async_engine(
            url,
            echo=pg.echo,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"timeout": pg.connect_timeout_seconds},
        )
    except MissingDatabaseConfigurationError:
        return create_async_engine(url, poolclass=NullPool)
```

**No other changes to `db.py`.** `create_sessionmaker`, `get_sessionmaker`, and `get_session` are unchanged.

### 2c — Verify

```powershell
python -c "
import asyncio
from agency.db import get_session
async def test():
    async with get_session() as s:
        print('session ok')
asyncio.run(test())
"
```

Expected output: `session ok` — with `agency_local.db` created in the repo root.

---

## Task 3 — SQLite support in `migrations/env.py`

**File:** `migrations/env.py`

SQLite does not support `ALTER TABLE ... ADD COLUMN NOT NULL` without batch mode. Alembic's `render_as_batch=True` rewrites such operations as a table rebuild.

### 3a — Replace `get_url`

**Old** (lines 22–23):
```python
def get_url() -> str:
    return build_database_url(DatabaseSettings.from_env()).render_as_string(hide_password=False)
```

**New:**
```python
def get_url() -> str:
    from agency.db import _effective_database_url
    return _effective_database_url()
```

### 3b — Replace `do_run_migrations`

**Old** (lines 38–42):
```python
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()
```

**New:**
```python
def do_run_migrations(connection: Connection) -> None:
    is_sqlite = connection.dialect.name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()
```

### 3c — Verify migrations run

```powershell
alembic -c alembic.ini upgrade head
```

Expected: 8 migration steps applied with no errors. `agency_local.db` now contains all tables.

---

## Task 4 — Dev startup script (new file)

**File:** `scripts/start_dev.ps1` (create new)

```powershell
#!/usr/bin/env pwsh
# Lightweight local dev startup — no Docker, no Supabase required.
# Uses SQLite for all DB state. Set Alpaca keys in .env to enable broker.

Set-Location $PSScriptRoot\..

# SQLite fallback — no DB_HOST needed
$env:DATABASE_URL = "sqlite+aiosqlite:///./agency_local.db"

# Disable scheduler (avoids APScheduler DB dependency at startup)
$env:AGENCY_SCHEDULER_ENABLED = "false"

# Paper trade promotion: WATCH candidates approved by human → promoted to BUY
$env:AGENCY_PAPER_TRADE_PROMOTION_ENABLED = "true"
$env:AGENCY_PAPER_TRADE_MIN_CONVICTION = "0.62"   # matches policy min_final_conviction

# Broker submit gates — set both to enable the submit button
$env:AGENCY_BROKER_SUBMIT_ENABLED = "true"
$env:AGENCY_ALPACA_BROKER_ENABLED = "true"

# Run migrations (idempotent — safe to run every startup)
Write-Host "[startup] Running database migrations..."
alembic -c alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Error "[startup] Migration failed. Aborting."
    exit 1
}

Write-Host "[startup] Starting agency on http://localhost:8000"
python -m uvicorn src.agency.app:app --host 0.0.0.0 --port 8000 --reload
```

**Verify:**
```powershell
.\scripts\start_dev.ps1
# In a second terminal:
Invoke-WebRequest http://localhost:8000/health
```
Expects: HTTP 200.

---

## Task 5 — `.env` keys required for Alpaca (user must supply)

These go in the `.env` file at repo root. Codex does not set these — they require the user's Alpaca paper account credentials.

```env
ALPACA_API_KEY=<paper account key>
ALPACA_SECRET_KEY=<paper account secret>
# Default base URL is already paper-api.alpaca.markets — no need to set unless overriding
```

Add these keys to `.env.example` so they are documented:

**File:** `.env.example`

Append or create with:
```env
# Alpaca paper broker — required for order submission
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets

# Paper trade promotion (WATCH → BUY via human approval)
AGENCY_PAPER_TRADE_PROMOTION_ENABLED=false   # set true to enable
AGENCY_PAPER_TRADE_MIN_CONVICTION=0.62       # minimum conviction to promote

# Broker submit gates
AGENCY_BROKER_SUBMIT_ENABLED=false           # set true to enable submit button
AGENCY_ALPACA_BROKER_ENABLED=false           # set true to enable Alpaca submit route

# LLM review (optional)
AGENCY_ENABLE_LLM_REVIEW=false
OPENAI_API_KEY=

# Database — leave blank to use SQLite local fallback
DATABASE_URL=
```

---

## End-to-End Verification Sequence

After all four tasks are done, run this sequence to confirm paper trading works:

```
1.  .\scripts\start_dev.ps1
    → Server on :8000, SQLite DB created, migrations applied

2.  Open http://localhost:8000/
    → Dashboard loads, shows latest cycle (168 candidates)

3.  Open http://localhost:8000/candidates/<TICKER>
    → Pick any WATCH candidate (e.g. from the review queue on dashboard)
    → Click "Approve" on the candidate detail page
    → Redirects back with "Approved" state

4.  Open http://localhost:8000/execution-preview
    → The approved WATCH candidate now appears as READY (promoted to BUY)
    → "Approve order" button is visible on that row

5.  Click "Approve order"
    → Records ORDER_APPROVAL lifecycle event in SQLite
    → Redirects back to execution preview

6.  The row now shows "Submit paper order" button

7.  Click "Submit paper order"
    → Calls POST /execution-preview/orders
    → Alpaca paper API receives market order
    → Redirect back to /execution-preview

8.  Verify:
    - Alpaca paper dashboard shows order in activity history
    - http://localhost:8000/audit shows execution state history event
    - http://localhost:8000/portfolio-monitor shows updated positions
```

---

## What Codex Must NOT Touch

- `src/agency/services/paper_trade_promotion.py` — complete, do not modify
- `src/agency/views/execution.py` — complete, do not modify
- `src/agency/dashboard.py` route handlers — complete, do not modify
- `src/agency/services/risk.py` — `broker_submit_enabled` env gate already wired
- Any migration version file in `migrations/versions/` — do not touch existing migrations
- `src/agency/broker/alpaca.py` — complete, do not modify

---

## Known Constraints

**SQLite `DateTime(timezone=True)` columns:** SQLAlchemy stores timezone-aware datetimes as strings in SQLite. This is fine for local dev. The `server_default=func.now()` in model definitions falls back to SQLite's `CURRENT_TIMESTAMP` which is UTC. Do not add any timezone-coercion logic — it will break Postgres compatibility.

**`NullPool` not set for SQLite:** Unlike Postgres, SQLite does not use `NullPool`. The engine for SQLite uses the default pool (StaticPool for in-process, file-based pool otherwise). This is intentional — do not add `NullPool` to the SQLite engine path.

**`AGENCY_PAPER_TRADE_MIN_CONVICTION=0.62`:** The default in `paper_trade_promotion.py` is `0.9`. Current WATCH candidates have conviction scores around `0.62–0.75`. Setting the env var to `0.62` aligns with `PortfolioPolicy.min_final_conviction` and makes at least some WATCH candidates promotable. Do not lower below `0.62`.

**`AGENCY_PAPER_TRADE_PROMOTION_ENABLED` is the master gate.** Until it is `true`, `promote_paper_trade_reports()` returns the reports unchanged (all WATCH stay WATCH → all previews stay DISABLED). The submit button never appears.

**Two-step approval is required before submit:** The execution preview route requires both `human_approved=True` (from a APPROVE candidate review event) AND `order_approved=True` (from a separate ORDER_APPROVAL event recorded when "Approve order" is clicked). Both must be true before `submit_enabled` becomes `True`. This is by design — do not bypass either check.
