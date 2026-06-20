from __future__ import annotations

from typing import Any

from agency.portfolio.policy import PortfolioPolicy


def compute_weekly_performance(
    account: dict[str, Any],
    weekly_baseline: dict[str, Any] | None,
    policy: PortfolioPolicy,
) -> dict[str, Any]:
    current_equity = _equity(account)
    if weekly_baseline is None or current_equity is None:
        return {
            "week_start": None,
            "baseline_equity": None,
            "current_equity": current_equity,
            "weekly_pl": None,
            "weekly_return_pct": None,
            "target_pct": policy.weekly_target_pct,
            "pct_of_target_reached": None,
        }

    baseline_equity = _positive_float(weekly_baseline.get("equity"))
    if baseline_equity is None:
        return {
            "week_start": weekly_baseline.get("week_start"),
            "baseline_equity": weekly_baseline.get("equity"),
            "current_equity": current_equity,
            "weekly_pl": None,
            "weekly_return_pct": None,
            "target_pct": policy.weekly_target_pct,
            "pct_of_target_reached": None,
        }

    weekly_pl = round(current_equity - baseline_equity, 2)
    weekly_return_pct = round((current_equity / baseline_equity - 1.0) * 100.0, 4)
    pct_of_target = (
        round(weekly_return_pct / policy.weekly_target_pct * 100.0, 2)
        if policy.weekly_target_pct
        else None
    )
    return {
        "week_start": weekly_baseline.get("week_start"),
        "baseline_equity": baseline_equity,
        "current_equity": round(current_equity, 2),
        "weekly_pl": weekly_pl,
        "weekly_return_pct": weekly_return_pct,
        "target_pct": policy.weekly_target_pct,
        "pct_of_target_reached": pct_of_target,
    }


def compute_daily_performance(
    account: dict[str, Any],
    daily_baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    current_equity = _equity(account)
    if daily_baseline is None or current_equity is None:
        return {
            "date": None,
            "baseline_equity": None,
            "current_equity": current_equity,
            "daily_pl": None,
            "daily_return_pct": None,
        }

    baseline_equity = _positive_float(daily_baseline.get("equity"))
    if baseline_equity is None:
        return {
            "date": daily_baseline.get("date"),
            "baseline_equity": daily_baseline.get("equity"),
            "current_equity": current_equity,
            "daily_pl": None,
            "daily_return_pct": None,
        }

    daily_pl = round(current_equity - baseline_equity, 2)
    daily_return_pct = round((current_equity / baseline_equity - 1.0) * 100.0, 4)
    return {
        "date": daily_baseline.get("date"),
        "baseline_equity": baseline_equity,
        "current_equity": round(current_equity, 2),
        "daily_pl": daily_pl,
        "daily_return_pct": daily_return_pct,
    }


def _equity(account: dict[str, Any]) -> float | None:
    for key in ("portfolio_value", "equity"):
        equity = _positive_float(account.get(key))
        if equity is not None:
            return equity
    return None


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return numeric
