from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_HWM_FILE = "high_water_marks.json"
_STAGE1_FILE = "stage1_executed.json"
_ENTRY_FILE = "entry_timestamps.json"
_WEEKLY_FILE = "weekly_baseline.json"
_DAILY_FILE = "daily_baseline.json"
_COOLDOWN_FILE = "reentry_cooldowns.json"


def load_high_water_marks(state_dir: Path) -> dict[str, float]:
    return _load_float_dict(state_dir / _HWM_FILE)


def save_high_water_marks(state_dir: Path, marks: dict[str, float]) -> None:
    _write_json(state_dir / _HWM_FILE, marks)


def update_high_water_marks(
    current: dict[str, float],
    broker_positions: list[dict[str, Any]],
) -> dict[str, float]:
    result = dict(current)
    for position in broker_positions:
        ticker = _ticker(position)
        if not ticker:
            continue
        raw_value = position.get("unrealized_plpc")
        if raw_value is None:
            continue
        pct = float(raw_value) * 100.0
        result[ticker] = max(result.get(ticker, pct), pct)
    return result


def load_stage1_executed(state_dir: Path) -> dict[str, dict[str, Any]]:
    raw = _load_json(state_dir / _STAGE1_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(key).upper(): value for key, value in raw.items() if isinstance(value, dict)}


def save_stage1_executed(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    _write_json(state_dir / _STAGE1_FILE, data)


def is_stage1_executed(state_dir: Path, ticker: str) -> bool:
    data = load_stage1_executed(state_dir)
    return bool(data.get(ticker.upper(), {}).get("executed", False))


def mark_stage1_executed(state_dir: Path, ticker: str, executed_at: str) -> None:
    data = load_stage1_executed(state_dir)
    data[ticker.upper()] = {"executed": True, "executed_at": executed_at}
    save_stage1_executed(state_dir, data)


def load_entry_timestamps(state_dir: Path) -> dict[str, dict[str, Any]]:
    raw = _load_json(state_dir / _ENTRY_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(key).upper(): value for key, value in raw.items() if isinstance(value, dict)}


def save_entry_timestamps(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    _write_json(state_dir / _ENTRY_FILE, data)


def get_trading_days_held(state_dir: Path, ticker: str) -> int:
    data = load_entry_timestamps(state_dir)
    return int(data.get(ticker.upper(), {}).get("trading_days_held", 0))


def load_weekly_baseline(state_dir: Path) -> dict[str, Any] | None:
    raw = _load_json(state_dir / _WEEKLY_FILE)
    if isinstance(raw, dict) and "equity" in raw:
        return raw
    return None


def save_weekly_baseline(state_dir: Path, baseline: dict[str, Any]) -> None:
    _write_json(state_dir / _WEEKLY_FILE, baseline)


def ensure_weekly_baseline(
    state_dir: Path,
    *,
    account: dict[str, Any],
    week_start: str,
) -> dict[str, Any]:
    current = load_weekly_baseline(state_dir)
    if current is not None and current.get("week_start") == week_start:
        return current
    baseline = {"week_start": week_start, "equity": _account_equity(account)}
    save_weekly_baseline(state_dir, baseline)
    return baseline


def load_daily_baseline(state_dir: Path) -> dict[str, Any] | None:
    raw = _load_json(state_dir / _DAILY_FILE)
    if isinstance(raw, dict) and "equity" in raw:
        return raw
    return None


def save_daily_baseline(state_dir: Path, baseline: dict[str, Any]) -> None:
    _write_json(state_dir / _DAILY_FILE, baseline)


def ensure_daily_baseline(
    state_dir: Path,
    *,
    account: dict[str, Any],
    date: str,
) -> dict[str, Any]:
    current = load_daily_baseline(state_dir)
    if current is not None and current.get("date") == date:
        return current
    baseline = {"date": date, "equity": _account_equity(account)}
    save_daily_baseline(state_dir, baseline)
    return baseline


def load_reentry_cooldowns(state_dir: Path) -> dict[str, dict[str, Any]]:
    raw = _load_json(state_dir / _COOLDOWN_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(key).upper(): value for key, value in raw.items() if isinstance(value, dict)}


def save_reentry_cooldowns(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    _write_json(state_dir / _COOLDOWN_FILE, data)


def cooldown_is_active(state_dir: Path, ticker: str, now_utc: str) -> bool:
    cooldowns = load_reentry_cooldowns(state_dir)
    entry = cooldowns.get(ticker.upper())
    if not entry:
        return False
    blocked_until_value = str(entry.get("blocked_until") or "")
    if not blocked_until_value:
        return False
    try:
        blocked_until = _parse_utc(blocked_until_value)
        now = _parse_utc(now_utc)
    except ValueError:
        return False
    return now < blocked_until


def record_stop_loss_exit(
    state_dir: Path,
    ticker: str,
    exit_time_utc: str,
    cooldown_hours: int,
) -> None:
    exit_time = _parse_utc(exit_time_utc)
    blocked_until = _format_utc(exit_time + timedelta(hours=cooldown_hours))
    cooldowns = load_reentry_cooldowns(state_dir)
    cooldowns[ticker.upper()] = {
        "blocked_until": blocked_until,
        "reason": f"Stop-loss exit recorded {exit_time_utc}",
    }
    save_reentry_cooldowns(state_dir, cooldowns)


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _load_float_dict(path: Path) -> dict[str, float]:
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        result[str(key).upper()] = float(value)
    return result


def _ticker(position: dict[str, Any]) -> str:
    return str(position.get("symbol") or position.get("ticker") or "").upper()


def _account_equity(account: dict[str, Any]) -> float:
    for key in ("equity", "portfolio_value"):
        value = account.get(key)
        if isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
