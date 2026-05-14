from __future__ import annotations

import warnings
from datetime import UTC, datetime

import pandas as pd

from sec.form13f import parse_13f_xml
from sec.submissions import FilingSummary
from pit.cusip_utils import cusip_map_coverage_check

FETCHED_AT = datetime(2026, 5, 14, tzinfo=UTC)
AAPL_CUSIP = "037833100"
UNKNOWN_CUSIP = "999999999"


def _filing(*, report_date: str = "2024-12-31") -> FilingSummary:
    return FilingSummary(
        cik="0000320193",
        accession_number="0000320193-25-000010",
        filing_date="2025-02-14",
        report_date=report_date,
        form="13F-HR",
        primary_document="infotable.xml",
    )


def _xml_with_cusip(cusip: str) -> str:
    return f"""
    <informationTable><infoTable>
      <nameOfIssuer>SOME CORP</nameOfIssuer><cusip>{cusip}</cusip>
      <value>500</value><shrsOrPrnAmt><sshPrnamt>500</sshPrnamt></shrsOrPrnAmt>
    </infoTable></informationTable>
    """


def test_unmapped_cusip_emits_warning() -> None:
    """An unknown CUSIP should emit a UserWarning containing 'cusip_not_mapped'."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parse_13f_xml(
            filing=_filing(),
            document="infotable.xml",
            xml=_xml_with_cusip(UNKNOWN_CUSIP),
            fetched_at=FETCHED_AT,
            cusip_to_ticker={},  # empty map → unknown CUSIP
        )

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert user_warnings, "Expected at least one UserWarning for unmapped CUSIP"
    messages = [str(w.message) for w in user_warnings]
    assert any("cusip_not_mapped" in msg for msg in messages), (
        f"Expected 'cusip_not_mapped' in warning messages, got: {messages}"
    )
    assert any(UNKNOWN_CUSIP in msg for msg in messages), (
        f"Expected CUSIP value {UNKNOWN_CUSIP!r} in warning messages, got: {messages}"
    )


def test_mapped_cusip_no_warning() -> None:
    """A CUSIP that exists in the map should not emit any UserWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame = parse_13f_xml(
            filing=_filing(),
            document="infotable.xml",
            xml=_xml_with_cusip(AAPL_CUSIP),
            fetched_at=FETCHED_AT,
            cusip_to_ticker={AAPL_CUSIP: "AAPL"},
        )

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings, (
        f"Expected no UserWarning for a mapped CUSIP, got: {[str(w.message) for w in user_warnings]}"
    )
    # Also verify the row was included (sanity check)
    assert not frame.empty
    assert frame.iloc[0]["ticker"] == "AAPL"


def test_cusip_map_coverage_check_returns_stats() -> None:
    """Coverage check should correctly count mapped vs unmapped CUSIPs."""
    holdings = pd.DataFrame(
        {
            "cusip": [AAPL_CUSIP, "594918104", UNKNOWN_CUSIP],
            "shares_held": [100, 200, 50],
        }
    )
    cusip_map = {
        AAPL_CUSIP: "AAPL",
        "594918104": "MSFT",
    }

    result = cusip_map_coverage_check(holdings, cusip_map)

    assert result["total"] == 3
    assert result["mapped"] == 2
    assert result["unmapped"] == 1
    assert result["unmapped_cusips"] == [UNKNOWN_CUSIP]


def test_cusip_map_coverage_check_empty_dataframe() -> None:
    """Empty DataFrame should return all-zero stats."""
    result = cusip_map_coverage_check(pd.DataFrame(), {})
    assert result == {"total": 0, "mapped": 0, "unmapped": 0, "unmapped_cusips": []}


def test_cusip_map_coverage_check_all_mapped() -> None:
    """All CUSIPs mapped → unmapped count is zero and list is empty."""
    holdings = pd.DataFrame({"cusip": [AAPL_CUSIP, "594918104"]})
    cusip_map = {AAPL_CUSIP: "AAPL", "594918104": "MSFT"}

    result = cusip_map_coverage_check(holdings, cusip_map)

    assert result["total"] == 2
    assert result["mapped"] == 2
    assert result["unmapped"] == 0
    assert result["unmapped_cusips"] == []
