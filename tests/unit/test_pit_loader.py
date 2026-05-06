from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from pit.exceptions import DataNotAvailableAt, LookaheadRequested
from pit.loader import PITLoader, ProvenancedTickerSet
from pit.manifest import DatasetName
from pit_fixtures import (
    FY22_REVENUE,
    Q3_MARKET_VALUE,
    TODAY,
    filing_row,
    loader_with,
    member,
    price,
    provenance,
    write_manifest,
)

from agency.provenance import SourceTier


def test_prices_filter_record_date_and_timestamp_as_of(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            price("AAPL", date(2022, 6, 14), 140.0, date(2022, 6, 14), "p1"),
            price("AAPL", date(2022, 6, 15), 141.0, date(2022, 6, 15), "p2"),
            price("AAPL", date(2022, 6, 15), 999.0, date(2022, 6, 16), "future"),
            price("MSFT", date(2022, 6, 15), 250.0, date(2022, 6, 15), "p3"),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.PRICES: frame})

    result = loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=2)

    assert result.get_column("close").to_list() == [140.0, 141.0]
    assert set(result.columns).issuperset({"source", "timestamp_as_of", "verification_level"})


def test_fundamentals_use_latest_filing_before_as_of(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_date": date(2022, 10, 28),
                "revenue": FY22_REVENUE,
                **provenance(SourceTier.OFFICIAL_FILING, date(2022, 10, 28), source_id="fy22"),
            },
            {
                "ticker": "AAPL",
                "filing_date": date(2023, 1, 31),
                "revenue": 999_999,
                **provenance(SourceTier.OFFICIAL_FILING, date(2023, 1, 31), source_id="future"),
            },
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.FUNDAMENTALS: frame})

    result = loader.fundamentals("aapl", date(2022, 12, 31))

    assert result.value["revenue"] == FY22_REVENUE
    assert result.provenance.source_id == "fy22"


def test_insider_transactions_use_filing_date_lookback(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            filing_row("AAPL", date(2022, 12, 2), "old", shares=10),
            filing_row("AAPL", date(2022, 12, 21), "inside", shares=20),
            filing_row("AAPL", date(2023, 1, 3), "future", shares=30),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.INSIDER_TRANSACTIONS: frame})

    result = loader.insider_transactions("AAPL", date(2022, 12, 31), lookback_days=20)

    assert [item.provenance.source_id for item in result] == ["inside"]
    assert [item.value["shares"] for item in result] == [20]


def test_institutional_holdings_use_latest_available_filing(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            filing_row("AAPL", date(2022, 8, 15), "q2", market_value=100),
            filing_row("AAPL", date(2022, 11, 14), "q3", market_value=Q3_MARKET_VALUE),
            filing_row("AAPL", date(2023, 2, 14), "future", market_value=999),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.INSTITUTIONAL_HOLDINGS: frame})

    result = loader.institutional_holdings("AAPL", date(2022, 12, 31))

    assert result.value["market_value"] == Q3_MARKET_VALUE
    assert result.provenance.source_id == "q3"


def test_universe_membership_uses_historical_boundaries(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            member("AAPL", date(2019, 1, 1), None),
            member("OLD", date(2019, 1, 1), date(2023, 3, 15)),
            member("NEWC", date(2023, 3, 15), None),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.UNIVERSE_MEMBERSHIP: frame})

    before = loader.universe_members(date(2023, 3, 14))
    after = loader.universe_members(date(2023, 3, 15))
    known = loader.universe_members(date(2022, 6, 15))

    assert "AAPL" in known
    assert "NEWC" not in before
    assert "NEWC" in after
    assert "OLD" in before
    assert "OLD" not in after
    assert isinstance(after, ProvenancedTickerSet)


def test_sector_etfs_are_pit_filtered(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            price("XLK", date(2022, 6, 14), 120.0, date(2022, 6, 14), "xlk-1"),
            price("XLK", date(2022, 6, 15), 121.0, date(2022, 6, 16), "future"),
            price("XLF", date(2022, 6, 15), 30.0, date(2022, 6, 15), "xlf-1"),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.SECTOR_ETFS: frame})

    result = loader.sector_etfs(date(2022, 6, 15), lookback_days=2)

    assert result.get_column("ticker").to_list() == ["XLF", "XLK"]
    assert result.get_column("source_id").to_list() == ["xlf-1", "xlk-1"]


def test_future_as_of_dates_raise_before_manifest_access(tmp_path: Path) -> None:
    loader = PITLoader(parquet_root=tmp_path, manifest_root=tmp_path, today=lambda: TODAY)

    with pytest.raises(LookaheadRequested):
        loader.prices(["AAPL"], date(2026, 5, 7), lookback_days=1)


def test_missing_manifest_raises_data_not_available(tmp_path: Path) -> None:
    loader = PITLoader(parquet_root=tmp_path, manifest_root=tmp_path, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="missing"):
        loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)


def test_missing_parquet_raises_data_not_available(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    write_manifest(manifest_root, DatasetName.PRICES, "missing.parquet", row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="missing"):
        loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)


def test_stale_manifest_raises_data_not_available(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    frame = pl.DataFrame([price("AAPL", date(2022, 6, 15), 141.0, date(2022, 6, 15), "p1")])
    frame.write_parquet(parquet_root / "prices.parquet")
    write_manifest(
        manifest_root,
        DatasetName.PRICES,
        "prices.parquet",
        frame.height,
        stale_after="2020-01-01T00:00:00+00:00",
    )
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="stale"):
        loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)
