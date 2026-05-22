"""Production view model for the V3 pre-flight cockpit."""
from __future__ import annotations

import asyncio
import math
import os
import re
from collections.abc import Mapping, Sequence
from typing import cast

from agency.runtime.cockpit_monitor import (
    monitor_events_from_scheduler,
    monitor_status_from_scheduler,
    source_health_rows,
)

TRADE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}
MAX_COCKPIT_CANDIDATES = 25
QA_SCENARIOS = {"normal", "no-actionable", "outage", "submitted"}


async def cockpit_context(
    *,
    qa_scenario: str | None = None,
    qa_scenarios_enabled: bool | None = None,
) -> dict[str, object]:
    """Build the cockpit aggregate from existing production page contexts."""

    from agency.views.command import dashboard_context, paper_review_status_context
    from agency.views.execution import execution_preview_context
    from agency.views.portfolio import portfolio_monitor_context

    dashboard, execution, portfolio, paper_review = await asyncio.gather(
        dashboard_context(),
        execution_preview_context(),
        portfolio_monitor_context(),
        paper_review_status_context(),
    )
    if _list(paper_review.get("queue")):
        dashboard = {
            **dashboard,
            "review_queue": _list(paper_review.get("queue")),
            "review_progress": _mapping(paper_review.get("progress")),
        }
    return cockpit_context_from_sources(
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
    positions = _position_rows(portfolio)
    account = _account_section(market, portfolio, dashboard, execution, len(candidates))
    portfolio_phase = _portfolio_phase_section(positions)
    clearance = _clearance_section(positions, candidates, execution)
    cycle = _cycle_section(dashboard, engines)
    qa_enabled = _qa_scenarios_enabled(qa_scenarios_enabled)
    scheduler = _mapping(dashboard.get("scheduler"))
    proof_timestamp = _first_text(
        _mapping(dashboard.get("data_load_status")).get("latest_checked_at"),
        _mapping(dashboard.get("data_load_status")).get("updated_at"),
        _mapping(dashboard.get("data_load_status")).get("as_of"),
    )
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
        "sectors": _sector_rows(market),
        "sources": _source_rows(dashboard, proof_timestamp=proof_timestamp),
        "universe_blocked": _universe_blocked_rows(dashboard),
        "signals": _signal_rows(signals_context),
        "audit_lifecycle": _audit_lifecycle(candidates, _first_text(cycle.get("id"))),
        "policy": _policy_section(dashboard),
        "monitor_events": _monitor_events(dashboard),
        "monitor": monitor_status_from_scheduler(scheduler),
        "preferences": _preferences_section(),
        "qa_scenarios_enabled": qa_enabled,
        "qa_scenarios": sorted(QA_SCENARIOS),
    }
    context["scenario"] = _scenario_from_context(context, execution)
    if qa_enabled and qa_scenario in QA_SCENARIOS:
        context["scenario"] = _qa_scenario(qa_scenario, context)
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
    reviewable = sum(1 for row in candidates if row.get("reviewable") is True)
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
    previews = {_first_text(_mapping(row).get("ticker")): _mapping(row) for row in _list(execution.get("preview_rows"))}
    rows: list[dict[str, object]] = []
    for raw_index, raw in enumerate(source_rows, start=1):
        item = _mapping(raw)
        ticker = _first_text(item.get("ticker"), default=f"ROW{raw_index}")
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
        gate_blocked = "BLOCK" in risk_label
        actionable = action in TRADE_ACTIONS and item.get("is_reviewable") is not False and not gate_blocked
        reviewable = _candidate_is_reviewable(item, gate_blocked=gate_blocked)
        status = "approved" if actionable else "blocked" if "BLOCK" in risk_label else "demoted"
        evidence_items = _evidence_items(item)
        evidence_line = evidence_items[0]["text"]
        risk_text = _first_text(
            item.get("risk_detail"),
            item.get("risk_reason"),
            item.get("blocker"),
            default="No major risk flag in current pack.",
        )
        score_display = f"{final_conviction:.2f}"
        rows.append(
            {
                "rank": raw_index,
                "ticker": ticker,
                "name": _first_text(item.get("company"), item.get("name"), default=ticker),
                "sector": _first_text(item.get("sector"), default="Sector not reported"),
                "direction": "short" if action in {"SELL", "SHORT", "COVER"} else "long",
                "det_conviction": _score(item.get("det_conviction"), item.get("deterministic_score_label")),
                "llm_conviction": _score(item.get("llm_conviction"), item.get("llm_score_label")),
                "llm_label": _first_text(item.get("llm_status_label"), default=""),
                "llm_rationale": _first_text(
                    item.get("llm_rationale"),
                    item.get("llm_summary"),
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
                    reviewable=reviewable,
                    risk_label=risk_label,
                ),
                "blocker": None if actionable else risk_text,
                "actionable": actionable,
                "reviewable": reviewable,
                "action_label": "Approve, defer, or reject" if reviewable else "Open audit",
                "decision_controls": ["approve", "defer", "reject"] if reviewable else ["audit"],
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
                "risk_status_label": _first_text(item.get("risk_status_label"), default="No major risk flag"),
                "order_preview": _first_text(preview.get("notional_label"), preview.get("order_value_label"), default="No paper order yet"),
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
    equity = _float(account.get("equity"), portfolio_summary.get("equity"), fallback=100000.0)
    staged_notional = _staged_order_notional(execution)
    staged_exposure_pct = staged_notional / equity * 100 if equity > 0 else 0.0
    gross_post_trade = round(gross_exposure + staged_exposure_pct, 1)
    gross_cap = _float(policy.get("max_gross_exposure_pct"), fallback=100.0)
    capacity_warning = ""
    if gross_post_trade > gross_cap:
        capacity_warning = (
            f"Gross exposure would be {gross_post_trade:.1f}% versus the {gross_cap:.1f}% cap. "
            "Reduce staged buys or close exposure before clearance."
        )
    return {
        "gross_exposure": gross_exposure,
        "gross_post_trade": gross_post_trade,
        "gross_cap": gross_cap,
        "cash_available": _float(portfolio_summary.get("cash_reserve_pct"), fallback=0.0),
        "cash_cap": _float(policy.get("cash_reserve_pct"), fallback=10.0),
        "sector_exposure": _float(portfolio_summary.get("sector_exposure_pct"), fallback=0.0),
        "sector_cap": _float(policy.get("max_sector_exposure_pct"), fallback=35.0),
        "largest_name": _float(portfolio_summary.get("largest_name_pct"), fallback=0.0),
        "largest_name_cap": _float(policy.get("largest_name_cap_pct"), fallback=25.0),
        "open_orders": _int(broker.get("open_order_count"), fallback=len(_list(broker.get("orders")))),
        "open_orders_cap": _int(policy.get("max_open_orders"), fallback=10),
        "buying_power": _float(account.get("buying_power")),
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
    candidates = [_mapping(item) for item in _list(context.get("candidates"))]
    actionable_count = sum(1 for row in candidates if row.get("actionable") is True)
    reviewable_count = sum(1 for row in candidates if row.get("reviewable") is True)
    if reviewable_count == 0 and any(engine.get("state") == "down" for engine in engines):
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
    if actionable_count == 0:
        if reviewable_count > 0:
            return {
                "state": "review",
                "headline": f"{reviewable_count} candidates are ready for research review.",
                "detail": "Approve, defer, or reject the review rows; no paper order is staged until policy and execution gates create an orderable preview.",
            }
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
            "detail": "QA scenario only. Refresh actions are disabled as readiness proof.",
        }
    elif state == "submitted":
        scenario = {
            "state": "submitted",
            "headline": "1 paper orders were transmitted for this cycle.",
            "detail": "QA scenario only. Broker evidence is simulated by the scenario shell.",
        }
    elif state == "no-actionable":
        scenario = {
            "state": "no-actionable",
            "headline": "Nothing actionable today. The agent already filtered the universe.",
            "detail": "QA scenario only. Review calm empty-state behavior.",
        }
    else:
        actionable = _int(_mapping(context.get("funnel")).get("actionable"), fallback=0)
        scenario = {
            "state": "normal",
            "headline": f"{actionable} trades ready. Approve what you want to ship today.",
            "detail": "QA scenario only. This page is not operational evidence.",
        }
    scenario["qa_override"] = True
    return scenario


def _portfolio_phase_section(positions: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "bluf": "Review current positions before clearing today's manifest.",
        "empty_state": "No open paper positions are reported by the broker for this cycle.",
        "position_count": len(positions),
    }


def _clearance_section(
    positions: Sequence[Mapping[str, object]],
    candidates: Sequence[Mapping[str, object]],
    execution: Mapping[str, object],
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
    return {
        "bluf": "Check the manifest, confirm the paper-only gate, then submit approved paper orders.",
        "requires_position_decisions": len(positions) > 0,
        "submit_phrase": "submit paper orders",
        "manifest": manifest,
        "exits": [row for row in manifest if row.get("kind") == "exit"],
        "orders": [row for row in manifest if row.get("kind") != "exit"],
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


def _candidate_status_label(*, actionable: bool, reviewable: bool, risk_label: str) -> str:
    if actionable:
        return "Ready for your decision"
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
