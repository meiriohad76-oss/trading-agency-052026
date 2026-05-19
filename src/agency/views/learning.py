"""View-model constructors for the learning page."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import asyncio
import pandas as pd

from agency.services import build_learning_outcome

from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    PRICES_DAILY_ROOT,
    _dashboard_selection_reports,
    _int_field,
    _latest_selection_cycle_id,
    _mapping_field,
    _selection_reports_for_cycle,
    dashboard_data_health,
    live_dashboard_data_load_status,
)


async def learning_context() -> dict[str, object]:
    reports, data_load_status = await asyncio.gather(
        _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
        live_dashboard_data_load_status(),
    )
    cycle_id = _latest_selection_cycle_id(reports)
    cycle_reports = _selection_reports_for_cycle(reports, cycle_id)
    price_history = await asyncio.to_thread(_learning_price_history, cycle_reports)
    outcome = build_learning_outcome(
        selection_reports=cycle_reports,
        price_history=price_history,
    )
    return {
        "outcome": outcome,
        "near_miss": outcome["near_miss_journal"],
        "summary": learning_summary(outcome),
        "data_health": dashboard_data_health(
            "Learning dashboard",
            data_load_status=data_load_status,
            datasets=("prices_daily",),
            cycle_id=cycle_id or "",
            extra_rows=(
                {
                    "kind": "Learning inputs",
                    "name": "Selection outcomes and price history",
                    "status_label": "Ready" if cycle_reports else "Waiting for cycle",
                    "status_class": "pass" if cycle_reports else "neutral",
                    "coverage_label": (
                        f"{len(cycle_reports)} report(s), "
                        f"{len(price_history)} price row(s)"
                    ),
                    "freshness_label": "latest selection cycle",
                    "last_update": cycle_id or "no persisted cycle",
                    "detail": (
                        "Learning uses persisted selection reports plus daily price "
                        "history for near-miss what-if checks."
                    ),
                },
            ),
        ),
    }

def _learning_price_history(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    price_root: Path = PRICES_DAILY_ROOT,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ticker in sorted({str(report.get("ticker", "")).upper() for report in selection_reports}):
        if not ticker:
            continue
        ticker_root = price_root / f"ticker={ticker}"
        if not ticker_root.exists():
            continue
        for path in sorted(ticker_root.rglob("*.parquet")):
            try:
                frame = pd.read_parquet(path, columns=["ticker", "date", "close"])
            except Exception:
                continue
            if frame.empty:
                continue
            rows.extend(
                {
                    "ticker": str(row["ticker"]).upper(),
                    "date": str(row["date"]),
                    "close": float(row["close"]),
                }
                for row in frame.to_dict("records")
                if row.get("close") is not None
            )
    return rows

def learning_summary(outcome: Mapping[str, object]) -> dict[str, object]:
    sample_count = _int_field(outcome, "sample_count")
    required_count = _int_field(outcome, "required_sample_count")
    near_miss = _mapping_field(outcome, "near_miss_journal")
    return {
        "status": str(outcome["status"]),
        "sample_count": sample_count,
        "required_sample_count": required_count,
        "near_miss_count": _int_field(near_miss, "near_miss_count"),
        "headline": str(outcome["message"]),
        "detail": "Learning feedback is advisory until audit persistence and review exist.",
    }
