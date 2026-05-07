from __future__ import annotations

from fastapi import FastAPI

from agency.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trading Agency v2",
        version="0.1.0",
        description="Supervised equity research and paper-trading assistant.",
    )
    app.include_router(health_router)
    return app


app = create_app()
