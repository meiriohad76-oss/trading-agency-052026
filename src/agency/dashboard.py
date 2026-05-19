from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
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
from agency.runtime import record_candidate_lifecycle_event
from agency.runtime.artifact_fallbacks import append_runtime_lifecycle_event_artifact
from agency.runtime.lane_promotion import load_lane_promotion_status
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.scheduler_work_queue import execution_freshness_gate
from agency.runtime.scheduler_runner import run_manual_massive_lane_refresh
from agency.services import (
    PortfolioPolicy,
    build_and_persist_human_review_event,
    build_human_review_event,
    build_order_approval_event,
    load_active_portfolio_policy,
    persist_portfolio_snapshot,
    selection_report_hash,
)
from agency.services.risk import load_policy_from_db
from agency.views._shared import (
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _env_bool_text,
    _matching_payload,
    _mapping_field,
    _optional_float_field,
    _runtime_payload_key,
    dashboard_data_health,
    live_dashboard_data_load_status,
)

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
    _review_caution,
    timeline_rows,
)
from agency.views.command import (  # noqa: F401
    broker_status_view,
    command_status_overview,
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
    scheduler_work_queue_raw_context,
    scheduler_work_queue_status_context,
    source_status_rows,
)
from agency.views.execution import (  # noqa: F401
    _record_failed_order_submission,
    _record_order_submission_intent,
    _record_submitted_order,
    execution_preview_context,
    execution_preview_order_row,
    execution_preview_rows,
    row_from_execution_context,
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


@router.get("/status/execution-preview")
async def execution_preview_status() -> dict[str, object]:
    return _execution_preview_status_payload(await execution_preview_context())


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


@router.post("/scheduler/massive-lanes/{lane_id}/refresh")
async def refresh_massive_lane(
    lane_id: str,
    background_tasks: BackgroundTasks,
) -> Response:
    queue_context = await scheduler_work_queue_raw_context()
    background_tasks.add_task(
        run_manual_massive_lane_refresh,
        lane_id,
        queue_provider=lambda: queue_context,
    )
    return RedirectResponse(url="/#scheduler-heading", status_code=303)


@router.get("/candidates/{ticker}")
async def candidate_detail(request: Request, ticker: str) -> Response:
    return templates.TemplateResponse(
        request,
        "candidate_detail.html",
        await candidate_detail_context(ticker),
    )


@router.post("/candidates/{ticker}/reviews")
async def record_candidate_review(
    request: Request,
    ticker: str,
    cycle_id: str,
    as_of: str,
    decision: str,
    review_reason: str | None = None,
    notes: str | None = None,
    caution_acknowledged: bool = False,
) -> Response:
    report_hash = await _selection_report_hash_for_review(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if report_hash is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "current selection report not found; refresh the candidate page "
                "before recording a hash-bound review"
            ),
        )
    caution_acknowledged = caution_acknowledged or await _request_form_bool(
        request,
        "caution_acknowledged",
    )
    if (
        decision.upper() == "APPROVE"
        and not caution_acknowledged
        and await _caution_acknowledgement_required_for_review(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "caution acknowledgement is required before approving this "
                "research/watch-list candidate"
            ),
        )
    try:
        async with get_session() as session:
            review_kwargs: dict[str, object] = {
                "cycle_id": cycle_id,
                "ticker": ticker,
                "as_of": as_of,
                "decision": decision,
                "review_reason": review_reason,
                "notes": notes,
                "selection_report_hash": report_hash,
            }
            if caution_acknowledged:
                review_kwargs["caution_acknowledged"] = True
            await build_and_persist_human_review_event(session, **review_kwargs)
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        try:
            event_kwargs: dict[str, object] = {
                "cycle_id": cycle_id,
                "ticker": ticker,
                "as_of": as_of,
                "decision": decision,
                "review_reason": review_reason,
                "notes": notes,
                "selection_report_hash": report_hash,
            }
            if caution_acknowledged:
                event_kwargs["caution_acknowledged"] = True
            event = build_human_review_event(**event_kwargs)
            append_runtime_lifecycle_event_artifact(event)
        except ValueError as review_error:
            raise HTTPException(status_code=400, detail=str(review_error)) from review_error
        except OSError as write_error:
            raise HTTPException(
                status_code=503,
                detail="review persistence unavailable",
            ) from write_error
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


def _execution_preview_status_payload(
    context: dict[str, object],
) -> dict[str, object]:
    summary = _mapping_field(context, "summary")
    rows = [
        _execution_preview_status_row(row)
        for row in context.get("preview_rows", [])
        if isinstance(row, dict)
    ]
    blockers = [
        _execution_preview_blocker(row)
        for row in rows
        if row["submit_enabled"] is not True
    ]
    cycle_id = str(rows[0]["cycle_id"]) if rows else ""
    ready_count = _status_int(summary, "ready_count")
    submit_ready_count = _status_int(summary, "submit_ready_count")
    approval_available_count = sum(
        1 for row in rows if row["order_approval_available"] is True
    )
    freshness_gate = context.get("execution_freshness_gate", {})
    freshness = freshness_gate if isinstance(freshness_gate, dict) else {}
    submit_gate_open = bool(summary.get("submit_gate_open") is True)
    return {
        "schema_version": "0.1.0",
        "cycle_id": cycle_id,
        "ready": submit_ready_count > 0,
        "verdict": _execution_preview_status_verdict(
            preview_count=_status_int(summary, "preview_count"),
            ready_count=ready_count,
            submit_ready_count=submit_ready_count,
            order_approval_available_count=approval_available_count,
        ),
        "preview_count": _status_int(summary, "preview_count"),
        "ready_count": ready_count,
        "orderable_count": ready_count,
        "submit_ready_count": submit_ready_count,
        "order_approval_available_count": approval_available_count,
        "review_only_count": sum(1 for row in rows if row["preview_state"] == "DISABLED"),
        "blocked_count": _status_int(summary, "blocked_count"),
        "disabled_count": _status_int(summary, "disabled_count"),
        "submit_gate_open": submit_gate_open,
        "submit_gate_label": str(summary.get("submit_gate_label") or "Unknown"),
        "headline": str(summary.get("headline") or ""),
        "detail": str(summary.get("detail") or ""),
        "freshness_gate": {
            "ready": freshness.get("ready") is True,
            "status_label": str(freshness.get("status_label") or "Unknown"),
            "status_class": str(freshness.get("status_class") or "neutral"),
            "detail": str(freshness.get("detail") or ""),
        },
        "rows": rows,
        "blockers": blockers[:20],
    }


def _execution_preview_status_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "cycle_id": str(row.get("cycle_id") or ""),
        "ticker": str(row.get("ticker") or "").upper(),
        "as_of": str(row.get("as_of") or ""),
        "preview_state": str(row.get("preview_state") or ""),
        "side": str(row.get("side") or "NONE"),
        "risk_decision": str(row.get("risk_decision") or ""),
        "submit_enabled": row.get("submit_enabled") is True,
        "order_approval_available": row.get("order_approval_available") is True,
        "submit_blocker": str(row.get("submit_blocker") or ""),
        "paper_promotion_status_label": str(
            row.get("paper_promotion_status_label") or ""
        ),
        "paper_promotion_reasons": [
            str(reason)
            for reason in row.get("paper_promotion_reasons", [])
            if reason is not None
        ],
        "order_intent_hash_label": str(row.get("order_intent_hash_label") or ""),
        "order_value_label": str(row.get("order_value_label") or ""),
        "approval_label": str(row.get("approval_label") or ""),
        "next_step": str(row.get("next_step") or ""),
    }


def _execution_preview_blocker(row: dict[str, object]) -> dict[str, object]:
    reasons = row.get("paper_promotion_reasons")
    first_reason = ""
    if isinstance(reasons, list) and reasons:
        first_reason = str(reasons[0])
    reason = first_reason or str(row.get("submit_blocker") or row.get("next_step") or "")
    return {
        "ticker": row["ticker"],
        "state": row["preview_state"],
        "side": row["side"],
        "risk_decision": row["risk_decision"],
        "reason": reason,
    }


def _execution_preview_status_verdict(
    *,
    preview_count: int,
    ready_count: int,
    submit_ready_count: int,
    order_approval_available_count: int,
) -> str:
    if submit_ready_count > 0:
        return "submit_ready"
    if order_approval_available_count > 0:
        return "awaiting_order_approval"
    if ready_count > 0:
        return "orderable_needs_approval_or_freshness"
    if preview_count > 0:
        return "research_only_or_blocked"
    return "no_execution_previews"


def _status_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key, 0)
    return value if isinstance(value, int) else 0


@router.post("/execution-preview/orders/approve")
async def approve_execution_order(
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    broker, data_sources = await asyncio.gather(
        _fresh_broker_status_context(),
        runtime_data_source_status(),
    )
    _require_immediate_execution_freshness(broker, data_sources)
    context = await execution_preview_context(broker=broker, data_sources=data_sources)
    gate = _mapping_field(context, "execution_freshness_gate")
    if gate["ready"] is not True:
        raise HTTPException(status_code=409, detail=str(gate["detail"]))
    row = row_from_execution_context(
        context,
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="execution preview not found")
    if row.get("order_approval_available") is not True:
        raise HTTPException(status_code=400, detail="only READY paper orders can be approved")
    if str(row["order_intent_hash"]) != order_intent_hash:
        raise HTTPException(
            status_code=409,
            detail="order intent changed; refresh and approve again",
        )
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
    policy = await load_active_portfolio_policy()
    if not policy.broker_submit_enabled:
        raise HTTPException(status_code=403, detail="broker submission is disabled")
    broker, data_sources = await asyncio.gather(
        _fresh_broker_status_context(),
        runtime_data_source_status(),
    )
    _require_immediate_execution_freshness(broker, data_sources)
    context = await execution_preview_context(broker=broker, data_sources=data_sources)
    gate = _mapping_field(context, "execution_freshness_gate")
    if gate["ready"] is not True:
        raise HTTPException(status_code=409, detail=str(gate["detail"]))
    row = row_from_execution_context(
        context,
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="execution preview not found")
    if str(row["order_intent_hash"]) != order_intent_hash:
        raise HTTPException(
            status_code=409,
            detail="order intent changed; refresh and approve again",
        )
    if row["order_approved"] is not True:
        raise HTTPException(status_code=403, detail="hash-bound order approval required")
    if row["submit_enabled"] is not True:
        raise HTTPException(status_code=400, detail=str(row["submit_blocker"]))
    order_payload: dict[str, object] | None = None
    order_submitted = False
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
            order_intent_hash=order_intent_hash,
        )
        await _record_order_submission_intent(row, order_payload)
        order = await client.submit_order(order_payload)
        order_submitted = True
        reconciled_order, reconciliation = await _reconcile_submitted_order(
            client,
            order_payload=order_payload,
            submitted_order=order,
        )
        await _record_submitted_order(row, reconciled_order, reconciliation)
    except AlpacaBrokerError as exc:
        if order_payload is not None and not order_submitted:
            with suppress(MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
                await _record_failed_order_submission(row, order_payload, str(exc))
        if order_submitted:
            raise HTTPException(
                status_code=202,
                detail=(
                    "paper order was submitted, but broker reconciliation failed; "
                    "verify Alpaca before retrying"
                ),
            ) from exc
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        if order_submitted:
            raise HTTPException(
                status_code=202,
                detail=(
                    "paper order was submitted, but execution audit persistence failed; "
                    "verify Alpaca before retrying"
                ),
            ) from exc
        raise HTTPException(
            status_code=503,
            detail="order intent or submission audit persistence failed",
        ) from exc
    return RedirectResponse(url="/execution-preview", status_code=303)


async def _fresh_broker_status_context() -> dict[str, object]:
    try:
        return await broker_status_context(use_cache=False)
    except TypeError:
        return await broker_status_context()


def _require_immediate_execution_freshness(
    broker: dict[str, object],
    data_sources: list[dict[str, object]],
) -> dict[str, object]:
    gate = execution_freshness_gate(broker, data_sources)
    if gate.get("ready") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(
                gate.get("detail")
                or "Broker state or critical market evidence is not fresh enough to submit."
            ),
        )
    return gate


async def _reconcile_submitted_order(
    client: AlpacaBrokerClient,
    *,
    order_payload: dict[str, object],
    submitted_order: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    client_order_id = str(order_payload.get("client_order_id") or "").strip()
    if not client_order_id:
        raise AlpacaBrokerError("paper order payload is missing client_order_id")
    submitted_client_order_id = str(submitted_order.get("client_order_id") or "").strip()
    if submitted_client_order_id and submitted_client_order_id != client_order_id:
        raise AlpacaBrokerError(
            "Alpaca paper order response client_order_id did not match the approved intent"
        )
    try:
        reconciled_order = await client.order_by_client_order_id(client_order_id)
    except AlpacaBrokerError as exc:
        return submitted_order, {
            "state": "client_order_id_lookup_failed",
            "client_order_id": client_order_id,
            "error": str(exc),
        }
    reconciled_client_order_id = str(reconciled_order.get("client_order_id") or "").strip()
    if reconciled_client_order_id != client_order_id:
        raise AlpacaBrokerError(
            "Alpaca paper order reconciliation returned a different client_order_id"
        )
    return reconciled_order, {
        "state": "client_order_id_confirmed",
        "client_order_id": client_order_id,
        "order_id_present": bool(str(reconciled_order.get("order_id", "")).strip()),
        "status": str(reconciled_order.get("status", "")),
    }


async def _selection_report_hash_for_review(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> str | None:
    reports = await _dashboard_selection_reports(ticker=ticker, limit=50)
    key = (cycle_id, ticker.upper(), as_of)
    for report in reports:
        if _runtime_payload_key(report) == key:
            return selection_report_hash(report)
    return None


async def _caution_acknowledgement_required_for_review(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> bool:
    reference = {"cycle_id": cycle_id, "ticker": ticker.upper(), "as_of": as_of}
    reports, risk_decisions = await asyncio.gather(
        _dashboard_selection_reports(ticker=ticker, limit=50),
        _dashboard_risk_decisions(ticker=ticker, limit=50),
    )
    report = _matching_payload(reports, reference)
    if report is None:
        return False
    caution = _review_caution(report, _matching_payload(risk_decisions, report))
    return bool(caution["required"])


async def _request_form_bool(request: Request, field_name: str) -> bool:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        try:
            body = (await request.body()).decode("utf-8")
        except UnicodeDecodeError:
            return False
        values = parse_qs(body, keep_blank_values=True)
        return any(_truthy_form_value(value) for value in values.get(field_name, []))
    if "multipart/form-data" not in content_type:
        return False
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return False
    return _truthy_form_value(form.get(field_name))


def _truthy_form_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@router.get("/policy")
async def policy(request: Request) -> Response:
    db_policy: PortfolioPolicy | None = None
    try:
        async with get_session() as session:
            db_policy = await load_policy_from_db(session)
    except Exception:  # noqa: BLE001
        pass

    active_policy = await load_active_portfolio_policy()
    db_backed = db_policy is not None
    data_load_status = await live_dashboard_data_load_status()
    return templates.TemplateResponse(
        request,
        "policy.html",
        {
            "policy_sections": policy_sections(active_policy),
            "policy": active_policy.as_dict(),
            "summary": policy_summary(db_backed=db_backed, policy=active_policy),
            "data_health": dashboard_data_health(
                "Policy dashboard",
                data_load_status=data_load_status,
                extra_rows=(
                    {
                        "kind": "Policy source",
                        "name": "Portfolio and execution policy",
                        "status_label": "DB-backed" if db_backed else "Local fallback",
                        "status_class": "pass" if db_backed else "warn",
                        "coverage_label": "active policy loaded",
                        "freshness_label": "loaded on request",
                        "last_update": "database" if db_backed else "environment/local config",
                        "detail": (
                            "Risk and execution gates read these limits before "
                            "paper sizing and submission."
                        ),
                    },
                ),
            ),
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
    broker = await _fresh_broker_status_context()
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
