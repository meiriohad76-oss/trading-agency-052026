from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from pit.exceptions import DataNotAvailableAt, LookaheadRequested
from pit.loader import PITLoader, ProvenancedTickerSet
from pit.manifest import DatasetName
from pit_fixtures import (
    FY22_REVENUE,
    Q3_HOLDER_COUNT,
    Q3_MARKET_VALUE,
    Q3_SHARES_A,
    Q3_TOTAL_CHANGE,
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
    loader = loader_with(tmp_path, {DatasetName.PRICES_DAILY: frame})

    result = loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=2)

    assert result.get_column("close").to_list() == [140.0, 141.0]
    assert set(result.columns).issuperset({"source", "timestamp_as_of", "verification_level"})


def test_prices_filter_intraday_timestamp_as_of_for_same_day_replay(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            {
                **price("AAPL", date(2026, 5, 6), 141.0, date(2026, 5, 6), "known"),
                "timestamp_as_of": datetime(2026, 5, 6, 14, 55, tzinfo=UTC),
            },
            {
                **price("AAPL", date(2026, 5, 6), 999.0, date(2026, 5, 6), "later"),
                "timestamp_as_of": datetime(2026, 5, 6, 15, 5, tzinfo=UTC),
            },
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.PRICES_DAILY: frame})
    loader = PITLoader(
        parquet_root=loader.parquet_root,
        manifest_root=loader.manifest_root,
        today=lambda: date(2026, 5, 6),
        clock=lambda: datetime(2026, 5, 6, 15, 0, tzinfo=UTC),
    )

    result = loader.prices(["AAPL"], date(2026, 5, 6), lookback_days=1)

    assert result.get_column("source_id").to_list() == ["known"]


def test_fundamentals_use_latest_filing_before_as_of(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            {
                "ticker": "AAPL",
                "metric": "revenue",
                "value": FY22_REVENUE,
                "period_end": date(2022, 9, 24),
                "filing_date": date(2022, 10, 28),
                **provenance(SourceTier.OFFICIAL_FILING, date(2022, 10, 28), source_id="fy22"),
            },
            {
                "ticker": "AAPL",
                "metric": "revenue",
                "value": 999_999,
                "period_end": date(2022, 12, 31),
                "filing_date": date(2023, 1, 31),
                **provenance(SourceTier.OFFICIAL_FILING, date(2023, 1, 31), source_id="future"),
            },
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.SEC_COMPANY_FACTS: frame})

    result = loader.fundamentals("aapl", date(2022, 12, 31))

    assert result.value["revenue"] == float(FY22_REVENUE)
    assert result.provenance.source_id == "fy22"


def test_insider_transactions_use_filing_date_lookback(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            filing_row("AAPL", date(2022, 12, 2), "old", shares=10),
            filing_row("AAPL", date(2022, 12, 21), "inside", shares=20),
            filing_row("AAPL", date(2023, 1, 3), "future", shares=30),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.SEC_FORM4: frame})

    result = loader.insider_transactions("AAPL", date(2022, 12, 31), lookback_days=20)

    assert [item.provenance.source_id for item in result] == ["inside"]
    assert [item.value["shares"] for item in result] == [20]


def test_institutional_holdings_use_latest_available_filing(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            filing_row(
                "AAPL",
                date(2022, 11, 14),
                "q3-a",
                filer_cik="1",
                quarter_end_date=date(2022, 9, 30),
                shares_held=Q3_SHARES_A,
                change_from_prev_quarter=20,
            ),
            filing_row(
                "AAPL",
                date(2022, 11, 15),
                "q3-b",
                filer_cik="2",
                quarter_end_date=date(2022, 9, 30),
                shares_held=Q3_MARKET_VALUE,
                change_from_prev_quarter=30,
            ),
            filing_row(
                "AAPL",
                date(2023, 2, 14),
                "future",
                filer_cik="1",
                quarter_end_date=date(2022, 12, 31),
                shares_held=999,
                change_from_prev_quarter=999,
            ),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.SEC_13F: frame})

    result = loader.institutional_holdings("AAPL", date(2022, 12, 31))

    assert result.value["holder_count"] == Q3_HOLDER_COUNT
    assert result.value["total_shares_held"] == Q3_SHARES_A + Q3_MARKET_VALUE
    assert result.value["total_change_from_prev_quarter"] == Q3_TOTAL_CHANGE
    assert result.provenance.source_id == "q3-b"


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


def test_universe_membership_uses_conservative_provenance_for_full_set(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            member("OLDER", date(2020, 1, 1), None),
            member("NEWER", date(2022, 1, 1), None),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.UNIVERSE_MEMBERSHIP: frame})

    result = loader.universe_members(date(2022, 6, 15))

    assert result == {"OLDER", "NEWER"}
    assert isinstance(result, ProvenancedTickerSet)
    assert str(result.provenance.source_id).startswith("universe-membership:2:")
    assert result.provenance.timestamp_as_of.date() == date(2022, 1, 1)


def test_sector_etfs_are_pit_filtered(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            price("XLK", date(2022, 6, 14), 120.0, date(2022, 6, 14), "xlk-1"),
            price("XLK", date(2022, 6, 15), 121.0, date(2022, 6, 16), "future"),
            price("XLF", date(2022, 6, 15), 30.0, date(2022, 6, 15), "xlf-1"),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.PRICES_DAILY: frame})

    result = loader.sector_etfs(date(2022, 6, 15), lookback_days=2)

    assert result.get_column("ticker").to_list() == ["XLF", "XLK"]
    assert result.get_column("source_id").to_list() == ["xlf-1", "xlk-1"]


def test_stock_trades_filter_trade_date_and_timestamp_as_of(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            stock_trade("AAPL", date(2026, 5, 5), date(2026, 5, 5), "a1"),
            stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "a2"),
            stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 7), "future"),
            stock_trade("MSFT", date(2026, 5, 6), date(2026, 5, 6), "m1"),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.STOCK_TRADES: frame})

    result = loader.stock_trades(["AAPL"], date(2026, 5, 6), lookback_days=2)

    assert result.get_column("source_id").to_list() == ["a1", "a2"]


def test_stock_trades_read_only_requested_partitions(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    aapl_path = trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet"
    bad_msft_path = trade_root / "ticker=MSFT" / "year=2026" / "trades.parquet"
    aapl_path.parent.mkdir(parents=True)
    bad_msft_path.parent.mkdir(parents=True)
    manifest_root.mkdir()
    pl.DataFrame(
        [
            stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "a1"),
        ]
    ).write_parquet(aapl_path)
    bad_msft_path.write_text("this is deliberately not parquet", encoding="utf-8")
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "complete",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    result = loader.stock_trades(["AAPL"], date(2026, 5, 6), lookback_days=1)

    assert result.get_column("source_id").to_list() == ["a1"]


def test_stock_trades_reject_partial_coverage_partitions(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    aapl_path = trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet"
    aapl_path.parent.mkdir(parents=True)
    manifest_root.mkdir()
    pl.DataFrame(
        [
            stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "a1"),
        ]
    ).write_parquet(aapl_path)
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1,
                        "pages_downloaded": 1,
                        "order": "desc",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="incomplete stock trade coverage"):
        loader.stock_trades(["AAPL"], date(2026, 5, 6), lookback_days=1)


def test_stock_trade_activity_frames_can_allow_partial_live_slice(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    aapl_path = trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet"
    aapl_path.parent.mkdir(parents=True)
    manifest_root.mkdir()
    pl.DataFrame(
        [
            stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "a1"),
        ]
    ).write_parquet(aapl_path)
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1,
                        "pages_downloaded": 1,
                        "order": "desc",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="incomplete stock trade coverage"):
        loader.stock_trade_activity_frames(["AAPL"], date(2026, 5, 6), lookback_days=1)

    total, daily = loader.stock_trade_activity_frames(
        ["AAPL"],
        date(2026, 5, 6),
        lookback_days=3,
        allow_partial_coverage=True,
    )

    assert total.get_column("ticker").to_list() == ["AAPL"]
    assert daily.get_column("date").to_list() == [date(2026, 5, 6)]


def test_stock_trade_activity_frames_for_trade_window_uses_separate_knowledge_cutoff(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    aapl_path = trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet"
    aapl_path.parent.mkdir(parents=True)
    manifest_root.mkdir()
    pl.DataFrame(
        [
            {
                **stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "known-next-day"),
                "timestamp_as_of": datetime(2026, 5, 7, 0, 5, tzinfo=UTC),
            },
            {
                **stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "future-later"),
                "timestamp_as_of": datetime(2026, 5, 8, 0, 5, tzinfo=UTC),
            },
        ]
    ).write_parquet(aapl_path)
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "partial",
                        "downloaded_row_count": 2,
                        "pages_downloaded": 1,
                        "order": "desc",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", row_count=2)
    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=lambda: date(2026, 5, 8),
    )

    with pytest.raises(DataNotAvailableAt, match="no stock trade rows matched"):
        loader.stock_trade_activity_frames(
            ["AAPL"],
            date(2026, 5, 6),
            lookback_days=1,
            allow_partial_coverage=True,
        )

    total, daily = loader.stock_trade_activity_frames_for_trade_window(
        ["AAPL"],
        trade_end=date(2026, 5, 6),
        knowledge_as_of=date(2026, 5, 7),
        lookback_days=1,
        allow_partial_coverage=True,
    )

    assert total.get_column("trade_count").to_list() == [1]
    assert daily.get_column("trade_count").to_list() == [1]


def test_stock_trades_reject_missing_requested_coverage_rows(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    aapl_path = trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet"
    aapl_path.parent.mkdir(parents=True)
    manifest_root.mkdir()
    pl.DataFrame(
        [
            stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "a1"),
        ]
    ).write_parquet(aapl_path)
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "complete",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="MSFT\\|2026-05-06:missing"):
        loader.stock_trades(["AAPL", "MSFT"], date(2026, 5, 6), lookback_days=1)


def test_complete_stock_trade_tickers_returns_only_full_lookback_coverage(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    for ticker in ("AAPL", "MSFT"):
        trade_path = trade_root / f"ticker={ticker}" / "year=2026" / "trades.parquet"
        trade_path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            [
                stock_trade(ticker, date(2026, 5, 5), date(2026, 5, 5), f"{ticker}-1"),
                stock_trade(ticker, date(2026, 5, 6), date(2026, 5, 6), f"{ticker}-2"),
            ]
        ).write_parquet(trade_path)
    manifest_root.mkdir()
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-05": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-05",
                        "coverage_status": "complete",
                    },
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "complete",
                    },
                    "MSFT|2026-05-05": {
                        "ticker": "MSFT",
                        "trade_date": "2026-05-05",
                        "coverage_status": "complete",
                    },
                    "MSFT|2026-05-06": {
                        "ticker": "MSFT",
                        "trade_date": "2026-05-06",
                        "coverage_status": "partial",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", row_count=4)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    result = loader.complete_stock_trade_tickers(
        ["MSFT", "AAPL", "MISSING"],
        date(2026, 5, 6),
        lookback_days=2,
    )

    assert result == ("AAPL",)


def test_stock_trades_today_filter_uses_intraday_timestamp_cutoff(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            {
                **stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "known"),
                "timestamp_as_of": datetime(2026, 5, 6, 14, 55, tzinfo=UTC),
            },
            {
                **stock_trade("AAPL", date(2026, 5, 6), date(2026, 5, 6), "later"),
                "timestamp_as_of": datetime(2026, 5, 6, 15, 5, tzinfo=UTC),
            },
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.STOCK_TRADES: frame})
    loader = PITLoader(
        parquet_root=loader.parquet_root,
        manifest_root=loader.manifest_root,
        today=lambda: date(2026, 5, 6),
        clock=lambda: datetime(2026, 5, 6, 15, 0, tzinfo=UTC),
    )

    result = loader.stock_trades(["AAPL"], date(2026, 5, 6), lookback_days=1)

    assert result.get_column("source_id").to_list() == ["known"]


def test_prices_returns_empty_on_date_with_no_data(tmp_path: Path) -> None:
    """prices() must return an empty DataFrame (not raise) when the parquet file
    exists but no records fall within the requested date window.  This guards the
    contract that callers can safely check `result.is_empty()` rather than catching
    DataNotAvailableAt for the "no rows" case.
    """
    # Parquet contains data on 2023-01-03; querying as_of=2023-01-02 (before any data)
    frame = pl.DataFrame(
        [
            price("AAPL", date(2023, 1, 3), 130.0, date(2023, 1, 3), "p1"),
            price("AAPL", date(2023, 1, 4), 131.0, date(2023, 1, 4), "p2"),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.PRICES_DAILY: frame})

    result = loader.prices(["AAPL"], date(2023, 1, 2), lookback_days=1)

    assert isinstance(result, pl.DataFrame)
    assert len(result) == 0


def test_sector_etfs_returns_empty_on_date_with_no_data(tmp_path: Path) -> None:
    """sector_etfs() must return an empty DataFrame (not raise) when no sector-ETF
    rows fall within the requested window.  Same contract as prices().
    """
    frame = pl.DataFrame(
        [
            # XLK data is only on 2023-01-03; querying as_of=2023-01-02 will match nothing
            price("XLK", date(2023, 1, 3), 120.0, date(2023, 1, 3), "xlk-1"),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.PRICES_DAILY: frame})

    result = loader.sector_etfs(date(2023, 1, 2), lookback_days=1)

    assert isinstance(result, pl.DataFrame)
    assert len(result) == 0


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
    write_manifest(manifest_root, DatasetName.PRICES_DAILY, "missing.parquet", row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="missing"):
        loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)


def test_loader_cache_invalidates_when_manifest_identity_changes(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    parquet_path = parquet_root / "prices_daily.parquet"
    pl.DataFrame(
        [price("AAPL", date(2022, 6, 15), 141.0, date(2022, 6, 15), "p1")]
    ).write_parquet(parquet_path)
    write_manifest(manifest_root, DatasetName.PRICES_DAILY, parquet_path.name, row_count=1)
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    first = loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)
    pl.DataFrame(
        [price("AAPL", date(2022, 6, 15), 200.0, date(2022, 6, 15), "p2")]
    ).write_parquet(parquet_path)
    manifest_path = manifest_root / "prices_daily.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["checksum"] = "fixture-v2"
    manifest["fetched_at"] = "2026-05-06T01:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    second = loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)

    assert first.get_column("close").to_list() == [141.0]
    assert second.get_column("close").to_list() == [200.0]
    assert second.get_column("source_id").to_list() == ["p2"]


def test_stale_manifest_raises_data_not_available(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    frame = pl.DataFrame([price("AAPL", date(2022, 6, 15), 141.0, date(2022, 6, 15), "p1")])
    frame.write_parquet(parquet_root / "prices_daily.parquet")
    write_manifest(
        manifest_root,
        DatasetName.PRICES_DAILY,
        "prices_daily.parquet",
        frame.height,
        stale_after="2020-01-01T00:00:00+00:00",
    )
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="stale"):
        loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)


def test_malformed_manifest_timestamp_raises_data_not_available(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    frame = pl.DataFrame([price("AAPL", date(2022, 6, 15), 141.0, date(2022, 6, 15), "p1")])
    frame.write_parquet(parquet_root / "prices_daily.parquet")
    write_manifest(manifest_root, DatasetName.PRICES_DAILY, "prices_daily.parquet", frame.height)
    manifest_path = manifest_root / "prices_daily.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fetched_at"] = "not-a-timestamp"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root, today=lambda: TODAY)

    with pytest.raises(DataNotAvailableAt, match="fetched_at must be an ISO datetime"):
        loader.prices(["AAPL"], date(2022, 6, 15), lookback_days=1)


def stock_trade(
    ticker: str,
    trade_date: date,
    timestamp_as_of: date,
    source_id: str,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "trade_ts": trade_date,
        "price": 100.0,
        "size": 100.0,
        "notional": 10_000.0,
        "direction": 1,
        "signed_volume": 100.0,
        "signed_notional": 10_000.0,
        "session": "REGULAR",
        "is_block_trade": False,
        "is_off_exchange": False,
        "sequence_number": 1,
        **provenance(SourceTier.CONFIRMED_TRADE_PRINT, timestamp_as_of, source_id=source_id),
    }
