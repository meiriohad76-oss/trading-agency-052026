from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sec.filing_monitor import FilingCheckpoint, FilingMonitor

FORMS_OF_INTEREST = {"8-K", "10-Q", "10-K", "SC 13D"}


def _submissions_payload(filings: list[dict]) -> dict:
    """Build a fake EDGAR submissions API response."""
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [f["accession"] for f in filings],
                "filingDate":     [f["date"] for f in filings],
                "reportDate":     [f.get("report_date", f["date"]) for f in filings],
                "form":           [f["form"] for f in filings],
                "primaryDocument": [f.get("doc", "filing.htm") for f in filings],
            }
        },
    }


def test_check_new_filings_returns_filings_since_date() -> None:
    client = MagicMock()
    client.submissions = AsyncMock(return_value=_submissions_payload([
        {"accession": "0001-new-8k",  "date": "2024-11-05", "form": "8-K"},
        {"accession": "0002-old-10q", "date": "2024-09-15", "form": "10-Q"},  # before cutoff
    ]))

    monitor = FilingMonitor(
        client=client,
        cik_map={"AAPL": "0000320193"},
    )
    results = asyncio.run(monitor.check_new_filings(["AAPL"], since=date(2024, 11, 1)))

    assert len(results) == 1
    assert results[0].accession_number == "0001-new-8k"
    assert results[0].form == "8-K"
    assert results[0].ticker == "AAPL"


def test_filters_to_forms_of_interest() -> None:
    client = MagicMock()
    client.submissions = AsyncMock(return_value=_submissions_payload([
        {"accession": "0001-10q",  "date": "2024-11-01", "form": "10-Q"},
        {"accession": "0002-s1",   "date": "2024-11-02", "form": "S-1"},   # not of interest
        {"accession": "0003-13d",  "date": "2024-11-03", "form": "SC 13D"},
    ]))

    monitor = FilingMonitor(client=client, cik_map={"AAPL": "0000320193"})
    results = asyncio.run(monitor.check_new_filings(["AAPL"], since=date(2024, 10, 1)))

    forms = {r.form for r in results}
    assert "S-1" not in forms
    assert "10-Q" in forms
    assert "SC 13D" in forms


def test_checkpoint_is_written_and_read(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    cp = FilingCheckpoint(path=checkpoint_path)

    cp.save(date(2024, 11, 15))
    loaded = cp.load()

    assert loaded == date(2024, 11, 15)


def test_returns_empty_when_no_cik_mapping() -> None:
    client = MagicMock()
    monitor = FilingMonitor(client=client, cik_map={})

    results = asyncio.run(monitor.check_new_filings(["UNKNOWN"], since=date(2024, 1, 1)))

    assert results == []
    client.submissions.assert_not_called()
