from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from prices.storage import (
    DateRange,
    existing_date_bounds,
    missing_ranges_for_ticker,
    write_empty_sentinel,
    write_manifest,
    write_price_frame,
)
from prices.types import Downloader, HistoryNormalizer
from prices.yfinance_daily import normalize_history, yfinance_downloader


@dataclass(frozen=True)
class PullSummary:
    tickers_requested: int
    ranges_downloaded: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_prices(
    *,
    tickers: list[str],
    requested: DateRange,
    price_root: Path,
    manifest_path: Path,
    refresh: bool = False,
    workers: int = 1,
    downloader: Downloader = yfinance_downloader,
    normalizer: HistoryNormalizer = normalize_history,
    source: str = "yfinance",
    source_url: str = "https://finance.yahoo.com",
    clock: Callable[[], datetime] | None = None,
) -> PullSummary:
    get_now = clock or (lambda: datetime.now(UTC))
    issues: list[dict[str, str]] = []
    ranges_downloaded = 0
    rows_written = 0
    semaphore = asyncio.Semaphore(_worker_count(workers))
    normalized_tickers = sorted({ticker.upper() for ticker in tickers})

    async def pull_one(ticker: str) -> None:
        nonlocal ranges_downloaded, rows_written
        ranges = missing_ranges_for_ticker(price_root, ticker, requested, refresh=refresh)
        for missing in ranges:
            try:
                async with semaphore:
                    raw = await downloader(ticker, missing)
                ranges_downloaded += 1
                normalized = normalizer(ticker, raw, fetched_at=get_now())
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    {
                        "ticker": ticker,
                        "reason": "download_or_parse_failed",
                        "detail": _issue_detail(exc),
                    }
                )
                continue
            if normalized.empty:
                if existing_date_bounds(price_root, ticker) is not None:
                    continue
                write_empty_sentinel(price_root, ticker)
                issues.append({"ticker": ticker, "reason": "no rows returned"})
                continue
            rows_written += write_price_frame(price_root, normalized)

    await asyncio.gather(*(pull_one(ticker) for ticker in normalized_tickers))
    write_manifest(
        manifest_path,
        price_root,
        fetched_at=get_now(),
        requested=requested,
        issues=issues,
        source=source,
        source_url=source_url,
    )
    return PullSummary(
        tickers_requested=len(normalized_tickers),
        ranges_downloaded=ranges_downloaded,
        rows_written=rows_written,
        issues=issues,
    )


def universe_tickers(path: Path) -> list[str]:
    frame = pd.read_parquet(path, columns=["ticker"])
    return sorted(str(ticker).upper() for ticker in frame["ticker"].dropna().unique())


def _worker_count(workers: int) -> int:
    if workers < 1:
        raise ValueError("workers must be >= 1")
    return min(workers, 4)


def _issue_detail(exc: Exception) -> str:
    detail = str(exc) or exc.__class__.__name__
    return detail[:240]
