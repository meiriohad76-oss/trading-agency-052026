from __future__ import annotations

from typing import Any

from agency.portfolio.policy import PortfolioPolicy


def evaluate_circuit_breakers(
    weekly_perf: dict[str, Any],
    daily_perf: dict[str, Any],
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    weekly_return = _pct(weekly_perf, "weekly_return_pct")
    daily_return = _pct(daily_perf, "daily_return_pct")

    signals: list[str] = []
    new_entries_blocked = False
    reduced_sizing_active = False

    if weekly_return is not None and weekly_return >= policy.weekly_target_pct:
        signals.append("WEEKLY_TARGET_REACHED")
        new_entries_blocked = True

    if weekly_return is not None and weekly_return <= -policy.weekly_drawdown_limit_pct:
        signals.append("WEEKLY_DRAWDOWN_LIMIT")
        new_entries_blocked = True

    if daily_return is not None and daily_return <= -policy.daily_circuit_breaker_pct:
        signals.append("DAILY_CIRCUIT_BREAKER")
        new_entries_blocked = True

    if (
        not new_entries_blocked
        and weekly_return is not None
        and weekly_return >= policy.weekly_target_approach_pct
    ):
        signals.append("WEEKLY_TARGET_APPROACH")
        reduced_sizing_active = True

    recommended_pct = (
        policy.reduced_position_pct
        if reduced_sizing_active
        else policy.default_position_pct
    )

    return {
        "active": bool(signals),
        "signals": signals,
        "new_entries_blocked": new_entries_blocked,
        "reduced_sizing_active": reduced_sizing_active,
        "recommended_position_pct": recommended_pct,
    }


def _pct(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
