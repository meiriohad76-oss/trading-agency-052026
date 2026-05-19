from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from sec.form4 import pull_form4
from sec.storage import write_partitioned_frame


async def test_pull_form4_records_rate_limit_issue_and_continues(tmp_path: Path) -> None:
    client = _RateLimitedForm4Client()

    summary = await pull_form4(
        tickers=["AAPL", "MSFT"],
        client=client,
        data_root=tmp_path / "sec_form4",
        manifest_path=tmp_path / "sec_form4.json",
        start=date(2026, 5, 1),
        end=date(2026, 5, 15),
        clock=lambda: datetime(2026, 5, 16, tzinfo=UTC),
    )

    assert summary.tickers_requested == 2
    assert summary.filings_seen == 0
    assert summary.rows_written == 0
    assert any(issue["ticker"] == "AAPL" for issue in summary.issues)
    assert any("HTTP 429" in issue["detail"] for issue in summary.issues)
    assert (tmp_path / "sec_form4.json").is_file()
    assert client.submission_ciks == ["0000320193"]


def test_sec_partition_writer_quarantines_corrupt_existing_parquet(tmp_path: Path) -> None:
    root = tmp_path / "sec_form4"
    corrupt_path = root / "ticker=AAPL" / "form4.parquet"
    corrupt_path.parent.mkdir(parents=True)
    corrupt_path.write_text("not parquet", encoding="utf-8")

    rows_written = write_partitioned_frame(
        root,
        pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "accession_number": "0000320193-26-000001",
                    "filer_cik": "0000320193",
                    "transaction_date": "2026-05-15",
                    "timestamp_as_of": "2026-05-15T00:00:00Z",
                }
            ]
        ),
        partition_column="ticker",
        filename="form4.parquet",
        unique_columns=["ticker", "accession_number", "filer_cik", "transaction_date"],
    )

    stored = pd.read_parquet(corrupt_path)
    quarantined = list(corrupt_path.parent.glob("form4.parquet.corrupt-*"))
    assert rows_written == 1
    assert stored["accession_number"].to_list() == ["0000320193-26-000001"]
    assert len(quarantined) == 1


class _RateLimitedForm4Client:
    def __init__(self) -> None:
        self.submission_ciks: list[str] = []

    async def company_tickers(self) -> dict[str, dict[str, object]]:
        return {
            "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
            "1": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp."},
        }

    async def submissions(self, cik: str) -> dict[str, Any]:
        self.submission_ciks.append(cik)
        if cik == "0000320193":
            request = httpx.Request(
                "GET",
                "https://data.sec.gov/submissions/CIK0000320193.json",
            )
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError(
                "SEC rate limit",
                request=request,
                response=response,
            )
        return {
            "filings": {
                "recent": {
                    "accessionNumber": [],
                    "filingDate": [],
                    "reportDate": [],
                    "form": [],
                    "primaryDocument": [],
                }
            }
        }

    async def get_text(self, url: str) -> str:
        raise AssertionError(f"unexpected fetch: {url}")
