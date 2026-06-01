from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest
from pit.exceptions import DataNotAvailableAt
from pit.sec_views import fundamentals_from_frame

AS_OF = date(2024, 11, 15)
OBSERVED = datetime(2024, 11, 15, tzinfo=UTC)


def _row(
    metric: str,
    value: float,
    form: str,
    fiscal_period: str,
    period_end: date,
    *,
    unit: str = "USD",
    as_of: date = AS_OF,
) -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "cik": "0000320193",
        "metric": metric,
        "value": value,
        "unit": unit,
        "source_tag": metric,
        "period_start": None,
        "period_end": period_end,
        "fiscal_year": period_end.year,
        "fiscal_period": fiscal_period,
        "form": form,
        "filing_date": as_of,
        "accession_number": f"0000-{metric[:4]}-{fiscal_period}-{value}",
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": f"sec:AAPL:{metric}:{fiscal_period}:{value}",
        "source_url": "https://data.sec.gov/fixture",
        "timestamp_observed": OBSERVED,
        "timestamp_as_of": as_of,
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }


def _make_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    frame = pl.DataFrame(
        rows,
        schema_overrides={
            "filing_date": pl.Date,
            "period_end": pl.Date,
            "timestamp_observed": pl.Datetime("us", "UTC"),
            "timestamp_as_of": pl.Date,
        },
    )
    return frame.with_columns(
        pl.col("period_end").alias("__period_end"),
        pl.col("timestamp_as_of").cast(pl.Datetime("us", "UTC")).alias("__as_of"),
    )


def test_uses_single_quarter_when_revenue_net_income_and_fcf_match() -> None:
    frame = _make_frame(
        [
            _row("revenue", 100_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("net_income", 25_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("free_cash_flow", 20_000.0, "10-Q", "Q3", date(2024, 9, 30)),
        ]
    )

    result = fundamentals_from_frame(frame, as_of=AS_OF)

    assert result.value["revenue"] == 100_000.0
    assert result.value["net_income"] == 25_000.0
    assert result.value["free_cash_flow"] == 20_000.0
    assert result.value["period_alignment_status"] == "aligned"
    assert result.value["quality_score_basis"] == "period_aligned_only"
    assert result.value["filing_period"] == "Q3"
    assert result.value["filing_form"] == "10-Q"


def test_does_not_mix_quarterly_net_income_with_annual_revenue() -> None:
    frame = _make_frame(
        [
            _row("revenue", 400_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("net_income", 90_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("free_cash_flow", 80_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("net_income", 25_000.0, "10-Q", "Q3", date(2024, 9, 30)),
        ]
    )

    result = fundamentals_from_frame(frame, as_of=AS_OF)

    assert result.value["revenue"] == 400_000.0
    assert result.value["net_income"] == 90_000.0
    assert result.value["free_cash_flow"] == 80_000.0


def test_does_not_mix_free_cash_flow_from_different_period() -> None:
    frame = _make_frame(
        [
            _row("revenue", 100_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("net_income", 25_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("free_cash_flow", 12_000.0, "10-Q", "Q2", date(2024, 6, 30)),
            _row("revenue", 380_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("net_income", 85_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("free_cash_flow", 75_000.0, "10-K", "FY", date(2023, 12, 31)),
        ]
    )

    result = fundamentals_from_frame(frame, as_of=AS_OF)

    assert result.value["revenue"] == 380_000.0
    assert result.value["net_income"] == 85_000.0
    assert result.value["free_cash_flow"] == 75_000.0


def test_falls_back_to_latest_consistent_annual_period() -> None:
    frame = _make_frame(
        [
            _row("revenue", 100_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("net_income", 24_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("revenue", 390_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("net_income", 90_000.0, "10-K", "FY", date(2023, 12, 31)),
            _row("free_cash_flow", 82_000.0, "10-K", "FY", date(2023, 12, 31)),
        ]
    )

    result = fundamentals_from_frame(frame, as_of=AS_OF)

    assert result.value["revenue"] == 390_000.0
    assert result.value["net_income"] == 90_000.0
    assert result.value["free_cash_flow"] == 82_000.0


def test_raises_when_no_consistent_period_has_required_metrics() -> None:
    frame = _make_frame(
        [
            _row("revenue", 100.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("net_income", 10.0, "10-Q", "Q2", date(2024, 6, 30)),
            _row("free_cash_flow", 9.0, "10-Q", "Q1", date(2024, 3, 31)),
        ]
    )

    with pytest.raises(DataNotAvailableAt):
        fundamentals_from_frame(frame, as_of=AS_OF)


def test_direct_frame_period_key_uses_period_end_when_loader_alias_is_absent() -> None:
    frame = pl.DataFrame(
        [
            _row("revenue", 120_000.0, "10-Q", "Q1", date(2025, 3, 31)),
            _row("net_income", 20_000.0, "10-Q", "Q1", date(2024, 3, 31)),
            _row("free_cash_flow", 18_000.0, "10-Q", "Q1", date(2024, 3, 31)),
        ],
        schema_overrides={
            "filing_date": pl.Date,
            "period_end": pl.Date,
            "timestamp_observed": pl.Datetime("us", "UTC"),
            "timestamp_as_of": pl.Date,
        },
    )

    with pytest.raises(DataNotAvailableAt, match="no consistent fiscal period"):
        fundamentals_from_frame(frame, as_of=AS_OF)


def test_amended_filing_wins_for_same_metric_period_and_form_family() -> None:
    frame = _make_frame(
        [
            _row("revenue", 100_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("revenue", 102_000.0, "10-Q/A", "Q3", date(2024, 9, 30)),
            _row("net_income", 24_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("free_cash_flow", 20_000.0, "10-Q", "Q3", date(2024, 9, 30)),
        ]
    )

    result = fundamentals_from_frame(frame, as_of=AS_OF)

    assert result.value["revenue"] == 102_000.0
    assert result.value["net_income"] == 24_000.0


def test_wrong_unit_usd_row_is_ignored_for_monetary_metric() -> None:
    frame = _make_frame(
        [
            _row("revenue", 999.0, "10-Q", "Q3", date(2024, 9, 30), unit="shares"),
            _row("revenue", 100_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("net_income", 25_000.0, "10-Q", "Q3", date(2024, 9, 30)),
            _row("free_cash_flow", 20_000.0, "10-Q", "Q3", date(2024, 9, 30)),
        ]
    )

    result = fundamentals_from_frame(frame, as_of=AS_OF)

    assert result.value["revenue"] == 100_000.0
