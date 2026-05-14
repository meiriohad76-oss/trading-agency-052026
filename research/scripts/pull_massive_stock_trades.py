from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.stock_trade_safety import (  # noqa: E402
    StockTradeSafetyLimits,
    stock_trade_safety_reasons,
)
from market_flow.massive import MassiveTradesConfig, pull_massive_trades  # noqa: E402
from market_flow.storage import DateRange  # noqa: E402
from prices.puller import universe_tickers  # noqa: E402

DEFAULT_PROGRESS_PATH = (
    ROOT / "research" / "results" / "latest-data-refresh" / "stock-trades-progress.json"
)


_FULL_UNIVERSE_SENTINEL = 10_000_000


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    if args.full_universe:
        print(
            "WARNING: Full-universe mode: safety limits disabled. "
            "Ensure API key has no daily limits.",
            flush=True,
        )
    tickers = tuple(args.ticker or universe_tickers(args.universe_path))
    progress = StockTradeProgressWriter(
        path=args.progress_path,
        tickers=tickers,
        start=args.start,
        end=args.end,
    )
    page_limit = _optional_page_limit(args.max_pages_per_day)
    if args.full_universe:
        max_trading_days = _FULL_UNIVERSE_SENTINEL
        max_ticker_days = _FULL_UNIVERSE_SENTINEL
        allow_large_window = True
    else:
        max_trading_days = args.max_direct_trading_days
        max_ticker_days = args.max_direct_ticker_days
        allow_large_window = args.allow_long_window
    safety_reasons = stock_trade_safety_reasons(
        tickers=tuple(ticker.upper() for ticker in tickers),
        start=args.start,
        end=args.end,
        unbounded_pages=page_limit is None,
        limits=StockTradeSafetyLimits(
            max_trading_days=max_trading_days,
            max_ticker_days=max_ticker_days,
        ),
        allow_large_window=allow_large_window,
    )
    if safety_reasons:
        reason = "; ".join(safety_reasons)
        progress.fail(reason)
        raise SystemExit(reason)
    config = MassiveTradesConfig.from_env(
        base_url=args.massive_base_url,
        limit=args.limit,
        max_pages_per_day=page_limit,
        order=args.order,
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
        progress.fail(str(exc))
        raise
    progress.complete(
        rows_written=summary.rows_written,
        issues=summary.issues,
        coverage=summary.coverage,
    )
    print(json.dumps(summary.__dict__, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Massive stock trades.")
    parser.add_argument("--start", type=_date, default=date.today())
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--ticker", action="append", help="Ticker to refresh; repeatable.")
    parser.add_argument("--massive-base-url")
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--max-pages-per-day", type=int)
    parser.add_argument("--order", choices=("asc", "desc"), default=None)
    parser.add_argument(
        "--allow-long-window",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Bypass the direct live-refresh safety guard. Prefer "
            "backfill_massive_stock_trades.py for historical repair."
        ),
    )
    parser.add_argument(
        "--full-universe",
        action="store_true",
        default=False,
        help=(
            "Disable all safety limits and target the full trading universe. "
            "Requires --start and --end. "
            "Only use when the API key has no daily request limits."
        ),
    )
    parser.add_argument("--max-direct-trading-days", type=int, default=5)
    parser.add_argument("--max-direct-ticker-days", type=int, default=750)
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
    return parser.parse_args()


def _optional_page_limit(value: int | None) -> int | None:
    if value is None or value < 1:
        return None
    return value


def _date(value: str) -> date:
    return date.fromisoformat(value)


class StockTradeProgressWriter:
    def __init__(
        self,
        *,
        path: Path,
        tickers: tuple[str, ...],
        start: date,
        end: date,
    ) -> None:
        self.path = path
        self.tickers = tuple(sorted({ticker.upper() for ticker in tickers}))
        self.window_start = start
        self.window_end = end
        self.started_at = datetime.now(UTC).isoformat()
        self.current: dict[str, object] = {}
        self.completed: set[str] = set()
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
            self.partial.discard(key)
            self.failed.discard(key)
        elif status == "partial" and durable:
            self.partial.add(key)
            self.completed.discard(key)
            self.failed.discard(key)
        elif status == "failed":
            self.failed.add(key)
            self.completed.discard(key)
            self.partial.discard(key)
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
            if row.get("complete") is True or status == "complete":
                self.completed.add(key)
                self.partial.discard(key)
                self.failed.discard(key)
            elif status == "failed":
                self.failed.add(key)
                self.partial.discard(key)
                self.completed.discard(key)
            else:
                self.partial.add(key)
                self.completed.discard(key)

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
        processed = len(self.completed | self.partial | self.failed)
        percent = 100 if state == "complete" else round(processed / total * 100)
        payload = {
            "schema_version": "0.1.0",
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
        usable = list(ready)
        pending = [row["ticker"] for row in statuses if row["status"] in {"pending", "partial"}]
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
                f"{len(ready)} have complete full-depth coverage; "
                f"{len(pending)} still extracting; {len(failed)} failed."
            ),
        }

    def _ticker_statuses(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for ticker in self.tickers:
            keys = _ticker_day_keys(ticker, self.window_start, self.window_end)
            completed = len(keys.intersection(self.completed))
            partial = len(keys.intersection(self.partial))
            failed = len(keys.intersection(self.failed))
            total = len(keys)
            missing = max(total - completed - partial - failed, 0)
            if total > 0 and completed == total:
                status = "complete"
            elif failed and completed + partial + failed == total:
                status = "failed"
            elif completed or partial:
                status = "partial"
            else:
                status = "pending"
            rows.append(
                {
                    "ticker": ticker,
                    "status": status,
                    "complete": status == "complete",
                    "eligible_for_pipeline": status == "complete",
                    "usable_for_live_pipeline": status == "complete",
                    "completed_days": completed,
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
        keys.add(f"{ticker.upper()}:{current.isoformat()}")
        current = date.fromordinal(current.toordinal() + 1)
    return keys


def _date_count(start: date, end: date) -> int:
    return max((end - start).days + 1, 1)


if __name__ == "__main__":
    raise SystemExit(main())
