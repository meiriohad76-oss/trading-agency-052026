from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = os.environ.get("AGENCY_PYTHON", "python")

_PHASE_JOBS: dict[str, list[dict[str, Any]]] = {
    "pre_market": [
        {"name": "stock_trades",        "interval_minutes": 15},
        {"name": "subscription_emails", "interval_minutes": 10},
        {"name": "news_rss",            "interval_minutes": 30},
    ],
    "regular_market": [
        {"name": "news_rss",            "interval_minutes": 30},
        {"name": "subscription_emails", "interval_minutes": 10},
    ],
    "after_hours": [
        {"name": "prices_daily",        "interval_minutes": 30},
        {"name": "stock_trades",        "interval_minutes": 20},
        {"name": "subscription_emails", "interval_minutes": 15},
    ],
    "overnight": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
        {"name": "sec_13f",             "interval_minutes": 720},
        {"name": "news_rss",            "interval_minutes": 60},
        {"name": "prices_daily",        "interval_minutes": 60},
    ],
    "holiday": [
        {"name": "sec_company_facts",   "interval_minutes": 360},
        {"name": "sec_form4",           "interval_minutes": 180},
    ],
}


def jobs_for_phase(phase: str) -> list[dict[str, Any]]:
    """Return the job specs active for the given market phase."""
    return _PHASE_JOBS.get(phase, [])


def _run_dataset_refresh(dataset: str) -> None:
    config_path = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
    if not config_path.is_file():
        print(f"[scheduler] WARNING: live-refresh config not found at {config_path}", flush=True)
        return
    cmd = [
        PYTHON,
        str(REPO_ROOT / "research" / "scripts" / "run_data_refresh_batch.py"),
        "--config", str(config_path),
        "--datasets", dataset,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    status = "ok" if result.returncode == 0 else "FAILED"
    print(f"[scheduler] {dataset} refresh {status} (exit {result.returncode})", flush=True)
    if result.returncode != 0:
        print(f"[scheduler] stderr: {result.stderr[:500]}", flush=True)


def build_scheduler(db_url: str) -> "AsyncIOScheduler":  # type: ignore[type-arg]
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
    _register_phase_jobs(scheduler)
    return scheduler


def _register_phase_jobs(scheduler: "AsyncIOScheduler") -> None:  # type: ignore[type-arg]
    import sys
    from datetime import UTC, datetime

    research_src = str(REPO_ROOT / "research" / "src")
    added = False
    if research_src not in sys.path:
        sys.path.insert(0, research_src)
        added = True
    try:
        from data_refresh.market_calendar import classify_market_session
        session = classify_market_session(datetime.now(UTC))
        phase = session.phase
    finally:
        if added:
            sys.path.remove(research_src)

    for spec in jobs_for_phase(phase):
        scheduler.add_job(
            _run_dataset_refresh,
            "interval",
            minutes=spec["interval_minutes"],
            args=[spec["name"]],
            id=f"refresh_{spec['name']}",
            replace_existing=True,
            name=f"refresh:{spec['name']}",
        )
    print(f"[scheduler] registered {len(jobs_for_phase(phase))} jobs for phase={phase}", flush=True)
