from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agency.api.audit import router as audit_api_router
from agency.api.candidates import router as candidates_router
from agency.api.health import router as health_router
from agency.api.reports import router as reports_router
from agency.api.risk import policy_router
from agency.api.risk import router as risk_router
from agency.audit_dashboard import router as audit_dashboard_router
from agency.dashboard import router as dashboard_router

REPO_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_dotenv(REPO_ROOT / ".env")
    db_url = os.environ.get("DATABASE_URL", "")
    scheduler = None
    from agency.runtime.scheduler_status import record_scheduler_runtime_status

    if _scheduler_enabled_for_app(db_url):
        try:
            from agency.runtime.scheduler_runner import build_scheduler
            record_scheduler_runtime_status(
                state="starting",
                detail="Automatic lane refresh scheduler is starting.",
            )
            scheduler = build_scheduler(db_url or None)
            scheduler.start()
            record_scheduler_runtime_status(
                state="running",
                detail=(
                    "Automatic lane refresh scheduler is running in this app "
                    "process. It executes due scheduler-work-queue lane commands "
                    "and refreshes live runtime artifacts after data changes."
                ),
                job_count=len(scheduler.get_jobs()),
            )
            print("[scheduler] started", flush=True)
        except Exception as exc:  # pragma: no cover - startup guardrail
            scheduler = None
            record_scheduler_runtime_status(
                state="error",
                detail=f"Automatic lane refresh scheduler failed to start: {exc}",
            )
    else:
        reason = (
            "Set AGENCY_SCHEDULER_ENABLED=true to run automatic jobs without DATABASE_URL."
            if not db_url
            else "AGENCY_SCHEDULER_ENABLED is false, so automatic jobs are disabled."
        )
        record_scheduler_runtime_status(
            state="disabled",
            detail=reason,
        )
    try:
        from agency.views.cockpit import warm_cockpit_context_cache

        if await warm_cockpit_context_cache():
            print("[cockpit] context cache warmed", flush=True)
        else:
            print("[cockpit] context cache warmup skipped after timeout or error", flush=True)
    except Exception as exc:  # pragma: no cover - startup guardrail
        print(f"[cockpit] context cache warmup failed: {exc}", flush=True)
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        record_scheduler_runtime_status(
            state="stopped",
            detail="Automatic refresh scheduler stopped during app shutdown.",
        )
        print("[scheduler] stopped", flush=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trading Agency v3",
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
    app.include_router(policy_router)
    return app


app = create_app()


def _scheduler_enabled_for_app(db_url: str) -> bool:
    value = os.environ.get("AGENCY_SCHEDULER_ENABLED")
    if value is None:
        return True
    return value.lower() not in {"0", "false", "no", "off"}
