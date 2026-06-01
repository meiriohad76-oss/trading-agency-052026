"""Production view model for the V3 pre-flight cockpit."""
from __future__ import annotations

import asyncio
import math
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from time import monotonic
from typing import cast

from agency.api.health import runtime_data_source_status
from agency.runtime.cockpit_monitor import (
    monitor_events_from_scheduler,
    monitor_status_from_scheduler,
    source_health_rows,
)
from agency.runtime.ticker_reference import load_ticker_reference_index
from agency.views._shared import (
    REFRESHABLE_DATASET_TO_LANE,
    REFRESHABLE_MASSIVE_LANES,
    RUNNABLE_MASSIVE_LANES,
    _dashboard_selection_reports,
    _label_text,
    dashboard_data_health,
    live_runtime_source_health_rows,
)
from agency.views.execution import execution_preview_context
from agency.views.market_regime import broker_status_context

TRADE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}
MAX_COCKPIT_CANDIDATES = 25
QA_SCENARIOS = {"normal", "no-actionable", "outage", "submitted"}
DEFAULT_SECTOR_LABEL = "Reference data not loaded"
DEFAULT_OPTIONAL_CONTEXT_TIMEOUT_SECONDS = 1.0
DEFAULT_REQUIRED_CONTEXT_TIMEOUT_SECONDS = 8.0
DEFAULT_SOURCE_LOAD_TIMEOUT_SECONDS = 1.5
DEFAULT_TICKER_DETAIL_TIMEOUT_SECONDS = 1.5
COCKPIT_CONTEXT_CACHE_SECONDS = 30.0
COCKPIT_CONTEXT_MAX_STALE_SECONDS = 120.0
COCKPIT_CONTEXT_WARM_TIMEOUT_SECONDS = 45.0
COCKPIT_DATA_HEALTH_DATASETS = (
    "prices_daily",
    "stock_trades",
    "sec_company_facts",
    "sec_form4",
    "sec_13f",
    "news_rss",
    "subscription_emails",
)

ContextBuilder = Callable[[], Awaitable[dict[str, object]]]
CockpitContextCacheKey = tuple[str | None, bool | None]
_cockpit_context_cache: dict[CockpitContextCacheKey, tuple[float, dict[str, object]]] = {}
_cockpit_context_inflight: dict[CockpitContextCacheKey, asyncio.Task[dict[str, object]]] = {}


async def warm_cockpit_context_cache(
    *,
    timeout_seconds: float = COCKPIT_CONTEXT_WARM_TIMEOUT_SECONDS,
) -> bool:
    """Prime the cockpit cache so the first operator/API request is responsive."""

    try:
        await asyncio.wait_for(cached_cockpit_context(), timeout=timeout_seconds)
    except Exception:
        return False
    return True


async def cached_cockpit_context(
    *,
    qa_scenario: str | None = None,
    qa_scenarios_enabled: bool | None = None,
) -> dict[str, object]:
    """Coalesce concurrent cockpit route/API reads without hiding live changes."""

    key = (qa_scenario, qa_scenarios_enabled)
    cached = _cockpit_context_cache.get(key)
    if cached is not None:
        cached_at, context = cached
        cache_age = monotonic() - cached_at
        if cache_age <= COCKPIT_CONTEXT_CACHE_SECONDS:
            return deepcopy(context)
        if cache_age <= COCKPIT_CONTEXT_MAX_STALE_SECONDS:
            _refresh_cockpit_context_cache_in_background(
                key,
                qa_scenario=qa_scenario,
                qa_scenarios_enabled=qa_scenarios_enabled,
            )
            return deepcopy(context)
        _cockpit_context_cache.pop(key, None)
    task = _cockpit_context_inflight.get(key)
    if task is None or task.done():
        task = asyncio.create_task(
            cockpit_context(
                qa_scenario=qa_scenario,
                qa_scenarios_enabled=qa_scenarios_enabled,
            )
        )
        _cockpit_context_inflight[key] = task
    try:
        context = await task
    except Exception:
        if _cockpit_context_inflight.get(key) is task:
            _cockpit_context_inflight.pop(key, None)
        raise
    if _cockpit_context_inflight.get(key) is task:
        _cockpit_context_inflight.pop(key, None)
    _cockpit_context_cache[key] = (monotonic(), deepcopy(context))
    return deepcopy(context)


def _refresh_cockpit_context_cache_in_background(
    key: CockpitContextCacheKey,
    *,
    qa_scenario: str | None,
    qa_scenarios_enabled: bool | None,
) -> None:
    task = _cockpit_context_inflight.get(key)
    if task is not None and not task.done():
        return
    task = asyncio.create_task(
        cockpit_context(
            qa_scenario=qa_scenario,
            qa_scenarios_enabled=qa_scenarios_enabled,
        )
    )
    _cockpit_context_inflight[key] = task
    task.add_done_callback(lambda completed: _store_cockpit_context_refresh(key, completed))


def _store_cockpit_context_refresh(
    key: CockpitContextCacheKey,
    task: asyncio.Task[dict[str, object]],
) -> None:
    try:
        context = task.result()
    except BaseException:
        if _cockpit_context_inflight.get(key) is task:
            _cockpit_context_inflight.pop(key, None)
        return
    if _cockpit_context_inflight.get(key) is task:
        _cockpit_context_inflight.pop(key, None)
    _cockpit_context_cache[key] = (monotonic(), deepcopy(context))


async def cockpit_context(
    *,
    qa_scenario: str | None = None,
    qa_scenarios_enabled: bool | None = None,
) -> dict[str, object]:
    """Build the cockpit aggregate from existing production page contexts."""

    from agency.views.command import (
        _runtime_data_source_status_with_load_status_live,
        dashboard_context,
        data_load_status_view,
        paper_review_status_context,
        source_status_rows,
    )
    from agency.views.portfolio import portfolio_monitor_context

    optional_timeout = _optional_context_timeout_seconds()
    required_timeout = _required_context_timeout_seconds()
    dashboard, execution, portfolio, paper_review = await asyncio.gather(
        _source_context(
            "dashboard",
            dashboard_context,
            timeout_seconds=required_timeout,
        ),
        _source_context(
            "execution",
            _cockpit_execution_preview_context,
            timeout_seconds=optional_timeout,
        ),
        _source_context(
            "portfolio",
            portfolio_monitor_context,
            timeout_seconds=optional_timeout,
        ),
        _source_context(
            "paper_review",
            paper_review_status_context,
            timeout_seconds=required_timeout,
        ),
    )
    dashboard = await _dashboard_with_cockpit_data_proof(
        dashboard,
        source_load_status_builder=_runtime_data_source_status_with_load_status_live,
        data_load_status_view_builder=data_load_status_view,
        source_status_rows_builder=source_status_rows,
    )
    dashboard = _dashboard_with_paper_review(dashboard, paper_review)
    dashboard = _dashboard_with_ticker_reference(dashboard)
    context = cockpit_context_from_sources(
        {
            "dashboard": dashboard,
            "execution": execution,
            "portfolio": portfolio,
            "market": {},
            "signals": {},
        },
        qa_scenario=qa_scenario,
        qa_scenarios_enabled=qa_scenarios_enabled,
    )
    candidates = _list(context.get("candidates"))
    if candidates and _list(paper_review.get("queue")):
        return context

    # The scheduler can publish reports while a cockpit request is already
    # assembling its contexts. Re-check paper review once before trusting an
    # empty or dashboard-only partial cockpit, because the queue is the
    # operator's primary workflow.
    paper_review = await paper_review_status_context()
    dashboard = _dashboard_with_paper_review(dashboard, paper_review)
    dashboard = _dashboard_with_ticker_reference(dashboard)
    retry_context = cockpit_context_from_sources(
        {
            "dashboard": dashboard,
            "execution": execution,
            "portfolio": portfolio,
            "market": {},
            "signals": {},
        },
        qa_scenario=qa_scenario,
        qa_scenarios_enabled=qa_scenarios_enabled,
    )
    retry_candidates = _list(retry_context.get("candidates"))
    if len(retry_candidates) > len(candidates):
        return retry_context
    return context if candidates else retry_context


async def _cockpit_execution_preview_context() -> dict[str, object]:
    reports, data_sources, broker = await asyncio.gather(
        _dashboard_selection_reports(limit=MAX_COCKPIT_CANDIDATES),
        live_runtime_source_health_rows(runtime_data_source_status),
        broker_status_context(use_cache=True, allow_live_read=False),
    )
    return await execution_preview_context(
        raw_reports=reports,
        data_sources=data_sources,
        broker=broker,
    )


async def _source_context(
    name: str,
    builder: ContextBuilder,
    *,
    timeout_seconds: float,
) -> dict[str, object]:
    """Load a non-critical cockpit section without freezing the first screen."""

    task = asyncio.create_task(builder())
    done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
    if task not in done:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return _delayed_context(name, timeout_seconds=timeout_seconds)
    try:
        return task.result()
    except Exception as exc:
        return _failed_context(name, exc)


def _consume_context_task_result(task: asyncio.Task[dict[str, object]]) -> None:
    with suppress(BaseException):
        task.result()


def _optional_context_timeout_seconds() -> float:
    return _context_timeout_seconds(
        "AGENCY_COCKPIT_OPTIONAL_CONTEXT_TIMEOUT_SECONDS",
        default=DEFAULT_OPTIONAL_CONTEXT_TIMEOUT_SECONDS,
    )


def _required_context_timeout_seconds() -> float:
    return _context_timeout_seconds(
        "AGENCY_COCKPIT_REQUIRED_CONTEXT_TIMEOUT_SECONDS",
        default=DEFAULT_REQUIRED_CONTEXT_TIMEOUT_SECONDS,
    )


def _source_load_timeout_seconds() -> float:
    return _context_timeout_seconds(
        "AGENCY_COCKPIT_SOURCE_LOAD_TIMEOUT_SECONDS",
        default=DEFAULT_SOURCE_LOAD_TIMEOUT_SECONDS,
    )


def _context_timeout_seconds(env_name: str, *, default: float) -> float:
    raw = os.environ.get(env_name, "")
    if not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.1, value)


def _delayed_context(name: str, *, timeout_seconds: float) -> dict[str, object]:
    label = _source_context_label(name)
    return {
        "context_status": {
            "status": "delayed",
            "status_label": f"{label} Check Delayed",
            "status_class": "warn",
            "detail": (
                f"{label} did not finish within {timeout_seconds:.1f}s. "
                "The cockpit loaded the current review queue first; open the dedicated dashboard "
                "or refresh this section before using it for a decision."
            ),
        }
    }


def _failed_context(name: str, exc: Exception) -> dict[str, object]:
    label = _source_context_label(name)
    return {
        "context_status": {
            "status": "failed",
            "status_label": f"{label} Check Failed",
            "status_class": "block",
            "detail": f"{label} could not be loaded for the cockpit: {exc}",
        }
    }


def _source_context_label(name: str) -> str:
    return {
        "execution": "Execution Preview",
        "dashboard": "Command Dashboard",
        "paper_review": "Review Queue",
        "portfolio": "Portfolio",
    }.get(name, name.replace("_", " ").title())


def _dashboard_with_paper_review(
    dashboard: Mapping[str, object],
    paper_review: Mapping[str, object],
) -> dict[str, object]:
    queue = _list(paper_review.get("queue"))
    if not queue:
        return dict(dashboard)
    return {
        **dashboard,
        "review_queue": queue,
        "review_progress": _mapping(paper_review.get("progress")),
    }


def _dashboard_with_ticker_reference(dashboard: Mapping[str, object]) -> dict[str, object]:
    if _mapping(dashboard.get("ticker_reference")):
        return dict(dashboard)
    reference = load_ticker_reference_index()
    if not reference:
        return dict(dashboard)
    return {**dict(dashboard), "ticker_reference": reference}


async def _dashboard_with_cockpit_data_proof(
    dashboard: Mapping[str, object],
    *,
    source_load_status_builder: Callable[[], Awaitable[dict[str, object]]],
    data_load_status_view_builder: Callable[[Mapping[str, object]], dict[str, object]],
    source_status_rows_builder: Callable[[Sequence[Mapping[str, object]]], list[dict[str, object]]],
) -> dict[str, object]:
    if _dashboard_has_cockpit_data_proof(dashboard):
        return dict(dashboard)
    if not _dashboard_context_needs_data_proof_fallback(dashboard):
        return dict(dashboard)
    fallback = dict(dashboard)
    try:
        source_load_status = await asyncio.wait_for(
            source_load_status_builder(),
            timeout=_source_load_timeout_seconds(),
        )
    except TimeoutError:
        return fallback
    except Exception:
        return fallback
    data_sources = [
        _mapping(row)
        for row in _list(source_load_status.get("data_sources"))
        if _mapping(row)
    ]
    data_load_status = _mapping(source_load_status.get("data_load_status"))
    if not data_sources and not data_load_status:
        return fallback
    existing_data_load = _mapping(fallback.get("data_load_status"))
    if not _dashboard_data_load_has_lane_rows(existing_data_load):
        fallback["data_load_status"] = data_load_status_view_builder(data_load_status)
    if not _list(fallback.get("data_sources")) and data_sources:
        fallback["data_sources"] = source_status_rows_builder(data_sources)
    if not _list(_mapping(fallback.get("data_health")).get("rows")):
        fallback["data_health"] = dashboard_data_health(
            "Pre-flight cockpit",
            data_load_status=data_load_status,
            datasets=COCKPIT_DATA_HEALTH_DATASETS,
        )
    return fallback


def _dashboard_has_cockpit_data_proof(dashboard: Mapping[str, object]) -> bool:
    return _dashboard_data_load_has_lane_rows(_mapping(dashboard.get("data_load_status"))) and bool(
        _list(_mapping(dashboard.get("data_health")).get("rows"))
    )


def _dashboard_context_needs_data_proof_fallback(dashboard: Mapping[str, object]) -> bool:
    context_status = _mapping(dashboard.get("context_status"))
    status = _first_text(context_status.get("status")).lower()
    status_class = _first_text(context_status.get("status_class")).lower()
    return status in {"delayed", "failed"} or status_class == "block"


def _dashboard_data_load_has_lane_rows(data_load_status: Mapping[str, object]) -> bool:
    return bool(
        _list(data_load_status.get("lane_state_rows"))
        or _list(data_load_status.get("lane_states"))
    )


def cockpit_context_from_sources(
    sources: Mapping[str, object],
    *,
    qa_scenario: str | None = None,
    qa_scenarios_enabled: bool | None = None,
) -> dict[str, object]:
    """Map production view contexts to the cockpit contract.

    This function is intentionally pure so tests can prove the contract without
    relying on current market data or runtime services.
    """

    dashboard = _mapping(sources.get("dashboard"))
    execution = _mapping(sources.get("execution"))
    portfolio = _mapping(sources.get("portfolio"))
    market = _mapping(sources.get("market"))
    signals_context = _mapping(sources.get("signals"))
    candidates = _candidate_rows(dashboard, execution)
    engines = _engine_rows(dashboard, signals_context, execution)
    portfolio_status = _source_context_status(portfolio)
    execution_status = _source_context_status(execution)
    positions = _position_rows(portfolio)
    account = _account_section(market, portfolio, dashboard, execution, len(candidates))
    portfolio_phase = _portfolio_phase_section(positions, portfolio_status=portfolio_status)
    clearance = _clearance_section(
        positions,
        candidates,
        execution,
        execution_status=execution_status,
    )
    cycle = _cycle_section(dashboard, engines)
    qa_enabled = _qa_scenarios_enabled(qa_scenarios_enabled)
    scheduler = _mapping(dashboard.get("scheduler"))
    proof_timestamp = _first_text(
        _mapping(dashboard.get("data_load_status")).get("latest_checked_at"),
        _mapping(dashboard.get("data_load_status")).get("updated_at"),
        _mapping(dashboard.get("data_load_status")).get("as_of"),
    )
    data_state = _data_state_section(dashboard)
    context: dict[str, object] = {
        "active_nav": "cockpit",
        "cycle": cycle,
        "market": _market_section(market, dashboard),
        "engines": engines,
        "funnel": _funnel_section(dashboard, candidates),
        "candidates": candidates,
        "positions": positions,
        "account": account,
        "portfolio_phase": portfolio_phase,
        "clearance": clearance,
        "source_contexts": {
            "portfolio": portfolio_status,
            "execution": execution_status,
        },
        "sectors": _sector_rows(market),
        "sources": _source_rows(dashboard, proof_timestamp=proof_timestamp),
        "universe_blocked": _universe_blocked_rows(dashboard),
        "signals": _signal_rows(signals_context),
        "audit_lifecycle": _audit_lifecycle(candidates, _first_text(cycle.get("id"))),
        "policy": _policy_section(dashboard),
        "monitor_events": _monitor_events(dashboard),
        "monitor": monitor_status_from_scheduler(scheduler),
        "data_health": _mapping(dashboard.get("data_health")),
        "data_state": data_state,
        "preferences": _preferences_section(),
        "qa_scenarios_enabled": qa_enabled,
        "qa_scenarios": sorted(QA_SCENARIOS),
    }
    context["scenario"] = _scenario_from_context(context, execution)
    if qa_enabled and qa_scenario in QA_SCENARIOS:
        context["scenario"] = _qa_scenario(qa_scenario, context)
    context["scenario"] = _scenario_display_titles(_mapping(context.get("scenario")))
    context["phase_states"] = _phase_states(context)
    return context


def safe_cockpit_api_payload(context: Mapping[str, object]) -> dict[str, object]:
    """Return a bounded, secret-free JSON snapshot."""

    payload = dict(context)
    payload["candidates"] = _list(context.get("candidates"))[:MAX_COCKPIT_CANDIDATES]
    payload["monitor_events"] = _list(context.get("monitor_events"))[:50]
    return _scrub_secrets(payload)


def cockpit_cycle_payload(context: Mapping[str, object]) -> dict[str, object]:
    return {
        "cycle": _mapping(context.get("cycle")),
        "market": _mapping(context.get("market")),
        "engines": _list(context.get("engines")),
        "scenario": _mapping(context.get("scenario")),
    }


def cockpit_audit_payload(context: Mapping[str, object], ticker: str) -> dict[str, object]:
    normalized = normalize_ticker(ticker)
    lifecycle = _mapping(context.get("audit_lifecycle"))
    traces = _mapping(lifecycle.get("traces"))
    events = _list(traces.get(normalized))
    if not events:
        for candidate in _list(context.get("candidates")):
            row = _mapping(candidate)
            if row.get("ticker") == normalized:
                events = [
                    {
                        "message": (
                            "Approved by current cockpit context."
                            if row.get("status") == "approved"
                            else str(row.get("blocker") or "Candidate is visible for audit.")
                        ),
                        "status": str(row.get("status") or "unknown"),
                    }
                ]
                break
    return {"ticker": normalized, "events": events}


async def cockpit_ticker_detail_payload(ticker: str) -> dict[str, object]:
    """Return a compact rich-detail payload for the cockpit ticker drawer."""

    from agency.views.candidates import candidate_detail_context

    normalized = normalize_ticker(ticker)
    try:
        context = await asyncio.wait_for(
            candidate_detail_context(
                normalized,
                include_rich_signal_evidence=False,
                return_source="cockpit",
            ),
            timeout=_ticker_detail_timeout_seconds(),
        )
    except TimeoutError:
        return _cockpit_ticker_detail_timeout_payload(normalized)
    return cockpit_ticker_detail_payload_from_context(context)


def _ticker_detail_timeout_seconds() -> float:
    raw = os.environ.get("AGENCY_COCKPIT_TICKER_DETAIL_TIMEOUT_SECONDS", "")
    if not raw.strip():
        return DEFAULT_TICKER_DETAIL_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TICKER_DETAIL_TIMEOUT_SECONDS
    return max(0.01, value)


def _cockpit_ticker_detail_timeout_payload(ticker: str) -> dict[str, object]:
    payload = {
        "ticker": ticker,
        "title": f"{ticker} Detail",
        "summary": (
            "The quick cockpit drawer did not finish in time. The full candidate "
            "brief remains available."
        ),
        "headline": f"{ticker} detail is loading slowly.",
        "next_step": "Open the full candidate page for complete evidence and review history.",
        "action_label": "Open full candidate page",
        "status_label": "Detail delayed",
        "conviction_pct": 0,
        "source_count": 0,
        "confirmed_signal_count": 0,
        "llm": {
            "status_label": "Not loaded in quick drawer",
            "status_detail": "The cockpit stopped waiting before rich evidence was loaded.",
            "action": "None",
            "confidence_pct": 0,
            "rationale": "Open the full candidate page for the current LLM rationale.",
            "manual_review_available": False,
            "manual_review_action": "",
            "manual_review_detail": "Manual LLM review needs the current report hash, cycle ID, and as-of timestamp.",
        },
        "data_health": {
            "status_label": "Detail delayed",
            "status_class": "warn",
            "headline": "Quick drawer timed out.",
            "recommended_action": "Open the full candidate page for complete evidence.",
            "primary_blocker": "Quick drawer timeout",
            "primary_blocker_detail": "The cockpit drawer is intentionally bounded.",
            "overall_percent": 0,
            "last_verified_label": "",
        },
        "review": {"decision": "Pending", "reason": "", "event_time_label": ""},
        "support_cards": [],
        "caution_cards": [],
        "decision_points": [],
        "signal_mix_note": "",
        "signals": [],
        "context_cards": [],
        "detail_url": f"/candidates/{ticker}",
    }
    return _scrub_secrets(payload)


def cockpit_ticker_detail_payload_from_context(
    context: Mapping[str, object],
) -> dict[str, object]:
    """Map the classic candidate brief context into a small cockpit API payload."""

    ticker = normalize_ticker(_first_text(context.get("ticker"), default="TICKER"))
    brief = _mapping(context.get("decision_brief"))
    latest = _mapping(context.get("latest_report"))
    review = _mapping(context.get("review"))
    data_health = _mapping(context.get("data_health"))
    email_evidence = _mapping(context.get("email_evidence"))
    news_evidence = _mapping(context.get("news_evidence"))
    cycle_id = _first_text(latest.get("cycle_id"))
    as_of = _first_text(latest.get("as_of"))
    generated_at = _first_text(latest.get("generated_at"))
    manual_llm_available = bool(cycle_id and as_of)
    payload = {
        "ticker": ticker,
        "cycle_id": cycle_id,
        "as_of": as_of,
        "generated_at": generated_at,
        "title": f"{ticker} Detail",
        "summary": _first_text(
            brief.get("detail"),
            latest.get("decision_takeaway"),
            default="No current candidate detail is available.",
        ),
        "headline": _first_text(
            brief.get("headline"),
            latest.get("decision_explanation"),
            default=f"{ticker} has a recorded candidate report.",
        ),
        "next_step": _first_text(
            brief.get("next_step"),
            latest.get("review_next_step"),
            default="Review the latest candidate report before taking action.",
        ),
        "action_label": _first_text(brief.get("action_label"), latest.get("action")),
        "status_label": _first_text(brief.get("state_label"), latest.get("action")),
        "conviction_pct": _int(brief.get("conviction_pct"), latest.get("conviction_pct")),
        "source_count": _int(brief.get("source_count"), latest.get("source_count")),
        "confirmed_signal_count": _int(
            brief.get("confirmed_signal_count"),
            latest.get("confirmed_signal_count"),
        ),
        "llm": {
            "status_label": _first_text(latest.get("llm_status_label"), default="Not run"),
            "status_detail": _first_text(latest.get("llm_status_detail")),
            "action": _first_text(latest.get("llm_action"), default="None"),
            "confidence_pct": _int(latest.get("llm_confidence_pct")),
            "rationale": _first_text(
                latest.get("llm_rationale"),
                default="LLM review has not produced a rationale for this ticker yet.",
            ),
            "manual_review_available": manual_llm_available,
            "manual_review_action": f"/candidates/{ticker}/llm-review" if manual_llm_available else "",
            "manual_review_detail": (
                "Automatic LLM review is limited to the top 10 ranked candidates. "
                "This runs the same reviewer for the selected ticker and report timestamp."
            )
            if manual_llm_available
            else "Manual LLM review is unavailable because the current report timestamp is missing.",
        },
        "data_health": {
            "status_label": _first_text(data_health.get("status_label"), default="Unverified"),
            "status_class": _first_text(data_health.get("status_class"), default="neutral"),
            "headline": _first_text(data_health.get("headline")),
            "recommended_action": _first_text(data_health.get("recommended_action")),
            "primary_blocker": _first_text(data_health.get("primary_blocker")),
            "primary_blocker_detail": _first_text(data_health.get("primary_blocker_detail")),
            "overall_percent": _int(data_health.get("overall_percent")),
            "last_verified_label": _first_text(data_health.get("last_verified_label")),
        },
        "review": {
            "decision": _first_text(review.get("decision"), default="Pending"),
            "reason": _first_text(review.get("reason")),
            "event_time_label": _first_text(review.get("event_time_label")),
        },
        "support_cards": _compact_cards(_list(brief.get("support_cards"))),
        "caution_cards": _compact_cards(_list(brief.get("caution_cards"))),
        "decision_points": _compact_cards(_list(brief.get("decision_points"))),
        "signal_mix_note": _first_text(brief.get("signal_mix_note")),
        "signals": _compact_signals(
            [
                *_list(latest.get("actionable_signals")),
                *_list(latest.get("context_signals")),
                *_list(latest.get("suppressed_signals")),
            ]
        ),
        "context_cards": [
            card
            for card in (
                _compact_evidence_context("Subscription email", email_evidence),
                _compact_evidence_context("News/RSS", news_evidence),
            )
            if card
        ],
        "detail_url": f"/candidates/{ticker}",
    }
    return _scrub_secrets(payload)


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
        raise ValueError("Ticker must be 1-10 letters, digits, dots, or dashes.")
    return ticker


def _cycle_section(
    dashboard: Mapping[str, object],
    engines: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    readiness = _mapping(dashboard.get("full_live_readiness")) or _mapping(
        dashboard.get("readiness")
    )
    data_load = _mapping(dashboard.get("data_load_status"))
    cycle_id = _first_text(
        readiness.get("cycle_id"),
        data_load.get("cycle_id"),
        dashboard.get("cycle_id"),
        default="current-cycle",
    )
    sources_total = _int(readiness.get("source_count"), fallback=len(engines))
    if sources_total <= 0:
        sources_total = len(engines)
    fresh_sources = _int(
        readiness.get("fresh_source_count"),
        fallback=sum(1 for engine in engines if engine.get("state") == "live"),
    )
    engine_degraded = sum(1 for engine in engines if engine.get("state") != "live")
    degraded = _int(
        readiness.get("degraded_source_count"),
        fallback=max(sources_total - fresh_sources, engine_degraded, 0),
    )
    degraded = max(0, min(degraded, sources_total))
    return {
        "id": cycle_id,
        "as_of": _first_text(data_load.get("as_of"), data_load.get("updated_at"), default="latest available"),
        "next_in": _first_text(
            data_load.get("next_update_label"),
            dashboard.get("next_cycle_label"),
            default="scheduled by refresh policy",
        ),
        "mode": "PAPER",
        "submit_enabled": False,
        "sources_degraded": degraded,
        "sources_total": sources_total,
        "status_label": _first_text(readiness.get("status_label"), default="Readiness checked"),
        "status_class": _first_text(readiness.get("status_class"), default="neutral"),
    }


def _market_section(
    market: Mapping[str, object],
    dashboard: Mapping[str, object],
) -> dict[str, object]:
    summary = _mapping(market.get("summary"))
    readiness = _mapping(dashboard.get("full_live_readiness"))
    regime_score = _bounded_score(
        summary.get("score"),
        summary.get("regime_score"),
        market.get("regime_score"),
        fallback=0.5,
    )
    return {
        "regime": _first_text(
            summary.get("headline"),
            summary.get("status_label"),
            market.get("regime"),
            default="Market regime unavailable",
        ),
        "score": regime_score,
        "needle_degrees": _gauge_degrees(regime_score, 1.0),
        "status_label": _first_text(summary.get("status_label"), default="Market check"),
        "readiness_label": _first_text(readiness.get("status_label"), default="Readiness check"),
        "long_threshold": _float(_mapping(dashboard.get("policy_summary")).get("min_conviction"), fallback=0.62),
    }


def _engine_rows(
    dashboard: Mapping[str, object],
    signals_context: Mapping[str, object],
    execution: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in _list(dashboard.get("data_sources")):
        item = _mapping(source)
        rows.append(
            {
                "name": _first_text(item.get("name"), item.get("source"), default="Data source"),
                "state": _source_engine_state(item),
                "age": _first_text(
                    item.get("freshness_label"),
                    item.get("freshness"),
                    item.get("checked_at"),
                    item.get("last_update"),
                    default="not checked",
                ),
                "detail": _first_text(
                    item.get("detail"),
                    item.get("notes"),
                    _source_health_detail(item),
                    default="No detail reported.",
                ),
            }
        )
    for lane in _list(signals_context.get("lanes")):
        item = _mapping(lane)
        rows.append(
            {
                "name": _first_text(item.get("label"), item.get("lane"), default="Signal process"),
                "state": _status_to_engine_state(item.get("status_class"), item.get("status_label")),
                "age": _first_text(item.get("freshness_label"), default="latest signal status"),
                "detail": _first_text(item.get("detail"), default="Signal process reported no detail."),
            }
        )
    summary = _mapping(execution.get("summary"))
    if summary:
        rows.append(
            {
                "name": "Execution preview",
                "state": _status_to_engine_state(
                    summary.get("status_class"),
                    summary.get("status_label"),
                ),
                "age": "checked for current cycle",
                "detail": _first_text(summary.get("detail"), summary.get("status_label"), default="Execution preview status."),
            }
        )
    return rows or [
        {
            "name": "Runtime",
            "state": "down",
            "age": "not checked",
            "detail": "No engine health rows were available.",
        }
    ]


def _funnel_section(
    dashboard: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    progress = _mapping(dashboard.get("review_progress"))
    total = _int(progress.get("total_count"), fallback=len(candidates))
    actionable = sum(1 for row in candidates if row.get("actionable") is True)
    reviewable = sum(
        1
        for row in candidates
        if row.get("reviewable") is True or row.get("order_reviewable") is True
    )
    blocked = sum(1 for row in candidates if row.get("status") == "blocked")
    return {
        "universe": _int(_mapping(dashboard.get("live_config")).get("active_universe_count"), fallback=total),
        "universe_ready": _int(_mapping(dashboard.get("full_live_readiness")).get("universe_count"), fallback=total),
        "fundamentals_pass": _int(progress.get("approve_count"), fallback=0),
        "fundamentals_watch": _int(progress.get("pending_count"), fallback=0),
        "signals": len(_list(dashboard.get("candidates"))),
        "deterministic": total,
        "llm_agree": sum(1 for row in candidates if "not run" not in str(row.get("llm_label", "")).lower()),
        "final": len(candidates),
        "actionable": actionable,
        "reviewable": reviewable,
        "blocked_by_policy": blocked,
    }


def _candidate_rows(
    dashboard: Mapping[str, object],
    execution: Mapping[str, object],
) -> list[dict[str, object]]:
    source_rows = _list(dashboard.get("review_queue")) or _list(dashboard.get("candidates"))
    reference_index = _ticker_reference_index(dashboard.get("ticker_reference"))
    previews = {_first_text(_mapping(row).get("ticker")): _mapping(row) for row in _list(execution.get("preview_rows"))}
    orderable_tickers = {
        _first_text(_mapping(row).get("ticker")).upper()
        for row in _list(execution.get("orderable_rows"))
        if _first_text(_mapping(row).get("ticker"))
    }
    rows: list[dict[str, object]] = []
    for raw_index, raw in enumerate(source_rows, start=1):
        item = _mapping(raw)
        deterministic = _mapping(item.get("deterministic"))
        llm_review = _mapping(item.get("llm_review"))
        ticker = _first_text(item.get("ticker"), default=f"ROW{raw_index}")
        reference = _mapping(reference_index.get(ticker.upper()))
        action = _first_text(item.get("final_action"), item.get("action"), default="WATCH").upper()
        risk_label = _first_text(
            item.get("risk_status_label"),
            item.get("risk_status"),
            item.get("risk_decision"),
            item.get("gate_status"),
            default="",
        ).upper()
        final_conviction = _score(
            item.get("final_conviction"),
            item.get("final_score"),
            item.get("score"),
            item.get("conviction"),
            item.get("conviction_pct"),
        )
        preview = previews.get(ticker, {})
        preview_state = _first_text(preview.get("preview_state")).upper()
        preview_side = _first_text(preview.get("side")).upper()
        preview_ready = preview_state == "READY" and (
            preview_side in TRADE_ACTIONS or ticker.upper() in orderable_tickers
        )
        submit_ready = preview_ready and (
            preview.get("submit_enabled") is True or ticker.upper() in orderable_tickers
        )
        gate_blocked = "BLOCK" in risk_label
        order_reviewable = preview_ready and not submit_ready and not gate_blocked
        actionable = submit_ready and item.get("is_reviewable") is not False and not gate_blocked
        reviewable = (
            False
            if actionable or order_reviewable
            else _candidate_is_reviewable(item, gate_blocked=gate_blocked)
        )
        status = (
            "approved"
            if actionable
            else "pending"
            if order_reviewable
            else "blocked"
            if "BLOCK" in risk_label
            else "demoted"
        )
        evidence_items = _evidence_items(item)
        evidence_line = evidence_items[0]["text"]
        risk_text = _first_text(
            item.get("risk_detail"),
            item.get("risk_reason"),
            item.get("blocker"),
            default="Risk check did not attach a specific finding.",
        )
        score_display = f"{final_conviction:.2f}"
        rows.append(
            {
                "rank": raw_index,
                "ticker": ticker,
                "name": _first_text(
                    item.get("company"),
                    item.get("name"),
                    reference.get("company"),
                    reference.get("name"),
                    default=ticker,
                ),
                "sector": _first_text(
                    item.get("sector"),
                    reference.get("sector"),
                    reference.get("industry"),
                    reference.get("sic_description"),
                    default=DEFAULT_SECTOR_LABEL,
                ),
                "direction": "short" if (preview_side or action) in {"SELL", "SHORT", "COVER"} else "long",
                "det_conviction": _score(
                    item.get("det_conviction"),
                    item.get("deterministic_conviction"),
                    deterministic.get("conviction"),
                    item.get("deterministic_score_label"),
                    deterministic.get("score"),
                ),
                "llm_conviction": _score(
                    item.get("llm_conviction"),
                    item.get("llm_confidence"),
                    item.get("llm_confidence_pct"),
                    llm_review.get("confidence"),
                    item.get("llm_score_label"),
                    preview.get("llm_confidence_pct"),
                ),
                "llm_label": _first_text(
                    item.get("llm_status_label"),
                    preview.get("llm_status_label"),
                    preview.get("llm_action"),
                    _llm_review_status_label(llm_review),
                    default="",
                ),
                "llm_rationale": _first_text(
                    item.get("llm_rationale"),
                    item.get("llm_summary"),
                    preview.get("llm_rationale"),
                    llm_review.get("rationale"),
                    item.get("llm_status_label"),
                    default="LLM not run for this ticker",
                ),
                "final_conviction": final_conviction,
                "final_conviction_label": score_display,
                "score_display": score_display,
                "conviction_dial_degrees": int(round(final_conviction * 120 - 60)),
                "status": status,
                "status_label": _candidate_status_label(
                    actionable=actionable,
                    order_reviewable=order_reviewable,
                    reviewable=reviewable,
                    risk_label=risk_label,
                ),
                "blocker": None if actionable else "Order details approval is required before submit." if order_reviewable else risk_text,
                "actionable": actionable,
                "order_reviewable": order_reviewable,
                "reviewable": reviewable,
                "action_label": (
                    "Submit paper order"
                    if actionable
                    else "Review order details"
                    if order_reviewable
                    else "Approve, defer, or reject"
                    if reviewable
                    else "Open audit"
                ),
                "decision_controls": (
                    ["order"]
                    if actionable or order_reviewable
                    else ["approve", "defer", "reject"]
                    if reviewable
                    else ["audit"]
                ),
                "order_action_url": "",
                "execution_focus_url": f"/execution-preview?ticker={ticker.upper()}#focused-preview-{ticker.upper()}",
                "approve_review_action": _first_text(item.get("approve_review_action")),
                "defer_review_action": _first_text(item.get("defer_review_action")),
                "reject_review_action": _first_text(item.get("reject_review_action")),
                "caution_acknowledgement_required": bool(
                    item.get("caution_acknowledgement_required")
                ),
                "caution_acknowledgement_text": _first_text(
                    item.get("caution_acknowledgement_text")
                ),
                "evidence": evidence_items,
                "evidence_tiers": _candidate_evidence_tiers(evidence_items),
                "evidence_line": evidence_line,
                "evidence_hard_value": _first_metric(evidence_line),
                "risk_line": risk_text,
                "risk_hard_value": _first_metric(risk_text),
                "risk_status_label": _first_text(
                    item.get("risk_status_label"),
                    default="Risk proof not attached",
                ),
                "order_preview": _first_text(
                    preview.get("notional_label"),
                    preview.get("order_value_label"),
                    default="No paper order yet",
                ),
                "order_notional": _money_value(preview.get("notional"), preview.get("notional_label"), preview.get("order_value_label")),
                "order_intent_hash": _first_text(preview.get("order_intent_hash"), default=""),
                "order_intent_hash_label": _first_text(preview.get("order_intent_hash_label"), default=""),
                "cycle_id": _first_text(item.get("cycle_id"), default=""),
                "as_of": _first_text(item.get("as_of"), default=""),
                "evidence_hash": _first_text(item.get("evidence_hash"), default=""),
                "detail_url": f"/candidates/{ticker}",
                "audit_url": f"/api/audit/{ticker}",
            }
        )
    sorted_rows = sorted(rows, key=lambda row: cast(float, row["final_conviction"]), reverse=True)[
        :MAX_COCKPIT_CANDIDATES
    ]
    for index, row in enumerate(sorted_rows, start=1):
        row["rank"] = index
        if not _first_text(row.get("llm_label")):
            row["llm_label"] = (
                "LLM not run because this ticker is outside the top 10 automatic review set."
                if index > 10
                else "LLM not run for this ticker"
            )
    return sorted_rows


def _llm_review_status_label(review: Mapping[str, object]) -> str:
    action = _first_text(review.get("action")).upper()
    rationale = _first_text(review.get("rationale")).lower()
    if not action:
        return ""
    if action == "AGREE":
        return "LLM agrees"
    if action == "DISAGREE":
        return "LLM disagrees"
    if action == "NEEDS_MORE_EVIDENCE":
        return "LLM needs more evidence"
    if action == "NO_REVIEW":
        if "not enabled" in rationale or "disabled" in rationale:
            return "LLM disabled for this run"
        return "LLM not run automatically"
    return f"LLM {action.replace('_', ' ').title()}"


def _ticker_reference_index(value: object) -> dict[str, Mapping[str, object]]:
    if isinstance(value, Mapping):
        return {
            str(ticker).upper(): _mapping(row)
            for ticker, row in value.items()
            if str(ticker).strip() and _mapping(row)
        }
    if isinstance(value, list | tuple):
        rows: dict[str, Mapping[str, object]] = {}
        for row in value:
            item = _mapping(row)
            ticker = _first_text(item.get("ticker")).upper()
            if ticker:
                rows[ticker] = item
        return rows
    return {}


def _position_rows(portfolio: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in _list(portfolio.get("positions")):
        item = _mapping(raw)
        ticker = _first_text(item.get("ticker"), item.get("symbol"), default="Position")
        current = _float(item.get("current_price"), item.get("current"))
        entry = _float(item.get("entry_price"), item.get("avg_entry_price"), item.get("average_entry_price"))
        stop = _float(item.get("stop_price"), item.get("stop"))
        pl_pct = _float(item.get("unrealized_pl_pct"), item.get("pl_pct"), fallback=float("nan"))
        if math.isnan(pl_pct) and entry > 0:
            pl_pct = round((current - entry) / entry * 100, 2)
        if math.isnan(pl_pct):
            pl_pct = 0.0
        stop_distance_pct = round((current - stop) / current * 100, 2) if current > 0 and stop > 0 else 0.0
        rows.append(
            {
                "ticker": ticker,
                "qty": _float(item.get("qty"), item.get("quantity")),
                "current": current,
                "entry": entry,
                "stop": stop,
                "market_value": _float(item.get("market_value")),
                "pl_pct": pl_pct,
                "stop_distance_pct": stop_distance_pct,
                "status": _first_text(item.get("status_label"), item.get("status"), default="Hold"),
                "exit_signal": _first_text(item.get("exit_signal"), default="NONE"),
                "requires_exit": _position_requires_exit(item, current=current, stop=stop),
                "decision_controls": ["keep", "close"],
                "thesis": _first_text(item.get("thesis"), item.get("detail"), default="No position thesis reported."),
            }
        )
    return rows


def _account_section(
    market: Mapping[str, object],
    portfolio: Mapping[str, object],
    dashboard: Mapping[str, object],
    execution: Mapping[str, object],
    candidate_count: int,
) -> dict[str, object]:
    broker = _mapping(market.get("broker")) or _mapping(dashboard.get("broker_status"))
    account = _mapping(broker.get("account"))
    policy = _mapping(dashboard.get("policy_summary"))
    portfolio_summary = _mapping(portfolio.get("summary"))
    orderable_count = len(_list(execution.get("orderable_rows")))
    gross_exposure = _float(
        broker.get("gross_exposure_pct"),
        portfolio_summary.get("gross_exposure_pct"),
    )
    equity_reported = _number_reported(account.get("equity"), portfolio_summary.get("equity"))
    equity = _float(account.get("equity"), portfolio_summary.get("equity"), fallback=0.0)
    staged_notional = _staged_order_notional(execution)
    staged_exposure_pct = staged_notional / equity * 100 if equity > 0 else 0.0
    gross_post_trade = round(gross_exposure + staged_exposure_pct, 1)
    gross_cap_reported = _number_reported(policy.get("max_gross_exposure_pct"))
    cash_cap_reported = _number_reported(policy.get("cash_reserve_pct"))
    sector_cap_reported = _number_reported(policy.get("max_sector_exposure_pct"))
    largest_name_cap_reported = _number_reported(policy.get("largest_name_cap_pct"))
    open_orders_cap_reported = _number_reported(policy.get("max_open_orders"))
    gross_cap = _float(policy.get("max_gross_exposure_pct"), fallback=0.0)
    capacity_warning = ""
    if gross_cap_reported and gross_cap > 0 and gross_post_trade > gross_cap:
        capacity_warning = (
            f"Gross exposure would be {gross_post_trade:.1f}% versus the {gross_cap:.1f}% cap. "
            "Reduce staged buys or close exposure before clearance."
        )
    cash_available = _float(portfolio_summary.get("cash_reserve_pct"), fallback=0.0)
    cash_cap = _float(policy.get("cash_reserve_pct"), fallback=0.0)
    sector_exposure = _float(portfolio_summary.get("sector_exposure_pct"), fallback=0.0)
    sector_cap = _float(policy.get("max_sector_exposure_pct"), fallback=0.0)
    largest_name = _float(portfolio_summary.get("largest_name_pct"), fallback=0.0)
    largest_name_cap = _float(policy.get("largest_name_cap_pct"), fallback=0.0)
    buying_power_reported = _number_reported(account.get("buying_power"))
    buying_power = _float(account.get("buying_power"))
    return {
        "equity_reported": equity_reported,
        "equity": equity,
        "policy_reported": any(
            (
                gross_cap_reported,
                cash_cap_reported,
                sector_cap_reported,
                largest_name_cap_reported,
                open_orders_cap_reported,
            )
        ),
        "gross_exposure": gross_exposure,
        "gross_post_trade": gross_post_trade,
        "gross_cap": gross_cap,
        "gross_cap_label": _percent_label(gross_cap, reported=gross_cap_reported, decimals=0),
        "gross_needle_degrees": _gauge_degrees(gross_post_trade, gross_cap),
        "cash_available": cash_available,
        "cash_cap": cash_cap,
        "cash_cap_label": _percent_label(cash_cap, reported=cash_cap_reported, decimals=0),
        "cash_needle_degrees": _gauge_degrees(cash_available, cash_cap),
        "sector_exposure": sector_exposure,
        "sector_cap": sector_cap,
        "sector_cap_label": _percent_label(sector_cap, reported=sector_cap_reported, decimals=0),
        "sector_needle_degrees": _gauge_degrees(sector_exposure, sector_cap),
        "largest_name": largest_name,
        "largest_name_cap": largest_name_cap,
        "largest_name_cap_label": _percent_label(
            largest_name_cap,
            reported=largest_name_cap_reported,
            decimals=0,
        ),
        "concentration_needle_degrees": _gauge_degrees(largest_name, largest_name_cap),
        "open_orders": _int(broker.get("open_order_count"), fallback=len(_list(broker.get("orders")))),
        "open_orders_cap": _int(policy.get("max_open_orders"), fallback=0),
        "open_orders_cap_label": (
            str(_int(policy.get("max_open_orders"), fallback=0))
            if open_orders_cap_reported
            else "not reported"
        ),
        "buying_power": buying_power,
        "buying_power_label": _money_label(buying_power, reported=buying_power_reported),
        "week_pnl": _float(portfolio_summary.get("week_pnl_pct"), fallback=0.0),
        "week_target": _float(policy.get("weekly_target_pct"), fallback=0.0),
        "ready_to_trade": f"{orderable_count}/{candidate_count}",
        "staged_notional": staged_notional,
        "capacity_warning": capacity_warning,
    }


def _source_rows(
    dashboard: Mapping[str, object],
    *,
    proof_timestamp: str = "",
) -> list[dict[str, object]]:
    return source_health_rows(_list(dashboard.get("data_sources")), proof_timestamp=proof_timestamp)


def _data_state_section(dashboard: Mapping[str, object]) -> dict[str, object]:
    data_load = _mapping(dashboard.get("data_load_status"))
    lane_rows = _data_state_lane_rows(data_load)
    review_ready = _data_state_bool(
        data_load.get("review_operational_ready"),
        fallback=not any(row["status_class"] == "block" for row in lane_rows),
    )
    paper_ready = _data_state_bool(
        data_load.get("tradable_ready"),
        fallback=all(
            row["ready_for_paper_execution"] is True
            for row in lane_rows
            if row["required_now"] is True and row["blocks_execution"] is True
        ),
    )
    top_gaps = _data_state_top_gaps(lane_rows)
    overall_percent = _bounded_int(
        data_load.get("overall_percent"),
        fallback=_progress_average(lane_rows),
    )
    critical_lane_percent = _bounded_int(
        data_load.get("critical_lane_percent"),
        fallback=_progress_average(
            [
                row
                for row in lane_rows
                if row["required_now"] is True and row["blocks_execution"] is True
            ]
        ),
    )
    expected_ticker_count = _int(
        data_load.get("expected_ticker_count"),
        _mapping(dashboard.get("live_config")).get("active_universe_count"),
        fallback=0,
    )
    warning_count = _int(data_load.get("warning_count"), fallback=len(top_gaps))
    blocker_count = _int(
        data_load.get("blocker_count"),
        fallback=sum(1 for row in lane_rows if row["blocker"] is True),
    )
    review_label = "Review ready" if review_ready else "Review not ready"
    paper_label = "Ready for paper execution" if paper_ready else "Paper execution gated"
    gap_summary = (
        _data_state_gap_summary(top_gaps)
        if top_gaps
        else "No required data or agent gaps are reported for the current workflow."
    )
    return {
        "status_label": _data_state_text(data_load.get("status_label") or "Data state checked"),
        "status_class": _first_text(data_load.get("status_class"), default="neutral"),
        "headline": (
            f"{review_label}; {paper_label}. "
            f"{overall_percent}% overall data readiness with {warning_count} warning(s) "
            f"and {blocker_count} must-fix issue(s)."
        ),
        "overall_percent": overall_percent,
        "critical_lane_percent": critical_lane_percent,
        "active_universe_count": expected_ticker_count,
        "active_universe_label": (
            f"{expected_ticker_count} active-universe tickers"
            if expected_ticker_count
            else "Active-universe size not reported"
        ),
        "review": {
            "ready": review_ready,
            "label": review_label,
            "status_class": "pass" if review_ready else "warn",
            "detail": (
                "The loaded evidence is usable for research review."
                if review_ready
                else "Research review needs the listed data or agent gaps resolved first."
            ),
        },
        "paper": {
            "ready": paper_ready,
            "label": paper_label,
            "status_class": "pass" if paper_ready else "warn",
            "detail": (
                "Paper execution can proceed after broker and order approval checks."
                if paper_ready
                else gap_summary
            ),
        },
        "top_gaps": top_gaps[:3],
        "lane_rows": lane_rows,
        "loading_count": sum(1 for row in lane_rows if row["state"] == "loading"),
        "loaded_unanalyzed_count": sum(
            1 for row in lane_rows if row["state"] == "loaded_unanalyzed"
        ),
        "needs_refresh_count": sum(1 for row in lane_rows if row["state"] == "needs_refresh"),
        "unavailable_count": sum(
            1 for row in lane_rows if row["state"] == "provider_unavailable"
        ),
        "ready_review_count": sum(
            1 for row in lane_rows if row["ready_for_review"] is True
        ),
        "ready_paper_count": sum(
            1 for row in lane_rows if row["ready_for_paper_execution"] is True
        ),
        "optional_count": sum(1 for row in lane_rows if row["state"] == "disabled_optional"),
        "as_of_label": _data_state_text(
            _first_text(
                data_load.get("as_of_label"),
                data_load.get("as_of"),
                data_load.get("updated_at"),
                data_load.get("generated_at_label"),
                default="not recorded",
            )
        ),
        "proof_label": _data_state_text(
            _first_text(
                data_load.get("status_checked_at_label"),
                data_load.get("latest_checked_at"),
                data_load.get("generated_at"),
                default="not checked",
            )
        ),
    }


def _data_state_lane_rows(data_load: Mapping[str, object]) -> list[dict[str, object]]:
    rows = _list(data_load.get("lane_state_rows")) or _list(data_load.get("lane_states"))
    return [_data_state_lane_row(_mapping(row)) for row in rows]


def _data_state_lane_row(row: Mapping[str, object]) -> dict[str, object]:
    lane_id = _first_text(row.get("lane_id"), row.get("lane"), row.get("name"), default="data_source")
    name = _data_state_text(
        _first_text(row.get("name"), row.get("label"), row.get("lane_id"), default="Data source")
    )
    state = _first_text(row.get("state"), default=_state_from_lane_label(row))
    status_label = _data_state_text(
        _first_text(row.get("status_label"), row.get("display_status_label"), default="Status not reported")
    )
    status_class = _first_text(row.get("status_class"), default=_lane_state_class(row))
    progress_label = _data_state_text(_first_text(row.get("progress_label"), default="not tracked"))
    required_now = _data_state_bool(row.get("required_now"), fallback=True)
    blocks_execution = _data_state_bool(row.get("blocks_execution"), fallback=False)
    ready_for_review = _data_state_bool(
        row.get("ready_for_review"),
        fallback=state in {"ready_for_review", "ready_for_paper_execution"},
    )
    ready_for_paper = _data_state_bool(
        row.get("ready_for_paper_execution"),
        fallback=state == "ready_for_paper_execution",
    )
    blocker = _data_state_bool(
        row.get("blocker"),
        fallback=required_now
        and blocks_execution
        and state
        in {"loading", "loaded_unanalyzed", "needs_refresh", "provider_unavailable"},
    )
    raw_requirements = [
        _data_state_text(item)
        for item in _list(row.get("raw_lanes_required"))
        if _first_text(item)
    ]
    requirement_label = _data_state_text(
        _first_text(
            row.get("requirement_label"),
            ", ".join(raw_requirements),
            default="Direct source",
        )
    )
    operator_message = _data_state_text(
        _first_text(row.get("operator_message"), row.get("detail"), default="No data-source explanation recorded.")
    )
    recommended_action = _lane_recommended_action(
        row,
        state=state,
        name=name,
        required_now=required_now,
        blocks_execution=blocks_execution,
    )
    latest_as_of_label = _data_state_text(
        _first_text(row.get("latest_as_of_label"), row.get("latest_as_of"), default="not recorded")
    )
    checked_at_label = _data_state_text(
        _first_text(row.get("checked_at_label"), row.get("checked_at"), default="not checked")
    )
    refresh_action = _lane_refresh_action(
        row,
        lane_id=lane_id,
        source_dataset=_first_text(row.get("source_dataset")),
    )
    return {
        "lane_id": lane_id,
        "name": name,
        "lane_kind_label": _data_state_text(
            _first_text(row.get("lane_kind_label"), row.get("lane_kind"), default="data source")
        ),
        "state": state,
        "status_label": status_label,
        "status_class": status_class,
        "progress_label": progress_label,
        "progress_percent": _lane_progress_percent(row, progress_label),
        "required_now": required_now,
        "required_label": "Required now" if required_now else "Optional today",
        "blocks_execution": blocks_execution,
        "blocks_paper_label": "Yes" if blocks_execution else "No",
        "blocker": blocker,
        "ready_for_review": ready_for_review,
        "ready_for_paper_execution": ready_for_paper,
        "latest_as_of_label": latest_as_of_label,
        "checked_at_label": checked_at_label,
        "refresh_action": refresh_action,
        "requirement_label": requirement_label,
        "operator_message": operator_message,
        "recommended_action": recommended_action,
        "gap_detail": operator_message,
        "tooltip": (
            f"{name}: {status_label}. Progress: {progress_label}. "
            f"Proof: {latest_as_of_label}. Next action: {recommended_action}"
        ),
        "sort_key": _data_lane_sort_key(
            state,
            required_now=required_now,
            blocks_execution=blocks_execution,
            status_class=status_class,
        ),
    }


def _lane_refresh_action(
    row: Mapping[str, object],
    *,
    lane_id: str,
    source_dataset: str,
) -> dict[str, str]:
    explicit_url = _first_text(row.get("refresh_action_url"))
    explicit_label = _data_state_text(_first_text(row.get("refresh_action_label")))
    if explicit_url:
        return {
            "url": explicit_url,
            "label": explicit_label or "Refresh data source",
            "detail": _data_state_text(
                _first_text(
                    row.get("refresh_action_detail"),
                    default="Runs the data refresh through the scheduler policy.",
                )
            ),
        }
    massive_lane = _refresh_massive_lane_id(lane_id, source_dataset)
    if massive_lane:
        if massive_lane not in RUNNABLE_MASSIVE_LANES:
            return {
                "url": "",
                "label": "Policy locked",
                "detail": (
                    f"{REFRESHABLE_MASSIVE_LANES.get(massive_lane, massive_lane)} "
                    "is tracked for health, but this data source is not exposed as a "
                    "runnable scheduler refresh in the current policy."
                ),
            }
        return {
            "url": f"/scheduler/massive-lanes/{massive_lane}/refresh",
            "label": REFRESHABLE_MASSIVE_LANES.get(massive_lane, "Refresh data source"),
            "detail": "Runs this data source through the scheduler's trade-aware policy.",
        }
    dataset = source_dataset or lane_id
    if dataset == "subscription_emails" or lane_id == "subscription_thesis":
        return {
            "url": "/scheduler/subscription-emails/login-refresh",
            "label": "Open Seeking Alpha login refresh",
            "detail": "Opens regular installed Chrome for the login-gated email/article refresh flow.",
        }
    if dataset in {"news_rss", "sec_company_facts", "sec_form4", "sec_13f"}:
        return {
            "url": f"/scheduler/datasets/{dataset}/refresh",
            "label": f"Refresh {dataset.replace('_', ' ').title()}",
            "detail": "Runs this dataset refresh through the scheduler policy.",
        }
    return {"url": "", "label": "", "detail": ""}


def _refresh_massive_lane_id(lane_id: str, source_dataset: str) -> str:
    if lane_id in REFRESHABLE_MASSIVE_LANES:
        return lane_id
    mapped = REFRESHABLE_DATASET_TO_LANE.get(source_dataset) or REFRESHABLE_DATASET_TO_LANE.get(
        lane_id
    )
    return mapped or ""


def _data_state_top_gaps(
    lane_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    gap_rows = [
        row
        for row in lane_rows
        if row.get("required_now") is True
        and (
            row.get("blocker") is True
            or str(row.get("state") or "")
            in {"loading", "loaded_unanalyzed", "needs_refresh", "provider_unavailable"}
        )
    ]
    ordered = sorted(gap_rows, key=lambda row: _int(row.get("sort_key"), fallback=99))
    return [
        {
            "lane": str(row.get("name") or "Data source"),
            "status_label": str(row.get("status_label") or "Needs attention"),
            "status_class": str(row.get("status_class") or "warn"),
            "progress_label": str(row.get("progress_label") or "not tracked"),
            "detail": str(row.get("operator_message") or "No data-source detail recorded."),
            "recommended_action": str(row.get("recommended_action") or "Review this data source."),
            "blocks_execution": bool(row.get("blocks_execution")),
        }
        for row in ordered
    ]


def _data_state_gap_summary(top_gaps: Sequence[Mapping[str, object]]) -> str:
    execution_gaps = [row for row in top_gaps if row.get("blocks_execution") is True]
    rows = execution_gaps or list(top_gaps)
    labels = [
        f"{_label_text(str(row.get('name') or row.get('label') or row.get('lane') or 'Data source'))} ({row.get('progress_label')})"
        for row in rows[:3]
        if row.get("lane")
    ]
    if not labels:
        return "Paper execution needs data or agent attention before submit."
    return "Resolve or acknowledge these readiness items before paper submit: " + "; ".join(labels) + "."


def _lane_recommended_action(
    row: Mapping[str, object],
    *,
    state: str,
    name: str,
    required_now: bool,
    blocks_execution: bool,
) -> str:
    explicit = _data_state_text(_first_text(row.get("recommended_action")))
    if explicit:
        return explicit
    if state == "loading":
        return f"Wait for {name} to finish loading, then refresh the cockpit."
    if state == "loaded_unanalyzed":
        return f"Run the {name} analysis before using this source for decisions."
    if state == "needs_refresh":
        return f"Refresh {name}, then recheck the cockpit proof timestamp."
    if state == "provider_unavailable":
        return f"Check provider access for {name}, then retry the data refresh."
    if state == "ready_for_paper_execution":
        return f"No action needed for {name}; it is ready for paper execution."
    if state == "ready_for_review":
        return f"Use {name} for research review; refresh if proof is outside policy."
    if not required_now:
        return f"No action needed today; {name} is not required for the current workflow."
    if blocks_execution:
        return f"Review {name} before paper execution because this source is paper-critical."
    return f"Review {name} before advancing this workflow."


def _lane_progress_percent(
    row: Mapping[str, object],
    progress_label: str,
) -> int | None:
    for key in ("progress_percent", "coverage_pct", "manifest_coverage_pct"):
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return _bounded_int(value)
    ratio_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", progress_label)
    if ratio_match:
        done = _float(ratio_match.group(1))
        total = _float(ratio_match.group(2))
        if total > 0:
            return _bounded_int(done / total * 100)
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", progress_label)
    if percent_match:
        return _bounded_int(_float(percent_match.group(1)))
    return None


def _progress_average(rows: Sequence[Mapping[str, object]]) -> int:
    values = [
        _int(row.get("progress_percent"), fallback=-1)
        for row in rows
        if row.get("progress_percent") is not None
    ]
    values = [value for value in values if value >= 0]
    if not values:
        return 0
    return _bounded_int(sum(values) / len(values))


def _bounded_int(value: object, *, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    numeric = _float(value, fallback=float(fallback))
    return max(0, min(100, int(round(numeric))))


def _data_state_bool(value: object, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ready", "pass"}
    return fallback


def _data_state_text(value: object) -> str:
    text = _first_text(value)
    return re.sub(r"\bstale\b", "needs refresh", text, flags=re.IGNORECASE)


def _state_from_lane_label(row: Mapping[str, object]) -> str:
    text = _first_text(
        row.get("status_label"),
        row.get("state"),
        row.get("analysis_state"),
    ).lower()
    if "loading" in text or "running" in text:
        return "loading"
    if "not required" in text or "optional" in text:
        return "disabled_optional"
    if "unavailable" in text or "failed" in text or "missing" in text:
        return "provider_unavailable"
    if "refresh" in text:
        return "needs_refresh"
    if "paper execution" in text:
        return "ready_for_paper_execution"
    if "review" in text:
        return "ready_for_review"
    return "loaded_unanalyzed"


def _lane_state_class(row: Mapping[str, object]) -> str:
    state = _state_from_lane_label(row)
    if state == "provider_unavailable":
        return "block"
    if state in {"loading", "loaded_unanalyzed", "needs_refresh"}:
        return "warn"
    if state in {"ready_for_review", "ready_for_paper_execution"}:
        return "pass"
    return "neutral"


def _data_lane_sort_key(
    state: str,
    *,
    required_now: bool,
    blocks_execution: bool,
    status_class: str,
) -> int:
    if not required_now:
        return 90
    base = {
        "provider_unavailable": 0,
        "loading": 1,
        "loaded_unanalyzed": 2,
        "needs_refresh": 3,
        "ready_for_review": 6,
        "ready_for_paper_execution": 8,
        "disabled_optional": 9,
    }.get(state, 5)
    if blocks_execution:
        base -= 1
    if status_class == "block":
        base -= 1
    return max(0, base)


def _signal_rows(signals_context: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in _list(signals_context.get("lanes")):
        item = _mapping(raw)
        state = _status_to_source_state(item.get("status_class"), item.get("status_label"))
        rows.append(
            {
                "name": _first_text(item.get("label"), item.get("lane"), default="Signal"),
                "status": _first_text(item.get("status_label"), default="Signal status"),
                "state": state,
                "tier": _signal_tier_for_state(state),
                "detail": _first_text(item.get("detail"), default="No signal detail reported."),
            }
        )
    return rows


def _signal_tier_for_state(state: str) -> str:
    if state == "ready":
        return "confirmed"
    if state == "partial":
        return "inferred"
    return "suppressed"


def _scenario_from_context(
    context: Mapping[str, object],
    execution: Mapping[str, object],
) -> dict[str, object]:
    engines = [_mapping(item) for item in _list(context.get("engines"))]
    candidates = [_mapping(item) for item in _list(context.get("candidates"))]
    actionable_count = sum(1 for row in candidates if row.get("actionable") is True)
    reviewable_count = sum(1 for row in candidates if row.get("reviewable") is True)
    order_reviewable_count = sum(1 for row in candidates if row.get("order_reviewable") is True)
    submitted_rows = _submitted_order_rows(execution)
    if submitted_rows:
        total_notional = round(sum(_money_value(row.get("notional")) for row in submitted_rows), 2)
        return {
            "state": "submitted",
            "headline": f"{len(submitted_rows)} paper orders were transmitted for this cycle.",
            "detail": "Review broker IDs and wait for the next cycle before staging more orders.",
            "submitted_orders": submitted_rows,
            "submitted_total_notional": total_notional,
            "candidate_controls_enabled": False,
        }
    down_engines = [engine for engine in engines if engine.get("state") == "down"]
    if down_engines:
        return {
            "state": "outage",
            "headline": "Selection is paused because critical data is unavailable.",
            "detail": "Refresh the red engine or open its detail before approving new decisions.",
            "engine_cards": _engine_cards(down_engines),
            "retry_label": _first_text(
                _mapping(context.get("cycle")).get("next_in"),
                default="Retry follows the scheduler refresh policy.",
            ),
            "last_good_cycle_label": _last_good_cycle_label(context),
            "candidate_controls_enabled": False,
        }
    if actionable_count == 0:
        if reviewable_count + order_reviewable_count > 0:
            review_subject = (
                f"{order_reviewable_count} order detail approvals need review"
                if order_reviewable_count and not reviewable_count
                else f"{reviewable_count} candidates are ready for research review"
                if reviewable_count and not order_reviewable_count
                else f"{reviewable_count + order_reviewable_count} candidates are ready for review"
            )
            return {
                "state": "review",
                "headline": f"{review_subject}.",
                "detail": "Approve, defer, or reject the review rows; no paper order is staged until policy and execution gates create an orderable preview.",
                "candidate_controls_enabled": True,
            }
        return {
            "state": "no-actionable",
            "headline": "Nothing actionable today. The agent already filtered the universe.",
            "detail": "Review the closest candidates or portfolio only; no paper order is staged.",
            "skip_to_portfolio_label": "Skip to Portfolio",
            "closest_candidates": _closest_candidate_rows(candidates),
            "agent_note": "The agent completed the funnel and filtered out every setup that did not clear the policy bar.",
            "candidate_controls_enabled": False,
        }
    return {
        "state": "normal",
        "headline": f"{actionable_count} trades ready. Approve what you want to ship today.",
        "detail": "Start with the ranked candidates, then review portfolio capacity before clearance.",
        "candidate_controls_enabled": True,
    }


def _scenario_display_titles(scenario: Mapping[str, object]) -> dict[str, object]:
    row = dict(scenario)
    headline = _first_text(row.get("headline"), default="Today's cockpit is ready")
    state = _first_text(row.get("state"), default="normal")
    if state == "submitted":
        page_title = "Paper orders were submitted"
    elif state == "outage":
        page_title = "Critical data needs attention"
    elif state == "no-actionable":
        page_title = "No paper trade is ready right now"
    elif state == "review":
        page_title = "Review queue is ready"
    else:
        page_title = headline
    row["page_title"] = page_title
    row["browser_title"] = f"{page_title} - Trading Agency"
    return row


def _phase_states(context: Mapping[str, object]) -> dict[str, dict[str, str]]:
    scenario = _mapping(context.get("scenario"))
    funnel = _mapping(context.get("funnel"))
    clearance = _mapping(context.get("clearance"))
    state = _first_text(scenario.get("state"), default="normal")
    reviewable = _int(funnel.get("reviewable"), funnel.get("actionable"), fallback=0)
    orderable = _int(clearance.get("orderable_count"), clearance.get("ready_count"), fallback=0)
    submitted = state == "submitted"
    blocked = state == "outage"
    return {
        "candidates": {
            "state": "blocked" if blocked else "complete" if submitted or reviewable == 0 else "active",
            "label": "Needs attention" if blocked else "Complete" if submitted or reviewable == 0 else "Review now",
        },
        "portfolio": {
            "state": "complete" if submitted else "active" if reviewable == 0 and not blocked else "waiting",
            "label": "Checked" if submitted else "Review exposure" if reviewable == 0 and not blocked else "After candidates",
        },
        "clearance": {
            "state": "complete" if submitted else "active" if orderable else "waiting",
            "label": "Complete" if submitted else f"{orderable} ready" if orderable else "No orders",
        },
        "cleared": {
            "state": "complete" if submitted else "waiting",
            "label": "Submitted" if submitted else "After submit",
        },
    }


def _submitted_order_rows(execution: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in _list(execution.get("preview_rows")):
        item = _mapping(raw)
        state = _first_text(item.get("execution_state"), item.get("status")).upper()
        if state not in {"SUBMITTED", "FILLED", "ACCEPTED"}:
            continue
        ticker = _first_text(item.get("ticker"), default="Order")
        rows.append(
            {
                "ticker": ticker,
                "side": _first_text(item.get("side"), default="BUY"),
                "qty": _float(item.get("qty"), item.get("quantity")),
                "limit_price": _float(item.get("limit_price"), item.get("limit")),
                "notional": _money_value(
                    item.get("notional"),
                    item.get("notional_label"),
                    item.get("order_value_label"),
                ),
                "broker_order_id": _first_text(
                    item.get("broker_order_id"),
                    item.get("order_id"),
                    default="broker id not reported",
                ),
                "state": state,
            }
        )
    return rows


def _engine_cards(engines: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "name": _first_text(engine.get("name"), default="Critical engine"),
            "state_label": "Unavailable",
            "detail": _first_text(engine.get("detail"), default="No detail reported."),
            "age": _first_text(engine.get("age"), default="not checked"),
        }
        for engine in engines[:4]
    ]


def _closest_candidate_rows(candidates: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for candidate in candidates[:3]:
        ticker = _first_text(candidate.get("ticker"), default="Ticker")
        reason = _first_text(
            candidate.get("blocker"),
            candidate.get("risk_line"),
            candidate.get("evidence_line"),
            default="Did not clear the current policy bar.",
        )
        rows.append(
            {
                "ticker": ticker,
                "score": _first_text(candidate.get("score_display"), default="0.00"),
                "reason": reason,
            }
        )
    return rows


def _last_good_cycle_label(context: Mapping[str, object]) -> str:
    cycle = _mapping(context.get("cycle"))
    as_of = _first_text(cycle.get("as_of"), default="not reported")
    return f"Last good cycle proof: {as_of}"


def _policy_section(dashboard: Mapping[str, object]) -> dict[str, object]:
    raw_policy = dict(_mapping(dashboard.get("policy_summary")))
    deployed = {
        key: value
        for key, value in raw_policy.items()
        if key
        in {
            "min_final_conviction",
            "max_new_positions_per_cycle",
            "max_gross_exposure_pct",
            "default_position_pct",
            "take_profit_pct",
            "stop_loss_pct",
            "trailing_stop_pct",
            "hourly_loss_alert_pct",
        }
    }
    if not deployed:
        deployed = {
            "min_final_conviction": _float(raw_policy.get("min_conviction"), fallback=0.62),
            "default_position_pct": _float(raw_policy.get("default_position_pct"), fallback=5.0),
            "max_gross_exposure_pct": _float(raw_policy.get("max_gross_exposure_pct"), fallback=100.0),
        }
    return {
        **raw_policy,
        "mode": "paper",
        "write_route": "/api/policy",
        "apply_label": "Apply next cycle",
        "deployed_values": deployed,
        "staged_values": dict(deployed),
        "diff": [],
        "submit_revalidation_required": True,
        "dangerous_flags": {
            "live_trading": {
                "value": "locked off",
                "locked": True,
                "risk": "Live trading cannot be enabled from the cockpit.",
            },
            "broker_submit": {
                "value": "enabled" if raw_policy.get("broker_submit_enabled") else "disabled",
                "locked": False,
                "risk": "Paper broker submit still requires the execution-preview safety gate.",
            },
        },
        "live_trading": "locked off",
    }


def _sector_rows(market: Mapping[str, object]) -> list[dict[str, object]]:
    rows = _list(market.get("sectors"))
    return [dict(_mapping(row)) for row in rows]


def _universe_blocked_rows(dashboard: Mapping[str, object]) -> list[dict[str, object]]:
    return [dict(_mapping(row)) for row in _list(dashboard.get("universe_blocked"))]


def _monitor_events(dashboard: Mapping[str, object]) -> list[dict[str, object]]:
    return monitor_events_from_scheduler(_mapping(dashboard.get("scheduler")))


def _preferences_section() -> dict[str, str]:
    return {"color_preset": "amber", "theme": "accent", "density": "full"}


def _qa_scenarios_enabled(value: bool | None) -> bool:
    if value is not None:
        return value
    return os.getenv("AGENCY_COCKPIT_QA_SCENARIOS", "").strip().lower() in {"1", "true", "yes", "on"}


def _qa_scenario(state: str, context: Mapping[str, object]) -> dict[str, object]:
    if state == "outage":
        scenario = {
            "state": "outage",
            "headline": "Selection is paused because critical data is unavailable.",
            "detail": "Training scenario only. Refresh actions are disabled as readiness proof.",
            "engine_cards": _engine_cards([_mapping(item) for item in _list(context.get("engines"))][:2]),
            "retry_label": "Training retry countdown",
            "last_good_cycle_label": "Last good cycle proof: training scenario",
            "candidate_controls_enabled": False,
        }
    elif state == "submitted":
        submitted_orders = [
            {
                "ticker": "SCENARIO",
                "side": "BUY",
                "qty": 1.0,
                "limit_price": 0.0,
                "notional": 0.0,
                "broker_order_id": "training scenario only",
                "state": "SUBMITTED",
            }
        ]
        scenario = {
            "state": "submitted",
            "headline": "1 paper orders were transmitted for this cycle.",
            "detail": "Training scenario only. Broker evidence is simulated by the scenario shell.",
            "submitted_orders": submitted_orders,
            "submitted_total_notional": 0.0,
            "candidate_controls_enabled": False,
        }
    elif state == "no-actionable":
        scenario = {
            "state": "no-actionable",
            "headline": "Nothing actionable today. The agent already filtered the universe.",
            "detail": "Training scenario only. Review calm empty-state behavior.",
            "skip_to_portfolio_label": "Skip to Portfolio",
            "closest_candidates": _closest_candidate_rows(
                [_mapping(item) for item in _list(context.get("candidates"))]
            ),
            "agent_note": "Training scenario only. The production funnel is not being judged by this state.",
            "candidate_controls_enabled": False,
        }
    else:
        actionable = _int(_mapping(context.get("funnel")).get("actionable"), fallback=0)
        scenario = {
            "state": "normal",
            "headline": f"{actionable} trades ready. Approve what you want to ship today.",
            "detail": "Training scenario only. This page is not operational evidence.",
            "candidate_controls_enabled": True,
        }
    scenario["qa_override"] = True
    return scenario


def _source_context_status(context: Mapping[str, object]) -> dict[str, object]:
    status = _mapping(context.get("context_status"))
    if status:
        return status
    return {
        "status": "ready",
        "status_label": "Ready",
        "status_class": "pass",
        "detail": "Section data loaded for this cockpit request.",
    }


def _portfolio_phase_section(
    positions: Sequence[Mapping[str, object]],
    *,
    portfolio_status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    status = _mapping(portfolio_status)
    position_count = len(positions)
    guidance = (
        f"Review {position_count} open paper position(s). Choose Keep or Close before clearing new orders."
        if position_count
        else "No open paper positions are reported. You can continue to clearance; the server will still revalidate account capacity."
    )
    return {
        "bluf": (
            "Review current positions before clearing today's manifest."
            if position_count
            else "No open paper positions need review before clearance."
        ),
        "empty_state": "No open paper positions are reported by the broker for this cycle; continue to clearance if candidate review is complete.",
        "guidance": guidance,
        "advance_label": "Continue to Clearance",
        "portfolio_review_required": position_count > 0,
        "position_count": position_count,
        "status_label": _first_text(status.get("status_label"), default="Ready"),
        "status_class": _first_text(status.get("status_class"), default="pass"),
        "status_detail": _first_text(status.get("detail")),
    }


def _clearance_section(
    positions: Sequence[Mapping[str, object]],
    candidates: Sequence[Mapping[str, object]],
    execution: Mapping[str, object],
    *,
    execution_status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    manifest: list[dict[str, object]] = []
    for position in positions:
        if position.get("requires_exit") is True:
            manifest.append(
                {
                    "kind": "exit",
                    "ticker": position.get("ticker"),
                    "side": "SELL",
                    "reason": _first_text(position.get("exit_signal"), default="Exit review required"),
                    "notional": _float(position.get("market_value")),
                }
            )
    orderable = {_first_text(_mapping(row).get("ticker")): _mapping(row) for row in _list(execution.get("orderable_rows"))}
    for candidate in candidates:
        if candidate.get("actionable") is not True:
            continue
        ticker = _first_text(candidate.get("ticker"))
        preview = orderable.get(ticker)
        if not preview and not candidate.get("order_notional"):
            continue
        notional = _money_value(
            candidate.get("order_notional"),
            preview.get("notional") if preview else None,
            preview.get("notional_label") if preview else None,
        )
        manifest.append(
            {
                "kind": "buy" if candidate.get("direction") == "long" else "sell",
                "ticker": ticker,
                "side": _first_text(_mapping(preview).get("side"), default="BUY"),
                "reason": _first_text(candidate.get("evidence_line"), default="Approved candidate"),
                "notional": notional,
                "order_intent_hash": _first_text(candidate.get("order_intent_hash")),
                "cycle_id": _first_text(candidate.get("cycle_id")),
                "as_of": _first_text(candidate.get("as_of")),
            }
        )
    status = _mapping(execution_status)
    return {
        "bluf": "Check the manifest, confirm the paper-only gate, then submit approved paper orders.",
        "requires_position_decisions": len(positions) > 0,
        "submit_phrase": "submit paper orders",
        "manifest": manifest,
        "exits": [row for row in manifest if row.get("kind") == "exit"],
        "orders": [row for row in manifest if row.get("kind") != "exit"],
        "status_label": _first_text(status.get("status_label"), default="Ready"),
        "status_class": _first_text(status.get("status_class"), default="pass"),
        "status_detail": _first_text(status.get("detail")),
    }


def _audit_lifecycle(
    candidates: Sequence[Mapping[str, object]],
    cycle_id: str,
) -> dict[str, object]:
    traces: dict[str, list[dict[str, object]]] = {}
    for row in candidates:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        traces[ticker] = [
            {
                "message": (
                    "Approved by current cockpit context."
                    if row.get("status") == "approved"
                    else str(row.get("blocker") or "Candidate is visible for audit.")
                ),
                "status": str(row.get("status") or "unknown"),
                "evidence_hash": str(row.get("evidence_hash") or ""),
            }
        ]
    return {"cycle_id": cycle_id, "traces": traces}


def _evidence_items(item: Mapping[str, object]) -> list[dict[str, str]]:
    raw_reasons = _list(item.get("top_reasons")) or _list(item.get("evidence"))
    rows: list[dict[str, str]] = []
    for reason in raw_reasons[:3]:
        if isinstance(reason, Mapping):
            text = _first_text(reason.get("text"), reason.get("detail"), reason.get("reason"))
            tier = _first_text(reason.get("tier"), default="confirmed")
            source = _first_text(reason.get("source"), default="Evidence")
        else:
            text = str(reason)
            tier = "confirmed"
            source = "Evidence"
        if text:
            rows.append({"tier": tier, "source": source, "text": text})
    if rows:
        return rows
    source_count = _int(item.get("source_count"))
    confirmed_count = _int(item.get("confirmed_signal_count"))
    if source_count or confirmed_count:
        return [
            {
                "tier": "confirmed" if confirmed_count else "inferred",
                "source": "Evidence coverage",
                "text": f"{source_count} independent source(s); {confirmed_count} confirmed signal(s).",
            }
        ]
    return [
        {
            "tier": "suppressed",
            "source": "Evidence",
            "text": "No concrete evidence line is available in the current pack.",
        }
    ]


def _compact_cards(cards: Sequence[object], *, limit: int = 4) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in cards[:limit]:
        card = _mapping(raw)
        label = _first_text(card.get("label"), card.get("title"), default="Evidence")
        detail = _first_text(card.get("detail"), card.get("text"), default="Detail unavailable.")
        meta = _first_text(card.get("meta"), card.get("tone"))
        tone = _first_text(card.get("tone"), default="neutral")
        rows.append({"label": label, "detail": detail, "meta": meta, "tone": tone})
    return rows


def _compact_signals(signals: Sequence[object], *, limit: int = 8) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in signals[:limit]:
        signal = _mapping(raw)
        lane = _label_text(
            _first_text(signal.get("display_name"), signal.get("label"), signal.get("lane"), default="Signal")
        )
        score = _first_text(signal.get("score"))
        confidence = _first_text(signal.get("confidence_pct"))
        confidence_label = f"{confidence}%" if confidence and not confidence.endswith("%") else confidence
        source = _first_text(signal.get("source"), signal.get("source_key"), default="source unknown")
        timestamp = _first_text(signal.get("timestamp_label"), signal.get("timestamp_as_of"))
        hard_evidence = _signal_hard_evidence(signal, score=score, confidence=confidence_label)
        summary = _first_text(
            signal.get("trigger_headline"),
            signal.get("summary"),
            default=f"{lane} signal was recorded.",
        )
        rows.append(
            {
                "lane": lane,
                "direction": _first_text(signal.get("direction"), default="NEUTRAL"),
                "actionability": _first_text(signal.get("actionability_label"), default="Context"),
                "freshness": _first_text(signal.get("freshness"), default="unknown"),
                "verification": _first_text(signal.get("verification_label"), default="unverified"),
                "score": score,
                "confidence": confidence_label,
                "source": source,
                "timestamp": timestamp,
                "summary": summary,
                "detail": _first_text(signal.get("trigger_detail"), signal.get("reason_text")),
                "reason": _first_text(signal.get("reason_codes_label"), signal.get("reason_text")),
                "hard_evidence": hard_evidence,
            }
        )
    return rows


def _signal_hard_evidence(
    signal: Mapping[str, object],
    *,
    score: str,
    confidence: str,
) -> str:
    cards = [_mapping(card) for card in _list(signal.get("trigger_cards"))]
    pieces: list[str] = []
    for card in cards[:4]:
        label = _first_text(card.get("label"))
        value = _first_text(card.get("value"))
        if label and value:
            pieces.append(f"{label} {value}")
    if not pieces and score:
        pieces.append(f"Score {score}")
    if not pieces and _first_text(signal.get("source")):
        pieces.append(f"Source {_first_text(signal.get('source'))}")
    if confidence and not any(piece.lower().startswith("confidence ") for piece in pieces):
        pieces.append(f"Confidence {confidence}")
    return "; ".join(pieces)


def _compact_evidence_context(
    label: str,
    evidence: Mapping[str, object],
) -> dict[str, str] | None:
    if not evidence:
        return None
    meaning = _first_text(evidence.get("meaning"), evidence.get("status_label"))
    detail = _first_text(evidence.get("detail"), evidence.get("reason"))
    if not meaning and not detail:
        return None
    return {
        "label": label,
        "detail": detail or meaning,
        "meta": meaning,
        "tone": _first_text(evidence.get("status_class"), default="neutral"),
    }


def _candidate_is_reviewable(item: Mapping[str, object], *, gate_blocked: bool) -> bool:
    if gate_blocked:
        return False
    if item.get("is_reviewable") is False:
        return False
    review_state = _first_text(item.get("review_state")).upper()
    human_decision = _first_text(item.get("human_review_decision"), default="PENDING").upper()
    has_review_action = bool(
        _first_text(item.get("approve_review_action"))
        and _first_text(item.get("defer_review_action"))
        and _first_text(item.get("reject_review_action"))
    )
    return has_review_action and human_decision == "PENDING" and review_state in {"", "READY", "WAITING"}


def _candidate_status_label(
    *,
    actionable: bool,
    order_reviewable: bool,
    reviewable: bool,
    risk_label: str,
) -> str:
    if actionable:
        return "Ready to submit paper order"
    if order_reviewable:
        return "Order details need approval"
    if reviewable:
        return "Ready for research review"
    if "BLOCK" in risk_label:
        return "Audit only - policy gate blocks order"
    return "Review context - not orderable now"


def _candidate_evidence_tiers(items: Sequence[Mapping[str, object]]) -> list[str]:
    tiers = {_first_text(item.get("tier"), default="confirmed") for item in items}
    return [tier for tier in ("confirmed", "inferred", "suppressed") if tier in tiers] or ["suppressed"]


def _first_metric(text: str) -> str:
    match = re.search(r"[-+]?\d+(?:\.\d+)?%?", text)
    return match.group(0) if match else ""


def _source_health_detail(item: Mapping[str, object]) -> str:
    source = _first_text(item.get("source"), item.get("name"), default="Data source")
    status = _first_text(item.get("status"), item.get("status_label"), default="status not reported")
    freshness = _first_text(item.get("freshness"), item.get("freshness_label"), default="freshness not reported")
    checked_at = _first_text(item.get("checked_at"), item.get("last_update"), default="")
    suffix = f"; checked at {checked_at}" if checked_at else ""
    return f"{source} reports {status} / {freshness}{suffix}."


def _money_value(*values: object) -> float:
    return _float(*values, fallback=0.0)


def _number_reported(*values: object) -> bool:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return True
        if isinstance(value, str):
            text = value.replace("$", "").replace(",", "").replace("%", "").strip()
            if not text:
                continue
            try:
                float(text)
            except ValueError:
                continue
            return True
    return False


def _percent_label(value: float, *, reported: bool, decimals: int = 1) -> str:
    if not reported:
        return "not reported"
    return f"{value:.{decimals}f}%"


def _money_label(value: float, *, reported: bool) -> str:
    if not reported:
        return "not reported"
    return f"${value:,.0f}"


def _staged_order_notional(execution: Mapping[str, object]) -> float:
    rows = _list(execution.get("orderable_rows")) or [
        row
        for row in _list(execution.get("preview_rows"))
        if _mapping(row).get("preview_state") == "READY"
    ]
    total = 0.0
    for raw in rows:
        row = _mapping(raw)
        total += _money_value(row.get("notional"), row.get("notional_label"), row.get("order_value_label"))
    return round(total, 2)


def _position_requires_exit(item: Mapping[str, object], *, current: float, stop: float) -> bool:
    exit_signal = _first_text(item.get("exit_signal"), item.get("exit_priority")).upper()
    if exit_signal and exit_signal not in {"NONE", "HOLD"}:
        return True
    return current > 0 and stop > 0 and current <= stop


def _status_to_engine_state(status_class: object, status_label: object) -> str:
    label = f"{status_class or ''} {status_label or ''}".lower()
    if any(token in label for token in ("block", "down", "unavailable", "void", "failed")):
        return "down"
    if any(token in label for token in ("warn", "degraded", "needs", "partial", "delayed")):
        return "needs_refresh"
    return "live"


def _source_engine_state(item: Mapping[str, object]) -> str:
    status = _first_text(item.get("status"), item.get("status_label")).upper()
    freshness = _first_text(item.get("freshness"), item.get("freshness_label")).upper()
    status_class = _first_text(item.get("status_class")).lower()
    if status in {"HEALTHY", "OK", "PASS"} and freshness == "FRESH":
        return "needs_refresh" if status_class == "block" else "live"
    if status in {"STALE", "DEGRADED"} or freshness in {"STALE", "AGING"}:
        return "needs_refresh"
    return _status_to_engine_state(item.get("status_class"), item.get("status_label"))


def _status_to_source_state(status_class: object, status_label: object) -> str:
    state = _status_to_engine_state(status_class, status_label)
    if state == "down":
        return "unavailable"
    if state == "needs_refresh":
        return "partial"
    return "ready"


def _scrub_secrets(value: object) -> object:
    if isinstance(value, Mapping):
        scrubbed: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if _is_secret_key(key_lower):
                continue
            scrubbed[key_text] = _scrub_secrets(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_secrets(item) for item in value]
    return value


def _is_secret_key(key_lower: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key_lower).strip("_")
    exact_secret_keys = {
        "secret",
        "api_key",
        "apikey",
        "password",
        "database_url",
        "token",
        "bearer",
        "credential",
        "credentials",
        "authorization",
        "private_key",
        "certificate",
        "access_key",
        "access_token",
        "accesstoken",
        "refresh_key",
        "refresh_token",
        "refreshtoken",
        "auth_token",
    }
    return (
        normalized in exact_secret_keys
        or normalized.endswith(("_secret", "_token", "_password", "_api_key", "_private_key", "_access_key"))
        or normalized.startswith("secret_")
    )


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _first_text(*values: object, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        normalized = value
        if isinstance(value, list | tuple):
            normalized = ", ".join(str(item) for item in value if item is not None)
        text = str(normalized).strip()
        if text:
            return text
    return default


def _float(*values: object, fallback: float = 0.0) -> float:
    for value in values:
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            text = value.replace("$", "").replace(",", "").replace("%", "").strip()
            try:
                return float(text)
            except ValueError:
                continue
    return fallback


def _int(*values: object, fallback: int = 0) -> int:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value.strip()))
            except ValueError:
                continue
    return fallback


def _score(*values: object) -> float:
    value = _float(*values, fallback=0.0)
    if value > 1.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


def _bounded_score(*values: object, fallback: float = 0.0) -> float:
    value = _float(*values, fallback=fallback)
    if value > 1.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


def _gauge_degrees(value: float, cap: float) -> int:
    ratio = value / cap if cap > 0 else 0.0
    return int(round(max(0.0, min(1.0, ratio)) * 180 - 90))
