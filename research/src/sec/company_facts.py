from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import pandas as pd
from sec.cik import cik_lookup_for_tickers, parse_company_tickers
from sec.client import DATA_SEC_BASE
from sec.company_facts_parser import parse_company_facts
from sec.storage import write_manifest, write_partitioned_frame, write_raw_json

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, instrumented_call

DATASET = "sec_company_facts"


class CompanyFactsClient(Protocol):
    async def company_tickers(self) -> Mapping[str, Any]: ...

    async def company_facts(self, cik: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SecPullSummary:
    tickers_requested: int
    tickers_matched: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_company_facts(
    *,
    tickers: list[str],
    client: CompanyFactsClient,
    raw_root: Path,
    data_root: Path,
    manifest_path: Path,
    refresh: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> SecPullSummary:
    get_now = clock or (lambda: datetime.now(UTC))
    cik_mapping = parse_company_tickers(await client.company_tickers())
    matched, missing = cik_lookup_for_tickers(tickers, cik_mapping)
    issues = [{"ticker": ticker, "reason": "missing CIK"} for ticker in missing]
    frames: list[pd.DataFrame] = []
    for ticker, ticker_cik in matched.items():
        fetched_at = get_now()
        payload = await _cached_or_fetch(
            client,
            raw_root / f"CIK{ticker_cik.cik}.json",
            ticker=ticker,
            cik=ticker_cik.cik,
            refresh=refresh,
            clock=get_now,
        )
        source_url = f"{DATA_SEC_BASE}/api/xbrl/companyfacts/CIK{ticker_cik.cik}.json"
        frame = parse_company_facts(
            ticker=ticker,
            cik=ticker_cik.cik,
            payload=payload,
            fetched_at=fetched_at,
            source_url=source_url,
        )
        if frame.empty:
            issues.append({"ticker": ticker, "reason": "no company facts parsed"})
            continue
        frames.append(frame)

    rows_written = 0
    if frames:
        rows_written = write_partitioned_frame(
            data_root,
            pd.concat(frames, ignore_index=True),
            partition_column="ticker",
            filename="facts.parquet",
            unique_columns=["ticker", "metric", "period_end", "accession_number"],
        )
    write_manifest(
        manifest_path,
        data_root,
        dataset=DATASET,
        fetched_at=get_now(),
        source_url=DATA_SEC_BASE,
        issues=issues,
    )
    return SecPullSummary(len(tickers), len(matched), rows_written, issues)

async def _cached_or_fetch(
    client: CompanyFactsClient,
    path: Path,
    *,
    ticker: str,
    cik: str,
    refresh: bool,
    clock: Callable[[], datetime],
) -> Mapping[str, Any]:
    if path.is_file() and not refresh:
        return cast(Mapping[str, Any], json.loads(path.read_text(encoding="utf-8")))

    async def call() -> Mapping[str, Any]:
        return await client.company_facts(cik)

    wrapped = await instrumented_call(
        call,
        source="sec_edgar",
        source_tier=SourceTier.OFFICIAL_FILING,
        source_id=f"companyfacts:{ticker}:{cik}",
        verification_level=VerificationLevel.CONFIRMED,
        freshness_domain=FreshnessDomain.SEC_FUNDAMENTALS,
        timestamp_as_of=clock(),
        confidence=1.0,
        source_url=f"{DATA_SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json",
        clock=clock,
    )
    write_raw_json(path, wrapped.value)
    return wrapped.value
