from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from data_refresh.massive_lane_manifest import (  # noqa: E402
    manifest_path_for_lane,
    read_lane_manifest,
    write_lane_manifest,
)

DEFAULT_TRADE_ROOT = ROOT / "research" / "data" / "parquet" / "stock_trades"
DEFAULT_OUTPUT_ROOT = ROOT / "research" / "data" / "parquet" / "massive_block_trade_feed"
DEFAULT_SOURCE_LANE_MANIFEST = manifest_path_for_lane(ROOT, "massive_live_trade_slices")
DEFAULT_PROGRESS_PATH = (
    ROOT
    / "research"
    / "results"
    / "latest-data-refresh"
    / "massive_block_trade_feed-progress.json"
)
BLOCK_TRADE_LANE_ID = "massive_block_trade_feed"
SOURCE_LIVE_SLICE_LANE_ID = "massive_live_trade_slices"


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    _validate_lane_invocation(args)
    source_manifest = read_lane_manifest(_resolve(args.source_lane_manifest))
    tickers = _selected_tickers(args.ticker, source_manifest)
    progress = BlockFeedProgressWriter(
        path=_resolve(args.progress_path),
        lane_id=args.lane_id,
        tickers=tickers,
        start=args.start,
        end=args.end,
    )
    progress.mark_started()
    if not source_manifest:
        reason = "source Massive live-trade lane manifest is missing"
        progress.fail(reason)
        _write_blocked_manifest(args, tickers, reason=reason)
        print(json.dumps({"status": "blocked", "reason": reason}, sort_keys=True))
        return 2
    source_problem = _source_manifest_problem(source_manifest, args)
    if source_problem:
        progress.fail(source_problem)
        _write_blocked_manifest(args, tickers, reason=source_problem)
        print(json.dumps({"status": "blocked", "reason": source_problem}, sort_keys=True))
        return 2
    if not tickers:
        reason = "no tickers selected for block-trade derivation"
        progress.fail(reason)
        _write_blocked_manifest(args, tickers, reason=reason)
        print(json.dumps({"status": "blocked", "reason": reason}, sort_keys=True))
        return 2

    coverage = _coverage_from_source(source_manifest, tickers, start=args.start, end=args.end)
    trade_frame = _read_trade_frame(
        _resolve(args.trade_root),
        tickers=tickers,
        start=args.start,
        end=args.end,
    )
    focus_frame = _focus_trade_frame(trade_frame)
    rows_written = _write_focus_frame(_resolve(args.output_root), focus_frame)
    fetched_at = datetime.now(UTC)
    issues = _coverage_issues(coverage)
    status = _coverage_status(coverage, issues)
    manifest_path = _resolve(args.lane_manifest_path) if args.lane_manifest_path else manifest_path_for_lane(ROOT, args.lane_id)
    write_lane_manifest(
        manifest_path,
        lane_id=args.lane_id,
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=fetched_at,
        requested_start=args.start,
        requested_end=args.end,
        tickers=tickers,
        row_count=rows_written,
        source_manifest=_resolve(args.source_lane_manifest),
        status=status,
        issues=issues,
        coverage=coverage,
        coverage_pct=_coverage_pct(coverage),
        request_budget_label="0 Massive requests; derived from massive_live_trade_slices",
    )
    progress.complete(rows_written=rows_written, issues=issues)
    summary = {
        "status": status,
        "lane_id": args.lane_id,
        "ticker_count": len(tickers),
        "rows_written": rows_written,
        "issue_count": len(issues),
        "manifest_path": str(manifest_path),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if not issues else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive the Massive block-trade lane from live trade slices."
    )
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--ticker", action="append", help="Ticker to derive; repeatable.")
    parser.add_argument("--lane-id", default=BLOCK_TRADE_LANE_ID)
    parser.add_argument("--trade-root", type=Path, default=DEFAULT_TRADE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--source-lane-manifest", type=Path, default=DEFAULT_SOURCE_LANE_MANIFEST)
    parser.add_argument("--lane-manifest-path", type=Path)
    parser.add_argument("--progress-path", type=Path, default=DEFAULT_PROGRESS_PATH)
    return parser.parse_args()


def _validate_lane_invocation(args: argparse.Namespace) -> None:
    if str(args.lane_id or "") != BLOCK_TRADE_LANE_ID:
        raise SystemExit(
            "derive_massive_block_trade_feed.py may only write the "
            "massive_block_trade_feed lane manifest."
        )


def _source_manifest_problem(
    source_manifest: Mapping[str, object],
    args: argparse.Namespace,
) -> str:
    lane_id = str(source_manifest.get("lane_id") or "")
    if lane_id != SOURCE_LIVE_SLICE_LANE_ID:
        return (
            "block-trade derivation requires a massive_live_trade_slices source "
            f"manifest; got {lane_id or 'unknown'}."
        )
    dataset = str(source_manifest.get("raw_source_dataset") or source_manifest.get("dataset") or "")
    if dataset != "stock_trades":
        return (
            "block-trade derivation requires stock_trades source data; "
            f"got {dataset or 'unknown'}."
        )
    window = source_manifest.get("window")
    if not isinstance(window, Mapping):
        return "source live-trade lane manifest has no recorded window."
    if str(window.get("start") or "") != args.start.isoformat() or str(
        window.get("end") or ""
    ) != args.end.isoformat():
        return (
            "source live-trade lane manifest window does not match the requested "
            f"derivation window {args.start.isoformat()} to {args.end.isoformat()}."
        )
    return ""


def _selected_tickers(
    requested: Sequence[str] | None,
    source_manifest: Mapping[str, object],
) -> tuple[str, ...]:
    if requested:
        return _normalize_tickers(requested)
    values = source_manifest.get("tickers")
    if isinstance(values, list):
        return _normalize_tickers(str(value) for value in values)
    return ()


def _coverage_from_source(
    source_manifest: Mapping[str, object],
    tickers: Sequence[str],
    *,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    coverage_rows = [
        dict(row)
        for row in _sequence_mappings(source_manifest.get("coverage"))
        if _date_in_window(row.get("trade_date"), start=start, end=end)
    ]
    by_ticker: dict[str, dict[str, object]] = {
        str(row.get("ticker") or "").upper(): row
        for row in coverage_rows
        if str(row.get("ticker") or "").strip()
    }
    result: list[dict[str, object]] = []
    for ticker in tickers:
        source_row = by_ticker.get(ticker.upper())
        status = str(
            (source_row or {}).get("coverage_status")
            or (source_row or {}).get("status")
            or ""
        ).lower()
        source_complete = bool(source_row) and _source_coverage_complete(source_row)
        usable = bool(source_row) and _source_coverage_usable(source_row)
        coverage_status = (
            "complete" if source_complete else "partial_usable" if usable else "failed"
        )
        result.append(
            {
                "ticker": ticker.upper(),
                "trade_date": start.isoformat() if start == end else f"{start.isoformat()}..{end.isoformat()}",
                "coverage_status": coverage_status,
                "complete": source_complete,
                "usable_for_live_pipeline": usable,
                "source_lane_status": status or "missing",
                "source_complete": source_complete,
                "source_row_count_verified": (source_row or {}).get("row_count_verified"),
                "source_rows_downloaded": (source_row or {}).get("downloaded_row_count"),
                "source_pages_downloaded": (source_row or {}).get("pages_downloaded"),
                "source_fetched_at": (source_row or {}).get("fetched_at")
                or source_manifest.get("fetched_at"),
            }
        )
    return result


def _source_coverage_usable(source_row: Mapping[str, object] | None) -> bool:
    if not source_row:
        return False
    status = str(
        source_row.get("coverage_status") or source_row.get("status") or ""
    ).lower()
    if _source_coverage_complete(source_row) or status in {"ready", "usable", "partial_usable"}:
        return True
    if status != "partial":
        return False
    rows = _int_value(
        source_row.get("downloaded_row_count"),
        _int_value(source_row.get("rows_written"), 0),
    )
    pages = _int_value(source_row.get("pages_downloaded"), 0)
    return rows > 0 and pages > 0 and str(source_row.get("order") or "").lower() == "desc"


def _source_coverage_complete(source_row: Mapping[str, object] | None) -> bool:
    if not source_row:
        return False
    status = str(
        source_row.get("coverage_status") or source_row.get("status") or ""
    ).lower()
    if not (source_row.get("complete") is True or status == "complete"):
        return False
    return source_row.get("row_count_verified") is not False


def _read_trade_frame(
    trade_root: Path,
    *,
    tickers: Sequence[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        for year in range(start.year, end.year + 1):
            path = trade_root / f"ticker={ticker.upper()}" / f"year={year}" / "trades.parquet"
            if not path.is_file():
                continue
            frame = pd.read_parquet(path)
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined["ticker"] = combined["ticker"].astype(str).str.upper()
    combined["trade_date"] = pd.to_datetime(combined["trade_date"], errors="coerce").dt.date
    selected = {ticker.upper() for ticker in tickers}
    return combined[
        combined["ticker"].isin(selected)
        & (combined["trade_date"] >= start)
        & (combined["trade_date"] <= end)
    ].copy()


def _focus_trade_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    output = frame.copy()
    block = _bool_series(output, "is_block_trade")
    off_exchange = _bool_series(output, "is_off_exchange")
    return output[block | off_exchange].copy().reset_index(drop=True)


def _write_focus_frame(root: Path, frame: pd.DataFrame) -> int:
    root.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        return 0
    written = 0
    output = frame.copy()
    if "year" not in output.columns:
        output["year"] = pd.to_datetime(output["trade_date"], errors="coerce").dt.year
    for _, group in output.groupby(["ticker", "year"]):
        ticker = str(group["ticker"].iat[0]).upper()
        year = int(str(group["year"].iat[0]))
        path = root / f"ticker={ticker}" / f"year={year}" / "block_trades.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = group.copy()
        previous_count = 0
        if path.is_file():
            existing = pd.read_parquet(path)
            previous_count = len(existing)
            merged = pd.concat([existing, merged], ignore_index=True)
        dedupe_columns = [
            column
            for column in ("source_id", "trade_id", "sequence_number", "trade_ts")
            if column in merged.columns
        ]
        if dedupe_columns:
            merged = merged.drop_duplicates(subset=dedupe_columns, keep="last")
        merged = merged.sort_values(
            [column for column in ("ticker", "trade_ts", "sequence_number") if column in merged.columns]
        ).reset_index(drop=True)
        merged.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
        written += max(0, len(merged) - previous_count)
    return written


def _write_blocked_manifest(
    args: argparse.Namespace,
    tickers: Sequence[str],
    *,
    reason: str,
) -> None:
    manifest_path = _resolve(args.lane_manifest_path) if args.lane_manifest_path else manifest_path_for_lane(ROOT, args.lane_id)
    write_lane_manifest(
        manifest_path,
        lane_id=args.lane_id,
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=datetime.now(UTC),
        requested_start=args.start,
        requested_end=args.end,
        tickers=tickers,
        row_count=0,
        source_manifest=_resolve(args.source_lane_manifest),
        status="blocked",
        issues=[{"reason": reason}],
        coverage=[],
        coverage_pct=0,
        request_budget_label="0 Massive requests; derived from massive_live_trade_slices",
    )


def _coverage_issues(coverage: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "ticker": str(row.get("ticker") or "unknown"),
            "trade_date": str(row.get("trade_date") or "unknown"),
            "reason": "source live-trade slice was not usable",
        }
        for row in coverage
        if row.get("usable_for_live_pipeline") is not True
    ]


def _coverage_pct(coverage: Sequence[Mapping[str, object]]) -> int:
    if not coverage:
        return 0
    usable = sum(1 for row in coverage if row.get("usable_for_live_pipeline") is True)
    return round(usable / len(coverage) * 100)


def _coverage_status(
    coverage: Sequence[Mapping[str, object]],
    issues: Sequence[Mapping[str, str]],
) -> str:
    if issues or not coverage:
        return "partial"
    complete = sum(1 for row in coverage if row.get("complete") is True)
    usable = sum(1 for row in coverage if row.get("usable_for_live_pipeline") is True)
    if complete == len(coverage):
        return "complete"
    if usable:
        return "partial_usable"
    return "partial"


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([False for _ in range(len(frame))], index=frame.index)
    return frame[column].map(_bool_value).fillna(False).astype(bool)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and pd.isna(value):
            return False
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "t", "yes", "y"}
    return False


def _int_value(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    return fallback


def _date_in_window(value: object, *, start: date, end: date) -> bool:
    if value is None:
        return start == end
    text = str(value).strip()
    if ".." in text:
        first, _, last = text.partition("..")
        return first <= end.isoformat() and last >= start.isoformat()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return False
    return start <= parsed <= end


def _sequence_mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _normalize_tickers(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value).upper().strip() for value in values if str(value).strip()}))


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _date(value: str) -> date:
    return date.fromisoformat(value)


class BlockFeedProgressWriter:
    def __init__(
        self,
        *,
        path: Path,
        lane_id: str,
        tickers: Sequence[str],
        start: date,
        end: date,
    ) -> None:
        self.path = path
        self.lane_id = lane_id
        self.tickers = tuple(tickers)
        self.start = start
        self.end = end
        self.started_at = datetime.now(UTC).isoformat()

    def mark_started(self) -> None:
        self._write(state="running", status="deriving")

    def complete(self, *, rows_written: int, issues: Sequence[Mapping[str, object]]) -> None:
        state = "complete" if not issues else "partial"
        self._write(
            state=state,
            status=state,
            rows_written=rows_written,
            issue_count=len(issues),
            issues=issues,
        )

    def fail(self, reason: str) -> None:
        self._write(state="failed", status="failed", reason=reason, issue_count=1)

    def _write(
        self,
        *,
        state: str,
        status: str,
        rows_written: int = 0,
        issue_count: int = 0,
        issues: Sequence[Mapping[str, object]] = (),
        reason: str | None = None,
    ) -> None:
        payload = {
            "schema_version": "0.1.0",
            "lane_id": self.lane_id,
            "state": state,
            "status": status,
            "started_at": self.started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "ticker_count": len(self.tickers),
            "ticker_days_total": len(self.tickers),
            "ticker_days_completed": len(self.tickers) if state == "complete" else 0,
            "ticker_days_processed": len(self.tickers) if state in {"complete", "partial"} else 0,
            "percent_complete": 100 if state == "complete" else 0,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "rows_written": rows_written,
            "issues": [dict(issue) for issue in issues],
            "issue_count": issue_count,
            "reason": reason,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
