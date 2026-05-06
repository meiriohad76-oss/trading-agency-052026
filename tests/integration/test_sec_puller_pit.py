from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pit.loader import PITLoader
from sec.company_facts import pull_company_facts
from sec.form4 import pull_form4
from sec.form13f import pull_form13f

AAPL_REVENUE_Q4_2022 = 90_146_000_000.0
AAPL_13F_SHARES = 1_000
AAPL_CIK = "0000320193"
FILER_CIK = "0001067983"
AAPL_CUSIP = "037833100"


async def test_sec_pullers_write_pit_readable_datasets(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    raw_root = tmp_path / "raw"
    client = _FakeSecClient()

    def clock() -> datetime:
        return datetime(2026, 5, 6, tzinfo=UTC)

    await pull_company_facts(
        tickers=["AAPL"],
        client=client,
        raw_root=raw_root,
        data_root=parquet_root / "sec_company_facts",
        manifest_path=manifest_root / "sec_company_facts.json",
        clock=clock,
    )
    await pull_form4(
        tickers=["AAPL"],
        client=client,
        data_root=parquet_root / "sec_form4",
        manifest_path=manifest_root / "sec_form4.json",
        start=date(2022, 1, 1),
        end=date(2023, 1, 31),
        clock=clock,
    )
    await pull_form13f(
        filer_ciks=[FILER_CIK],
        client=client,
        data_root=parquet_root / "sec_13f",
        manifest_path=manifest_root / "sec_13f.json",
        start=date(2022, 1, 1),
        end=date(2023, 2, 28),
        cusip_to_ticker={AAPL_CUSIP: "AAPL"},
        clock=clock,
    )

    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=lambda: date(2026, 5, 6),
    )

    fundamentals = loader.fundamentals("AAPL", date(2022, 12, 31))
    insiders = loader.insider_transactions("AAPL", date(2023, 1, 15), lookback_days=90)
    holdings = loader.institutional_holdings("AAPL", date(2023, 2, 28))

    assert fundamentals.value["revenue"] == AAPL_REVENUE_Q4_2022
    assert insiders[0].value["transaction_type"] == "P"
    assert holdings.value["total_shares_held"] == AAPL_13F_SHARES


class _FakeSecClient:
    async def company_tickers(self) -> dict[str, Any]:
        return {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}

    async def company_facts(self, cik: str) -> dict[str, Any]:
        assert cik == AAPL_CIK
        return _company_facts_payload()

    async def submissions(self, cik: str) -> dict[str, Any]:
        if cik == AAPL_CIK:
            return _submissions_payload("4", "form4.xml", "2022-11-10", "2022-11-10")
        return _submissions_payload("13F-HR", "primary.xml", "2023-02-14", "2022-12-31")

    async def filing_index(self, cik: str, accession_number: str) -> dict[str, Any]:
        assert cik == FILER_CIK
        assert accession_number == "0001067983-23-000010"
        return {
            "directory": {
                "item": [{"name": "infotable.xml", "type": "INFORMATION TABLE"}]
            }
        }

    async def get_text(self, url: str) -> str:
        if "infotable" in url:
            return _form13f_xml()
        return _form4_xml()


def _submissions_payload(
    form: str,
    document: str,
    filing_date: str,
    report_date: str,
) -> dict[str, Any]:
    accession = "0001067983-23-000010" if form == "13F-HR" else "0000320193-22-000108"
    return {
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": [filing_date],
                "reportDate": [report_date],
                "form": [form],
                "primaryDocument": [document],
            }
        }
    }


def _company_facts_payload() -> dict[str, Any]:
    base = {
        "start": "2022-06-26",
        "end": "2022-09-24",
        "accn": "0000320193-22-000108",
        "fy": 2022,
        "fp": "Q4",
        "form": "10-K",
        "filed": "2022-10-28",
    }
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [{**base, "val": AAPL_REVENUE_Q4_2022}]}
                }
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


def _form13f_xml() -> str:
    return """
    <informationTable><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip>
    <value>1000</value><shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt></shrsOrPrnAmt>
    </infoTable></informationTable>
    """
