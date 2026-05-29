from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from dotenv import load_dotenv

POLICY_PATH_ENV = "AGENCY_PORTFOLIO_POLICY_PATH"
DEFAULT_POLICY_PATH = Path("research/config/portfolio-policy.local.json")


@dataclass(frozen=True)
class PortfolioPolicy:
    weekly_target_pct: float = 3.0
    weekly_target_approach_pct: float = 2.5
    weekly_drawdown_limit_pct: float = 6.0
    daily_circuit_breaker_pct: float = 3.0

    max_positions: int = 8
    max_new_positions_per_day: int = 2
    default_position_pct: float = 10.0
    reduced_position_pct: float = 5.0
    max_single_name_pct: float = 20.0
    max_sector_exposure_pct: float = 30.0
    cash_reserve_pct: float = 20.0
    max_gross_exposure_pct: float = 80.0

    stop_loss_pct: float = 2.0
    take_profit_stage1_pct: float = 2.0
    take_profit_stage2_pct: float = 4.0
    trailing_stop_pct: float = 1.5
    trailing_stop_activates_at_pct: float = 1.5
    suggested_stage1_trim_pct: float = 0.50

    thesis_broken_conviction_floor: float = 0.40
    min_final_conviction: float = 0.65

    minimum_hold_days: int = 2
    time_stop_days: int = 4
    time_stop_flat_threshold_pct: float = 0.5
    reentry_cooldown_hours: int = 24

    live_trading_enabled: bool = False
    broker_submit_enabled: bool = False
    allow_short_trades: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PortfolioPolicy:
        if env is None:
            load_dotenv()
        values: Mapping[str, str] = os.environ if env is None else env
        policy = cls(
            **{
                name: _env_value(values.get(_env_key(name)), default)
                for name, default in _field_defaults(cls()).items()
            }
        )
        return _policy_with_file_overrides(policy, values)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def load_policy(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> PortfolioPolicy:
    values = os.environ if env is None else env
    base = PortfolioPolicy.from_env(values)
    if path is None:
        return base
    return _policy_from_path(base, Path(path), values)


def _policy_with_file_overrides(
    policy: PortfolioPolicy,
    env: Mapping[str, str],
) -> PortfolioPolicy:
    path = Path(env.get(POLICY_PATH_ENV, DEFAULT_POLICY_PATH.as_posix()))
    return _policy_from_path(policy, path, env)


def _policy_from_path(
    policy: PortfolioPolicy,
    path: Path,
    env: Mapping[str, str],
) -> PortfolioPolicy:
    if not path.is_file():
        return policy
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return policy
    if not isinstance(payload, Mapping):
        return policy
    updates: dict[str, object] = {}
    for name, default in _field_defaults(policy).items():
        if name not in payload:
            continue
        updates[name] = _payload_value(payload[name], default)
    for name in ("live_trading_enabled", "broker_submit_enabled", "allow_short_trades"):
        if _env_bool_is_configured(env, _env_key(name)):
            updates[name] = getattr(policy, name)
    return replace(policy, **updates)


def _field_defaults(policy: PortfolioPolicy) -> dict[str, object]:
    return {field.name: getattr(policy, field.name) for field in fields(policy)}


def _env_key(field_name: str) -> str:
    return f"AGENCY_{field_name.upper()}"


def _env_value(value: str | None, default: object) -> object:
    if isinstance(default, bool):
        return _bool_value(value, default)
    if isinstance(default, int):
        return int(value) if value and value.strip() else default
    if isinstance(default, float):
        return float(value) if value and value.strip() else default
    return value if value is not None else default


def _payload_value(value: object, default: object) -> object:
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else default
    if isinstance(default, float):
        return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else default
    return value if isinstance(value, type(default)) else default


def _bool_value(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_bool_is_configured(values: Mapping[str, str], key: str) -> bool:
    value = values.get(key)
    return value is not None and bool(value.strip())
