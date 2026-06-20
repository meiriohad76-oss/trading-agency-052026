from __future__ import annotations

from pathlib import Path
from typing import Any

from agency.market_regime.fetcher import refresh_regime_state
from agency.market_regime.policy import RegimePolicy
from agency.market_regime.snapshot import build_regime_snapshot


def schedule_regime_refresh(scheduler: Any, state_dir: Path, policy: RegimePolicy) -> None:
    scheduler.add_job(
        full_refresh,
        "cron",
        hour=7,
        minute=0,
        day_of_week="mon-fri",
        kwargs={"state_dir": state_dir, "policy": policy, "mode": "pre_market"},
    )
    scheduler.add_job(
        intraday_refresh,
        "cron",
        minute=0,
        hour="9-16",
        day_of_week="mon-fri",
        kwargs={"state_dir": state_dir, "policy": policy, "mode": "intraday"},
    )
    scheduler.add_job(
        full_refresh,
        "cron",
        hour=16,
        minute=30,
        day_of_week="mon-fri",
        kwargs={"state_dir": state_dir, "policy": policy, "mode": "post_market"},
    )


def full_refresh(
    *,
    state_dir: Path,
    policy: RegimePolicy,
    mode: str,
) -> dict[str, object]:
    summary = refresh_regime_state(state_dir, mode=mode, policy=policy)
    snapshot = build_regime_snapshot(state_dir=state_dir, policy=policy, refresh_mode=mode)
    return {"fetch": summary, "snapshot": snapshot}


def intraday_refresh(
    *,
    state_dir: Path,
    policy: RegimePolicy,
    mode: str,
) -> dict[str, object]:
    summary = refresh_regime_state(state_dir, mode=mode, policy=policy)
    snapshot = build_regime_snapshot(state_dir=state_dir, policy=policy, refresh_mode="intraday")
    return {"fetch": summary, "snapshot": snapshot}
