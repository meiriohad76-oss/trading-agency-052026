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


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    db_url = os.environ.get("DATABASE_URL", "")
    scheduler = None
    if db_url and os.environ.get("AGENCY_SCHEDULER_ENABLED", "").lower() == "true":
        from agency.runtime.scheduler_runner import build_scheduler
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
