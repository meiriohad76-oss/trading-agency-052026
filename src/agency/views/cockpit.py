"""Production view model for the V3 pre-flight cockpit."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import cast

TRADE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}
MAX_COCKPIT_CANDIDATES = 25


async def cockpit_context() -> dict[str, object]:
    """Build the cockpit aggregate from existing production page contexts."""

    from agency.views.command import dashboard_context
    from agency.views.execution import execution_preview_context
    from agency.views.portfolio import portfolio_monitor_context

    dashboard, execution, portfolio = await asyncio.gather(
        dashboard_context(),
        execution_preview_context(),
        portfolio_monitor_context(),
    )
    return cockpit_context_from_sources(
        {
            "dashboard": dashboard,
            "execution": execution,
            "portfolio": portfolio,
            "market": {},
            "signals": {},
        }
    )


def cockpit_context_from_sources(sources: Mapping[str, object]) -> dict[str, object]:
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
    positions = _position_rows(portfolio)
    account = _account_section(market, portfolio, dashboard, execution, len(candidates))
    context: dict[str, object] = {
        "active_nav": "cockpit",
        "cycle": _cycle_section(dashboard, engines),
        "market": _market_section(market, dashboard),
        "engines": engines,
        "funnel": _funnel_section(dashboard, candidates),
        "candidates": candidates,
        "positions": positions,
        "account": account,
        "sectors": _sector_rows(market),
        "sources": _source_rows(dashboard),
        "universe_blocked": _universe_blocked_rows(dashboard),
        "signals": _signal_rows(signals_context),
        "audit_lifecycle": _audit_lifecycle(candidates),
        "policy": _policy_section(dashboard),
        "monitor_events": _monitor_events(dashboard),
    }
    context["scenario"] = _scenario_from_context(context, execution)
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
            default="scheduled by lane policy",
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
    return {
        "regime": _first_text(
            summary.get("headline"),
            summary.get("status_label"),
            market.get("regime"),
            default="Market regime unavailable",
        ),
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
                "state": _status_to_engine_state(item.get("status_class"), item.get("status_label")),
                "age": _first_text(item.get("freshness_label"), item.get("last_update"), default="not checked"),
                "detail": _first_text(item.get("detail"), item.get("notes"), default="No detail reported."),
            }
        )
    for lane in _list(signals_context.get("lanes")):
        item = _mapping(lane)
        rows.append(
            {
                "name": _first_text(item.get("label"), item.get("lane"), default="Signal lane"),
                "state": _status_to_engine_state(item.get("status_class"), item.get("status_label")),
                "age": _first_text(item.get("freshness_label"), default="latest lane status"),
                "detail": _first_text(item.get("detail"), default="Signal lane reported no detail."),
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
        "blocked_by_policy": blocked,
    }


def _candidate_rows(
    dashboard: Mapping[str, object],
    execution: Mapping[str, object],
) -> list[dict[str, object]]:
    source_rows = _list(dashboard.get("review_queue")) or _list(dashboard.get("candidates"))
    previews = {_first_text(_mapping(row).get("ticker")): _mapping(row) for row in _list(execution.get("preview_rows"))}
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(source_rows, start=1):
        item = _mapping(raw)
        ticker = _first_text(item.get("ticker"), default=f"ROW{index}")
        action = _first_text(item.get("final_action"), item.get("action"), default="WATCH").upper()
        risk_label = _first_text(item.get("risk_status_label"), item.get("risk_status"), default="").upper()
        final_conviction = _score(
            item.get("final_conviction"),
            item.get("final_score"),
            item.get("score"),
            item.get("conviction"),
        )
        preview = previews.get(ticker, {})
        actionable = action in TRADE_ACTIONS and item.get("is_reviewable") is not False and "BLOCK" not in risk_label
        status = "approved" if actionable else "blocked" if "BLOCK" in risk_label else "demoted"
        evidence_items = _evidence_items(item)
        risk_text = _first_text(
            item.get("risk_detail"),
            item.get("risk_reason"),
            item.get("blocker"),
            default="No major risk flag in current pack.",
        )
        rows.append(
            {
                "rank": index,
                "ticker": ticker,
                "name": _first_text(item.get("company"), item.get("name"), default=ticker),
                "sector": _first_text(item.get("sector"), default="Sector not reported"),
                "direction": "short" if action in {"SELL", "SHORT", "COVER"} else "long",
                "det_conviction": _score(item.get("det_conviction"), item.get("deterministic_score_label")),
                "llm_conviction": _score(item.get("llm_conviction"), item.get("llm_score_label")),
                "llm_label": _first_text(item.get("llm_status_label"), default="LLM not run for this ticker"),
                "final_conviction": final_conviction,
                "final_conviction_label": f"{final_conviction:.2f}",
                "status": status,
                "status_label": _first_text(item.get("review_status_label"), default="Ready for review" if actionable else "Audit only"),
                "blocker": None if actionable else risk_text,
                "actionable": actionable,
                "action_label": "Approve, defer, or reject" if actionable else "Open audit",
                "evidence": evidence_items,
                "evidence_line": evidence_items[0]["text"],
                "risk_line": risk_text,
                "risk_status_label": _first_text(item.get("risk_status_label"), default="No major risk flag"),
                "order_preview": _first_text(preview.get("notional_label"), preview.get("order_value_label"), default="No paper order yet"),
                "cycle_id": _first_text(item.get("cycle_id"), default=""),
                "as_of": _first_text(item.get("as_of"), default=""),
                "detail_url": f"/candidates/{ticker}",
                "audit_url": f"/api/audit/{ticker}",
            }
        )
    return sorted(rows, key=lambda row: cast(float, row["final_conviction"]), reverse=True)[
        :MAX_COCKPIT_CANDIDATES
    ]


def _position_rows(portfolio: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in _list(portfolio.get("positions")):
        item = _mapping(raw)
        ticker = _first_text(item.get("ticker"), item.get("symbol"), default="Position")
        rows.append(
            {
                "ticker": ticker,
                "qty": _float(item.get("qty"), item.get("quantity")),
                "current": _float(item.get("current_price"), item.get("current")),
                "market_value": _float(item.get("market_value")),
                "pl_pct": _float(item.get("unrealized_pl_pct"), item.get("pl_pct")),
                "status": _first_text(item.get("status_label"), item.get("status"), default="Hold"),
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
    return {
        "gross_exposure": _float(
            broker.get("gross_exposure_pct"),
            portfolio_summary.get("gross_exposure_pct"),
        ),
        "gross_post_trade": _float(
            broker.get("gross_exposure_pct"),
            portfolio_summary.get("gross_exposure_pct"),
        ),
        "gross_cap": _float(policy.get("max_gross_exposure_pct"), fallback=100.0),
        "cash_available": _float(portfolio_summary.get("cash_reserve_pct"), fallback=0.0),
        "cash_cap": _float(policy.get("cash_reserve_pct"), fallback=10.0),
        "largest_name": _float(portfolio_summary.get("largest_name_pct"), fallback=0.0),
        "largest_name_cap": _float(policy.get("largest_name_cap_pct"), fallback=25.0),
        "open_orders": _int(broker.get("open_order_count"), fallback=len(_list(broker.get("orders")))),
        "open_orders_cap": _int(policy.get("max_open_orders"), fallback=10),
        "buying_power": _float(account.get("buying_power")),
        "week_pnl": _float(portfolio_summary.get("week_pnl_pct"), fallback=0.0),
        "week_target": _float(policy.get("weekly_target_pct"), fallback=0.0),
        "ready_to_trade": f"{orderable_count}/{candidate_count}",
    }


def _source_rows(dashboard: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in _list(dashboard.get("data_sources")):
        item = _mapping(raw)
        rows.append(
            {
                "name": _first_text(item.get("name"), item.get("source"), default="Data source"),
                "tier": _source_tier(item),
                "state": _status_to_source_state(item.get("status_class"), item.get("status_label")),
                "last_pull": _first_text(item.get("last_update"), default="not reported"),
                "coverage": _first_text(item.get("coverage_label"), default="coverage not reported"),
                "note": _first_text(item.get("detail"), default="No source note reported."),
            }
        )
    return rows


def _signal_rows(signals_context: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in _list(signals_context.get("lanes")):
        item = _mapping(raw)
        rows.append(
            {
                "name": _first_text(item.get("label"), item.get("lane"), default="Signal"),
                "status": _first_text(item.get("status_label"), default="Signal status"),
                "state": _status_to_source_state(item.get("status_class"), item.get("status_label")),
                "detail": _first_text(item.get("detail"), default="No signal detail reported."),
            }
        )
    return rows


def _scenario_from_context(
    context: Mapping[str, object],
    execution: Mapping[str, object],
) -> dict[str, object]:
    engines = [_mapping(item) for item in _list(context.get("engines"))]
    if any(engine.get("state") == "down" for engine in engines):
        return {
            "state": "outage",
            "headline": "Selection is paused because critical data is unavailable.",
            "detail": "Refresh the red engine or open its lane detail before approving new decisions.",
        }
    submitted_rows = [
        _mapping(row)
        for row in _list(execution.get("preview_rows"))
        if str(_mapping(row).get("execution_state") or "").upper() in {"SUBMITTED", "FILLED"}
    ]
    if submitted_rows:
        return {
            "state": "submitted",
            "headline": f"{len(submitted_rows)} paper orders were transmitted for this cycle.",
            "detail": "Review broker IDs and wait for the next cycle before staging more orders.",
        }
    candidates = [_mapping(item) for item in _list(context.get("candidates"))]
    actionable_count = sum(1 for row in candidates if row.get("actionable") is True)
    if actionable_count == 0:
        return {
            "state": "no-actionable",
            "headline": "Nothing actionable today. The agent already filtered the universe.",
            "detail": "Review the closest candidates or portfolio only; no paper order is staged.",
        }
    return {
        "state": "normal",
        "headline": f"{actionable_count} trades ready. Approve what you want to ship today.",
        "detail": "Start with the ranked candidates, then review portfolio capacity before clearance.",
    }


def _policy_section(dashboard: Mapping[str, object]) -> dict[str, object]:
    policy = dict(_mapping(dashboard.get("policy_summary")))
    policy.setdefault("live_trading", "locked off")
    policy.setdefault("mode", "paper")
    return policy


def _sector_rows(market: Mapping[str, object]) -> list[dict[str, object]]:
    rows = _list(market.get("sectors"))
    return [dict(_mapping(row)) for row in rows]


def _universe_blocked_rows(dashboard: Mapping[str, object]) -> list[dict[str, object]]:
    return [dict(_mapping(row)) for row in _list(dashboard.get("universe_blocked"))]


def _monitor_events(dashboard: Mapping[str, object]) -> list[dict[str, object]]:
    scheduler = _mapping(dashboard.get("scheduler"))
    events: list[dict[str, object]] = []
    for raw in _list(scheduler.get("running_jobs")):
        item = _mapping(raw)
        events.append(
            {
                "kind": "running",
                "message": _first_text(item.get("label"), item.get("lane"), default="Job running"),
                "timestamp": _first_text(item.get("started_at"), item.get("eta_label"), default="now"),
            }
        )
    for raw in _list(scheduler.get("next_jobs")):
        item = _mapping(raw)
        events.append(
            {
                "kind": "next",
                "message": _first_text(item.get("label"), item.get("lane"), default="Next job"),
                "timestamp": _first_text(item.get("eta_label"), default="scheduled"),
            }
        )
    return events


def _audit_lifecycle(candidates: Sequence[Mapping[str, object]]) -> dict[str, object]:
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
            }
        ]
    return {"traces": traces}


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
    return rows or [
        {
            "tier": "suppressed",
            "source": "Evidence",
            "text": "No concrete evidence line is available in the current pack.",
        }
    ]


def _status_to_engine_state(status_class: object, status_label: object) -> str:
    label = f"{status_class or ''} {status_label or ''}".lower()
    if any(token in label for token in ("block", "down", "unavailable", "void", "failed")):
        return "down"
    if any(token in label for token in ("warn", "degraded", "needs", "partial", "delayed")):
        return "needs_refresh"
    return "live"


def _status_to_source_state(status_class: object, status_label: object) -> str:
    state = _status_to_engine_state(status_class, status_label)
    if state == "down":
        return "unavailable"
    if state == "needs_refresh":
        return "partial"
    return "fresh"


def _source_tier(source: Mapping[str, object]) -> str:
    name = _first_text(source.get("name"), source.get("source")).lower()
    if "alpaca" in name or "broker" in name:
        return "broker"
    if "massive" in name or "price" in name or "trade" in name:
        return "market"
    if "sec" in name or "edgar" in name:
        return "official"
    if "email" in name or "subscription" in name or "seeking alpha" in name:
        return "paid-sub"
    if "llm" in name:
        return "llm"
    return "operational"


def _scrub_secrets(value: object) -> object:
    if isinstance(value, Mapping):
        scrubbed: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(token in key_text.lower() for token in ("secret", "api_key", "password", "database_url")):
                continue
            scrubbed[key_text] = _scrub_secrets(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_secrets(item) for item in value]
    return value


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
