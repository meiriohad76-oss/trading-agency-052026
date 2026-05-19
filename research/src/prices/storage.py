from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
from prices.sector_etfs import covered_sector_etfs

PRICE_COLUMNS = [
    "ticker",
    "year",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividend",
    "split_factor",
    "source",
    "fetched_at",
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


def missing_ranges_for_ticker(
    price_root: Path,
    ticker: str,
    requested: DateRange,
    *,
    refresh: bool = False,
) -> list[DateRange]:
    if refresh:
        return [requested]
    existing_dates = existing_dates_for_ticker(price_root, ticker)
    if not existing_dates:
        return [requested]
    existing_start = min(existing_dates)
    existing_end = max(existing_dates)
    if requested.start < existing_start or requested.end > existing_end:
        edge_ranges = []
        if requested.start < existing_start:
            edge_ranges.append(
                DateRange(
                    requested.start,
                    min(requested.end, existing_start - timedelta(days=1)),
                )
            )
        if requested.end > existing_end:
            edge_ranges.append(
                DateRange(
                    max(requested.start, existing_end + timedelta(days=1)),
                    requested.end,
                )
            )
        return [item for item in edge_ranges if item.start <= item.end]
    ranges: list[DateRange] = []
    current_start: date | None = None
    current = requested.start
    while current <= requested.end:
        if current not in existing_dates:
            current_start = current if current_start is None else current_start
        elif current_start is not None:
            ranges.append(DateRange(current_start, current - timedelta(days=1)))
            current_start = None
        current += timedelta(days=1)
    if current_start is not None:
        ranges.append(DateRange(current_start, requested.end))
    return ranges


def existing_date_bounds(price_root: Path, ticker: str) -> tuple[date, date] | None:
    dates = existing_dates_for_ticker(price_root, ticker)
    if not dates:
        return None
    return min(dates), max(dates)


def existing_dates_for_ticker(price_root: Path, ticker: str) -> set[date]:
    frames: list[pd.DataFrame] = []
    for path in _ticker_files(price_root, ticker):
        frame = pd.read_parquet(path, columns=["date"])
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return set()
    dates = pd.to_datetime(pd.concat(frames, ignore_index=True)["date"]).dt.date
    return set(dates)


def write_price_frame(price_root: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    written = 0
    for _, group in frame.groupby(["ticker", "year"]):
        ticker = str(group["ticker"].iat[0])
        year = _partition_year(group["year"].iat[0])
        path = _partition_path(price_root, ticker, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        output = group[PRICE_COLUMNS].copy()
        previous_keys: set[tuple[str, date]] = set()
        if path.exists():
            existing = pd.read_parquet(path)
            previous_keys = _price_keys(existing)
            output = pd.concat([existing, output], ignore_index=True)
        output = (
            output.drop_duplicates(subset=["ticker", "date"], keep="last")
            .sort_values(["ticker", "date"])
            .reset_index(drop=True)
        )
        output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
        written += len(_price_keys(output) - previous_keys)
    return written


def write_empty_sentinel(price_root: Path, ticker: str) -> Path:
    path = _partition_path(price_root, ticker, 0).with_name("empty.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=PRICE_COLUMNS).to_parquet(
        path,
        engine="pyarrow",
        compression="snappy",
        index=False,
    )
    return path


def write_manifest(
    manifest_path: Path,
    price_root: Path,
    *,
    fetched_at: datetime,
    requested: DateRange,
    issues: list[dict[str, str]],
    source: str = "yfinance",
    source_url: str = "https://finance.yahoo.com",
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _price_stats(price_root)
    tickers = _price_tickers(price_root)
    sources = _price_sources(price_root)
    manifest = {
        "dataset": "prices_daily",
        "path": price_root.name,
        "schema_version": 1,
        "row_count": stats["row_count"],
        "checksum": _tree_checksum(price_root),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": "2099-01-01T00:00:00+00:00",
        "source_url": source_url,
        "source": _manifest_source(sources, source),
        "sources": sources or [source],
        "ticker_count": stats["ticker_count"],
        "tickers": tickers,
        "sector_etfs": covered_sector_etfs(tickers),
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


def _price_stats(price_root: Path) -> dict[str, str | int]:
    frames: list[pd.DataFrame] = []
    for path in sorted(price_root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["ticker", "timestamp_as_of"])
        if not frame.empty:
            frames.append(frame)
    if not frames:
        now = datetime.now(UTC).isoformat()
        return {"row_count": 0, "ticker_count": 0, "max_timestamp_as_of": now}
    combined = pd.concat(frames, ignore_index=True)
    max_date = pd.to_datetime(combined["timestamp_as_of"]).max().to_pydatetime()
    if max_date.tzinfo is None or max_date.utcoffset() is None:
        max_date = max_date.replace(tzinfo=UTC)
    return {
        "row_count": len(combined),
        "ticker_count": int(combined["ticker"].nunique()),
        "max_timestamp_as_of": max_date.isoformat(),
    }


def _price_tickers(price_root: Path) -> list[str]:
    tickers: set[str] = set()
    for path in sorted(price_root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["ticker"])
        if not frame.empty:
            tickers.update(str(ticker).upper() for ticker in frame["ticker"].unique())
    return sorted(tickers)


def _price_sources(price_root: Path) -> list[str]:
    sources: set[str] = set()
    for path in sorted(price_root.rglob("*.parquet")):
        frame = pd.read_parquet(path, columns=["source"])
        if not frame.empty:
            sources.update(str(source) for source in frame["source"].dropna().unique())
    return sorted(sources)


def _manifest_source(sources: list[str], fallback: str) -> str:
    if len(sources) == 1:
        return sources[0]
    if len(sources) > 1:
        return "mixed"
    return fallback


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.parquet")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _ticker_files(price_root: Path, ticker: str) -> list[Path]:
    return sorted((price_root / f"ticker={ticker.upper()}").rglob("*.parquet"))


def _price_keys(frame: pd.DataFrame) -> set[tuple[str, date]]:
    if frame.empty:
        return set()
    dates = pd.to_datetime(frame["date"]).dt.date
    return {
        (str(ticker).upper(), observed)
        for ticker, observed in zip(frame["ticker"], dates, strict=False)
    }


def _partition_year(value: object) -> int:
    if isinstance(value, int | str | bytes | bytearray):
        return int(value)
    if isinstance(value, float):
        return int(value)
    return int(str(value))


def _partition_path(price_root: Path, ticker: str, year: int) -> Path:
    return price_root / f"ticker={ticker.upper()}" / f"year={year}" / "prices.parquet"
