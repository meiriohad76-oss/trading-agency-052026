from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

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
        output = group[STOCK_TRADE_COLUMNS].copy()
        if path.exists():
            output = pd.concat([pd.read_parquet(path), output], ignore_index=True)
        output = (
            output.drop_duplicates(subset=["source_id"], keep="last")
            .sort_values(["ticker", "trade_ts", "sequence_number", "source_id"])
            .reset_index(drop=True)
        )
        output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
        written += len(group)
    return written


def write_manifest(
    manifest_path: Path,
    trade_root: Path,
    *,
    fetched_at: datetime,
    requested: DateRange,
    issues: list[dict[str, str]],
    source_url: str,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
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
            "start": requested.start.isoformat(),
            "end": requested.end.isoformat(),
        },
        "issues": issues,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _stats(root: Path) -> dict[str, int | str]:
    frames: list[pd.DataFrame] = []
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["ticker", "timestamp_as_of"])
        if not frame.empty:
            frames.append(frame)
    if not frames:
        now = datetime.now(UTC).isoformat()
        return {"row_count": 0, "ticker_count": 0, "max_timestamp_as_of": now}
    combined = pd.concat(frames, ignore_index=True)
    max_date = pd.to_datetime(combined["timestamp_as_of"], utc=True).max().to_pydatetime()
    return {
        "row_count": len(combined),
        "ticker_count": int(combined["ticker"].nunique()),
        "max_timestamp_as_of": max_date.isoformat(),
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
