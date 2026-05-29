from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agency.market_regime.policy import RegimePolicy

FRED_SERIES = (
    "VIXCLS",
    "T10Y2Y",
    "DGS10",
    "BAMLH0A0HYM2",
    "BAMLC0A0CM",
    "STLFSI4",
    "ICSA",
)


@dataclass(frozen=True)
class FetchSummary:
    ok: bool
    issues: list[str] = field(default_factory=list)
    used_cache: bool = False
    updated_files: list[str] = field(default_factory=list)


def load_state_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_state_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def refresh_fred_series(
    path: Path,
    *,
    policy: RegimePolicy,
    now: datetime,
    series_client: Callable[[str], object] | None = None,
) -> FetchSummary:
    cached = load_state_json(path)
    if _cache_is_fresh(cached, policy=policy, now=now):
        return FetchSummary(ok=True, used_cache=True)
    client = series_client or _default_fred_client()
    if client is None:
        return FetchSummary(ok=False, issues=["FRED_API_KEY is not configured."])
    series: dict[str, list[dict[str, object]]] = {}
    issues: list[str] = []
    for series_id in FRED_SERIES:
        try:
            series[series_id] = _series_points(client(series_id))
        except Exception as exc:
            issues.append(f"{series_id}: {exc}")
    if issues:
        return FetchSummary(ok=False, issues=issues)
    write_state_json(path, {"generated_at": now.isoformat(), "series": series})
    return FetchSummary(ok=True, updated_files=[str(path)])


def grouped_daily_breadth(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    total = 0
    advancers = 0
    decliners = 0
    unchanged = 0
    for row in rows:
        open_price = _float(row.get("open"))
        close_price = _float(row.get("close"))
        if open_price is None or close_price is None or open_price <= 0.0:
            continue
        total += 1
        if close_price > open_price:
            advancers += 1
        elif close_price < open_price:
            decliners += 1
        else:
            unchanged += 1
    return {
        "total": total,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "advancers_pct": round(advancers / total * 100.0, 2) if total else 0.0,
        "decliners_pct": round(decliners / total * 100.0, 2) if total else 0.0,
    }


def refresh_regime_state(
    state_dir: Path,
    *,
    mode: str,
    policy: RegimePolicy | None = None,
    now: datetime | None = None,
) -> FetchSummary:
    active_policy = policy or RegimePolicy.from_env()
    timestamp = now or datetime.now(UTC)
    state_dir.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []
    updated_files: list[str] = []
    fred_summary = refresh_fred_series(
        state_dir / "macro_fred.json",
        policy=active_policy,
        now=timestamp,
    )
    issues.extend(fred_summary.issues)
    updated_files.extend(fred_summary.updated_files)
    marker = state_dir / "last_fetch.json"
    write_state_json(
        marker,
        {
            "generated_at": timestamp.isoformat(),
            "mode": mode,
            "ok": not issues,
            "issues": issues,
        },
    )
    updated_files.append(str(marker))
    return FetchSummary(ok=not issues, issues=issues, updated_files=updated_files)


def _cache_is_fresh(payload: Mapping[str, object], *, policy: RegimePolicy, now: datetime) -> bool:
    generated_at = _datetime(payload.get("generated_at"))
    if generated_at is None:
        return False
    age_seconds = (now - generated_at).total_seconds()
    return 0 <= age_seconds <= policy.fred_cache_hours * 3600


def _default_fred_client() -> Callable[[str], object] | None:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return None
    try:
        from fredapi import Fred
    except ImportError:
        return None
    client = Fred(api_key=api_key)
    return client.get_series


def _series_points(raw: object) -> list[dict[str, object]]:
    if hasattr(raw, "tail"):
        raw = raw.tail(10)
    if hasattr(raw, "items"):
        return [
            {"date": str(index.date() if hasattr(index, "date") else index), "value": _float(value)}
            for index, value in raw.items()
            if _float(value) is not None
        ]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
