from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from data_refresh.market_calendar import is_trading_day
from market_flow.storage import coverage_key, load_stock_trade_coverage_metadata


@dataclass(frozen=True)
class StockTradeBackfillRequest:
    tickers: tuple[str, ...]
    start: date
    end: date
    trade_root: Path
    batch_size: int = 10
    max_batches: int | None = None
    recent_first: bool = False
    include_existing: bool = False
    max_pages_per_day: int | None = None


@dataclass(frozen=True)
class StockTradeBackfillBatch:
    batch_id: int
    trade_date: date
    tickers: tuple[str, ...]
    estimated_requests: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "trade_date": self.trade_date.isoformat(),
            "tickers": list(self.tickers),
            "ticker_count": len(self.tickers),
            "estimated_requests": self.estimated_requests,
            "reason": self.reason,
        }


def build_stock_trade_backfill_plan(request: StockTradeBackfillRequest) -> dict[str, object]:
    _validate_request(request)
    tickers = tuple(sorted({ticker.upper() for ticker in request.tickers}))
    trading_days = _trading_days(request.start, request.end, recent_first=request.recent_first)
    coverage = stock_trade_coverage_states(
        request.trade_root,
        tickers=tickers,
        start=request.start,
        end=request.end,
    )
    batches = _batches(
        tickers=tickers,
        trading_days=trading_days,
        coverage=coverage,
        request=request,
    )
    selected_batches = (
        batches
        if request.max_batches is None
        else batches[: max(request.max_batches, 0)]
    )
    summary = _summary(
        tickers=tickers,
        trading_days=trading_days,
        coverage=coverage,
        batches=batches,
        selected_batches=selected_batches,
        request=request,
    )
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "window": {
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "trading_days": len(trading_days),
        },
        "trade_root": request.trade_root.as_posix(),
        "batch_size": request.batch_size,
        "recent_first": request.recent_first,
        "include_existing": request.include_existing,
        "summary": summary,
        "coverage_by_date": _coverage_by_date_rows(trading_days, tickers, coverage),
        "batches": [batch.as_dict() for batch in selected_batches],
        "deferred_batches": [batch.as_dict() for batch in batches[len(selected_batches) :]],
    }


def stock_trade_coverage(
    trade_root: Path,
    *,
    tickers: Sequence[str],
    start: date,
    end: date,
) -> dict[tuple[str, date], int]:
    normalized = {ticker.upper() for ticker in tickers}
    coverage: dict[tuple[str, date], int] = {}
    for ticker in sorted(normalized):
        for path in sorted((trade_root / f"ticker={ticker}").rglob("*.parquet")):
            try:
                frame = pd.read_parquet(path, columns=["ticker", "trade_date"])
            except Exception:
                continue
            if frame.empty:
                continue
            frame["ticker"] = frame["ticker"].astype(str).str.upper()
            frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
            filtered = frame[
                (frame["ticker"] == ticker)
                & (frame["trade_date"] >= start)
                & (frame["trade_date"] <= end)
            ]
            for trade_date, group in filtered.groupby("trade_date", dropna=True):
                if isinstance(trade_date, date):
                    coverage[(ticker, trade_date)] = coverage.get((ticker, trade_date), 0) + len(
                        group
                    )
    return coverage


def stock_trade_coverage_states(
    trade_root: Path,
    *,
    tickers: Sequence[str],
    start: date,
    end: date,
) -> dict[tuple[str, date], dict[str, object]]:
    row_counts = stock_trade_coverage(trade_root, tickers=tickers, start=start, end=end)
    metadata = load_stock_trade_coverage_metadata(trade_root)
    states: dict[tuple[str, date], dict[str, object]] = {}
    for ticker in sorted({item.upper() for item in tickers}):
        for trade_date in _trading_days(start, end, recent_first=False):
            rows = row_counts.get((ticker, trade_date), 0)
            meta = metadata.get(coverage_key(ticker, trade_date), {})
            meta_status = str(meta.get("coverage_status", "")).lower()
            complete = meta_status == "complete" or meta.get("complete") is True
            status = "complete" if complete else "partial" if rows > 0 else "missing"
            states[(ticker, trade_date)] = {
                "rows": rows,
                "status": status,
                "pages_downloaded": _int(meta.get("pages_downloaded")),
                "updated_at": str(meta.get("updated_at", "")),
            }
    return states


def write_stock_trade_backfill_plan(plan: Mapping[str, object], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "stock-trade-backfill-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "stock-trade-backfill-plan.md").write_text(
        stock_trade_backfill_plan_markdown(plan),
        encoding="utf-8",
    )


def stock_trade_backfill_plan_markdown(plan: Mapping[str, object]) -> str:
    summary = _mapping(plan.get("summary"))
    window = _mapping(plan.get("window"))
    lines = [
        "# T137 Massive Stock-Trade Backfill Plan",
        "",
        f"Generated at: `{plan.get('generated_at', 'unknown')}`",
        (
            "Window: "
            f"`{window.get('start', 'unknown')}` to `{window.get('end', 'unknown')}` "
            f"({window.get('trading_days', 0)} trading day(s))"
        ),
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Tickers | {summary.get('ticker_count', 0)} |",
        f"| Ticker-days expected | {summary.get('expected_ticker_days', 0)} |",
        f"| Ticker-days complete | {summary.get('covered_ticker_days', 0)} |",
        f"| Ticker-days partial | {summary.get('partial_ticker_days', 0)} |",
        f"| Ticker-days missing | {summary.get('missing_ticker_days', 0)} |",
        f"| Planned batches | {summary.get('planned_batch_count', 0)} |",
        f"| Deferred batches | {summary.get('deferred_batch_count', 0)} |",
        f"| Estimated requests | {summary.get('estimated_requests', 0)} |",
        "",
        "## Planned Batches",
        "",
        "| Batch | Date | Tickers | Estimated requests | Reason |",
        "| ---: | --- | ---: | ---: | --- |",
    ]
    batches = _mapping_rows(plan.get("batches"))
    if not batches:
        lines.append("| n/a | n/a | 0 | 0 | No missing ticker-days selected. |")
    for batch in batches:
        lines.append(
            "| "
            f"{batch.get('batch_id', 'n/a')} | {batch.get('trade_date', 'n/a')} | "
            f"{batch.get('ticker_count', 0)} | {batch.get('estimated_requests', 0)} | "
            f"{batch.get('reason', '')} |"
        )
    lines.extend(["", "## Coverage By Date", ""])
    lines.extend(
        [
            "| Date | Complete | Partial | Missing |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in _mapping_rows(plan.get("coverage_by_date")):
        lines.append(
            f"| {row.get('trade_date', 'n/a')} | "
            f"{row.get('covered_count', 0)} | {row.get('partial_count', 0)} | "
            f"{row.get('missing_count', 0)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_stock_trade_backfill_status(
    status: Mapping[str, object],
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "stock-trade-backfill-status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "stock-trade-backfill-status.md").write_text(
        stock_trade_backfill_status_markdown(status),
        encoding="utf-8",
    )


def stock_trade_backfill_status_markdown(status: Mapping[str, object]) -> str:
    summary = _mapping(status.get("summary"))
    progress = _mapping(status.get("current_progress"))
    lines = [
        "# T137 Massive Stock-Trade Backfill Status",
        "",
        f"Started at: `{status.get('started_at', 'unknown')}`",
        f"Finished at: `{status.get('finished_at', 'running')}`",
        f"Verdict: `{status.get('verdict', 'unknown')}`",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Planned batches | {summary.get('planned_batch_count', 0)} |",
        f"| Completed batches | {summary.get('completed_batch_count', 0)} |",
        f"| Partial batches | {summary.get('partial_batch_count', 0)} |",
        f"| Failed batches | {summary.get('failed_batch_count', 0)} |",
        f"| Deferred batches | {summary.get('deferred_batch_count', 0)} |",
        f"| Selected remaining batches | {summary.get('selected_remaining_batch_count', 0)} |",
        f"| Rows written | {summary.get('rows_written', 0)} |",
        f"| Issues | {summary.get('issue_count', 0)} |",
        f"| Initial complete ticker-days | {summary.get('initial_complete_ticker_days', 0)} |",
        f"| Initial partial ticker-days | {summary.get('initial_partial_ticker_days', 0)} |",
        f"| Initial missing ticker-days | {summary.get('initial_missing_ticker_days', 0)} |",
        f"| Resolved ticker-days | {summary.get('resolved_ticker_days', 0)} |",
        f"| Estimated remaining ticker-days | {summary.get('estimated_remaining_ticker_days', 0)} |",
    ]
    if progress:
        lines.extend(
            [
                "",
                "## Current Ticker-Day Progress",
                "",
                "| Ticker | Date | Pages | Rows | Status | Updated |",
                "| --- | --- | ---: | ---: | --- | --- |",
                (
                    f"| {progress.get('ticker', 'n/a')} | "
                    f"{progress.get('trade_date', 'n/a')} | "
                    f"{progress.get('pages_downloaded', 0)} | "
                    f"{progress.get('rows_downloaded', 0)} | "
                    f"{progress.get('status', 'running')} | "
                    f"{progress.get('updated_at', 'n/a')} |"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Batches",
            "",
            "| Batch | Date | Tickers | Rows | Status | Issue count |",
            "| ---: | --- | ---: | ---: | --- | ---: |",
        ]
    )
    for row in _mapping_rows(status.get("batches")):
        lines.append(
            "| "
            f"{row.get('batch_id', 'n/a')} | {row.get('trade_date', 'n/a')} | "
            f"{row.get('ticker_count', 0)} | {row.get('rows_written', 0)} | "
            f"{row.get('status', 'unknown')} | {row.get('issue_count', 0)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def backfill_status(
    *,
    plan: Mapping[str, object],
    started_at: datetime,
    finished_at: datetime | None,
    batch_results: Sequence[Mapping[str, object]],
    dry_run: bool = False,
    current_progress: Mapping[str, object] | None = None,
) -> dict[str, object]:
    status_counts = Counter(str(row.get("status", "unknown")) for row in batch_results)
    issue_count = sum(_int(row.get("issue_count")) for row in batch_results)
    rows_written = sum(_int(row.get("rows_written")) for row in batch_results)
    failed_count = status_counts.get("failed", 0)
    completed_count = status_counts.get("passed", 0)
    partial_count = status_counts.get("partial", 0)
    planned_count = len(_mapping_rows(plan.get("batches")))
    plan_summary = _mapping(plan.get("summary"))
    deferred_batch_count = _int(plan_summary.get("deferred_batch_count"))
    expected_ticker_days = _int(plan_summary.get("expected_ticker_days"))
    initial_complete = _int(plan_summary.get("covered_ticker_days"))
    initial_partial = _int(plan_summary.get("partial_ticker_days"))
    initial_missing = _int(plan_summary.get("missing_ticker_days"))
    resolved_ticker_days = sum(
        _int(row.get("ticker_day_count"))
        for row in batch_results
        if str(row.get("status")) == "passed"
    )
    selected_remaining = max(planned_count - completed_count - partial_count - failed_count, 0)
    estimated_remaining_ticker_days = max(
        initial_partial + initial_missing - resolved_ticker_days,
        0,
    )
    verdict = (
        "dry_run"
        if dry_run
        else "completed_with_failures"
        if failed_count
        else "partial"
        if partial_count or deferred_batch_count or selected_remaining or estimated_remaining_ticker_days
        else "completed"
        if completed_count == planned_count
        else "partial"
    )
    return {
        "schema_version": "0.1.0",
        "started_at": started_at.isoformat(),
        "finished_at": None if finished_at is None else finished_at.isoformat(),
        "verdict": verdict,
        "plan_summary": dict(plan_summary),
        "summary": {
            "planned_batch_count": planned_count,
            "completed_batch_count": completed_count,
            "partial_batch_count": partial_count,
            "failed_batch_count": failed_count,
            "deferred_batch_count": deferred_batch_count,
            "selected_remaining_batch_count": selected_remaining,
            "rows_written": rows_written,
            "issue_count": issue_count,
            "expected_ticker_days": expected_ticker_days,
            "initial_complete_ticker_days": initial_complete,
            "initial_partial_ticker_days": initial_partial,
            "initial_missing_ticker_days": initial_missing,
            "resolved_ticker_days": resolved_ticker_days,
            "estimated_remaining_ticker_days": estimated_remaining_ticker_days,
        },
        "current_progress": None if current_progress is None else dict(current_progress),
        "batches": [dict(row) for row in batch_results],
    }


def _batches(
    *,
    tickers: tuple[str, ...],
    trading_days: Sequence[date],
    coverage: Mapping[tuple[str, date], Mapping[str, object]],
    request: StockTradeBackfillRequest,
) -> list[StockTradeBackfillBatch]:
    rows: list[StockTradeBackfillBatch] = []
    batch_id = 1
    for trade_date in trading_days:
        missing = [
            ticker
            for ticker in tickers
            if request.include_existing
            or str(coverage.get((ticker, trade_date), {}).get("status", "missing")) != "complete"
        ]
        for chunk in _chunks(missing, request.batch_size):
            rows.append(
                StockTradeBackfillBatch(
                    batch_id=batch_id,
                    trade_date=trade_date,
                    tickers=tuple(chunk),
                    estimated_requests=len(chunk) * (request.max_pages_per_day or 1),
                    reason=_batch_reason(chunk, trade_date, coverage, request.include_existing),
                )
            )
            batch_id += 1
    return rows


def _summary(
    *,
    tickers: tuple[str, ...],
    trading_days: Sequence[date],
    coverage: Mapping[tuple[str, date], Mapping[str, object]],
    batches: Sequence[StockTradeBackfillBatch],
    selected_batches: Sequence[StockTradeBackfillBatch],
    request: StockTradeBackfillRequest,
) -> dict[str, object]:
    expected = len(tickers) * len(trading_days)
    covered = sum(
        1
        for key in _expected_keys(tickers, trading_days)
        if str(coverage.get(key, {}).get("status", "missing")) == "complete"
    )
    partial = sum(
        1
        for key in _expected_keys(tickers, trading_days)
        if str(coverage.get(key, {}).get("status", "missing")) == "partial"
    )
    selected_requests = sum(batch.estimated_requests for batch in selected_batches)
    return {
        "ticker_count": len(tickers),
        "trading_day_count": len(trading_days),
        "expected_ticker_days": expected,
        "covered_ticker_days": covered,
        "partial_ticker_days": partial,
        "missing_ticker_days": max(expected - covered - partial, 0),
        "planned_batch_count": len(selected_batches),
        "deferred_batch_count": max(len(batches) - len(selected_batches), 0),
        "estimated_requests": selected_requests,
        "max_pages_per_day": request.max_pages_per_day,
    }


def _coverage_by_date_rows(
    trading_days: Sequence[date],
    tickers: Sequence[str],
    coverage: Mapping[tuple[str, date], Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for trade_date in trading_days:
        covered = sum(
            1
            for ticker in tickers
            if str(coverage.get((ticker, trade_date), {}).get("status", "missing")) == "complete"
        )
        partial = sum(
            1
            for ticker in tickers
            if str(coverage.get((ticker, trade_date), {}).get("status", "missing")) == "partial"
        )
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "covered_count": covered,
                "partial_count": partial,
                "missing_count": max(len(tickers) - covered - partial, 0),
            }
        )
    return rows


def _expected_keys(
    tickers: Iterable[str],
    trading_days: Iterable[date],
) -> Iterable[tuple[str, date]]:
    for ticker in tickers:
        for trade_date in trading_days:
            yield (ticker, trade_date)


def _trading_days(start: date, end: date, *, recent_first: bool) -> list[date]:
    days = [
        pd.Timestamp(day).date()
        for day in pd.date_range(start, end, freq="D")
        if is_trading_day(pd.Timestamp(day).date())
    ]
    return sorted(days, reverse=recent_first)


def _chunks(values: Sequence[str], size: int) -> list[Sequence[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _batch_reason(
    tickers: Sequence[str],
    trade_date: date,
    coverage: Mapping[tuple[str, date], Mapping[str, object]],
    include_existing: bool,
) -> str:
    if include_existing:
        return "refresh existing ticker-day coverage"
    partial_count = sum(
        1
        for ticker in tickers
        if str(coverage.get((ticker, trade_date), {}).get("status", "missing")) == "partial"
    )
    if partial_count:
        return "partial ticker-day stock_trades coverage requires completion"
    return "missing ticker-day stock_trades partition coverage"


def _validate_request(request: StockTradeBackfillRequest) -> None:
    if request.end < request.start:
        raise ValueError("end must be on or after start")
    if request.batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if request.max_batches is not None and request.max_batches < 0:
        raise ValueError("max_batches must be >= 0")
    if not request.tickers:
        raise ValueError("tickers must not be empty")
    if request.max_pages_per_day is not None and request.max_pages_per_day < 1:
        raise ValueError("max_pages_per_day must be >= 1")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0
