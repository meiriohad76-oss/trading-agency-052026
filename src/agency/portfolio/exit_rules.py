from __future__ import annotations

from typing import Any

from agency.portfolio.policy import PortfolioPolicy


def evaluate_exit_signal(
    *,
    ticker: str,
    unrealized_pct: float,
    quantity: float,
    trading_days_held: int,
    high_water_mark_pct: float,
    stage1_executed: bool,
    selection_report: dict[str, Any] | None,
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []

    if unrealized_pct <= -policy.stop_loss_pct:
        signals.append(
            _signal(
                "STOP_LOSS",
                "URGENT",
                f"{ticker} unrealized loss {unrealized_pct:.2f}% hit the "
                f"-{policy.stop_loss_pct:.1f}% stop-loss.",
                {
                    "action": "CLOSE",
                    "rationale": "Hard stop reached. Close full position.",
                },
            )
        )

    if _thesis_is_broken(selection_report, policy):
        action = _report_action(selection_report)
        conviction = _report_conviction(selection_report)
        signals.append(
            _signal(
                "THESIS_BROKEN",
                "HIGH",
                f"{ticker} thesis broken: action={action or 'UNKNOWN'}, "
                f"conviction={conviction:.2f}.",
                {
                    "action": "CLOSE",
                    "rationale": "Research thesis no longer supports holding this position.",
                },
            )
        )

    if (
        trading_days_held >= policy.minimum_hold_days
        and unrealized_pct >= policy.take_profit_stage2_pct
    ):
        signals.append(
            _signal(
                "TAKE_PROFIT_STAGE_2",
                "NORMAL",
                f"{ticker} gain {unrealized_pct:.2f}% reached the "
                f"+{policy.take_profit_stage2_pct:.1f}% Stage 2 target.",
                {
                    "action": "CLOSE",
                    "rationale": "Stage 2 profit target reached. Close remaining position.",
                },
            )
        )

    trailing_active = high_water_mark_pct >= policy.trailing_stop_activates_at_pct
    if trading_days_held >= policy.minimum_hold_days and trailing_active:
        drawback = high_water_mark_pct - unrealized_pct
        if drawback >= policy.trailing_stop_pct:
            signals.append(
                _signal(
                    "TRAILING_STOP",
                    "NORMAL",
                    f"{ticker} drew back {drawback:.2f}% from peak "
                    f"{high_water_mark_pct:.2f}%.",
                    {
                        "action": "CLOSE",
                        "rationale": "Trailing stop triggered. Protect remaining gains.",
                    },
                )
            )

    if (
        trading_days_held >= policy.minimum_hold_days
        and not stage1_executed
        and unrealized_pct >= policy.take_profit_stage1_pct
        and quantity > 0
    ):
        suggested_qty = round(quantity * policy.suggested_stage1_trim_pct, 6)
        signals.append(
            _signal(
                "TAKE_PROFIT_STAGE_1",
                "NORMAL",
                f"{ticker} gain {unrealized_pct:.2f}% reached the "
                f"+{policy.take_profit_stage1_pct:.1f}% Stage 1 target after "
                f"{trading_days_held} trading days.",
                {
                    "action": "TRIM",
                    "suggested_trim_pct": policy.suggested_stage1_trim_pct,
                    "suggested_trim_qty": suggested_qty,
                    "breakeven_stop_recommendation": True,
                    "rationale": (
                        f"Secure {policy.suggested_stage1_trim_pct * 100:.0f}% "
                        "of the position at target. Move stop to break-even on "
                        "the remainder."
                    ),
                },
            )
        )

    if (
        trading_days_held > policy.time_stop_days
        and abs(unrealized_pct) < policy.time_stop_flat_threshold_pct
    ):
        signals.append(
            _signal(
                "TIME_STOP",
                "LOW",
                f"{ticker} held {trading_days_held} trading days with only "
                f"{unrealized_pct:.2f}% move.",
                {
                    "action": "REVIEW",
                    "rationale": (
                        "Position has not moved after the maximum hold window. "
                        "Consider redeployment."
                    ),
                },
            )
        )

    if _has_setup_warning(selection_report):
        signals.append(
            _signal(
                "SETUP_WARNING",
                "INFO",
                f"{ticker} current setup has warnings or risk flags.",
                {
                    "action": "REVIEW",
                    "rationale": "Review warnings before adding exposure to this ticker.",
                },
            )
        )

    if not signals:
        return _hold(ticker)
    return _winner(signals)


def _thesis_is_broken(
    selection_report: dict[str, Any] | None,
    policy: PortfolioPolicy,
) -> bool:
    if selection_report is None:
        return False
    action = _report_action(selection_report)
    conviction = _report_conviction(selection_report)
    return action == "NO_TRADE" or conviction < policy.thesis_broken_conviction_floor


def _report_action(selection_report: dict[str, Any] | None) -> str:
    if selection_report is None:
        return ""
    raw_value = selection_report.get("final_action", selection_report.get("action", ""))
    return str(raw_value or "").strip().upper()


def _report_conviction(selection_report: dict[str, Any] | None) -> float:
    if selection_report is None:
        return 1.0
    raw_value = selection_report.get(
        "final_conviction",
        selection_report.get("conviction", 1.0),
    )
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return 1.0


def _signal(
    signal_type: str,
    priority: str,
    reason: str,
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "exit_signal": signal_type,
        "exit_priority": priority,
        "exit_reason": reason,
        "recommendation": recommendation,
        "secondary_signals": [],
    }


def _winner(signals: list[dict[str, Any]]) -> dict[str, Any]:
    if signals[0]["exit_signal"] == "SETUP_WARNING":
        return _hold("", ["SETUP_WARNING"])
    winner = dict(signals[0])
    winner["secondary_signals"] = [signal["exit_signal"] for signal in signals[1:]]
    return winner


def _hold(ticker: str, secondary_signals: list[str] | None = None) -> dict[str, Any]:
    subject = ticker or "Position"
    signal = _signal(
        "HOLD",
        "NONE",
        f"{subject} is on track. No exit rule triggered.",
        {"action": "HOLD", "rationale": "Position is within all guardrails."},
    )
    signal["secondary_signals"] = secondary_signals or []
    return signal


def _has_setup_warning(selection_report: dict[str, Any] | None) -> bool:
    if selection_report is None:
        return False
    risk_flags = selection_report.get("risk_flags", [])
    has_risk_flags = isinstance(risk_flags, list) and bool(risk_flags)
    return has_risk_flags or _has_policy_gate_warn(selection_report)


def _has_policy_gate_warn(report: dict[str, Any]) -> bool:
    return any(
        str(gate.get("status")).strip().upper() == "WARN"
        for gate in report.get("policy_gates", [])
        if isinstance(gate, dict)
    )
