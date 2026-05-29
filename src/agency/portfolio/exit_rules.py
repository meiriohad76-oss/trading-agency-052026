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
