from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agency.portfolio.circuit_breaker import evaluate_circuit_breakers
from agency.portfolio.exit_rules import evaluate_exit_signal
from agency.portfolio.performance import compute_daily_performance, compute_weekly_performance
from agency.portfolio.policy import PortfolioPolicy
from agency.portfolio.state import (
    load_daily_baseline,
    load_entry_timestamps,
    load_high_water_marks,
    load_reentry_cooldowns,
    load_stage1_executed,
    load_weekly_baseline,
    save_high_water_marks,
    update_high_water_marks,
)


def build_portfolio_snapshot(
    *,
    broker_positions: list[dict[str, Any]],
    account: dict[str, Any],
    selection_reports: list[dict[str, Any]],
    state_dir: Path,
    policy: PortfolioPolicy | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    active_policy = policy or PortfolioPolicy()
    now = generated_at or _utc_now()

    stored_hwm = load_high_water_marks(state_dir)
    high_water_marks = update_high_water_marks(stored_hwm, broker_positions)
    save_high_water_marks(state_dir, high_water_marks)

    stage1 = load_stage1_executed(state_dir)
    entries = load_entry_timestamps(state_dir)
    cooldowns = load_reentry_cooldowns(state_dir)
    reports = {_report_ticker(report): report for report in selection_reports if _report_ticker(report)}

    weekly_perf = compute_weekly_performance(
        account,
        load_weekly_baseline(state_dir),
        active_policy,
    )
    daily_perf = compute_daily_performance(account, load_daily_baseline(state_dir))
    circuit = evaluate_circuit_breakers(weekly_perf, daily_perf, active_policy)

    rows = [
        _position_row(
            position,
            reports.get(_position_ticker(position)),
            high_water_marks,
            stage1,
            entries,
            cooldowns,
            now,
            circuit,
            active_policy,
        )
        for position in broker_positions
        if _position_ticker(position)
    ]

    return {
        "schema_version": "1.0.0",
        "generated_at": now,
        "mode": "PAPER" if broker_positions else "READ_ONLY",
        "circuit_breaker": circuit,
        "weekly_performance": weekly_perf,
        "daily_performance": daily_perf,
        "summary": _summary(rows, account, circuit, active_policy),
        "positions": rows,
        "reentry_blocks": _active_reentry_blocks(cooldowns, now),
    }


def _position_row(
    position: dict[str, Any],
    selection_report: dict[str, Any] | None,
    high_water_marks: dict[str, float],
    stage1: dict[str, dict[str, Any]],
    entries: dict[str, dict[str, Any]],
    cooldowns: dict[str, dict[str, Any]],
    now: str,
    circuit: dict[str, Any],
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    ticker = _position_ticker(position)
    unrealized_pct = _float(position.get("unrealized_plpc")) * 100.0
    quantity = _float(position.get("qty"))
    high_water_mark = high_water_marks.get(ticker, unrealized_pct)
    days_held = int(entries.get(ticker, {}).get("trading_days_held", 0))
    signal = evaluate_exit_signal(
        ticker=ticker,
        unrealized_pct=unrealized_pct,
        quantity=quantity,
        trading_days_held=days_held,
        high_water_mark_pct=high_water_mark,
        stage1_executed=bool(stage1.get(ticker, {}).get("executed", False)),
        selection_report=selection_report,
        policy=policy,
    )
    trailing_active = high_water_mark >= policy.trailing_stop_activates_at_pct
    drawdown = round(high_water_mark - unrealized_pct, 4) if trailing_active else None
    daily_review = "DAILY_CIRCUIT_BREAKER" in circuit.get("signals", [])
    return {
        "ticker": ticker,
        "side": str(position.get("side") or "long").upper(),
        "quantity": quantity,
        "market_value": _float(position.get("market_value")),
        "unrealized_pl": _float(position.get("unrealized_pl")),
        "unrealized_plpc": _float(position.get("unrealized_plpc")),
        "trading_days_held": days_held,
        "stage1_executed": bool(stage1.get(ticker, {}).get("executed", False)),
        "high_water_mark_pct": high_water_mark,
        "trailing_stop_active": trailing_active,
        "trailing_stop_drawdown_pct": drawdown,
        "exit_signal": signal["exit_signal"],
        "exit_priority": signal["exit_priority"],
        "exit_reason": signal["exit_reason"],
        "secondary_signals": signal["secondary_signals"],
        "recommendation": signal["recommendation"],
        "reentry_cooldown_active": _cooldown_active(cooldowns.get(ticker), now),
        "portfolio_review_required": daily_review,
        "classification": _classification(signal, daily_review),
        "urgency": signal["exit_priority"],
        "pnl_label": f"${_float(position.get('unrealized_pl')):+.2f} / {unrealized_pct:+.2f}%",
        "thesis_validity": _thesis_validity(selection_report, signal),
    }


def _summary(
    positions: list[dict[str, Any]],
    account: dict[str, Any],
    circuit: dict[str, Any],
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    equity = _float(account.get("equity") or account.get("portfolio_value"))
    market_value = sum(_float(position.get("market_value")) for position in positions)
    gross_exposure = round(market_value / equity * 100.0, 4) if equity > 0 else 0.0
    return {
        "position_count": len(positions),
        "urgent_count": sum(1 for position in positions if position["classification"] == "URGENT"),
        "action_needed_count": sum(
            1 for position in positions if position["classification"] == "ACTION_NEEDED"
        ),
        "hold_count": sum(1 for position in positions if position["classification"] == "HOLD"),
        "gross_exposure_pct": gross_exposure,
        "available_capacity_pct": round(max(policy.max_gross_exposure_pct - gross_exposure, 0.0), 4),
        "cash_pct": round(max(100.0 - gross_exposure, 0.0), 4),
        "equity": equity,
        "new_entries_blocked": circuit["new_entries_blocked"],
        "reduced_sizing_active": circuit["reduced_sizing_active"],
    }


def _active_reentry_blocks(
    cooldowns: dict[str, dict[str, Any]],
    now: str,
) -> dict[str, dict[str, Any]]:
    return {
        ticker: {
            "blocked_until": str(entry.get("blocked_until") or ""),
            "reason": str(entry.get("reason") or ""),
        }
        for ticker, entry in cooldowns.items()
        if _cooldown_active(entry, now)
    }


def _cooldown_active(entry: dict[str, Any] | None, now: str) -> bool:
    if not entry:
        return False
    try:
        blocked_until = _parse_utc(str(entry.get("blocked_until") or ""))
        return _parse_utc(now) < blocked_until
    except ValueError:
        return False


def _classification(signal: dict[str, Any], daily_review: bool) -> str:
    if signal["exit_priority"] == "URGENT":
        return "URGENT"
    if signal["exit_signal"] not in {"HOLD", "SETUP_WARNING"}:
        return "ACTION_NEEDED"
    if daily_review or "SETUP_WARNING" in signal.get("secondary_signals", []):
        return "WARNING"
    return "HOLD"


def _thesis_validity(
    selection_report: dict[str, Any] | None,
    signal: dict[str, Any],
) -> str:
    if signal["exit_signal"] == "THESIS_BROKEN":
        return "Thesis broken"
    if selection_report is None:
        return "No current thesis report"
    if "SETUP_WARNING" in signal.get("secondary_signals", []):
        return "Thesis valid with warnings"
    return "Thesis still valid"


def _position_ticker(position: dict[str, Any]) -> str:
    return str(position.get("symbol") or position.get("ticker") or "").upper()


def _report_ticker(report: dict[str, Any]) -> str:
    return str(report.get("ticker") or report.get("symbol") or "").upper()


def _float(value: Any) -> float:
    try:
        if isinstance(value, bool) or value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
