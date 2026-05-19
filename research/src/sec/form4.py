from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from xml.etree.ElementTree import ParseError

import httpx
import pandas as pd
from sec.cik import cik_lookup_for_tickers, parse_company_tickers
from sec.client import WWW_SEC_BASE
from sec.records import parse_date, parse_float, parse_int, provenance_columns
from sec.storage import write_manifest, write_partitioned_frame
from sec.submissions import FilingSummary, parse_recent_filings
from sec.xml import elements, first_text, parse_xml

from agency.provenance import FreshnessDomain, SourceTier, VerificationLevel, instrumented_call

DATASET = "sec_form4"


class Form4Client(Protocol):
    async def company_tickers(self) -> Mapping[str, Any]: ...

    async def submissions(self, cik: str) -> Mapping[str, Any]: ...

    async def get_text(self, url: str) -> str: ...


@dataclass(frozen=True)
class FormPullSummary:
    tickers_requested: int
    filings_seen: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_form4(
    *,
    tickers: list[str],
    client: Form4Client,
    data_root: Path,
    manifest_path: Path,
    start: date,
    end: date,
    clock: Callable[[], datetime] | None = None,
) -> FormPullSummary:
    get_now = clock or (lambda: datetime.now(UTC))
    cik_mapping = parse_company_tickers(await client.company_tickers())
    matched, missing = cik_lookup_for_tickers(tickers, cik_mapping)
    issues = [{"ticker": ticker, "reason": "missing CIK"} for ticker in missing]
    frames: list[pd.DataFrame] = []
    filings_seen = 0
    for ticker, ticker_cik in matched.items():
        try:
            submissions = await client.submissions(ticker_cik.cik)
        except httpx.HTTPError as exc:
            issue = _request_issue(
                ticker=ticker,
                detail=_http_error_detail(exc),
                reason=_http_error_reason(exc),
            )
            issues.append(issue)
            if _http_error_rate_limited(exc):
                break
            continue
        filings = parse_recent_filings(
            cik=ticker_cik.cik,
            payload=submissions,
            forms={"4", "4/A"},
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        filings_seen += len(filings)
        rate_limited = False
        for filing in filings:
            frame, issue = await _parse_filing(
                ticker=ticker,
                client=client,
                filing=filing,
                clock=get_now,
            )
            if issue is not None:
                issues.append(issue)
                if issue.get("reason") == "SEC request rate limited":
                    rate_limited = True
                    break
                continue
            if not frame.empty:
                frames.append(frame)
        if rate_limited:
            break

    rows_written = 0
    if frames:
        rows_written = write_partitioned_frame(
            data_root,
            pd.concat(frames, ignore_index=True),
            partition_column="ticker",
            filename="form4.parquet",
            unique_columns=["ticker", "accession_number", "filer_cik", "transaction_date"],
        )
    write_manifest(
        manifest_path,
        data_root,
        dataset=DATASET,
        fetched_at=get_now(),
        source_url=WWW_SEC_BASE,
        issues=issues,
    )
    return FormPullSummary(len(tickers), filings_seen, rows_written, issues)


async def _parse_filing(
    *,
    ticker: str,
    client: Form4Client,
    filing: FilingSummary,
    clock: Callable[[], datetime],
) -> tuple[pd.DataFrame, dict[str, str] | None]:
    normalized_filing = _normalized_filing(filing)
    try:
        xml = await _fetch_filing_xml(client, normalized_filing, clock)
    except httpx.HTTPError as exc:
        return (
            pd.DataFrame(),
            _filing_issue(
                ticker=ticker,
                filing=normalized_filing,
                detail=_http_error_detail(exc),
                reason=_http_error_reason(exc),
            ),
        )
    try:
        return (
            parse_form4_xml(
                ticker=ticker,
                filing=normalized_filing,
                xml=xml,
                fetched_at=clock(),
            ),
            None,
        )
    except ParseError as exc:
        return (
            pd.DataFrame(),
            _filing_issue(ticker=ticker, filing=normalized_filing, detail=str(exc)),
        )


def _normalized_filing(filing: FilingSummary) -> FilingSummary:
    document_name = PurePosixPath(filing.primary_document).name
    if document_name == filing.primary_document:
        return filing
    return replace(filing, primary_document=document_name)


def _request_issue(
    *,
    ticker: str,
    detail: str,
    reason: str = "SEC submissions request failed",
) -> dict[str, str]:
    return {
        "ticker": ticker,
        "reason": reason,
        "detail": detail,
        "source_url": WWW_SEC_BASE,
    }


def _filing_issue(
    *,
    ticker: str,
    filing: FilingSummary,
    detail: str,
    reason: str = "malformed Form 4 XML",
) -> dict[str, str]:
    return {
        "ticker": ticker,
        "accession_number": filing.accession_number,
        "primary_document": filing.primary_document,
        "reason": reason,
        "detail": detail,
        "source_url": filing.document_url,
    }


def _http_error_reason(exc: httpx.HTTPError) -> str:
    if _http_error_rate_limited(exc):
        return "SEC request rate limited"
    status_code = _http_status_code(exc)
    if status_code is not None:
        return f"SEC request failed with HTTP {status_code}"
    return "SEC request failed"


def _http_error_detail(exc: httpx.HTTPError) -> str:
    status_code = _http_status_code(exc)
    if status_code is not None:
        return f"HTTP {status_code}: {exc}"
    return str(exc)


def _http_status_code(exc: httpx.HTTPError) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return int(status_code) if isinstance(status_code, int) else None


def _http_error_rate_limited(exc: httpx.HTTPError) -> bool:
    return _http_status_code(exc) == httpx.codes.TOO_MANY_REQUESTS


def parse_form4_xml(
    *,
    ticker: str,
    filing: FilingSummary,
    xml: str,
    fetched_at: datetime,
) -> pd.DataFrame:
    root = parse_xml(xml)
    owner_cik = first_text(root, ("reportingOwner", "reportingOwnerId", "rptOwnerCik"))
    owner_name = first_text(root, ("reportingOwner", "reportingOwnerId", "rptOwnerName"))
    filing_date = parse_date(filing.filing_date)
    if filing_date is None:
        return pd.DataFrame()
    rows = [
        row
        for transaction in elements(root, "nonDerivativeTransaction")
        if (
            row := _transaction_row(
                ticker=ticker,
                filing=filing,
                transaction=transaction,
                filing_date=filing_date,
                fetched_at=fetched_at,
                owner_cik=owner_cik,
                owner_name=owner_name,
            )
        )
        is not None
    ]
    return pd.DataFrame(rows)


async def _fetch_filing_xml(
    client: Form4Client,
    filing: FilingSummary,
    clock: Callable[[], datetime],
) -> str:
    async def call() -> str:
        return await client.get_text(filing.document_url)

    wrapped = await instrumented_call(
        call,
        source="sec_edgar",
        source_tier=SourceTier.OFFICIAL_FILING,
        source_id=f"form4:{filing.accession_number}",
        verification_level=VerificationLevel.CONFIRMED,
        freshness_domain=FreshnessDomain.SEC_FORM4,
        timestamp_as_of=clock(),
        confidence=1.0,
        source_url=filing.document_url,
        clock=clock,
    )
    return wrapped.value


def _transaction_row(
    *,
    ticker: str,
    filing: FilingSummary,
    transaction: Any,
    filing_date: date,
    fetched_at: datetime,
    owner_cik: str | None,
    owner_name: str | None,
) -> dict[str, object] | None:
    transaction_date = parse_date(first_text(transaction, ("transactionDate", "value")))
    transaction_type = first_text(transaction, ("transactionCoding", "transactionCode"))
    shares = parse_float(
        first_text(transaction, ("transactionAmounts", "transactionShares", "value"))
    )
    if transaction_date is None or transaction_type is None or shares is None:
        return None
    source_id = f"sec:{ticker}:form4:{filing.accession_number}:{transaction_date.isoformat()}"
    return {
        "ticker": ticker.upper(),
        "issuer_cik": filing.cik,
        "filer_cik": owner_cik,
        "filer_name": owner_name,
        "accession_number": filing.accession_number,
        "transaction_date": transaction_date,
        "filing_date": filing_date,
        "transaction_type": transaction_type,
        "shares": shares,
        "price": parse_float(
            first_text(transaction, ("transactionAmounts", "transactionPricePerShare", "value"))
        ),
        "ownership_after": parse_int(
            first_text(
                transaction,
                ("postTransactionAmounts", "sharesOwnedFollowingTransaction", "value"),
            )
        ),
        **provenance_columns(
            source_id=source_id,
            source_url=filing.document_url,
            filing_date=filing_date,
            fetched_at=fetched_at,
        ),
    }
