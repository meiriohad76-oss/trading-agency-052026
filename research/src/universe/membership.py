from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from universe.checks import validate_membership
from universe.manifest import write_manifest

BASE_DATE = date(2019, 1, 1)
STALE_AFTER = "2099-01-01T00:00:00+00:00"
PROVENANCE = {
    "source": "universe-membership-reconstruction",
    "source_tier": "PROVIDER_NEWS",
    "freshness": "FRESH",
    "confidence": 0.85,
    "verification_level": "CONFIRMED",
}


@dataclass(frozen=True)
class BuildOutputs:
    parquet_path: Path
    manifest_path: Path
    row_count: int
    checksum: str


@dataclass(frozen=True)
class ChangeEvent:
    effective_date: date
    added_ticker: str | None
    removed_ticker: str | None
    as_of_source: str


def build_universe_membership(
    *,
    source_dir: Path,
    parquet_path: Path,
    manifest_path: Path,
) -> BuildOutputs:
    from universe.sources import (  # noqa: PLC0415 - avoids a tiny type/import cycle.
        _nasdaq100_current,
        _nasdaq100_events,
        _sp100_current,
        _sp100_events,
    )

    metadata = _load_metadata(source_dir)
    fetched_at = _parse_datetime(str(metadata["fetched_at"]))
    rows = [
        *_build_index_rows(
            index_name="SP100",
            current_tickers=_sp100_current(source_dir / "sp100.html"),
            events=_sp100_events(source_dir / "sp100_manual_events.csv"),
            fetched_at=fetched_at,
        ),
        *_build_index_rows(
            index_name="NASDAQ100",
            current_tickers=_nasdaq100_current(source_dir / "nasdaq100.html"),
            events=_nasdaq100_events(source_dir / "nasdaq100.html"),
            fetched_at=fetched_at,
        ),
    ]
    frame = pd.DataFrame(rows).sort_values(["index_name", "ticker", "start_date", "end_date"])
    validate_membership(frame)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, engine="pyarrow", compression="snappy", index=False)
    checksum = _sha256(parquet_path)
    write_manifest(
        manifest_path,
        parquet_path,
        frame,
        metadata,
        checksum,
        fetched_at,
        base_date=BASE_DATE,
        stale_after=STALE_AFTER,
        coverage_end=date(2026, 5, 6),
    )
    return BuildOutputs(
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        row_count=len(frame),
        checksum=checksum,
    )

def _build_index_rows(
    *,
    index_name: str,
    current_tickers: Iterable[str],
    events: Iterable[ChangeEvent],
    fetched_at: datetime,
) -> list[dict[str, object]]:
    active: dict[str, dict[str, object]] = {
        ticker: _open_interval(ticker, index_name, fetched_at, f"{index_name}:current")
        for ticker in sorted(set(current_tickers))
    }
    rows: list[dict[str, object]] = []
    for event in sorted(events, key=lambda item: item.effective_date, reverse=True):
        if event.added_ticker in active:
            added = active.pop(str(event.added_ticker))
            added["start_date"] = event.effective_date
            added["as_of_source"] = event.as_of_source
            added["timestamp_as_of"] = event.effective_date
            rows.append(added)
        if event.removed_ticker:
            active[event.removed_ticker] = _open_interval(
                event.removed_ticker,
                index_name,
                fetched_at,
                event.as_of_source,
                end_date=event.effective_date,
            )
    for interval in active.values():
        interval["start_date"] = BASE_DATE
        interval["timestamp_as_of"] = BASE_DATE
        rows.append(interval)
    return [_clip_row(row) for row in rows if _is_in_coverage(row)]


def _open_interval(
    ticker: str,
    index_name: str,
    fetched_at: datetime,
    source: str,
    *,
    end_date: date | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "index_name": index_name,
        "start_date": BASE_DATE,
        "end_date": end_date,
        "as_of_source": source,
        "source_fetched_at": fetched_at,
        "source_id": f"{index_name}:{ticker}",
        "source_url": source if source.startswith("http") else None,
        "timestamp_observed": fetched_at,
        "timestamp_as_of": BASE_DATE,
        **PROVENANCE,
    }


def _clip_row(row: dict[str, object]) -> dict[str, object]:
    start_date = cast(date, row["start_date"])
    if start_date < BASE_DATE:
        row["start_date"] = BASE_DATE
        row["timestamp_as_of"] = BASE_DATE
    return row


def _is_in_coverage(row: Mapping[str, object]) -> bool:
    end_date = cast(date | None, row["end_date"])
    return end_date is None or end_date > BASE_DATE

def _load_metadata(source_dir: Path) -> dict[str, object]:
    path = source_dir / "source_snapshot.json"
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("source snapshot fetched_at must include timezone")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
