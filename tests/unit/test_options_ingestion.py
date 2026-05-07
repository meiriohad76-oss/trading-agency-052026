from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
from options.puller import pull_option_chains
from options.yfinance_options import normalize_options
from pit.manifest import DatasetName
from pit_fixtures import loader_with, provenance

from agency.provenance import SourceTier

FETCHED_AT = datetime(2026, 5, 7, 8, 0, tzinfo=UTC)
RAW_OPTION_ROWS = 2


def test_normalize_options_adds_forward_snapshot_provenance() -> None:
    frame = normalize_options(
        "aapl",
        _raw_options(call_volume=100, put_volume=20),
        fetched_at=FETCHED_AT,
    )

    assert set(frame["option_type"]) == {"call", "put"}
    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["source_tier"] == SourceTier.MARKET_DATA.value
    assert frame.iloc[0]["snapshot_date"] == FETCHED_AT.date()


async def test_pull_option_chains_writes_partitioned_parquet_and_manifest(tmp_path: Path) -> None:
    data_root = tmp_path / "options_chains"
    manifest_path = tmp_path / "options_chains.json"

    async def downloader(ticker: str) -> pd.DataFrame:
        assert ticker == "AAPL"
        return _raw_options(call_volume=100, put_volume=20)

    summary = await pull_option_chains(
        tickers=["aapl"],
        data_root=data_root,
        manifest_path=manifest_path,
        downloader=downloader,
        clock=lambda: FETCHED_AT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert summary.rows_written == RAW_OPTION_ROWS
    assert (data_root / "ticker=AAPL" / "options.parquet").is_file()
    assert manifest["dataset"] == "options_chains"


def test_pit_loader_filters_option_chains_by_snapshot_and_ticker(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            _option("AAPL", date(2026, 5, 5), "call", 100),
            _option("AAPL", date(2026, 5, 7), "call", 999),
            _option("MSFT", date(2026, 5, 5), "call", 100),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.OPTIONS_CHAINS: frame})

    result = loader.option_chains(["AAPL"], date(2026, 5, 6), lookback_days=2)

    assert result.get_column("volume").to_list() == [100]


def _raw_options(*, call_volume: int, put_volume: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _raw_option("2026-06-19", "call", 100.0, call_volume),
            _raw_option("2026-06-19", "put", 100.0, put_volume),
        ]
    )


def _raw_option(expiration: str, option_type: str, strike: float, volume: int) -> dict[str, object]:
    return {
        "expiration": expiration,
        "option_type": option_type,
        "strike": strike,
        "lastPrice": 1.5,
        "bid": 1.4,
        "ask": 1.6,
        "volume": volume,
        "openInterest": volume * 2,
        "impliedVolatility": 0.3,
        "inTheMoney": False,
    }


def _option(ticker: str, snapshot: date, option_type: str, volume: int) -> dict[str, object]:
    return {
        "ticker": ticker,
        "snapshot_date": snapshot,
        "expiration": date(2026, 6, 19),
        "option_type": option_type,
        "strike": 100.0,
        "last_price": 1.5,
        "bid": 1.4,
        "ask": 1.6,
        "volume": volume,
        "open_interest": volume * 2,
        "implied_volatility": 0.3,
        "in_the_money": False,
        **provenance(SourceTier.MARKET_DATA, snapshot, source_id=f"{ticker}-{snapshot}"),
    }
