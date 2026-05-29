from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from agency.market_regime.policy import RegimePolicy


def classify_market_backdrop(
    *,
    spy_5d_pct: float | None,
    qqq_5d_pct: float | None,
    breadth_pct: float | None,
    spy_vol_10d: float | None,
    tlt_5d_pct: float | None,
    sector_zscore_spread: float | None,
    policy: RegimePolicy,
) -> dict[str, object]:
    if all(value is None for value in (spy_5d_pct, qqq_5d_pct, breadth_pct, spy_vol_10d)):
        return _backdrop("DATA_LIMITED", "warn", 0.0, policy.neutral_modifier, "BLOCKED")
    if (
        _at_most(spy_5d_pct, policy.risk_off_spy_5d_pct)
        or _at_most(breadth_pct, policy.risk_off_breadth_pct)
        or _at_least(tlt_5d_pct, policy.risk_off_tlt_5d_pct)
    ):
        return _backdrop("RISK_OFF", "block", 1.0, policy.risk_off_modifier, "CAUTIOUS")
    if _at_least(spy_vol_10d, policy.volatile_vol_threshold) and _at_least(
        abs(spy_5d_pct or 0.0), policy.volatile_abs_move_pct
    ):
        return _backdrop("VOLATILE", "warn", 1.0, policy.volatile_modifier, "CAUTIOUS")
    if (
        _at_least(sector_zscore_spread, policy.rotating_sector_spread)
        and _at_least(breadth_pct, policy.rotating_breadth_min)
        and _at_most(breadth_pct, policy.rotating_breadth_max)
    ):
        return _backdrop("ROTATING", "warn", 1.0, policy.rotating_modifier, "NORMAL")
    if (
        _at_least(spy_5d_pct, policy.risk_on_spy_5d_pct)
        and _at_least(qqq_5d_pct, policy.risk_on_qqq_5d_pct)
        and _at_least(breadth_pct, policy.risk_on_breadth_pct)
        and _at_most(spy_vol_10d, policy.risk_on_vol_cap)
    ):
        return _backdrop("RISK_ON", "pass", 1.0, policy.risk_on_modifier, "NORMAL")
    return _backdrop("NEUTRAL", "neutral", 1.0, policy.neutral_modifier, "NORMAL")


def classify_vol_regime(vix_value: float | None, policy: RegimePolicy) -> dict[str, object]:
    if vix_value is None:
        return {
            "vol_regime": "UNKNOWN",
            "status_class": "warn",
            "size_multiplier": policy.elevated_vol_size_multiplier,
        }
    if vix_value < policy.vix_calm:
        return {
            "vol_regime": "CALM",
            "status_class": "pass",
            "size_multiplier": policy.calm_size_multiplier,
        }
    if vix_value > policy.vix_high:
        return {
            "vol_regime": "HIGH",
            "status_class": "block",
            "size_multiplier": policy.high_vol_size_multiplier,
        }
    return {
        "vol_regime": "ELEVATED",
        "status_class": "warn",
        "size_multiplier": policy.elevated_vol_size_multiplier,
    }


def classify_macro_tilt(
    yield_curve: float | None,
    credit_spread_delta_bps: float | None,
    tlt_5d_pct: float | None,
    policy: RegimePolicy,
) -> dict[str, object]:
    if _below(yield_curve, policy.yield_curve_inverted) or _above(
        credit_spread_delta_bps, policy.credit_spread_stress_delta_bps
    ):
        return {"macro_tilt": "DEFENSIVE", "status_class": "warn"}
    if (
        _above(yield_curve, policy.macro_risk_appetite_curve)
        and _below(credit_spread_delta_bps, -10.0)
        and _below(tlt_5d_pct, 0.0)
    ):
        return {"macro_tilt": "RISK_APPETITE", "status_class": "pass"}
    return {"macro_tilt": "NEUTRAL", "status_class": "neutral"}


def classify_sector_state(
    rs_ratio: float | None,
    rs_momentum: float | None,
    cmf_14: float | None,
    obv_trend: str | None,
    policy: RegimePolicy,
) -> dict[str, object]:
    ratio = rs_ratio or 0.0
    momentum = rs_momentum or 0.0
    flow_confirmed = _above(cmf_14, policy.cmf_positive) and obv_trend == "UP"
    flow_bearish = _below(cmf_14, policy.cmf_negative) and obv_trend == "DOWN"
    if ratio > 0.0 and momentum > 0.0:
        state, quadrant = "ADVANCING", "Leading"
    elif ratio > 0.0 and momentum <= 0.0:
        state, quadrant = "TOPPING", "Weakening"
    elif ratio <= 0.0 and momentum > 0.0:
        state, quadrant = "BASING", "Improving"
    else:
        state, quadrant = "DECLINING", "Lagging"
    bias, boost, status_class = _sector_bias_and_boost(state, flow_confirmed, flow_bearish, policy)
    return {
        "state": state,
        "quadrant": quadrant,
        "bias": bias,
        "status_class": status_class,
        "flow_confirmed": flow_confirmed,
        "flow_bearish": flow_bearish,
        "conviction_boost": boost,
        "rs_ratio": ratio,
        "rs_momentum": momentum,
        "cmf_14": cmf_14,
        "obv_trend": obv_trend or "UNKNOWN",
    }


def per_stock_context(
    tickers: Sequence[str],
    ticker_sector_map: Mapping[str, str],
    sector_map: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for raw_ticker in tickers:
        ticker = raw_ticker.upper()
        sector = ticker_sector_map.get(ticker, "UNKNOWN")
        sector_entry = sector_map.get(sector, {})
        result[ticker] = {
            "ticker": ticker,
            "sector": sector,
            "sector_state": sector_entry.get("state", "UNKNOWN"),
            "sector_bias": sector_entry.get("bias", "NEUTRAL"),
            "conviction_boost": float(sector_entry.get("conviction_boost", 0.0)),
        }
    return result


def detect_regime_change(
    prior: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> dict[str, object]:
    prior_backdrop = _mapping(prior.get("market_backdrop") if prior else None)
    current_backdrop = _mapping(current.get("market_backdrop"))
    prior_regime = str(prior_backdrop.get("regime", "UNKNOWN"))
    current_regime = str(current_backdrop.get("regime", "UNKNOWN"))
    transitions = _sector_transitions(_mapping(prior.get("sector_map") if prior else None), current)
    return {
        "regime_changed": prior_regime != current_regime or bool(transitions),
        "prior_regime": prior_regime,
        "current_regime": current_regime,
        "sector_transitions": transitions,
    }


def analyze_intraday_drift(
    snapshots: Mapping[str, Mapping[str, object]],
    *,
    morning_rank: Sequence[str] | None = None,
) -> dict[str, object] | None:
    spy_return = _session_return_pct(snapshots.get("SPY"))
    if spy_return is None:
        return None
    sectors: dict[str, dict[str, object]] = {}
    for ticker, payload in snapshots.items():
        if ticker == "SPY":
            continue
        session_return = _session_return_pct(payload)
        if session_return is None:
            continue
        sectors[ticker] = {
            "ticker": ticker,
            "session_return_pct": session_return,
            "vs_spy_pct": round(session_return - spy_return, 2),
        }
    if not sectors:
        return None
    current_rank = sorted(sectors, key=lambda item: float(sectors[item]["session_return_pct"]), reverse=True)
    return {
        "spy_session_return_pct": spy_return,
        "sectors": sectors,
        "leadership_shift": _leadership_shift(morning_rank or [], current_rank),
        "current_rank": current_rank,
    }


def _backdrop(
    regime: str,
    status_class: str,
    confidence: float,
    modifier: float,
    entries_bias: str,
) -> dict[str, object]:
    return {
        "regime": regime,
        "status_class": status_class,
        "confidence": confidence,
        "new_entries_bias": entries_bias,
        "conviction_modifier": modifier,
    }


def _sector_bias_and_boost(
    state: str,
    flow_confirmed: bool,
    flow_bearish: bool,
    policy: RegimePolicy,
) -> tuple[str, float, str]:
    if state == "ADVANCING":
        boost = (
            policy.advancing_confirmed_boost
            if flow_confirmed
            else policy.advancing_unconfirmed_boost
        )
        return "TAILWIND", boost, "pass"
    if state == "DECLINING":
        penalty = (
            policy.declining_confirmed_penalty
            if flow_bearish
            else policy.declining_unconfirmed_penalty
        )
        return "HEADWIND", penalty, "block"
    return "NEUTRAL", 0.0, "neutral"


def _sector_transitions(
    prior_sector_map: Mapping[str, object],
    current: Mapping[str, Any],
) -> list[dict[str, str]]:
    current_sector_map = _mapping(current.get("sector_map"))
    transitions: list[dict[str, str]] = []
    for sector, raw_current in current_sector_map.items():
        current_entry = _mapping(raw_current)
        prior_entry = _mapping(prior_sector_map.get(sector))
        prior_state = str(prior_entry.get("state", "UNKNOWN"))
        current_state = str(current_entry.get("state", "UNKNOWN"))
        if prior_state != current_state:
            transitions.append(
                {"sector": str(sector), "from_state": prior_state, "to_state": current_state}
            )
    return transitions


def _session_return_pct(payload: Mapping[str, object] | None) -> float | None:
    if not payload:
        return None
    price = _float(payload.get("price"))
    prior_close = _float(payload.get("prior_close"))
    if price is None or prior_close is None or prior_close <= 0.0:
        return None
    return round((price / prior_close - 1.0) * 100.0, 2)


def _leadership_shift(morning_rank: Sequence[str], current_rank: Sequence[str]) -> bool:
    prior_positions = {ticker: index for index, ticker in enumerate(morning_rank)}
    for index, ticker in enumerate(current_rank):
        prior_index = prior_positions.get(ticker)
        if prior_index is not None and abs(prior_index - index) > 2:
            return True
    return False


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _at_most(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _above(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _below(value: float | None, threshold: float) -> bool:
    return value is not None and value < threshold
