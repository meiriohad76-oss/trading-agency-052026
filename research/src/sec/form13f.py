from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from sec.client import WWW_SEC_BASE, archive_url
from sec.form13f_documents import fetch_document, info_table_documents
from sec.records import parse_date, parse_float, parse_int, provenance_columns
from sec.storage import write_manifest, write_partitioned_frame
from sec.submissions import FilingSummary, parse_recent_filings
from sec.xml import elements, first_text, parse_xml

DATASET = "sec_13f"


class Form13FClient(Protocol):
    async def submissions(self, cik: str) -> Mapping[str, Any]: ...

    async def get_text(self, url: str) -> str: ...

    async def filing_index(self, cik: str, accession_number: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class Form13FPullSummary:
    filers_requested: int
    filings_seen: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_form13f(
    *,
    filer_ciks: list[str],
    client: Form13FClient,
    data_root: Path,
    manifest_path: Path,
    start: date,
    end: date,
    cusip_to_ticker: Mapping[str, str],
    clock: Callable[[], datetime] | None = None,
) -> Form13FPullSummary:
    get_now = clock or (lambda: datetime.now(UTC))
    frames: list[pd.DataFrame] = []
    issues: list[dict[str, str]] = []
    filings_seen = 0
    for cik in filer_ciks:
        submissions = await client.submissions(cik)
        filings = parse_recent_filings(
            cik=cik,
            payload=submissions,
            forms={"13F-HR", "13F-HR/A"},
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        filings_seen += len(filings)
        for filing in filings:
            documents = await info_table_documents(client, filing)
            if not documents:
                issues.append(
                    {
                        "cik": cik,
                        "reason": f"no 13F information table for {filing.accession_number}",
                    }
                )
            for document in documents:
                xml = await fetch_document(client, filing, document, get_now)
                frame = parse_13f_xml(
                    filing=filing,
                    document=document,
                    xml=xml,
                    fetched_at=get_now(),
                    cusip_to_ticker=cusip_to_ticker,
                )
                if not frame.empty:
                    frames.append(frame)

    rows_written = 0
    if frames:
        combined = _with_quarter_changes(pd.concat(frames, ignore_index=True))
        rows_written = write_partitioned_frame(
            data_root,
            combined,
            partition_column="quarter",
            filename="holdings.parquet",
            unique_columns=["ticker", "filer_cik", "quarter_end_date", "accession_number", "cusip"],
        )
    write_manifest(
        manifest_path,
        data_root,
        dataset=DATASET,
        fetched_at=get_now(),
        source_url=WWW_SEC_BASE,
        issues=issues,
    )
    return Form13FPullSummary(len(filer_ciks), filings_seen, rows_written, issues)


def parse_13f_xml(
    *,
    filing: FilingSummary,
    document: str,
    xml: str,
    fetched_at: datetime,
    cusip_to_ticker: Mapping[str, str],
) -> pd.DataFrame:
    root = parse_xml(xml)
    filing_date = parse_date(filing.filing_date)
    quarter_end = parse_date(filing.report_date)
    if filing_date is None or quarter_end is None:
        return pd.DataFrame()
    rows = [
        row
        for info_table in elements(root, "infoTable")
        if (
            row := _holding_row(
                filing=filing,
                document=document,
                info_table=info_table,
                filing_date=filing_date,
                quarter_end=quarter_end,
                fetched_at=fetched_at,
                cusip_to_ticker=cusip_to_ticker,
            )
        )
        is not None
    ]
    return pd.DataFrame(rows)


def _holding_row(
    *,
    filing: FilingSummary,
    document: str,
    info_table: Any,
    filing_date: date,
    quarter_end: date,
    fetched_at: datetime,
    cusip_to_ticker: Mapping[str, str],
) -> dict[str, object] | None:
    cusip = first_text(info_table, ("cusip",))
    if cusip is None:
        return None
    ticker = cusip_to_ticker.get(cusip.upper())
    if ticker is None:
        warnings.warn(
            f"cusip_not_mapped: CUSIP {cusip.upper()!r} not found in cusip_map"
            f" (filing_date={filing_date})",
            category=UserWarning,
            stacklevel=2,
        )
        return None
    source_url = archive_url(filing.cik, filing.accession_number, document)
    source_id = f"sec:13f:{filing.accession_number}:{cusip}"
    shares_held = parse_int(first_text(info_table, ("shrsOrPrnAmt", "sshPrnamt")))
    if shares_held is None:
        return None
    return {
        "ticker": ticker.upper(),
        "filer_cik": filing.cik,
        "filer_name": first_text(info_table, ("nameOfIssuer",)),
        "cusip": cusip.upper(),
        "quarter": _quarter_label(quarter_end),
        "quarter_end_date": quarter_end,
        "filing_date": filing_date,
        "accession_number": filing.accession_number,
        "shares_held": shares_held,
        "value_usd_thousands": parse_float(first_text(info_table, ("value",))),
        "change_from_prev_quarter": 0,
        **provenance_columns(
            source_id=source_id,
            source_url=source_url,
            filing_date=filing_date,
            fetched_at=fetched_at,
        ),
    }


def _with_quarter_changes(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.sort_values(["ticker", "filer_cik", "quarter_end_date"]).copy()
    output["change_from_prev_quarter"] = (
        output.groupby(["ticker", "filer_cik"])["shares_held"].diff().fillna(0).astype("int64")
    )
    return output


def _quarter_label(value: date) -> str:
    quarter = ((value.month - 1) // 3) + 1
    return f"{value.year}Q{quarter}"
