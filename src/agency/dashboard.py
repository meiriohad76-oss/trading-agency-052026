from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from agency.api.health import runtime_data_source_status
from agency.broker import (
    AlpacaBrokerClient,
    AlpacaBrokerError,
    AlpacaTradingConfig,
    build_market_order_payload,
)
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import execution_freshness_gate, record_candidate_lifecycle_event
from agency.runtime.lane_promotion import load_lane_promotion_status
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.services import (
    PortfolioPolicy,
    build_and_persist_human_review_event,
    build_order_approval_event,
    persist_portfolio_snapshot,
)
from agency.views._shared import _env_bool_text, _mapping_field, _optional_float_field

# Route handlers below reference these view-model constructors. Helper symbols
# that are not used directly by routes are still re-exported here so existing
# callers of ``agency.dashboard`` (and tests) keep working after the split.
from agency.views.candidates import (  # noqa: F401
    _candidate_review_redirect_url,
    candidate_decision_brief,
    candidate_detail_context,
    candidate_detail_report_rows,
    candidate_detail_summary,
    candidate_email_evidence,
    candidate_email_evidence_with_judgement,
    candidate_review_summary,
    candidate_rows,
    timeline_rows,
)
from agency.views.command import (  # noqa: F401
    command_summary,
    dashboard_context,
    data_load_status_view,
    data_refresh_progress_view,
    human_review_events_for_reports,
    live_config_view,
    operational_readiness_context,
    paper_review_progress,
    paper_review_queue,
    paper_review_status_context,
    paper_review_status_from_runtime,
    policy_sections,
    policy_summary,
    provider_readiness_view,
    readiness_view,
    scheduler_work_queue_status_context,
    source_status_rows,
)
from agency.views.execution import (  # noqa: F401
    _record_submitted_order,
    execution_preview_context,
    execution_preview_order_row,
    execution_preview_rows,
)
from agency.views.final_selection import (  # noqa: F401
    final_selection_context,
    final_selection_rows,
    final_selection_summary,
)
from agency.views.learning import learning_context, learning_summary  # noqa: F401
from agency.views.market_regime import (  # noqa: F401
    broker_status_context,
    market_regime_context,
)
from agency.views.portfolio import (  # noqa: F401
    portfolio_monitor_context,
    portfolio_monitor_summary,
)
from agency.views.risk import (  # noqa: F401
    risk_context,
    risk_decision_rows,
    risk_summary,
)
from agency.views.signals import (  # noqa: F401
    signal_dashboard_rows,
    signal_dashboard_summary,
    signal_lane_rows,
    signals_context,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@router.get("/")
async def dashboard(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        await dashboard_context(),
    )


@router.get("/status/paper-review")
async def paper_review_status() -> dict[str, object]:
    return await paper_review_status_context()


@router.get("/status/operational-readiness")
async def operational_readiness_status() -> dict[str, object]:
    return await operational_readiness_context()


@router.get("/status/lane-promotion")
async def lane_promotion_status() -> dict[str, object]:
    live_config = load_live_config_readiness()
    runtime_signals = live_config.get("runtime_signals", [])
    signals = [str(item) for item in runtime_signals] if isinstance(runtime_signals, list) else []
    return load_lane_promotion_status(signals)


@router.get("/status/scheduler-work-queue")
async def scheduler_work_queue_status() -> dict[str, object]:
    return await scheduler_work_queue_status_context()


@router.get("/candidates/{ticker}")
async def candidate_detail(request: Request, ticker: str) -> Response:
    return templates.TemplateResponse(
        request,
        "candidate_detail.html",
        await candidate_detail_context(ticker),
    )


@router.post("/candidates/{ticker}/reviews")
async def record_candidate_review(
    ticker: str,
    cycle_id: str,
    as_of: str,
    decision: str,
    review_reason: str | None = None,
    notes: str | None = None,
) -> Response:
    try:
        async with get_session() as session:
            await build_and_persist_human_review_event(
                session,
                cycle_id=cycle_id,
                ticker=ticker,
                as_of=as_of,
                decision=decision,
                review_reason=review_reason,
                notes=notes,
            )
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="review persistence unavailable") from exc
    return RedirectResponse(
        url=_candidate_review_redirect_url(ticker=ticker, decision=decision),
        status_code=303,
    )


@router.get("/final-selection")
async def final_selection(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "final_selection.html",
        await final_selection_context(),
    )


@router.get("/risk")
async def risk(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "risk.html",
        await risk_context(),
    )


@router.get("/execution-preview")
async def execution_preview(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "execution_preview.html",
        await execution_preview_context(),
    )


@router.post("/execution-preview/orders/approve")
async def approve_execution_order(
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    broker, data_sources = await asyncio.gather(
        broker_status_context(),
        runtime_data_source_status(),
    )
    gate = execution_freshness_gate(broker, data_sources)
    if gate["ready"] is not True:
        raise HTTPException(status_code=409, detail=str(gate["detail"]))
    row = await execution_preview_order_row(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
        broker=broker,
        data_sources=data_sources,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="execution preview not found")
    if row.get("order_approval_available") is not True:
        raise HTTPException(status_code=400, detail="only READY paper orders can be approved")
    if str(row["order_intent_hash"]) != order_intent_hash:
        raise HTTPException(status_code=409, detail="order intent changed; refresh and approve again")
    try:
        event = build_order_approval_event(_mapping_field(row, "preview"))
        async with get_session() as session:
            await record_candidate_lifecycle_event(session, event)
            await session.commit()
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="order approval could not be persisted",
        ) from exc
    return RedirectResponse(url="/execution-preview#orderable-heading", status_code=303)


@router.post("/execution-preview/orders")
async def submit_execution_order(
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    if not _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED"):
        raise HTTPException(status_code=403, detail="Alpaca broker is disabled")
    policy = PortfolioPolicy.from_env()
    if not policy.broker_submit_enabled:
        raise HTTPException(status_code=403, detail="broker submission is disabled")
    broker, data_sources = await asyncio.gather(
        broker_status_context(),
        runtime_data_source_status(),
    )
    gate = execution_freshness_gate(broker, data_sources)
    if gate["ready"] is not True:
        raise HTTPException(status_code=409, detail=str(gate["detail"]))
    row = await execution_preview_order_row(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
        broker=broker,
        data_sources=data_sources,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="execution preview not found")
    if str(row["order_intent_hash"]) != order_intent_hash:
        raise HTTPException(status_code=409, detail="order intent changed; refresh and approve again")
    if row["order_approved"] is not True:
        raise HTTPException(status_code=403, detail="hash-bound order approval required")
    if row["submit_enabled"] is not True:
        raise HTTPException(status_code=400, detail=str(row["submit_blocker"]))
    try:
        config = AlpacaTradingConfig.from_env()
        config.require_paper(purpose="execution preview order submission")
        client = AlpacaBrokerClient(config)
        order_payload = build_market_order_payload(
            cycle_id=cycle_id,
            ticker=ticker,
            side=str(row["side"]),
            quantity=_optional_float_field(row, "quantity"),
            notional=_optional_float_field(row, "notional"),
            time_in_force=str(row["time_in_force"]),
        )
        order = await client.submit_order(order_payload)
        await _record_submitted_order(row, order)
    except AlpacaBrokerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="order was submitted, but execution audit persistence failed",
        ) from exc
    return RedirectResponse(url="/execution-preview", status_code=303)


@router.get("/policy")
async def policy(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "policy.html",
        {
            "policy_sections": policy_sections(),
            "summary": policy_summary(),
        },
    )


@router.get("/portfolio-monitor")
async def portfolio_monitor(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "portfolio_monitor.html",
        await portfolio_monitor_context(),
    )


@router.get("/signals")
async def signals(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "signals.html",
        await signals_context(),
    )


@router.get("/market-regime")
async def market_regime(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "market_regime.html",
        await market_regime_context(),
    )


@router.get("/universe")
async def universe() -> RedirectResponse:
    return RedirectResponse("/market-regime", status_code=303)


@router.post("/portfolio-monitor/snapshots")
async def record_portfolio_snapshot() -> Response:
    broker = await broker_status_context()
    if broker.get("connected") is not True:
        raise HTTPException(status_code=503, detail=str(broker.get("detail", "broker offline")))
    try:
        async with get_session() as session:
            await persist_portfolio_snapshot(session, broker)
            await session.commit()
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="portfolio snapshot persistence unavailable",
        ) from exc
    return RedirectResponse(url="/portfolio-monitor", status_code=303)


@router.get("/status/broker")
async def broker_status() -> dict[str, object]:
    return await broker_status_context()


@router.get("/learning")
async def learning(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "learning.html",
        await learning_context(),
    )
