from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sec.form4 import pull_form4

AAPL_CIK = "0000320193"


async def test_form4_puller_records_malformed_xml_issue(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifests" / "sec_form4.json"

    summary = await pull_form4(
        tickers=["AAPL"],
        client=_MalformedForm4Client(),
        data_root=tmp_path / "parquet" / "sec_form4",
        manifest_path=manifest_path,
        start=date(2022, 1, 1),
        end=date(2023, 1, 31),
        clock=_clock,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary.rows_written == 0
    assert summary.issues[0]["reason"] == "malformed Form 4 XML"
    assert manifest["issues"][0]["accession_number"] == "0000320193-22-000108"


async def test_form4_puller_normalizes_sec_xsl_document_path(tmp_path: Path) -> None:
    summary = await pull_form4(
        tickers=["AAPL"],
        client=_XslForm4Client(),
        data_root=tmp_path / "parquet" / "sec_form4",
        manifest_path=tmp_path / "manifests" / "sec_form4.json",
        start=date(2022, 1, 1),
        end=date(2023, 1, 31),
        clock=_clock,
    )

    assert summary.rows_written == 1
    assert summary.issues == []


class _BaseForm4Client:
    async def company_tickers(self) -> dict[str, Any]:
        return {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}

    async def submissions(self, cik: str) -> dict[str, Any]:
        assert cik == AAPL_CIK
        return _submissions_payload("form4.xml")


class _MalformedForm4Client(_BaseForm4Client):
    async def get_text(self, url: str) -> str:
        del url
        return "<ownershipDocument><bad></ownershipDocument>"


class _XslForm4Client(_BaseForm4Client):
    async def submissions(self, cik: str) -> dict[str, Any]:
        assert cik == AAPL_CIK
        return _submissions_payload("xslF345X05/form4.xml")

    async def get_text(self, url: str) -> str:
        if "xslF345X05" in url:
            return "<ownershipDocument><bad></ownershipDocument>"
        return _form4_xml()


def _submissions_payload(document: str) -> dict[str, Any]:
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-22-000108"],
                "filingDate": ["2022-11-10"],
                "reportDate": ["2022-11-10"],
                "form": ["4"],
                "primaryDocument": [document],
            }
        }
    }


def _form4_xml() -> str:
    return """
    <ownershipDocument><reportingOwner><reportingOwnerId><rptOwnerCik>0001</rptOwnerCik>
    <rptOwnerName>Example Insider</rptOwnerName></reportingOwnerId></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction>
      <transactionDate><value>2022-11-10</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>100</value></transactionShares>
      <transactionPricePerShare><value>150.50</value></transactionPricePerShare></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>
    """


def _clock() -> datetime:
    return datetime(2026, 5, 6, tzinfo=UTC)
