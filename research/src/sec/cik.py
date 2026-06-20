from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sec.records import cik_string


@dataclass(frozen=True)
class TickerCik:
    ticker: str
    cik: str
    title: str


def parse_company_tickers(payload: Mapping[str, Any]) -> dict[str, TickerCik]:
    mapping: dict[str, TickerCik] = {}
    for raw in payload.values():
        if not isinstance(raw, Mapping):
            continue
        ticker = normalize_ticker(raw.get("ticker"))
        cik_raw = raw.get("cik_str")
        title_raw = raw.get("title")
        if ticker is None or cik_raw is None or title_raw is None:
            continue
        mapping[ticker] = TickerCik(
            ticker=ticker,
            cik=cik_string(str(cik_raw)),
            title=str(title_raw),
        )
    return mapping


def universe_tickers(
    path: Path,
    *,
    as_of: date | None = None,
    active_only: bool = True,
) -> list[str]:
    columns = ["ticker"]
    if active_only:
        columns.extend(["start_date", "end_date"])
    try:
        frame = pd.read_parquet(path, columns=columns)
    except (ValueError, KeyError):
        if active_only:
            frame = pd.read_parquet(path, columns=["ticker"])
        else:
            raise
    if active_only and {"start_date", "end_date"}.issubset(frame.columns):
        current = pd.Timestamp(as_of or date.today())
        start = pd.to_datetime(frame["start_date"], errors="coerce")
        end = pd.to_datetime(frame["end_date"], errors="coerce")
        frame = frame[(start <= current) & (end.isna() | (end > current))]
    return sorted(
        ticker
        for raw in frame["ticker"].dropna().unique()
        if (ticker := normalize_ticker(raw)) is not None
    )


def cik_lookup_for_tickers(
    tickers: list[str],
    mapping: Mapping[str, TickerCik],
) -> tuple[dict[str, TickerCik], list[str]]:
    matched: dict[str, TickerCik] = {}
    missing: list[str] = []
    for ticker in tickers:
        normalized = normalize_ticker(ticker)
        if normalized is None:
            continue
        if normalized in mapping:
            matched[normalized] = mapping[normalized]
        else:
            missing.append(normalized)
    return matched, sorted(missing)


def normalize_ticker(value: object) -> str | None:
    if value is None:
        return None
    ticker = str(value).strip().upper().replace(".", "-")
    return ticker or None
