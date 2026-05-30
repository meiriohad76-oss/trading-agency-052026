from __future__ import annotations

from datetime import UTC, datetime

from sec.cik import cik_lookup_for_tickers, parse_company_tickers
from sec.company_facts_parser import parse_company_facts
from sec.form4 import parse_form4_xml
from sec.form13f import parse_13f_xml
from sec.submissions import FilingSummary

FETCHED_AT = datetime(2026, 5, 6, tzinfo=UTC)
AAPL_CIK = "0000320193"
AAPL_CUSIP = "037833100"
AAPL_REVENUE_Q4_2022 = 90_146_000_000.0
AAPL_NET_INCOME_Q4_2022 = 20_721_000_000.0
AAPL_FREE_CASH_FLOW_Q4_2022 = 20_807_000_000.0
FORM4_SHARES = 100.0
FORM4_PRICE = 150.5
FORM13F_SHARES = 1_000


def test_ticker_to_cik_mapping_handles_share_class_tickers() -> None:
    mapping = parse_company_tickers(
        {
            "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
            "1": {"ticker": "BRK.B", "cik_str": 1067983, "title": "Berkshire Hathaway"},
            "2": {"ticker": "GOOGL", "cik_str": 1652044, "title": "Alphabet Inc."},
        }
    )

    matched, missing = cik_lookup_for_tickers(["aapl", "BRK.B", "GOOG"], mapping)

    assert matched["AAPL"].cik == AAPL_CIK
    assert matched["BRK-B"].cik == "0001067983"
    assert missing == ["GOOG"]


def test_company_facts_parser_extracts_metrics_and_free_cash_flow() -> None:
    frame = parse_company_facts(
        ticker="AAPL",
        cik=AAPL_CIK,
        payload=_company_facts_payload(),
        fetched_at=FETCHED_AT,
        source_url="fixture://companyfacts",
    )

    values = dict(zip(frame["metric"], frame["value"], strict=False))

    assert values["revenue"] == AAPL_REVENUE_Q4_2022
    assert values["net_income"] == AAPL_NET_INCOME_Q4_2022
    assert values["free_cash_flow"] == AAPL_FREE_CASH_FLOW_Q4_2022


def test_parser_extracts_profitability_statement_tags() -> None:
    frame = parse_company_facts(
        ticker="AAPL",
        cik=AAPL_CIK,
        payload=_company_facts_payload(
            {
                "GrossProfit": _fact(37_000_000_000.0),
                "OperatingIncomeLoss": _fact(28_000_000_000.0),
                "EarningsBeforeInterestTaxesDepreciationAndAmortization": _fact(
                    31_000_000_000.0
                ),
                "DepreciationDepletionAndAmortization": _fact(2_900_000_000.0),
                "ResearchAndDevelopmentExpense": _fact(7_700_000_000.0),
                "InterestExpenseNonOperating": _fact(930_000_000.0),
                "IncomeTaxExpenseBenefit": _fact(4_000_000_000.0),
            }
        ),
        fetched_at=FETCHED_AT,
        source_url="fixture://companyfacts",
    )

    values = _metric_values(frame)

    assert values["gross_profit"] == 37_000_000_000.0
    assert values["operating_income"] == 28_000_000_000.0
    assert values["ebitda"] == 31_000_000_000.0
    assert values["depreciation_amortization"] == 2_900_000_000.0
    assert values["research_development"] == 7_700_000_000.0
    assert values["interest_expense"] == 930_000_000.0
    assert values["income_tax_expense"] == 4_000_000_000.0


def test_parser_extracts_balance_sheet_tags() -> None:
    frame = parse_company_facts(
        ticker="AAPL",
        cik=AAPL_CIK,
        payload=_company_facts_payload(
            {
                "AssetsCurrent": _fact(130_000_000_000.0),
                "LiabilitiesCurrent": _fact(125_000_000_000.0),
                "LongTermDebtNoncurrent": _fact(95_000_000_000.0),
                "CashAndCashEquivalentsAtCarryingValue": _fact(28_000_000_000.0),
                "StockholdersEquity": _fact(74_000_000_000.0),
                "RetainedEarningsAccumulatedDeficit": _fact(4_300_000_000.0),
            }
        ),
        fetched_at=FETCHED_AT,
        source_url="fixture://companyfacts",
    )

    values = _metric_values(frame)

    assert values["current_assets"] == 130_000_000_000.0
    assert values["current_liabilities"] == 125_000_000_000.0
    assert values["long_term_debt"] == 95_000_000_000.0
    assert values["cash_and_equivalents"] == 28_000_000_000.0
    assert values["total_equity"] == 74_000_000_000.0
    assert values["retained_earnings"] == 4_300_000_000.0


def test_parser_extracts_eps_tags_with_per_share_unit() -> None:
    frame = parse_company_facts(
        ticker="AAPL",
        cik=AAPL_CIK,
        payload=_company_facts_payload(
            {
                "EarningsPerShareBasic": _fact(1.31, unit="USD/shares"),
                "EarningsPerShareDiluted": _fact(1.29, unit="USD/shares"),
            }
        ),
        fetched_at=FETCHED_AT,
        source_url="fixture://companyfacts",
    )

    eps_rows = frame[frame["metric"].isin(["eps_basic", "eps_diluted"])]
    values = _metric_values(eps_rows)

    assert values["eps_basic"] == 1.31
    assert values["eps_diluted"] == 1.29
    assert set(eps_rows["unit"]) == {"USD/shares"}


def test_free_cash_flow_derivation_still_works_with_expanded_tags() -> None:
    frame = parse_company_facts(
        ticker="AAPL",
        cik=AAPL_CIK,
        payload=_company_facts_payload(
            {
                "GrossProfit": _fact(37_000_000_000.0),
                "OperatingIncomeLoss": _fact(28_000_000_000.0),
            }
        ),
        fetched_at=FETCHED_AT,
        source_url="fixture://companyfacts",
    )

    values = _metric_values(frame)

    assert values["free_cash_flow"] == AAPL_FREE_CASH_FLOW_Q4_2022


def test_form4_parser_extracts_non_derivative_transaction() -> None:
    filing = _filing("4", "form4.xml", report_date="2022-11-10")

    frame = parse_form4_xml(ticker="AAPL", filing=filing, xml=_form4_xml(), fetched_at=FETCHED_AT)

    assert frame.iloc[0]["transaction_type"] == "P"
    assert frame.iloc[0]["shares"] == FORM4_SHARES
    assert frame.iloc[0]["price"] == FORM4_PRICE


def test_13f_parser_maps_cusip_to_ticker() -> None:
    filing = _filing("13F-HR", "infotable.xml", report_date="2022-12-31")

    frame = parse_13f_xml(
        filing=filing,
        document="infotable.xml",
        xml=_form13f_xml(),
        fetched_at=FETCHED_AT,
        cusip_to_ticker={AAPL_CUSIP: "AAPL"},
    )

    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["shares_held"] == FORM13F_SHARES
    assert frame.iloc[0]["quarter"] == "2022Q4"


def _filing(form: str, document: str, *, report_date: str) -> FilingSummary:
    return FilingSummary(
        cik=AAPL_CIK,
        accession_number="0000320193-22-000108",
        filing_date="2022-10-28",
        report_date=report_date,
        form=form,
        primary_document=document,
    )


def _company_facts_payload(
    extra_facts: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    base = {
        "start": "2022-06-26",
        "end": "2022-09-24",
        "accn": "0000320193-22-000108",
        "fy": 2022,
        "fp": "Q4",
        "form": "10-K",
        "filed": "2022-10-28",
    }
    facts = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": [{**base, "val": AAPL_REVENUE_Q4_2022}]}
        },
        "NetIncomeLoss": {"units": {"USD": [{**base, "val": AAPL_NET_INCOME_Q4_2022}]}},
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {"USD": [{**base, "val": 24_127_000_000}]}
        },
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {"USD": [{**base, "val": 3_320_000_000}]}
        },
    }
    if extra_facts:
        facts.update(extra_facts)
    return {
        "facts": {
            "us-gaap": facts
        }
    }


def _fact(value: float, *, unit: str = "USD") -> dict[str, object]:
    base = {
        "start": "2022-06-26",
        "end": "2022-09-24",
        "accn": "0000320193-22-000108",
        "fy": 2022,
        "fp": "Q4",
        "form": "10-K",
        "filed": "2022-10-28",
        "val": value,
    }
    return {"units": {unit: [base]}}


def _metric_values(frame) -> dict[str, float]:
    return dict(zip(frame["metric"], frame["value"], strict=False))


def _form4_xml() -> str:
    return """
    <ownershipDocument>
      <reportingOwner><reportingOwnerId><rptOwnerCik>0001</rptOwnerCik>
      <rptOwnerName>Example Insider</rptOwnerName></reportingOwnerId></reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionDate><value>2022-11-10</value></transactionDate>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts><transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>150.50</value></transactionPricePerShare></transactionAmounts>
        <postTransactionAmounts><sharesOwnedFollowingTransaction><value>500</value>
        </sharesOwnedFollowingTransaction></postTransactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>
    """


def _form13f_xml() -> str:
    return """
    <informationTable><infoTable>
      <nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip>
      <value>1000</value><shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt></shrsOrPrnAmt>
    </infoTable></informationTable>
    """
