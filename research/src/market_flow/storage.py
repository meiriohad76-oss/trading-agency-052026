from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.lib as pa_lib

STOCK_TRADE_COLUMNS = [
    "ticker",
    "year",
    "trade_date",
    "trade_ts",
    "participant_timestamp",
    "sip_timestamp",
    "trf_timestamp",
    "price",
    "size",
    "notional",
    "exchange",
    "conditions",
    "correction",
    "trade_id",
    "sequence_number",
    "tape",
    "trf_id",
    "is_trf_off_exchange",
    "trf_venue",
    "session",
    "eligible",
    "direction",
    "signed_volume",
    "signed_notional",
    "is_off_exchange",
    "is_block_trade",
    "source",
    "source_tier",
    "source_id",
    "source_url",
    "timestamp_observed",
    "timestamp_as_of",
    "freshness",
    "confidence",
    "verification_level",
]
COVERAGE_METADATA_FILENAME = "_coverage.json"


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


def write_stock_trade_frame(root: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    written = 0
    for _, group in frame.groupby(["ticker", "year"]):
        ticker = str(group["ticker"].iat[0]).upper()
        year = int(str(group["year"].iat[0]))
        path = _partition_path(root, ticker, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        output = _stock_trade_output(group)
        previous_count = 0
        if path.exists():
            try:
                existing = pd.read_parquet(path)
            except pa_lib.ArrowException, ValueError:
                _quarantine_corrupt_partition(path)
            else:
                previous_count = len(existing)
                output = pd.concat([existing, output], ignore_index=True)
        output = (
            output.drop_duplicates(subset=["source_id"], keep="last")
            .sort_values(["ticker", "trade_ts", "sequence_number", "source_id"])
            .reset_index(drop=True)
        )
        output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
        written += max(0, len(output) - previous_count)
    return written


def _stock_trade_output(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    defaults: dict[str, object] = {
        "is_trf_off_exchange": False,
        "trf_venue": "",
    }
    for column in STOCK_TRADE_COLUMNS:
        if column not in output.columns:
            output[column] = defaults.get(column)
    return output[STOCK_TRADE_COLUMNS].copy()


def _quarantine_corrupt_partition(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    counter = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{stamp}-{counter}")
        counter += 1
    path.replace(target)
    return target


def write_manifest(
    manifest_path: Path,
    trade_root: Path,
    *,
    fetched_at: datetime,
    requested: DateRange,
    issues: list[dict[str, str]],
    source_url: str,
    rows_written_delta: int | None = None,
    touched_tickers: Sequence[str] = (),
    incremental: bool = False,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    previous = _read_manifest(manifest_path)
    if incremental and previous:
        manifest = _incremental_manifest(
            previous,
            fetched_at=fetched_at,
            requested=requested,
            issues=issues,
            source_url=source_url,
            path=trade_root.name,
            rows_written_delta=rows_written_delta or 0,
            touched_tickers=touched_tickers,
        )
    else:
        stats = _stats(trade_root)
        manifest = {
            "dataset": "stock_trades",
            "path": trade_root.name,
            "schema_version": 1,
            "row_count": stats["row_count"],
            "checksum": _tree_checksum(trade_root),
            "fetched_at": fetched_at.isoformat(),
            "max_timestamp_as_of": stats["max_timestamp_as_of"],
            "stale_after": "2099-01-01T00:00:00+00:00",
            "source_url": source_url,
            "source": "massive",
            "ticker_count": stats["ticker_count"],
            "tickers": _tickers(trade_root),
            "date_range": {
                "start": str(stats.get("min_trade_date") or requested.start.isoformat()),
                "end": str(stats.get("max_trade_date") or requested.end.isoformat()),
            },
            "issues": issues,
        }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_stock_trade_coverage_metadata(root: Path) -> dict[str, dict[str, Any]]:
    path = root / COVERAGE_METADATA_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    rows = payload.get("ticker_days", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(rows, Mapping):
        return {}
    return {str(key): dict(value) for key, value in rows.items() if isinstance(value, Mapping)}


def update_stock_trade_coverage_metadata(
    root: Path,
    entries: Sequence[Mapping[str, Any]],
) -> None:
    if not entries:
        return
    root.mkdir(parents=True, exist_ok=True)
    path = root / COVERAGE_METADATA_FILENAME
    ticker_days = load_stock_trade_coverage_metadata(root)
    updated_at = datetime.now(UTC).isoformat()
    for entry in entries:
        ticker = str(entry.get("ticker", "")).upper().strip()
        trade_date = str(entry.get("trade_date", "")).strip()
        if not ticker or not trade_date:
            continue
        key = coverage_key(ticker, trade_date)
        previous = ticker_days.get(key, {})
        normalized = {str(field): value for field, value in entry.items()}
        if _preserve_complete_coverage(previous, normalized):
            normalized = _complete_preserving_update(previous, normalized, updated_at)
        ticker_days[key] = {
            **previous,
            **normalized,
            "ticker": ticker,
            "trade_date": trade_date,
            "updated_at": updated_at,
        }
    output = {
        "schema_version": "0.1.0",
        "updated_at": updated_at,
        "ticker_days": ticker_days,
    }
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def coverage_key(ticker: str, trade_date: str | date) -> str:
    return f"{ticker.upper()}|{trade_date}"


def _preserve_complete_coverage(
    previous: Mapping[str, Any],
    update: Mapping[str, Any],
) -> bool:
    previous_complete = (
        str(previous.get("coverage_status", "")).lower() == "complete"
        or previous.get("complete") is True
    )
    update_complete = (
        str(update.get("coverage_status", "")).lower() == "complete"
        or update.get("complete") is True
    )
    return previous_complete and not update_complete


def _complete_preserving_update(
    previous: Mapping[str, Any],
    update: Mapping[str, Any],
    updated_at: str,
) -> dict[str, Any]:
    preserved = dict(update)
    preserved["coverage_status"] = "complete"
    preserved["complete"] = True
    preserved["full_depth_preserved_after_latest_slice"] = True
    preserved["latest_slice_coverage_status"] = update.get("coverage_status")
    preserved["latest_slice_downloaded_row_count"] = update.get("downloaded_row_count")
    preserved["latest_slice_pages_downloaded"] = update.get("pages_downloaded")
    preserved["latest_slice_order"] = update.get("order")
    preserved["latest_slice_stop_reason"] = update.get("stop_reason")
    preserved["latest_slice_updated_at"] = updated_at
    preserved["downloaded_row_count"] = previous.get("downloaded_row_count")
    preserved["rows_written"] = previous.get("rows_written")
    preserved["pages_downloaded"] = previous.get("pages_downloaded")
    preserved["row_count_verified"] = previous.get("row_count_verified", True)
    preserved["resume_cursor"] = None
    return preserved


def _read_manifest(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _incremental_manifest(
    previous: Mapping[str, Any],
    *,
    fetched_at: datetime,
    requested: DateRange,
    issues: list[dict[str, str]],
    source_url: str,
    path: str,
    rows_written_delta: int,
    touched_tickers: Sequence[str],
) -> dict[str, object]:
    tickers = sorted(
        {
            *[str(ticker).upper() for ticker in _manifest_tickers(previous) if str(ticker).strip()],
            *[ticker.upper() for ticker in touched_tickers if ticker.strip()],
        }
    )
    previous_range = previous.get("date_range", {})
    if not isinstance(previous_range, Mapping):
        previous_range = {}
    start = min(
        str(previous_range.get("start") or requested.start.isoformat()),
        requested.start.isoformat(),
    )
    end = max(
        str(previous_range.get("end") or requested.end.isoformat()),
        requested.end.isoformat(),
    )
    row_count = _manifest_int(previous.get("row_count")) + max(rows_written_delta, 0)
    return {
        "dataset": "stock_trades",
        "path": path,
        "schema_version": 1,
        "row_count": row_count,
        "checksum": _incremental_checksum(previous, fetched_at, row_count, tickers),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": fetched_at.isoformat(),
        "stale_after": "2099-01-01T00:00:00+00:00",
        "source_url": source_url,
        "source": "massive",
        "ticker_count": len(tickers),
        "tickers": tickers,
        "date_range": {"start": start, "end": end},
        "issues": issues,
    }


def _incremental_checksum(
    previous: Mapping[str, Any],
    fetched_at: datetime,
    row_count: int,
    tickers: Sequence[str],
) -> str:
    payload = {
        "previous_checksum": previous.get("checksum"),
        "fetched_at": fetched_at.isoformat(),
        "row_count": row_count,
        "tickers": list(tickers),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _manifest_tickers(previous: Mapping[str, Any]) -> list[object]:
    value = previous.get("tickers", [])
    return value if isinstance(value, list) else []


def _stats(root: Path) -> dict[str, int | str | None]:
    frames: list[pd.DataFrame] = []
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["ticker", "timestamp_as_of", "trade_date"])
        if not frame.empty:
            frames.append(frame)
    if not frames:
        now = datetime.now(UTC).isoformat()
        return {
            "row_count": 0,
            "ticker_count": 0,
            "max_timestamp_as_of": now,
            "min_trade_date": None,
            "max_trade_date": None,
        }
    combined = pd.concat(frames, ignore_index=True)
    max_date = pd.to_datetime(combined["timestamp_as_of"], utc=True).max()
    trade_dates = pd.to_datetime(combined["trade_date"], errors="coerce").dropna()
    return {
        "row_count": len(combined),
        "ticker_count": int(combined["ticker"].nunique()),
        "max_timestamp_as_of": max_date.isoformat(),
        "min_trade_date": trade_dates.min().date().isoformat() if not trade_dates.empty else None,
        "max_trade_date": trade_dates.max().date().isoformat() if not trade_dates.empty else None,
    }


def _tickers(root: Path) -> list[str]:
    tickers: set[str] = set()
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["ticker"])
        if not frame.empty:
            tickers.update(str(ticker).upper() for ticker in frame["ticker"].unique())
    return sorted(tickers)


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.parquet")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _partition_path(root: Path, ticker: str, year: int) -> Path:
    return root / f"ticker={ticker}" / f"year={year}" / "trades.parquet"
