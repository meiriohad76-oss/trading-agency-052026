from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from data_refresh.market_calendar import classify_market_session
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy.exc import SQLAlchemyError

from agency.api.health import runtime_data_source_status
from agency.broker import (
    AlpacaBrokerClient,
    AlpacaBrokerError,
    AlpacaTradingConfig,
    build_market_order_payload,
)
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import (
    make_lifecycle_event_id,
    record_candidate_lifecycle_event,
    record_prompt_audit,
    upsert_selection_report,
)
from agency.runtime.artifact_fallbacks import append_runtime_lifecycle_event_artifact
from agency.runtime.lane_promotion import load_lane_promotion_status
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.scheduler_runner import (
    launch_subscription_email_login_refresh,
    run_manual_dataset_refresh,
    run_manual_massive_lane_refresh,
)
from agency.runtime.scheduler_work_queue import execution_freshness_gate
from agency.services import (
    OpenAILlmReviewProvider,
    PortfolioPolicy,
    build_and_persist_human_review_event,
    build_final_selection,
    build_human_review_event,
    build_operator_manual_advance_event,
    build_order_approval_event,
    evaluate_deterministic_rules,
    load_active_portfolio_policy,
    persist_portfolio_snapshot,
    selection_report_hash,
)
from agency.services.risk import load_policy_from_db
from agency.views._shared import (
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _env_bool_text,
    _mapping_field,
    _matching_payload,
    _operator_text,
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
    _review_caution,
    candidate_decision_brief,
    candidate_detail_context,
    candidate_detail_report_rows,
    candidate_detail_summary,
    candidate_email_evidence,
    candidate_email_evidence_with_judgement,
    candidate_news_evidence,
    candidate_review_summary,
    candidate_rows,
    timeline_rows,
)
from agency.views.cockpit import (  # noqa: F401
    cached_cockpit_context,
    cockpit_audit_payload,
    cockpit_context,
    cockpit_cycle_payload,
    cockpit_ticker_detail_payload,
    normalize_ticker,
    safe_cockpit_api_payload,
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
    execution_preview_focus_context,
    execution_preview_order_row,
    execution_preview_rows,
    row_from_execution_context,
)
from agency.views.final_selection import (  # noqa: F401
    final_selection_context,
    final_selection_focus_context,
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


def _operator_template_finalize(value: object) -> object:
    if isinstance(value, Markup):
        return value
    if isinstance(value, str):
        return _operator_text(value)
    return value


templates.env.finalize = _operator_template_finalize
EXECUTION_PREVIEW_ROUTE_CACHE_TTL_SECONDS = 60.0
FINAL_SELECTION_ROUTE_CACHE_TTL_SECONDS = 60.0
COMMAND_DASHBOARD_ROUTE_CACHE_TTL_SECONDS = 15.0
_execution_preview_route_cache: dict[str, object] = {
    "expires_at": 0.0,
    "context": None,
    "builder_id": 0,
}
_final_selection_route_cache: dict[str, object] = {
    "expires_at": 0.0,
    "context": None,
    "builder_id": 0,
}
_command_dashboard_route_cache: dict[str, object] = {
    "expires_at": 0.0,
    "context": None,
    "builder_id": 0,
}
_command_dashboard_route_cache_lock = asyncio.Lock()
BROKER_RECONCILIATION_TERMINAL_STATUSES = {
    "FILLED",
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
}
BROKER_RECONCILIATION_MAX_ATTEMPTS = 5
BROKER_RECONCILIATION_POLL_SECONDS = 0.25


@router.get("/")
async def dashboard(request: Request) -> Response:
    return await _cockpit_response(request)


@router.get("/command")
async def command_dashboard(request: Request) -> Response:
    return await _command_dashboard_response(request)


async def _command_dashboard_response(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        await _command_dashboard_route_context(),
    )


async def _command_dashboard_route_context() -> dict[str, object]:
    cached = _command_dashboard_route_cache.get("context")
    expires_at = _command_dashboard_route_cache.get("expires_at", 0.0)
    builder_id = id(dashboard_context)
    if (
        isinstance(cached, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _command_dashboard_route_cache.get("builder_id") == builder_id
    ):
        return dict(cached)
    async with _command_dashboard_route_cache_lock:
        cached = _command_dashboard_route_cache.get("context")
        expires_at = _command_dashboard_route_cache.get("expires_at", 0.0)
        if (
            isinstance(cached, dict)
            and isinstance(expires_at, float)
            and expires_at > time.monotonic()
            and _command_dashboard_route_cache.get("builder_id") == builder_id
        ):
            return dict(cached)
        context = await dashboard_context()
        _store_command_dashboard_route_cache(context)
        return dict(context)


def _store_command_dashboard_route_cache(context: Mapping[str, object]) -> None:
    _command_dashboard_route_cache["context"] = dict(context)
    _command_dashboard_route_cache["expires_at"] = (
        time.monotonic() + COMMAND_DASHBOARD_ROUTE_CACHE_TTL_SECONDS
    )
    _command_dashboard_route_cache["builder_id"] = id(dashboard_context)


def _clear_command_dashboard_route_cache() -> None:
    _command_dashboard_route_cache["context"] = None
    _command_dashboard_route_cache["expires_at"] = 0.0
    _command_dashboard_route_cache["builder_id"] = 0


def _clear_operator_route_caches() -> None:
    _clear_command_dashboard_route_cache()
    _clear_execution_preview_route_cache()
    _clear_final_selection_route_cache()


@router.get("/cockpit")
async def cockpit(request: Request) -> Response:
    return await _cockpit_response(request)


async def _cockpit_response(request: Request) -> Response:
    qa_enabled = _env_bool_text("AGENCY_COCKPIT_QA_SCENARIOS")
    qa_scenario = request.query_params.get("scenario") if qa_enabled else None
    return templates.TemplateResponse(
        request,
        "cockpit.html",
        await cached_cockpit_context(
            qa_scenario=qa_scenario,
            qa_scenarios_enabled=qa_enabled,
        ),
    )


@router.get("/api/cockpit")
async def cockpit_api() -> dict[str, object]:
    return safe_cockpit_api_payload(await cached_cockpit_context())


@router.get("/api/cycle")
async def cockpit_cycle_api() -> dict[str, object]:
    return cockpit_cycle_payload(await cached_cockpit_context())


@router.get("/api/audit/{ticker}")
async def cockpit_audit_api(ticker: str) -> dict[str, object]:
    try:
        return cockpit_audit_payload(await cached_cockpit_context(), ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/cockpit/ticker/{ticker}")
async def cockpit_ticker_detail_api(ticker: str) -> dict[str, object]:
    try:
        return await cockpit_ticker_detail_payload(normalize_ticker(ticker))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cockpit/submit")
async def cockpit_submit(request: Request) -> JSONResponse:
    """Submit the cockpit paper manifest through the execution-preview safety path."""

    if _env_bool_text("LIVE_TRADING"):
        raise HTTPException(
            status_code=403,
            detail="Cockpit clearance is paper-only; live trading is locked off.",
        )
    body = await request.body()
    payload = _cockpit_submit_payload_from_body(request, body)
    if _cockpit_submit_ack(payload) is not True:
        raise HTTPException(status_code=400, detail="Confirm the paper-only submit checkbox first.")
    if _cockpit_submit_phrase(payload).strip() != "submit paper orders":
        raise HTTPException(status_code=400, detail="Type the exact phrase: submit paper orders.")
    orders = _cockpit_submit_orders_from_json(payload) if _cockpit_payload_is_json(request) else _cockpit_submit_orders_from_form(payload)
    if not orders:
        raise HTTPException(status_code=400, detail="No paper order rows were included in the cockpit manifest.")

    broker, data_sources = await asyncio.gather(
        _fresh_broker_status_context(),
        runtime_data_source_status(),
    )
    _require_immediate_execution_freshness(broker, data_sources)
    context = await execution_preview_context(
        broker=broker,
        data_sources=data_sources,
        validate_contracts=True,
    )
    gate = _mapping_field(context, "execution_freshness_gate")
    if gate.get("ready") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(gate.get("detail") or "Execution data is not fresh enough."),
        )

    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    reconcile_pending: list[dict[str, object]] = []
    for order in orders:
        row = row_from_execution_context(
            context,
            cycle_id=str(order["cycle_id"]),
            ticker=str(order["ticker"]),
            as_of=str(order["as_of"]),
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"execution preview not found for {order['ticker']}")
        if str(row.get("order_intent_hash") or "") != str(order["order_intent_hash"]):
            raise HTTPException(status_code=409, detail="order intent changed; refresh cockpit and approve again")
        _reject_tampered_cockpit_order_hints(row, order)
        try:
            await submit_execution_order(
                request=request,
                cycle_id=str(row["cycle_id"]),
                ticker=str(row["ticker"]),
                as_of=str(row["as_of"]),
                order_intent_hash=str(row["order_intent_hash"]),
            )
        except HTTPException as exc:
            if exc.status_code == 202:
                accepted_row = {
                    "ticker": str(row.get("ticker") or order["ticker"]),
                    "broker_order_id": str(
                        row.get("broker_order_id")
                        or row.get("order_id")
                        or row.get("submitted_order_id")
                        or ""
                    ),
                    "order_intent_hash": str(row.get("order_intent_hash") or ""),
                    "detail": str(exc.detail),
                    "status_code": exc.status_code,
                }
                accepted.append(accepted_row)
                reconcile_pending.append(accepted_row)
                continue
            rejected.append(
                {
                    "ticker": str(row.get("ticker") or order["ticker"]),
                    "detail": str(exc.detail),
                    "status_code": exc.status_code,
                }
            )
        else:
            accepted.append(
                {
                    "ticker": str(row.get("ticker") or order["ticker"]),
                    "broker_order_id": str(
                        row.get("broker_order_id")
                        or row.get("order_id")
                        or row.get("submitted_order_id")
                        or ""
                    ),
                    "order_intent_hash": str(row.get("order_intent_hash") or ""),
                }
            )
    if reconcile_pending and not rejected:
        return JSONResponse(
            {
                "state": "reconcile_pending",
                "detail": "Paper submit was accepted and needs broker reconciliation.",
                "accepted": accepted,
                "rejected": rejected,
            },
            status_code=202,
        )
    if accepted and rejected:
        return JSONResponse(
            {
                "state": "partial",
                "detail": "Some paper orders were accepted and some require review.",
                "accepted": accepted,
                "rejected": rejected,
            },
            status_code=207,
        )
    if rejected:
        return JSONResponse(
            {
                "state": "rejected",
                "detail": "No paper orders were submitted. Review the rejected rows below.",
                "accepted": accepted,
                "rejected": rejected,
            },
            status_code=409,
        )
    return JSONResponse(
        {
            "state": "accepted",
            "detail": "Paper manifest accepted by the execution-preview submit path.",
            "accepted": accepted,
            "rejected": rejected,
        }
    )


def _cockpit_submit_payload_from_body(
    request: Request,
    body: bytes,
) -> Mapping[str, object]:
    if _cockpit_payload_is_json(request):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid cockpit submit JSON payload.") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Cockpit submit JSON payload must be an object.")
        return payload
    return parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)


def _cockpit_payload_is_json(request: Request) -> bool:
    return "application/json" in request.headers.get("content-type", "").lower()


def _cockpit_submit_ack(payload: Mapping[str, object]) -> bool:
    if "orders" in payload:
        value = payload.get("submit_ack", payload.get("submit_gate_armed", False))
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return _cockpit_form_first(payload, "submit_ack") == "on"


def _cockpit_submit_phrase(payload: Mapping[str, object]) -> str:
    if "orders" in payload:
        return str(payload.get("submit_phrase") or payload.get("operator_phrase") or "")
    return _cockpit_form_first(payload, "submit_phrase")


def _cockpit_submit_orders_from_json(payload: Mapping[str, object]) -> list[dict[str, object]]:
    raw_orders = payload.get("orders", [])
    if not isinstance(raw_orders, Sequence) or isinstance(raw_orders, str | bytes):
        raise HTTPException(status_code=400, detail="Cockpit submit orders must be a list.")
    orders: list[dict[str, object]] = []
    for raw_order in raw_orders:
        if not isinstance(raw_order, Mapping):
            raise HTTPException(status_code=400, detail="Each cockpit submit order must be an object.")
        ticker = str(raw_order.get("ticker") or "").strip().upper()
        orders.append(
            {
                "cycle_id": str(raw_order.get("cycle_id") or ""),
                "ticker": ticker,
                "as_of": str(raw_order.get("as_of") or ""),
                "order_intent_hash": str(raw_order.get("order_intent_hash") or ""),
                "notional_hint": str(raw_order.get("notional_hint") or ""),
                "side_hint": str(raw_order.get("side_hint") or ""),
            }
        )
    return [
        order
        for order in orders
        if order["cycle_id"] and order["ticker"] and order["as_of"]
    ]


def _cockpit_submit_orders_from_form(form: object) -> list[dict[str, object]]:
    cycles = _cockpit_form_values(form, "cycle_id")
    tickers = _cockpit_form_values(form, "ticker")
    as_of_values = _cockpit_form_values(form, "as_of")
    hashes = _cockpit_form_values(form, "order_intent_hash")
    notional_hints = _cockpit_form_values(form, "notional_hint")
    side_hints = _cockpit_form_values(form, "side_hint")
    orders: list[dict[str, object]] = []
    for index, ticker in enumerate(tickers):
        orders.append(
            {
                "cycle_id": _indexed(cycles, index),
                "ticker": ticker.upper(),
                "as_of": _indexed(as_of_values, index),
                "order_intent_hash": _indexed(hashes, index),
                "notional_hint": _indexed(notional_hints, index),
                "side_hint": _indexed(side_hints, index),
            }
        )
    return [
        order
        for order in orders
        if order["cycle_id"] and order["ticker"] and order["as_of"]
    ]


def _cockpit_form_first(form: object, key: str) -> str:
    values = _cockpit_form_values(form, key)
    return values[0] if values else ""


def _cockpit_form_values(form: object, key: str) -> list[str]:
    getlist = getattr(form, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(key)]
    value = getattr(form, "get", lambda _key: None)(key)
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)] if value is not None else []


def _indexed(values: Sequence[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _reject_tampered_cockpit_order_hints(
    row: Mapping[str, object],
    order: Mapping[str, object],
) -> None:
    side_hint = str(order.get("side_hint") or "").upper()
    if side_hint and side_hint != str(row.get("side") or "").upper():
        raise HTTPException(
            status_code=409,
            detail="Order side changed since the page loaded; refresh cockpit before submitting.",
        )
    notional_hint = _optional_float_text(order.get("notional_hint"))
    row_notional = _optional_float_field(row, "notional")
    if notional_hint is not None and row_notional is not None and abs(notional_hint - row_notional) > 0.01:
        raise HTTPException(
            status_code=409,
            detail="Order value changed since the page loaded; refresh cockpit before submitting.",
        )


def _optional_float_text(value: object) -> float | None:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@router.get("/status/paper-review")
async def paper_review_status() -> dict[str, object]:
    return await paper_review_status_context()


@router.get("/status/execution-preview")
async def execution_preview_status() -> dict[str, object]:
    return _execution_preview_status_payload(await _execution_preview_route_base_context())


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
    background_tasks.add_task(
        run_manual_massive_lane_refresh,
        lane_id,
    )
    return RedirectResponse(url="/#scheduler-heading", status_code=303)


@router.post("/scheduler/datasets/{dataset}/refresh")
async def refresh_scheduler_dataset(
    dataset: str,
    background_tasks: BackgroundTasks,
) -> Response:
    background_tasks.add_task(
        run_manual_dataset_refresh,
        dataset,
    )
    return RedirectResponse(url="/#scheduler-heading", status_code=303)


@router.post("/scheduler/subscription-emails/login-refresh")
async def refresh_subscription_email_with_login(
    background_tasks: BackgroundTasks,
) -> Response:
    background_tasks.add_task(launch_subscription_email_login_refresh)
    return RedirectResponse(url="/#scheduler-heading", status_code=303)


@router.get("/candidates/{ticker}")
async def candidate_detail(request: Request, ticker: str) -> Response:
    audit_mode = str(request.query_params.get("audit") or "").strip().lower()
    return_source = str(request.query_params.get("from") or "").strip().lower()
    return templates.TemplateResponse(
        request,
        "candidate_detail.html",
        await candidate_detail_context(
            ticker,
            include_rich_signal_evidence=audit_mode != "light",
            return_source=return_source,
        ),
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
    return_to: str | None = None,
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
            if caution_acknowledged:
                await build_and_persist_human_review_event(
                    session,
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                    caution_acknowledged=True,
                )
            else:
                await build_and_persist_human_review_event(
                    session,
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                )
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        try:
            if caution_acknowledged:
                event = build_human_review_event(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                    caution_acknowledged=True,
                )
            else:
                event = build_human_review_event(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                )
            append_runtime_lifecycle_event_artifact(event)
        except ValueError as review_error:
            raise HTTPException(status_code=400, detail=str(review_error)) from review_error
        except OSError as write_error:
            raise HTTPException(
                status_code=503,
                detail="review persistence unavailable",
            ) from write_error
    _clear_operator_route_caches()
    return RedirectResponse(
        url=_candidate_review_redirect_url(
            ticker=ticker,
            decision=decision,
            return_to=return_to,
        ),
        status_code=303,
    )


@router.post("/candidates/{ticker}/llm-review")
async def run_candidate_llm_review(request: Request, ticker: str) -> Response:
    normalized_ticker = ticker.upper()
    cycle_id = await _request_value(request, "cycle_id")
    as_of = await _request_value(request, "as_of")
    if not cycle_id or not as_of:
        raise HTTPException(
            status_code=400,
            detail="cycle_id and as_of are required to run a hashable candidate LLM review",
        )
    report = await _selection_report_for_manual_llm_review(
        ticker=normalized_ticker,
        cycle_id=cycle_id,
        as_of=as_of,
    )
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="selection report not found; refresh the candidate page before rerunning LLM review",
        )
    evidence_pack = _mapping_field(report, "evidence_pack")
    deterministic = evaluate_deterministic_rules(evidence_pack).decision
    provider = OpenAILlmReviewProvider.from_env(enabled=True)
    llm_event: dict[str, object] | None = None
    try:
        result = await provider.review(evidence_pack, deterministic)
        event_time = datetime.now(UTC).isoformat()
        llm_event = _manual_llm_lifecycle_event(
            result.lifecycle_event,
            event_time=event_time,
        )
        updated_report = build_final_selection(
            evidence_pack,
            generated_at=str(report["generated_at"]),
            llm_review=result.review,
            llm_lifecycle_event=llm_event,
        ).selection_report
        prompt_audit = (
            _manual_prompt_audit(result.prompt_audit, event_time=event_time)
            if result.prompt_audit is not None
            else None
        )
        async with get_session() as session:
            await upsert_selection_report(session, updated_report)
            await record_candidate_lifecycle_event(session, llm_event)
            if prompt_audit is not None:
                await record_prompt_audit(session, prompt_audit)
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        if llm_event is not None:
            with suppress(OSError):
                append_runtime_lifecycle_event_artifact(llm_event)
        raise HTTPException(
            status_code=503,
            detail="LLM review completed but report persistence is unavailable",
        ) from exc
    return RedirectResponse(
        url=f"/candidates/{normalized_ticker}?llm_review=completed",
        status_code=303,
    )


@router.get("/final-selection")
async def final_selection(request: Request) -> Response:
    focus_ticker = str(request.query_params.get("ticker") or "").strip().upper()
    return templates.TemplateResponse(
        request,
        "final_selection.html",
        await _final_selection_route_context(focus_ticker=focus_ticker or None),
    )


async def _final_selection_route_context(
    *,
    focus_ticker: str | None,
) -> dict[str, object]:
    if not focus_ticker:
        context = await final_selection_context()
        _store_final_selection_route_cache(context)
        return context
    context = await _final_selection_route_base_context(focus_ticker=focus_ticker)
    context["focused_ticker"] = focus_ticker
    rows_value = context.get("final_rows")
    final_rows = rows_value if isinstance(rows_value, list) else []
    context["focused_final_selection"] = final_selection_focus_context(
        final_rows,
        focus_ticker,
    )
    return context


async def _final_selection_route_base_context(
    *,
    focus_ticker: str | None = None,
) -> dict[str, object]:
    if focus_ticker:
        return await final_selection_context(focus_ticker=focus_ticker)
    cached = _final_selection_route_cache.get("context")
    expires_at = _final_selection_route_cache.get("expires_at", 0.0)
    builder_id = id(final_selection_context)
    if (
        isinstance(cached, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _final_selection_route_cache.get("builder_id") == builder_id
    ):
        return dict(cached)
    context = await final_selection_context()
    _store_final_selection_route_cache(context)
    return context


def _store_final_selection_route_cache(context: Mapping[str, object]) -> None:
    cached_context = dict(context)
    cached_context["focused_ticker"] = ""
    cached_context["focused_final_selection"] = final_selection_focus_context([], None)
    _final_selection_route_cache["context"] = cached_context
    _final_selection_route_cache["expires_at"] = (
        time.monotonic() + FINAL_SELECTION_ROUTE_CACHE_TTL_SECONDS
    )
    _final_selection_route_cache["builder_id"] = id(final_selection_context)


def _clear_final_selection_route_cache() -> None:
    _final_selection_route_cache["context"] = None
    _final_selection_route_cache["expires_at"] = 0.0
    _final_selection_route_cache["builder_id"] = 0


@router.post("/execution-preview/operator-advance")
async def record_operator_manual_advance(
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    override_reason: str | None = None,
    blocked_reason: str | None = None,
    acknowledged: bool = False,
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
                "current selection report not found; refresh the execution preview "
                "before recording a hash-bound manual advance"
            ),
        )
    reason = override_reason or await _request_form_text(request, "override_reason")
    blocked = blocked_reason or await _request_form_text(request, "blocked_reason")
    acknowledged = acknowledged or await _request_form_bool(request, "acknowledged")
    try:
        event = build_operator_manual_advance_event(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
            selection_report_hash=report_hash,
            override_reason=reason or "",
            blocked_reason=blocked,
            acknowledged=acknowledged,
        )
        async with get_session() as session:
            await record_candidate_lifecycle_event(session, event)
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        try:
            append_runtime_lifecycle_event_artifact(event)
        except OSError as write_error:
            raise HTTPException(
                status_code=503,
                detail="operator manual advance could not be persisted",
            ) from write_error
    _clear_operator_route_caches()
    normalized_ticker = ticker.upper()
    query = urlencode({"ticker": normalized_ticker})
    return RedirectResponse(
        url=f"/execution-preview?{query}#focused-preview-{normalized_ticker}",
        status_code=303,
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
    focus_ticker = str(request.query_params.get("ticker") or "").strip().upper()
    context = await _execution_preview_route_context(focus_ticker=focus_ticker or None)
    notice = _execution_notice_from_request(request)
    if notice is not None:
        context["execution_notice"] = notice
    return templates.TemplateResponse(
        request,
        "execution_preview.html",
        context,
    )


async def _execution_preview_route_context(
    *,
    focus_ticker: str | None,
) -> dict[str, object]:
    if not focus_ticker:
        context = await execution_preview_context()
        _store_execution_preview_route_cache(context)
        return context
    context = await _execution_preview_route_base_context()
    rows_value = context.get("preview_rows")
    preview_rows = rows_value if isinstance(rows_value, list) else []
    context["focused_execution"] = execution_preview_focus_context(
        preview_rows,
        focus_ticker,
    )
    return context


async def _execution_preview_route_base_context() -> dict[str, object]:
    cached = _execution_preview_route_cache.get("context")
    expires_at = _execution_preview_route_cache.get("expires_at", 0.0)
    builder_id = id(execution_preview_context)
    if (
        isinstance(cached, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _execution_preview_route_cache.get("builder_id") == builder_id
    ):
        return dict(cached)
    context = await execution_preview_context()
    _store_execution_preview_route_cache(context)
    return context


def _store_execution_preview_route_cache(context: Mapping[str, object]) -> None:
    _execution_preview_route_cache["context"] = dict(context)
    _execution_preview_route_cache["expires_at"] = (
        time.monotonic() + EXECUTION_PREVIEW_ROUTE_CACHE_TTL_SECONDS
    )
    _execution_preview_route_cache["builder_id"] = id(execution_preview_context)


def _clear_execution_preview_route_cache() -> None:
    _execution_preview_route_cache["context"] = None
    _execution_preview_route_cache["expires_at"] = 0.0
    _execution_preview_route_cache["builder_id"] = 0


def _execution_preview_status_payload(
    context: dict[str, object],
) -> dict[str, object]:
    summary = _mapping_field(context, "summary")
    preview_rows_value = context.get("preview_rows")
    preview_rows = preview_rows_value if isinstance(preview_rows_value, list) else []
    rows = [
        _execution_preview_status_row(row)
        for row in preview_rows
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
        "submit_gate_label": _operator_text(summary.get("submit_gate_label") or "Unknown"),
        "headline": _operator_text(summary.get("headline") or ""),
        "detail": _operator_text(summary.get("detail") or ""),
        "freshness_gate": {
            "ready": freshness.get("ready") is True,
            "status_label": _operator_text(freshness.get("status_label") or "Unknown"),
            "status_class": str(freshness.get("status_class") or "neutral"),
            "detail": _operator_text(freshness.get("detail") or ""),
        },
        "rows": rows,
        "blockers": blockers[:20],
    }


def _execution_preview_status_row(row: dict[str, object]) -> dict[str, object]:
    reasons = row.get("paper_promotion_reasons")
    paper_promotion_reasons = reasons if isinstance(reasons, list) else []
    return {
        "cycle_id": str(row.get("cycle_id") or ""),
        "ticker": str(row.get("ticker") or "").upper(),
        "as_of": str(row.get("as_of") or ""),
        "preview_state": _operator_text(row.get("preview_state") or ""),
        "side": str(row.get("side") or "NONE"),
        "risk_decision": _operator_text(row.get("risk_decision") or ""),
        "submit_enabled": row.get("submit_enabled") is True,
        "order_approval_available": row.get("order_approval_available") is True,
        "submit_blocker": _operator_text(row.get("submit_blocker") or ""),
        "paper_promotion_status_label": _operator_text(
            row.get("paper_promotion_status_label") or ""
        ),
        "paper_promotion_reasons": [
            _operator_text(reason)
            for reason in paper_promotion_reasons
            if reason is not None
        ],
        "order_intent_hash_label": str(row.get("order_intent_hash_label") or ""),
        "order_value_label": _operator_text(row.get("order_value_label") or ""),
        "approval_label": _operator_text(row.get("approval_label") or ""),
        "execution_state": str(row.get("execution_state") or "NONE"),
        "execution_status_label": _operator_text(row.get("execution_status_label") or ""),
        "execution_status_class": str(row.get("execution_status_class") or "neutral"),
        "execution_reason": _operator_text(row.get("execution_reason") or ""),
        "execution_event_time": str(row.get("execution_event_time") or ""),
        "execution_event_time_label": str(row.get("execution_event_time_label") or ""),
        "client_order_id": str(row.get("client_order_id") or ""),
        "filled_qty": row.get("filled_qty"),
        "filled_avg_price": row.get("filled_avg_price"),
        "submission_confirmation_label": _operator_text(
            row.get("submission_confirmation_label") or ""
        ),
        "next_step": _operator_text(row.get("next_step") or ""),
    }


def _execution_preview_blocker(row: dict[str, object]) -> dict[str, object]:
    reasons = row.get("paper_promotion_reasons")
    first_reason = ""
    if isinstance(reasons, list) and reasons:
        first_reason = str(reasons[0])
    reason = _operator_text(
        first_reason or str(row.get("submit_blocker") or row.get("next_step") or "")
    )
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


def _status_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key, 0)
    return value if isinstance(value, int) else 0


def _execution_notice_from_request(request: Request) -> dict[str, object] | None:
    detail = str(request.query_params.get("execution_notice") or "").strip()
    if not detail:
        return None
    status_class = str(request.query_params.get("execution_notice_class") or "warn")
    if status_class not in {"pass", "warn", "block", "neutral"}:
        status_class = "warn"
    return {
        "headline": "Execution action needs attention",
        "detail": detail[:500],
        "status_class": status_class,
    }


def _execution_preview_notice_redirect(
    detail: str,
    *,
    status_class: str = "warn",
    ticker: str | None = None,
    anchor: str = "orderable-heading",
) -> RedirectResponse:
    message = detail.strip() or "Execution action could not be completed."
    query_values = {
        "execution_notice": message[:500],
        "execution_notice_class": status_class,
    }
    normalized_ticker = str(ticker or "").strip().upper()
    if normalized_ticker:
        query_values["ticker"] = normalized_ticker
        anchor = f"focused-preview-{normalized_ticker}"
    query = urlencode(query_values)
    return RedirectResponse(url=f"/execution-preview?{query}#{anchor}", status_code=303)


@router.post("/execution-preview/orders/approve")
async def approve_execution_order(
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    del request
    try:
        broker, data_sources = await asyncio.gather(
            _fresh_broker_status_context(),
            runtime_data_source_status(),
        )
        context = await execution_preview_context(
            broker=broker,
            data_sources=data_sources,
            validate_contracts=True,
        )
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
    except HTTPException as exc:
        return _execution_preview_notice_redirect(str(exc.detail), ticker=ticker)
    _clear_operator_route_caches()
    normalized_ticker = ticker.upper()
    query = urlencode({"ticker": normalized_ticker})
    return RedirectResponse(
        url=f"/execution-preview?{query}#focused-preview-{normalized_ticker}",
        status_code=303,
    )


@router.post("/execution-preview/orders")
async def submit_execution_order(
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    normalized_ticker = ticker.upper()
    if not _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED"):
        return _execution_preview_notice_redirect("Alpaca broker is disabled", ticker=normalized_ticker)
    policy = await load_active_portfolio_policy()
    if not policy.broker_submit_enabled:
        return _execution_preview_notice_redirect("broker submission is disabled", ticker=normalized_ticker)
    broker, data_sources = await asyncio.gather(
        _fresh_broker_status_context(),
        runtime_data_source_status(),
    )
    try:
        _require_immediate_execution_freshness(broker, data_sources)
    except HTTPException as exc:
        return _execution_preview_notice_redirect(str(exc.detail), ticker=normalized_ticker)
    context = await execution_preview_context(
        broker=broker,
        data_sources=data_sources,
        validate_contracts=True,
    )
    gate = _mapping_field(context, "execution_freshness_gate")
    if gate["ready"] is not True:
        return _execution_preview_notice_redirect(str(gate["detail"]), ticker=normalized_ticker)
    row = row_from_execution_context(
        context,
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if row is None:
        return _execution_preview_notice_redirect("execution preview not found", ticker=normalized_ticker)
    if str(row["order_intent_hash"]) != order_intent_hash:
        return _execution_preview_notice_redirect(
            "order intent changed; refresh and approve again",
            ticker=normalized_ticker,
        )
    if row["order_approved"] is not True:
        return _execution_preview_notice_redirect(
            "hash-bound order approval required",
            ticker=normalized_ticker,
        )
    if row["submit_enabled"] is not True:
        return _execution_preview_notice_redirect(str(row["submit_blocker"]), ticker=normalized_ticker)
    submit_gate_armed, operator_phrase = await _paper_submit_confirmation(request)
    if submit_gate_armed is not True or operator_phrase.strip().lower() != "submit paper orders":
        return _execution_preview_notice_redirect(
            "Final paper-submit confirmation phrase is required.",
            ticker=normalized_ticker,
        )
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
            return _execution_preview_notice_redirect(
                (
                    "paper order was submitted, but broker reconciliation failed; "
                    "verify Alpaca before retrying"
                ),
                status_class="warn",
                ticker=normalized_ticker,
            )
        return _execution_preview_notice_redirect(str(exc), status_class="block", ticker=normalized_ticker)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        if order_submitted:
            return _execution_preview_notice_redirect(
                (
                    "paper order was submitted, but execution audit persistence failed; "
                    "verify Alpaca before retrying"
                ),
                status_class="warn",
                ticker=normalized_ticker,
            )
        return _execution_preview_notice_redirect(
            "order intent or submission audit persistence failed",
            status_class="block",
            ticker=normalized_ticker,
        )
    _clear_operator_route_caches()
    query = urlencode({"ticker": normalized_ticker})
    return RedirectResponse(
        url=f"/execution-preview?{query}#focused-preview-{normalized_ticker}",
        status_code=303,
    )


async def _paper_submit_confirmation(request: Request) -> tuple[bool, str]:
    body = await request.body()
    if _cockpit_payload_is_json(request):
        payload = _cockpit_submit_payload_from_body(request, body)
        return _cockpit_submit_ack(payload), _cockpit_submit_phrase(payload)
    values = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    armed_value = str(
        next(iter(values.get("submit_gate_armed") or values.get("submit_ack") or [""]), "")
    )
    phrase = str(
        next(iter(values.get("operator_phrase") or values.get("submit_phrase") or [""]), "")
    )
    return armed_value.strip().lower() in {"1", "true", "yes", "on"}, phrase


async def _fresh_broker_status_context() -> dict[str, object]:
    try:
        return await broker_status_context(use_cache=False)
    except TypeError:
        return await broker_status_context()


def _require_immediate_execution_freshness(
    broker: dict[str, object],
    data_sources: list[dict[str, object]],
) -> dict[str, object]:
    current_time = _execution_freshness_now()
    market_phase = classify_market_session(current_time).phase
    gate = execution_freshness_gate(
        broker,
        data_sources,
        now=current_time,
        market_phase=market_phase,
    )
    if gate.get("ready") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(
                gate.get("detail")
                or "Broker state or critical market evidence is not fresh enough to submit."
            ),
        )
    return gate


def _execution_freshness_now() -> datetime:
    return datetime.now(UTC)


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
    reconciled_order = submitted_order
    for attempt in range(1, BROKER_RECONCILIATION_MAX_ATTEMPTS + 1):
        try:
            reconciled_order = await client.order_by_client_order_id(client_order_id)
        except AlpacaBrokerError as exc:
            return submitted_order, {
                "state": "client_order_id_lookup_failed",
                "client_order_id": client_order_id,
                "attempt_count": attempt,
                "error": str(exc),
            }
        reconciled_client_order_id = str(
            reconciled_order.get("client_order_id") or ""
        ).strip()
        if reconciled_client_order_id != client_order_id:
            raise AlpacaBrokerError(
                "Alpaca paper order reconciliation returned a different client_order_id"
            )
        status = str(reconciled_order.get("status", "")).upper()
        terminal = status in BROKER_RECONCILIATION_TERMINAL_STATUSES
        if terminal or attempt == BROKER_RECONCILIATION_MAX_ATTEMPTS:
            return reconciled_order, {
                "state": "client_order_id_confirmed",
                "client_order_id": client_order_id,
                "attempt_count": attempt,
                "terminal": terminal,
                "order_id_present": bool(str(reconciled_order.get("order_id", "")).strip()),
                "status": status,
            }
        await asyncio.sleep(BROKER_RECONCILIATION_POLL_SECONDS)
    return reconciled_order, {
        "state": "client_order_id_confirmed",
        "client_order_id": client_order_id,
        "attempt_count": BROKER_RECONCILIATION_MAX_ATTEMPTS,
        "terminal": False,
        "order_id_present": bool(str(reconciled_order.get("order_id", "")).strip()),
        "status": str(reconciled_order.get("status", "")).upper(),
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


async def _selection_report_for_manual_llm_review(
    *,
    ticker: str,
    cycle_id: str,
    as_of: str,
) -> dict[str, object] | None:
    reports = await _dashboard_selection_reports(ticker=ticker, limit=50)
    key = (cycle_id, ticker.upper(), as_of)
    for report in reports:
        if _runtime_payload_key(report) == key:
            return dict(report)
    return None


def _manual_llm_lifecycle_event(
    event: Mapping[str, object],
    *,
    event_time: str,
) -> dict[str, object]:
    output = dict(event)
    cycle_id = str(output["cycle_id"])
    ticker = str(output["ticker"]).upper()
    event_type = str(output["event_type"])
    output["ticker"] = ticker
    output["event_time"] = event_time
    output["event_id"] = make_lifecycle_event_id(
        cycle_id=cycle_id,
        ticker=ticker,
        event_type=event_type,
        event_time=event_time,
    )
    payload = output.get("payload")
    output["payload"] = {
        **(dict(payload) if isinstance(payload, Mapping) else {}),
        "manual_trigger": True,
        "triggered_by": "candidate_detail",
    }
    return output


def _manual_prompt_audit(
    prompt_audit: Mapping[str, object],
    *,
    event_time: str,
) -> dict[str, object]:
    output = dict(prompt_audit)
    output["created_at"] = event_time
    payload = output.get("payload")
    output["payload"] = {
        **(dict(payload) if isinstance(payload, Mapping) else {}),
        "manual_trigger": True,
        "triggered_by": "candidate_detail",
    }
    return output


async def _request_value(request: Request, field_name: str) -> str | None:
    value = request.query_params.get(field_name)
    if value is not None and value.strip():
        return " ".join(value.split())
    return await _request_form_text(request, field_name)


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


async def _request_form_text(request: Request, field_name: str) -> str | None:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        try:
            body = (await request.body()).decode("utf-8")
        except UnicodeDecodeError:
            return None
        values = parse_qs(body, keep_blank_values=True)
        return _clean_form_text(values.get(field_name, [""])[0])
    if "multipart/form-data" not in content_type:
        return None
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return None
    return _clean_form_text(form.get(field_name))


def _truthy_form_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clean_form_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


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
    # Legacy alias. The V3 navigation exposes this workflow as "Universe & market".
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
