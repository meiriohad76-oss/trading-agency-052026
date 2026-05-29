from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Self


@dataclass(frozen=True)
class RegimePolicy:
    risk_off_spy_5d_pct: float = -1.5
    risk_off_breadth_pct: float = 35.0
    risk_off_tlt_5d_pct: float = 1.5
    risk_on_spy_5d_pct: float = 1.0
    risk_on_qqq_5d_pct: float = 0.0
    risk_on_breadth_pct: float = 55.0
    risk_on_vol_cap: float = 20.0
    volatile_vol_threshold: float = 25.0
    volatile_abs_move_pct: float = 2.0
    rotating_sector_spread: float = 1.5
    rotating_breadth_min: float = 40.0
    rotating_breadth_max: float = 65.0
    vix_calm: float = 20.0
    vix_elevated: float = 25.0
    vix_high: float = 35.0
    yield_curve_inverted: float = 0.0
    credit_spread_stress_delta_bps: float = 50.0
    rate_spike_delta_bps: float = 20.0
    macro_risk_appetite_curve: float = 1.0
    cmf_positive: float = 0.0
    cmf_negative: float = 0.0
    cmf_period: int = 14
    risk_on_modifier: float = 0.03
    risk_off_modifier: float = -0.08
    volatile_modifier: float = -0.05
    neutral_modifier: float = 0.0
    rotating_modifier: float = 0.0
    advancing_confirmed_boost: float = 0.03
    advancing_unconfirmed_boost: float = 0.01
    declining_confirmed_penalty: float = -0.05
    declining_unconfirmed_penalty: float = -0.02
    calm_size_multiplier: float = 1.0
    elevated_vol_size_multiplier: float = 0.75
    high_vol_size_multiplier: float = 0.50
    intraday_refresh_interval_minutes: int = 60
    fred_cache_hours: int = 24
    etf_bars_lookback_days: int = 65

    @classmethod
    def from_env(cls, *, config_path: Path | None = None) -> Self:
        policy = cls()
        local_overrides = _read_local_policy(config_path)
        if local_overrides:
            policy = replace(policy, **_coerce_overrides(policy, local_overrides))
        env_overrides = {
            field.name: os.environ[env_name]
            for field in fields(policy)
            if (env_name := f"AGENCY_{field.name.upper()}") in os.environ
        }
        if env_overrides:
            policy = replace(policy, **_coerce_overrides(policy, env_overrides))
        return policy


def _read_local_policy(path: Path | None) -> dict[str, object]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("market_regime", payload)
    return nested if isinstance(nested, dict) else {}


def _coerce_overrides(policy: RegimePolicy, raw: dict[str, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    fields_by_name = {field.name: field for field in fields(policy)}
    for name, value in raw.items():
        field = fields_by_name.get(str(name))
        if field is None:
            continue
        current = getattr(policy, field.name)
        result[field.name] = int(value) if isinstance(current, int) else float(value)
    return result
