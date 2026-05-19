from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.massive_lane_manifest import (  # noqa: E402
    manifest_path_for_lane,
    write_lane_manifest,
)
from market_flow.backfill import (  # noqa: E402
    StockTradeBackfillRequest,
    backfill_status,
    build_stock_trade_backfill_plan,
    write_stock_trade_backfill_plan,
    write_stock_trade_backfill_status,
)
from market_flow.massive import (  # noqa: E402
    MassiveTradesConfig,
    pull_massive_trades,
    redact_sensitive_text,
)
from market_flow.storage import DateRange  # noqa: E402
from prices.puller import universe_tickers  # noqa: E402

DEFAULT_OUTPUT_ROOT = ROOT / "research" / "results" / "t137-massive-stock-trade-backfill"
DEFAULT_TRADE_ROOT = ROOT / "research" / "data" / "parquet" / "stock_trades"
DEFAULT_MANIFEST_PATH = ROOT / "research" / "data" / "manifests" / "stock_trades.json"
DEFAULT_UNIVERSE_PATH = ROOT / "research" / "data" / "parquet" / "universe_membership.parquet"
BACKTEST_TRADE_TAPE_LANE_ID = "massive_backtest_trade_tape"


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    _validate_lane_invocation(args)
    if not args.ticker and not args.allow_active_universe:
        raise SystemExit(
            "backfill_massive_stock_trades.py requires at least one --ticker. "
            "Use --allow-active-universe only from a reviewed scheduler plan."
        )
    selected_tickers = args.ticker or _repair_universe_tickers(
        args.universe_path,
        as_of=args.end,
        include_inactive=args.include_inactive_universe,
    )
    tickers = tuple(ticker.upper() for ticker in selected_tickers)
    request = StockTradeBackfillRequest(
        tickers=tickers,
        start=args.start,
        end=args.end,
        trade_root=args.trade_root,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        recent_first=args.recent_first,
        include_existing=args.include_existing,
        max_pages_per_day=_optional_page_limit(args.max_pages_per_day),
    )
    plan = build_stock_trade_backfill_plan(request)
    write_stock_trade_backfill_plan(plan, args.output_root)
    started_at = datetime.now(UTC)
    if args.dry_run:
        status = backfill_status(
            plan=plan,
            started_at=started_at,
            finished_at=started_at,
            batch_results=[],
            dry_run=True,
        )
        status = _attach_final_coverage(status, request)
        write_stock_trade_backfill_status(status, args.output_root)
        _print_summary(args.output_root, plan, status)
        return 0
    config = MassiveTradesConfig.from_env(
        base_url=args.massive_base_url,
        limit=args.limit,
        max_pages_per_day=_optional_page_limit(args.max_pages_per_day),
        max_seconds_per_day=_optional_seconds_limit(args.max_seconds_per_day),
        order=args.order,
        window_minutes=_optional_window_minutes(args.window_minutes),
    )
    status = asyncio.run(
        _run_backfill(
            plan=plan,
            config=config,
            trade_root=args.trade_root,
            manifest_path=args.manifest_path,
            output_root=args.output_root,
            started_at=started_at,
        )
    )
    status = _attach_final_coverage(status, request)
    write_stock_trade_backfill_status(status, args.output_root)
    _write_backtest_lane_manifest(args, request=request, status=status)
    _print_summary(args.output_root, plan, status)
    return 0


async def _run_backfill(
    *,
    plan: Mapping[str, object],
    config: MassiveTradesConfig,
    trade_root: Path,
    manifest_path: Path,
    output_root: Path,
    started_at: datetime,
) -> dict[str, object]:
    batch_results: list[dict[str, object]] = []
    for batch in _batches(plan):
        def progress_writer(progress: Mapping[str, object]) -> None:
            write_stock_trade_backfill_status(
                backfill_status(
                    plan=plan,
                    started_at=started_at,
                    finished_at=None,
                    batch_results=batch_results,
                    current_progress=progress,
                ),
                output_root,
            )

        result = await _run_batch(
            batch,
            config=config,
            trade_root=trade_root,
            manifest_path=manifest_path,
            progress_callback=progress_writer,
        )
        batch_results.append(result)
        write_stock_trade_backfill_status(
            backfill_status(
                plan=plan,
                started_at=started_at,
                finished_at=None,
                batch_results=batch_results,
            ),
            output_root,
        )
    status = backfill_status(
        plan=plan,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        batch_results=batch_results,
    )
    write_stock_trade_backfill_status(status, output_root)
    return status


async def _run_batch(
    batch: Mapping[str, object],
    *,
    config: MassiveTradesConfig,
    trade_root: Path,
    manifest_path: Path,
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
) -> dict[str, object]:
    trade_date = date.fromisoformat(str(batch["trade_date"]))
    tickers = tuple(str(ticker).upper() for ticker in _string_rows(batch.get("tickers")))
    try:
        summary = await pull_massive_trades(
            tickers=tickers,
            requested=DateRange(trade_date, trade_date),
            trade_root=trade_root,
            manifest_path=manifest_path,
            config=config,
            progress_callback=progress_callback,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            **dict(batch),
            "status": "failed",
            "rows_written": 0,
            "issue_count": 1,
            "issues": [{"ticker": "batch", "reason": redact_sensitive_text(str(exc))}],
        }
    partial_ticker_days = sum(
        1
        for row in summary.coverage
        if isinstance(row, Mapping) and row.get("complete") is not True
    )
    issues = [dict(issue) for issue in summary.issues]
    issues.extend(_coverage_issues(summary.coverage))
    return {
        **dict(batch),
        "status": "failed" if summary.issues else "partial" if partial_ticker_days else "passed",
        "rows_written": summary.rows_written,
        "issue_count": len(issues),
        "issues": issues,
        "ticker_day_count": len(summary.coverage),
        "partial_ticker_day_count": partial_ticker_days,
        "coverage": summary.coverage,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan and run resumable Massive/Polygon stock-trade backfills."
    )
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--ticker", action="append")
    parser.add_argument(
        "--allow-active-universe",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Allow no --ticker by intentionally expanding to the active universe. "
            "Reserved for reviewed scheduler/off-hours repair plans."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help=(
            "Ticker-days per durable status batch. The operational default is 1 so "
            "one high-volume ticker cannot hide completion of the next ticker."
        ),
    )
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--recent-first", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--include-existing", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--massive-base-url")
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--max-pages-per-day", type=int)
    parser.add_argument("--max-seconds-per-day", type=float)
    parser.add_argument("--order", choices=("asc", "desc"), default=None)
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=30,
        help=(
            "Split each ticker-day into durable sub-day windows for full-depth "
            "repair. Use 0 to disable time-windowed repair."
        ),
    )
    parser.add_argument("--universe-path", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument(
        "--include-inactive-universe",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Use every ticker in the universe membership file. By default the repair "
            "targets only tickers active on --end."
        ),
    )
    parser.add_argument("--trade-root", type=Path, default=DEFAULT_TRADE_ROOT)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--lane-id",
        default=BACKTEST_TRADE_TAPE_LANE_ID,
        help="Massive raw lane manifest to update for this full-depth repair run.",
    )
    parser.add_argument(
        "--lane-manifest-path",
        type=Path,
        default=None,
        help="Optional explicit lane-level manifest path.",
    )
    return parser.parse_args()


def _validate_lane_invocation(args: argparse.Namespace) -> None:
    if str(args.lane_id or "") != BACKTEST_TRADE_TAPE_LANE_ID:
        raise SystemExit(
            "backfill_massive_stock_trades.py may only write the "
            "massive_backtest_trade_tape lane manifest. Use the live lane puller "
            "for massive_live_trade_slices or massive_premarket_trade_slices."
        )


def _attach_final_coverage(
    status: Mapping[str, object],
    request: StockTradeBackfillRequest,
) -> dict[str, object]:
    final_plan = build_stock_trade_backfill_plan(
        StockTradeBackfillRequest(
            tickers=request.tickers,
            start=request.start,
            end=request.end,
            trade_root=request.trade_root,
            batch_size=request.batch_size,
            max_batches=None,
            recent_first=request.recent_first,
            include_existing=request.include_existing,
            max_pages_per_day=request.max_pages_per_day,
        )
    )
    final_summary = _mapping(final_plan.get("summary"))
    final_partial = _int(final_summary.get("partial_ticker_days"))
    final_missing = _int(final_summary.get("missing_ticker_days"))
    final_complete = _int(final_summary.get("covered_ticker_days"))
    final_expected = _int(final_summary.get("expected_ticker_days"))
    summary = dict(_mapping(status.get("summary")))
    summary["final_complete_ticker_days"] = final_complete
    summary["final_partial_ticker_days"] = final_partial
    summary["final_missing_ticker_days"] = final_missing
    summary["final_remaining_ticker_days"] = final_partial + final_missing
    summary["final_coverage_pct"] = _coverage_pct(final_complete, final_expected)
    failed = _int(summary.get("failed_batch_count"))
    partial = _int(summary.get("partial_batch_count"))
    verdict = str(status.get("verdict") or "")
    if verdict != "dry_run":
        if failed:
            verdict = "completed_with_failures"
        elif final_partial or final_missing or partial:
            verdict = "partial"
        else:
            verdict = "completed"
    updated = dict(status)
    updated["verdict"] = verdict
    updated["summary"] = summary
    updated["final_plan_summary"] = dict(final_summary)
    return updated


def _write_backtest_lane_manifest(
    args: argparse.Namespace,
    *,
    request: StockTradeBackfillRequest,
    status: Mapping[str, object],
) -> None:
    summary = _mapping(status.get("summary"))
    final_summary = _mapping(status.get("final_plan_summary")) or _mapping(
        status.get("plan_summary")
    )
    expected = _int(final_summary.get("expected_ticker_days"))
    complete = _int(final_summary.get("covered_ticker_days"))
    remaining = _int(summary.get("final_remaining_ticker_days"))
    failed = _int(summary.get("failed_batch_count"))
    lane_status = "complete" if expected and remaining == 0 and failed == 0 else "partial"
    if failed:
        lane_status = "failed"
    manifest_payload = _json_mapping(args.manifest_path)
    source_row_count = _int(manifest_payload.get("row_count")) or _int(summary.get("rows_written"))
    issues = _lane_issues(status, remaining=remaining, failed=failed)
    write_lane_manifest(
        args.lane_manifest_path or manifest_path_for_lane(ROOT, str(args.lane_id)),
        lane_id=str(args.lane_id),
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=datetime.now(UTC),
        requested_start=request.start,
        requested_end=request.end,
        tickers=request.tickers,
        row_count=source_row_count,
        source_manifest=args.manifest_path,
        status=lane_status,
        issues=issues,
        coverage_pct=_coverage_pct(complete, expected),
        request_budget_label=(
            "off-hours full-depth time-windowed trade-tape repair; "
            f"window_minutes={args.window_minutes}; max_pages_per_day="
            f"{args.max_pages_per_day or 'uncapped'}"
        ),
    )


def _lane_issues(
    status: Mapping[str, object],
    *,
    remaining: int,
    failed: int,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if remaining:
        issues.append(
            {
                "kind": "remaining_backlog",
                "reason": f"{remaining} ticker-day(s) still require full-depth repair.",
            }
        )
    if failed:
        issues.append(
            {
                "kind": "failed_batches",
                "reason": f"{failed} repair batch(es) failed in the latest run.",
            }
        )
    for batch in _mapping_rows(status.get("batches")):
        for issue in _mapping_rows(batch.get("issues")):
            issues.append(dict(issue))
            if len(issues) >= 50:
                return issues
    return issues


def _coverage_issues(coverage: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in coverage:
        status = str(row.get("coverage_status") or "").lower()
        stop_reason = str(row.get("stop_reason") or row.get("reason") or "").strip()
        if status != "failed" and not stop_reason.startswith("request_failed"):
            continue
        ticker = str(row.get("ticker") or "unknown").upper()
        trade_date = str(row.get("trade_date") or "unknown")
        reason = redact_sensitive_text(stop_reason or "coverage did not complete")
        issues.append(
            {
                "ticker": ticker,
                "trade_date": trade_date,
                "reason": reason[:240],
            }
        )
    return issues


def _repair_universe_tickers(
    path: Path,
    *,
    as_of: date,
    include_inactive: bool,
) -> list[str]:
    if include_inactive:
        return universe_tickers(path)
    try:
        frame = pd.read_parquet(path, columns=["ticker", "start_date", "end_date"])
    except (OSError, ValueError, KeyError):
        return universe_tickers(path)
    if frame.empty:
        return []
    start = pd.to_datetime(frame["start_date"], errors="coerce")
    end = pd.to_datetime(frame["end_date"], errors="coerce")
    as_of_timestamp = pd.Timestamp(as_of)
    active = frame[
        (start.isna() | (start <= as_of_timestamp))
        & (end.isna() | (end > as_of_timestamp))
    ]
    return sorted(
        {
            str(ticker).upper()
            for ticker in active["ticker"].dropna().unique()
            if str(ticker).strip()
        }
    )


def _batches(plan: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = plan.get("batches", [])
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _string_rows(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _optional_page_limit(value: int | None) -> int | None:
    if value is None or value < 1:
        return None
    return value


def _optional_seconds_limit(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return value


def _optional_window_minutes(value: int | None) -> int | None:
    if value is None or value < 1:
        return None
    return value


def _print_summary(
    output_root: Path,
    plan: Mapping[str, object],
    status: Mapping[str, object],
) -> None:
    summary = _mapping(status.get("summary"))
    plan_summary = _mapping(plan.get("summary"))
    print(
        json.dumps(
            {
                "output_root": output_root.as_posix(),
                "verdict": status.get("verdict"),
                "planned_batches": summary.get("planned_batch_count", 0),
                "completed_batches": summary.get("completed_batch_count", 0),
                "failed_batches": summary.get("failed_batch_count", 0),
                "rows_written": summary.get("rows_written", 0),
                "missing_ticker_days": plan_summary.get("missing_ticker_days", 0),
                "final_remaining_ticker_days": summary.get("final_remaining_ticker_days", 0),
                "final_coverage_pct": summary.get("final_coverage_pct", 0),
                "estimated_requests": plan_summary.get("estimated_requests", 0),
            },
            sort_keys=True,
        )
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _json_mapping(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0


def _coverage_pct(complete: int, expected: int) -> int:
    if expected <= 0:
        return 100
    return round(max(0, min(complete, expected)) / expected * 100)


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
