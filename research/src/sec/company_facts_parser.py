from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pandas as pd
from sec.records import cik_string, parse_date, parse_float, parse_int, provenance_columns

METRIC_TAGS = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditures": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "shares_outstanding": ("EntityCommonStockSharesOutstanding",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "ebitda": ("EarningsBeforeInterestTaxesDepreciationAndAmortization",),
    "depreciation_amortization": ("DepreciationDepletionAndAmortization",),
    "research_development": ("ResearchAndDevelopmentExpense",),
    "interest_expense": ("InterestExpenseNonOperating",),
    "income_tax_expense": ("IncomeTaxExpenseBenefit",),
    "eps_basic": ("EarningsPerShareBasic",),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "long_term_debt": ("LongTermDebtNoncurrent",),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "total_equity": ("StockholdersEquity",),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
}


def parse_company_facts(
    *,
    ticker: str,
    cik: str,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    source_url: str,
) -> pd.DataFrame:
    rows = _fact_rows(
        ticker=ticker,
        cik=cik,
        payload=payload,
        fetched_at=fetched_at,
        source_url=source_url,
    )
    rows.extend(_free_cash_flow_rows(rows))
    return pd.DataFrame(rows)


def _fact_rows(
    *,
    ticker: str,
    cik: str,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    source_url: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        return rows
    tag_to_metric = {tag: metric for metric, tags in METRIC_TAGS.items() for tag in tags}
    for taxonomy in facts.values():
        if not isinstance(taxonomy, Mapping):
            continue
        for tag, fact in taxonomy.items():
            if tag not in tag_to_metric or not isinstance(fact, Mapping):
                continue
            rows.extend(
                _unit_rows(
                    ticker,
                    cik,
                    tag_to_metric[str(tag)],
                    str(tag),
                    fact,
                    fetched_at,
                    source_url,
                )
            )
    return rows


def _unit_rows(
    ticker: str,
    cik: str,
    metric: str,
    tag: str,
    fact: Mapping[str, Any],
    fetched_at: datetime,
    source_url: str,
) -> list[dict[str, object]]:
    units = fact.get("units")
    if not isinstance(units, Mapping):
        return []
    rows: list[dict[str, object]] = []
    for unit, observations in units.items():
        if not isinstance(observations, list):
            continue
        for observation in observations:
            if isinstance(observation, Mapping):
                row = _observation_row(
                    ticker,
                    cik,
                    metric,
                    tag,
                    str(unit),
                    observation,
                    fetched_at,
                    source_url,
                )
                if row is not None:
                    rows.append(row)
    return rows


def _observation_row(
    ticker: str,
    cik: str,
    metric: str,
    tag: str,
    unit: str,
    observation: Mapping[str, Any],
    fetched_at: datetime,
    source_url: str,
) -> dict[str, object] | None:
    filing_date = parse_date(observation.get("filed"))
    period_end = parse_date(observation.get("end"))
    value = parse_float(observation.get("val"))
    accession_number = str(observation.get("accn", ""))
    if filing_date is None or period_end is None or value is None or accession_number == "":
        return None
    source_id = f"sec:{ticker}:{metric}:{accession_number}:{period_end.isoformat()}"
    return {
        "ticker": ticker.upper(),
        "cik": cik_string(cik),
        "metric": metric,
        "value": value,
        "unit": unit,
        "source_tag": tag,
        "period_start": parse_date(observation.get("start")),
        "period_end": period_end,
        "fiscal_year": parse_int(observation.get("fy")),
        "fiscal_period": observation.get("fp"),
        "form": observation.get("form"),
        "filing_date": filing_date,
        "accession_number": accession_number,
        **provenance_columns(
            source_id=source_id,
            source_url=source_url,
            filing_date=filing_date,
            fetched_at=fetched_at,
        ),
    }


def _free_cash_flow_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key: dict[tuple[object, object, object], dict[str, dict[str, object]]] = {}
    for row in rows:
        metric = row["metric"]
        if metric not in {"operating_cash_flow", "capital_expenditures"}:
            continue
        key = (row["ticker"], row["accession_number"], row["period_end"])
        by_key.setdefault(key, {})[str(metric)] = row

    derived: list[dict[str, object]] = []
    for grouped in by_key.values():
        operating = grouped.get("operating_cash_flow")
        capex = grouped.get("capital_expenditures")
        if operating is None or capex is None:
            continue
        row = dict(operating)
        row["metric"] = "free_cash_flow"
        row["value"] = float(str(operating["value"])) - float(str(capex["value"]))
        row["source_tag"] = "derived:operating_cash_flow-capital_expenditures"
        row["source_id"] = str(row["source_id"]).replace("operating_cash_flow", "free_cash_flow")
        derived.append(row)
    return derived
