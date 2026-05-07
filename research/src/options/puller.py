from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from options.storage import write_manifest, write_options_frame
from options.yfinance_options import Downloader, normalize_options, yfinance_options_downloader


@dataclass(frozen=True)
class OptionsPullSummary:
    tickers_requested: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_option_chains(
    *,
    tickers: list[str],
    data_root: Path,
    manifest_path: Path,
    downloader: Downloader = yfinance_options_downloader,
    clock: Callable[[], datetime] | None = None,
) -> OptionsPullSummary:
    get_now = clock or (lambda: datetime.now(UTC))
    fetched_at = get_now()
    issues: list[dict[str, str]] = []
    frames: list[pd.DataFrame] = []
    for ticker in sorted({item.upper() for item in tickers}):
        try:
            raw = await downloader(ticker)
        except Exception as exc:
            issues.append({"ticker": ticker, "reason": str(exc)})
            continue
        normalized = normalize_options(ticker, raw, fetched_at=fetched_at)
        if normalized.empty:
            issues.append({"ticker": ticker, "reason": "no option rows returned"})
            continue
        frames.append(normalized)
    rows_written = 0
    if frames:
        rows_written = write_options_frame(data_root, pd.concat(frames, ignore_index=True))
    write_manifest(manifest_path, data_root, fetched_at=fetched_at)
    return OptionsPullSummary(len(set(tickers)), rows_written, issues)
