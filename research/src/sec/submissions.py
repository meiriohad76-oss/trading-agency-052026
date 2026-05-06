from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sec.client import archive_url
from sec.records import parse_date


@dataclass(frozen=True)
class FilingSummary:
    cik: str
    accession_number: str
    filing_date: str
    report_date: str | None
    form: str
    primary_document: str

    @property
    def document_url(self) -> str:
        return archive_url(self.cik, self.accession_number, self.primary_document)


def parse_recent_filings(
    *,
    cik: str,
    payload: Mapping[str, Any],
    forms: set[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[FilingSummary]:
    recent = payload.get("filings")
    if not isinstance(recent, Mapping):
        return []
    columns = recent.get("recent")
    if not isinstance(columns, Mapping):
        return []
    accessions = _list_column(columns, "accessionNumber")
    filing_dates = _list_column(columns, "filingDate")
    report_dates = _list_column(columns, "reportDate")
    form_values = _list_column(columns, "form")
    documents = _list_column(columns, "primaryDocument")
    rows: list[FilingSummary] = []
    for index, accession in enumerate(accessions):
        form = _at(form_values, index)
        filing_date = _at(filing_dates, index)
        document = _at(documents, index)
        if form not in forms or filing_date is None or document is None:
            continue
        if not _inside_window(filing_date, start_date, end_date):
            continue
        rows.append(
            FilingSummary(
                cik=cik,
                accession_number=str(accession),
                filing_date=filing_date,
                report_date=_at(report_dates, index),
                form=form,
                primary_document=document,
            )
        )
    return rows


def _inside_window(value: str, start_date: str | None, end_date: str | None) -> bool:
    parsed = parse_date(value)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if parsed is None:
        return False
    if start is not None and parsed < start:
        return False
    return not (end is not None and parsed > end)


def _list_column(columns: Mapping[str, object], key: str) -> list[object]:
    value = columns.get(key)
    return value if isinstance(value, list) else []


def _at(values: list[object], index: int) -> str | None:
    if index >= len(values) or values[index] in (None, ""):
        return None
    return str(values[index])
