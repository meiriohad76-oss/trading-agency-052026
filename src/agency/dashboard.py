from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from agency.api.health import bootstrap_data_source_status, contract_summaries

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@router.get("/")
def dashboard(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "contracts": contract_summaries(),
            "data_sources": bootstrap_data_source_status(),
        },
    )
