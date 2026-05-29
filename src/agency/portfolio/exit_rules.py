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
    raw_value = selection_report.get("final_conviction", selection_report.get("conviction", 1.0))
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
    winner = dict(signals[0])
    winner["secondary_signals"] = [signal["exit_signal"] for signal in signals[1:]]
    return winner


def _hold(ticker: str) -> dict[str, Any]:
    return _signal(
        "HOLD",
        "NONE",
        f"{ticker} is on track. No exit rule triggered.",
        {"action": "HOLD", "rationale": "Position is within all guardrails."},
    )


def _has_policy_gate_warn(report: dict[str, Any]) -> bool:
    return any(
        str(gate.get("status")).strip().upper() == "WARN"
        for gate in report.get("policy_gates", [])
        if isinstance(gate, dict)
    )
