from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agency.api.audit import router as audit_api_router
from agency.api.candidates import router as candidates_router
from agency.api.health import router as health_router
from agency.api.reports import router as reports_router
from agency.api.risk import router as risk_router
from agency.audit_dashboard import router as audit_dashboard_router
from agency.dashboard import router as dashboard_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trading Agency v2",
        version="0.1.0",
        description="Supervised equity research and paper-trading assistant.",
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
