from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.market_calendar import is_trading_day  # noqa: E402
from data_refresh.massive_lane_manifest import (  # noqa: E402
    manifest_path_for_lane,
    read_lane_manifest,
    write_lane_manifest,
)
from data_refresh.stock_trade_safety import (  # noqa: E402
    StockTradeSafetyLimits,
    stock_trade_safety_reasons,
)
from market_flow.massive import (  # noqa: E402
    MassiveTradesConfig,
    pull_massive_trades,
    redact_sensitive_text,
)
from market_flow.storage import DateRange  # noqa: E402
from prices.puller import universe_tickers  # noqa: E402

DEFAULT_PROGRESS_PATH = (
    ROOT / "research" / "results" / "latest-data-refresh" / "stock-trades-progress.json"
)
MAX_LIVE_LANE_TICKERS = int(os.environ.get("AGENCY_MAX_LIVE_LANE_TICKERS", "200"))
LIVE_STOCK_TRADE_LANES = {
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
}


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    _validate_lane_invocation(args)
    tickers = _selected_tickers(args)
    progress = StockTradeProgressWriter(
        path=args.progress_path,
        lane_id=args.lane_id,
        tickers=tickers,
        start=args.start,
        end=args.end,
    )
    page_limit = _optional_page_limit(args.max_pages_per_day)
    safety_reasons = stock_trade_safety_reasons(
        tickers=tuple(ticker.upper() for ticker in tickers),
        start=args.start,
        end=args.end,
        unbounded_pages=page_limit is None,
        limits=StockTradeSafetyLimits(
            max_trading_days=args.max_direct_trading_days,
            max_ticker_days=args.max_direct_ticker_days,
        ),
        allow_large_window=False,
    )
    if safety_reasons:
        reason = "; ".join(safety_reasons)
        progress.fail(reason)
        raise SystemExit(reason)
    config = MassiveTradesConfig.from_env(
        base_url=args.massive_base_url,
        limit=_lane_default_limit(args.lane_id, args.limit),
        max_pages_per_day=page_limit,
        max_seconds_per_day=_optional_seconds_limit(args.max_seconds_per_day),
        order=args.order,
        trade_session=_trade_session(args),
        resume_partial=_lane_resume_enabled(args.lane_id),
    )
    progress.mark_started()
    try:
        summary = asyncio.run(
            pull_massive_trades(
                tickers=tickers,
                requested=DateRange(args.start, args.end),
                trade_root=args.trade_root,
                manifest_path=args.manifest_path,
                config=config,
                progress_callback=progress.update,
            )
        )
    except Exception as exc:
        progress.fail(redact_sensitive_text(str(exc)))
        raise
    progress.complete(
        rows_written=summary.rows_written,
        issues=summary.issues,
        coverage=summary.coverage,
    )
    fetched_at = datetime.now(UTC)
    lane_manifest_path = args.lane_manifest_path or manifest_path_for_lane(
        ROOT,
        args.lane_id,
    )
    lane_payload = _merged_lane_manifest_payload(
        lane_manifest_path,
        lane_id=args.lane_id,
        fetched_at=fetched_at,
        requested_start=args.start,
        requested_end=args.end,
        tickers=tickers,
        rows_written=summary.rows_written,
        issues=summary.issues,
        coverage=summary.coverage,
        page_limit=page_limit,
    )
    lane_tickers = cast(list[str], lane_payload["tickers"])
    lane_issues = cast(list[Mapping[str, object]], lane_payload["issues"])
    lane_coverage = cast(list[dict[str, object]], lane_payload["coverage"])
    write_lane_manifest(
        lane_manifest_path,
        lane_id=args.lane_id,
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=fetched_at,
        requested_start=args.start,
        requested_end=args.end,
        tickers=lane_tickers,
        row_count=cast(int, lane_payload["row_count"]),
        source_manifest=args.manifest_path,
        status=str(lane_payload["status"]),
        issues=lane_issues,
        coverage=lane_coverage,
        coverage_pct=_lane_coverage_pct(args.lane_id, lane_coverage),
        request_budget_label=_lane_budget_label(args.lane_id, page_limit),
    )
    print(json.dumps(summary.__dict__, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Massive stock trades.")
    parser.add_argument("--start", type=_date, default=date.today())
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--ticker", action="append", help="Ticker to refresh; repeatable.")
    parser.add_argument("--massive-base-url")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-pages-per-day", type=int)
    parser.add_argument("--max-seconds-per-day", type=float)
    parser.add_argument("--order", choices=("asc", "desc"), default=None)
    parser.add_argument(
        "--trade-session",
        choices=("full_day", "pre_market"),
        default=None,
        help=(
            "Timestamp window to request from Massive. The pre-market lane "
            "automatically uses 04:00-09:30 ET."
        ),
    )
    parser.add_argument(
        "--allow-long-window",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Deprecated compatibility flag. This live lane puller rejects long "
            "windows; use backfill_massive_stock_trades.py for historical repair."
        ),
    )
    parser.add_argument(
        "--full-universe",
        action="store_true",
        default=False,
        help=(
            "Deprecated compatibility flag. This live lane puller rejects broad "
            "universe expansion; use backfill_massive_stock_trades.py with "
            "massive_backtest_trade_tape for reviewed historical repair."
        ),
    )
    parser.add_argument(
        "--include-inactive-universe",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "When no --ticker values are supplied, include every ticker in the "
            "universe membership file. By default the pull targets only tickers "
            "active on --end so live jobs cannot accidentally pull inactive or "
            "research-only tickers."
        ),
    )
    parser.add_argument("--max-direct-trading-days", type=int, default=5)
    parser.add_argument("--max-direct-ticker-days", type=int, default=750)
    parser.add_argument(
        "--lane-id",
        default=None,
        help="Massive raw lane that owns this pull and receives a lane manifest.",
    )
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument(
        "--trade-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "stock_trades",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "stock_trades.json",
    )
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=DEFAULT_PROGRESS_PATH,
        help="JSON file updated as Massive trade pages are pulled.",
    )
    parser.add_argument(
        "--lane-manifest-path",
        type=Path,
        default=None,
        help="Optional explicit lane-level manifest path.",
    )
    return parser.parse_args()


def _validate_lane_invocation(args: argparse.Namespace) -> None:
    lane_id = str(args.lane_id or "")
    if lane_id not in LIVE_STOCK_TRADE_LANES:
        raise SystemExit(
            "pull_massive_stock_trades.py is only for explicit live slice lanes "
            "(massive_live_trade_slices or massive_premarket_trade_slices). "
            "Use backfill_massive_stock_trades.py for massive_backtest_trade_tape."
        )
    if not args.ticker:
        raise SystemExit(
            "Explicit --ticker values are required. The scheduler work queue / "
            "Massive Lane Orchestrator must control live lane batch scope."
        )
    if len(args.ticker) > MAX_LIVE_LANE_TICKERS:
        raise SystemExit(
            f"Live slice lane pulls are capped at {MAX_LIVE_LANE_TICKERS} explicit "
            "tickers per invocation. Let the scheduler lane tiering split larger "
            "universes into batches."
        )
    if args.start != args.end:
        raise SystemExit(
            "Live slice lanes may request one trade date only. Use "
            "backfill_massive_stock_trades.py for multi-day historical repair."
        )
    if args.full_universe:
        raise SystemExit(
            "--full-universe is disabled for the live lane puller. Use the "
            "off-hours massive_backtest_trade_tape lane for broad historical repair."
        )
    if args.include_inactive_universe:
        raise SystemExit(
            "--include-inactive-universe is disabled for live slice lanes; lane tiering "
            "must select explicit active tickers."
        )
    if args.allow_long_window:
        raise SystemExit(
            "--allow-long-window is disabled for live slice lanes. Use "
            "backfill_massive_stock_trades.py for historical repair."
        )
    if lane_id == "massive_live_trade_slices" and args.trade_session == "pre_market":
        raise SystemExit(
            "Use --lane-id massive_premarket_trade_slices for pre-market trade-session pulls."
        )


def _selected_tickers(args: argparse.Namespace) -> tuple[str, ...]:
    if args.ticker:
        return _normalize_tickers(args.ticker)
    if args.full_universe or args.include_inactive_universe:
        return _normalize_tickers(universe_tickers(args.universe_path))
    tickers = _active_universe_tickers(args.universe_path, as_of=args.end)
    if tickers:
        return tickers
    raise SystemExit(
        "No active universe tickers were found for "
        f"{args.end.isoformat()} in {args.universe_path}. "
        "Pass explicit --ticker values from the scheduler tier plan, or use "
        "backfill_massive_stock_trades.py for reviewed historical repair."
    )


def _active_universe_tickers(path: Path, *, as_of: date) -> tuple[str, ...]:
    try:
        frame = pd.read_parquet(path, columns=["ticker", "start_date", "end_date"])
    except (OSError, ValueError, KeyError, ImportError):
        return ()
    if frame.empty:
        return ()
    start = pd.to_datetime(frame["start_date"], errors="coerce")
    end = pd.to_datetime(frame["end_date"], errors="coerce")
    current = pd.Timestamp(as_of)
    active = frame[(start <= current) & (end.isna() | (end > current))]
    return _normalize_tickers(str(ticker) for ticker in active["ticker"].dropna().unique())


def _normalize_tickers(values: object) -> tuple[str, ...]:
    if not isinstance(values, list | tuple | set) and not hasattr(values, "__iter__"):
        return ()
    return tuple(
        sorted(
            {
                str(value).upper().strip()
                for value in values
                if str(value).strip()
            }
        )
    )


def _optional_page_limit(value: int | None) -> int | None:
    if value is None or value < 1:
        return None
    return value


def _optional_seconds_limit(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return value


def _lane_default_limit(lane_id: str, value: int | None) -> int:
    if value is not None:
        return value
    if lane_id in {"massive_live_trade_slices", "massive_premarket_trade_slices"}:
        return 1_000
    return 50_000


def _lane_resume_enabled(lane_id: str) -> bool:
    del lane_id
    return False


def _trade_session(args: argparse.Namespace) -> str:
    if args.trade_session:
        return str(args.trade_session)
    if args.lane_id == "massive_premarket_trade_slices":
        return "pre_market"
    return "full_day"


def _lane_coverage_pct(
    lane_id: str,
    coverage: list[dict[str, object]],
) -> int | None:
    if lane_id not in {"massive_live_trade_slices", "massive_premarket_trade_slices"}:
        return None
    if not coverage:
        return 0
    usable = sum(1 for row in coverage if _live_lane_coverage_usable(row))
    return round(usable / max(len(coverage), 1) * 100)


def _live_lane_status(
    coverage: list[dict[str, object]],
    issues: list[dict[str, str]],
) -> str:
    if issues:
        return "partial"
    if not coverage:
        return "partial"
    complete = sum(1 for row in coverage if _live_lane_coverage_complete(row))
    usable = sum(1 for row in coverage if _live_lane_coverage_usable(row))
    if complete == len(coverage):
        return "complete"
    if usable:
        return "partial_usable"
    return "partial"


def _merged_lane_manifest_payload(
    path: Path,
    *,
    lane_id: str,
    fetched_at: datetime,
    requested_start: date,
    requested_end: date,
    tickers: tuple[str, ...],
    rows_written: int,
    issues: list[dict[str, str]],
    coverage: list[dict[str, object]],
    page_limit: int | None,
) -> dict[str, object]:
    if lane_id not in {"massive_live_trade_slices", "massive_premarket_trade_slices"}:
        annotated = _annotated_coverage(coverage, fetched_at=fetched_at)
        return {
            "tickers": list(tickers),
            "row_count": rows_written,
            "status": "complete" if not issues else "partial",
            "issues": issues,
            "coverage": annotated,
        }
    existing = read_lane_manifest(path)
    same_window = _same_lane_window(
        existing,
        lane_id=lane_id,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    existing_coverage = (
        [
            row
            for row in existing.get("coverage", [])
            if isinstance(row, Mapping)
        ]
        if same_window
        else []
    )
    merged_by_key: dict[str, dict[str, object]] = {
        _coverage_merge_key(row): dict(row)
        for row in existing_coverage
        if _coverage_merge_key(row)
    }
    for row in _annotated_coverage(coverage, fetched_at=fetched_at):
        key = _coverage_merge_key(row)
        if key:
            merged_by_key[key] = dict(row)
    merged_coverage = sorted(
        merged_by_key.values(),
        key=lambda row: (str(row.get("ticker") or ""), str(row.get("trade_date") or "")),
    )
    merged_tickers = sorted(
        {
            str(row.get("ticker")).upper()
            for row in merged_coverage
            if str(row.get("ticker") or "").strip()
        }
        | {ticker.upper() for ticker in tickers}
    )
    merged_issues = _live_lane_issues(issues, merged_coverage)
    existing_rows = int(existing.get("row_count") or 0) if same_window else 0
    return {
        "tickers": merged_tickers,
        "row_count": max(0, existing_rows) + max(rows_written, 0),
        "status": _live_lane_status(merged_coverage, merged_issues),
        "issues": merged_issues,
        "coverage": merged_coverage,
    }


def _annotated_coverage(
    coverage: list[dict[str, object]],
    *,
    fetched_at: datetime,
) -> list[dict[str, object]]:
    stamp = fetched_at.isoformat()
    annotated: list[dict[str, object]] = []
    for row in coverage:
        item = dict(row)
        item.setdefault("fetched_at", stamp)
        item.setdefault("updated_at", stamp)
        annotated.append(item)
    return annotated


def _coverage_merge_key(row: Mapping[str, object]) -> str:
    ticker = str(row.get("ticker") or "").upper().strip()
    trade_date = str(row.get("trade_date") or "").strip()
    if not ticker or not trade_date:
        return ""
    return f"{ticker}|{trade_date}"


def _same_lane_window(
    existing: Mapping[str, object],
    *,
    lane_id: str,
    requested_start: date,
    requested_end: date,
) -> bool:
    if not existing or str(existing.get("lane_id") or "") != lane_id:
        return False
    window = existing.get("window")
    if not isinstance(window, Mapping):
        return False
    return (
        str(window.get("start") or "") == requested_start.isoformat()
        and str(window.get("end") or "") == requested_end.isoformat()
    )


def _live_lane_issues(
    issues: list[dict[str, str]],
    coverage: list[dict[str, object]],
) -> list[dict[str, str]]:
    merged = [dict(issue) for issue in issues]
    failed_keys = {
        _coverage_merge_key(row)
        for row in coverage
        if not _live_lane_coverage_usable(row)
    }
    for key in sorted(value for value in failed_keys if value):
        ticker, trade_date = key.split("|", maxsplit=1)
        merged.append(
            {
                "ticker": ticker,
                "trade_date": trade_date,
                "reason": "latest live trade slice failed",
            }
        )
    return merged


def _live_lane_coverage_usable(row: Mapping[str, object]) -> bool:
    status = str(row.get("coverage_status") or row.get("status") or "").lower()
    if _live_lane_coverage_complete(row) or status in {"ready", "usable", "partial_usable"}:
        return True
    if status != "partial":
        return False
    rows = _int_value(
        row.get("downloaded_row_count"),
        _int_value(row.get("rows_written"), 0),
    )
    pages = _int_value(row.get("pages_downloaded"), 0)
    return rows > 0 and pages > 0 and str(row.get("order") or "").lower() == "desc"


def _live_lane_coverage_complete(row: Mapping[str, object]) -> bool:
    status = str(row.get("coverage_status") or row.get("status") or "").lower()
    if not (row.get("complete") is True or status == "complete"):
        return False
    return row.get("row_count_verified") is not False


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _int_value(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    return fallback


class StockTradeProgressWriter:
    def __init__(
        self,
        *,
        path: Path,
        lane_id: str = "massive_live_trade_slices",
        tickers: tuple[str, ...],
        start: date,
        end: date,
    ) -> None:
        self.path = path
        self.lane_id = lane_id
        self.tickers = tuple(sorted({ticker.upper() for ticker in tickers}))
        self.window_start = start
        self.window_end = end
        self.started_at = datetime.now(UTC).isoformat()
        self.current: dict[str, object] = {}
        self.completed: set[str] = set()
        self.usable: set[str] = set()
        self.partial: set[str] = set()
        self.failed: set[str] = set()

    def mark_started(self) -> None:
        self._write(state="running", status="starting")

    def update(self, event: Mapping[str, object]) -> None:
        self.current = dict(event)
        status = str(event.get("status") or "running")
        durable = event.get("durable") is True
        key = _ticker_day_key(event)
        if status == "complete" and durable:
            self.completed.add(key)
            self.usable.add(key)
            self.partial.discard(key)
            self.failed.discard(key)
        elif status == "partial" and durable and self._live_slice_lane():
            self.usable.add(key)
            self.partial.add(key)
            self.completed.discard(key)
            self.failed.discard(key)
        elif status == "partial" and durable:
            self.partial.add(key)
            self.completed.discard(key)
            self.usable.discard(key)
            self.failed.discard(key)
        elif status == "failed":
            self.failed.add(key)
            self.completed.discard(key)
            self.partial.discard(key)
            self.usable.discard(key)
        self._write(state="running", status=status)

    def complete(
        self,
        *,
        rows_written: int,
        issues: list[dict[str, str]],
        coverage: list[dict[str, object]],
    ) -> None:
        self._merge_coverage(coverage)
        state = "complete" if self._complete_enough(issues) else "partial"
        self._write(
            state=state,
            status=state,
            rows_written=rows_written,
            issues=issues[:5],
            issue_count=len(issues) + len(self.partial) + len(self.failed),
        )

    def fail(self, reason: str) -> None:
        self._write(state="failed", status="failed", reason=reason)

    def _merge_coverage(self, coverage: list[dict[str, object]]) -> None:
        for row in coverage:
            key = _ticker_day_key(row)
            status = str(row.get("coverage_status") or row.get("status") or "").lower()
            if _live_lane_coverage_complete(row):
                self.completed.add(key)
                self.usable.add(key)
                self.partial.discard(key)
                self.failed.discard(key)
            elif self._live_slice_lane() and _live_lane_coverage_usable(row):
                self.usable.add(key)
                self.partial.add(key)
                self.completed.discard(key)
                self.failed.discard(key)
            elif status == "failed":
                self.failed.add(key)
                self.partial.discard(key)
                self.completed.discard(key)
                self.usable.discard(key)
            else:
                self.partial.add(key)
                self.completed.discard(key)
                self.usable.discard(key)

    def _live_slice_lane(self) -> bool:
        return self.lane_id in {
            "massive_live_trade_slices",
            "massive_premarket_trade_slices",
        }

    def _complete_enough(self, issues: list[dict[str, str]]) -> bool:
        total = max(len(self.tickers) * _date_count(self.window_start, self.window_end), 1)
        return (
            not issues
            and not self.partial
            and not self.failed
            and len(self.completed) >= total
        )

    def _write(
        self,
        *,
        state: str,
        status: str,
        rows_written: int | None = None,
        issues: list[dict[str, str]] | None = None,
        issue_count: int = 0,
        reason: str | None = None,
    ) -> None:
        total = max(len(self.tickers) * _date_count(self.window_start, self.window_end), 1)
        completed = len(self.completed)
        processed = len(self.completed | self.usable | self.partial | self.failed)
        percent = 100 if state == "complete" else round(processed / total * 100)
        payload = {
            "schema_version": "0.1.0",
            "lane_id": self.lane_id,
            "state": state,
            "status": status,
            "started_at": self.started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "ticker_count": len(self.tickers),
            "ticker_days_total": total,
            "ticker_days_completed": completed if state != "complete" else total,
            "ticker_days_processed": processed if state != "complete" else total,
            "ticker_days_partial": len(self.partial),
            "ticker_days_failed": len(self.failed),
            "percent_complete": percent,
            **self._pipeline_payload(),
            "start": self.window_start.isoformat(),
            "end": self.window_end.isoformat(),
            "current_ticker": self.current.get("ticker"),
            "current_trade_date": self.current.get("trade_date"),
            "current_pages_downloaded": self.current.get("pages_downloaded", 0),
            "current_rows_downloaded": self.current.get("rows_downloaded", 0),
            "rows_written": rows_written,
            "issues": issues or [],
            "issue_count": issue_count,
            "reason": reason,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _pipeline_payload(self) -> dict[str, object]:
        statuses = self._ticker_statuses()
        ready = [row["ticker"] for row in statuses if row["status"] == "complete"]
        usable = [row["ticker"] for row in statuses if row["usable_for_live_pipeline"] is True]
        pending = [
            row["ticker"]
            for row in statuses
            if row["status"] == "pending"
            or (
                row["status"] == "partial"
                and row["usable_for_live_pipeline"] is not True
            )
        ]
        failed = [row["ticker"] for row in statuses if row["status"] == "failed"]
        return {
            "ticker_statuses": statuses,
            "pipeline_ready_tickers": ready,
            "pipeline_usable_tickers": usable,
            "pipeline_pending_tickers": pending,
            "pipeline_failed_tickers": failed,
            "pipeline_ready_count": len(ready),
            "pipeline_usable_count": len(usable),
            "pipeline_pending_count": len(pending),
            "pipeline_failed_count": len(failed),
            "pipeline_ready_label": f"{len(ready)}/{len(self.tickers)} tickers ready",
            "pipeline_usable_label": f"{len(usable)}/{len(self.tickers)} tickers usable",
            "pipeline_detail": (
                f"{len(usable)} ticker(s) can pass forward now; "
                f"{len(ready)} have complete requested-window coverage; "
                f"{len(pending)} still extracting; {len(failed)} failed."
            ),
        }

    def _ticker_statuses(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for ticker in self.tickers:
            keys = _ticker_day_keys(ticker, self.window_start, self.window_end)
            completed = len(keys.intersection(self.completed))
            usable = len(keys.intersection(self.usable))
            partial = len(keys.intersection(self.partial))
            failed = len(keys.intersection(self.failed))
            total = len(keys)
            missing = max(total - completed - usable - partial - failed, 0)
            if total > 0 and completed == total:
                status = "complete"
            elif failed and completed + partial + failed == total:
                status = "failed"
            elif completed or usable or partial:
                status = "partial"
            else:
                status = "pending"
            usable_for_live = total > 0 and completed + usable >= total and failed == 0
            rows.append(
                {
                    "ticker": ticker,
                    "status": status,
                    "complete": status == "complete",
                    "eligible_for_pipeline": status == "complete",
                    "usable_for_live_pipeline": usable_for_live,
                    "completed_days": completed,
                    "usable_days": usable,
                    "partial_days": partial,
                    "failed_days": failed,
                    "missing_days": missing,
                    "total_days": total,
                }
            )
        return rows


def _ticker_day_key(event: Mapping[str, object]) -> str:
    return f"{str(event.get('ticker', '')).upper()}:{event.get('trade_date')}"


def _ticker_day_keys(ticker: str, start: date, end: date) -> set[str]:
    keys: set[str] = set()
    current = start
    while current <= end:
        if is_trading_day(current):
            keys.add(f"{ticker.upper()}:{current.isoformat()}")
        current = date.fromordinal(current.toordinal() + 1)
    return keys


def _date_count(start: date, end: date) -> int:
    count = 0
    current = start
    while current <= end:
        if is_trading_day(current):
            count += 1
        current = date.fromordinal(current.toordinal() + 1)
    return max(count, 1)


def _lane_budget_label(lane_id: str, page_limit: int | None) -> str:
    page_text = "uncapped pages" if page_limit is None else f"{page_limit} page(s)/ticker-day"
    if lane_id == "massive_premarket_trade_slices":
        return f"pre-market live slice; {page_text}"
    if lane_id == "massive_backtest_trade_tape":
        return f"off-hours full-depth trade tape; {page_text}"
    return f"live trade slice; {page_text}"


if __name__ == "__main__":
    raise SystemExit(main())
