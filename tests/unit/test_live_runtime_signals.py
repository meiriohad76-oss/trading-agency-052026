from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from live_runtime.signals import _LiveStockTradeLoader, build_runtime_signals
from pit.manifest import DataManifest, DatasetName


def test_live_stock_trade_loader_falls_back_to_full_latest_slice_when_window_partial() -> None:
    loader = _WindowAwareTradeLoader()
    wrapped = _LiveStockTradeLoader(loader)

    wrapped.stock_trade_activity_frames(["AAPL", "MSFT"], date(2026, 5, 15), 3)

    assert loader.activity_requests == [(("AAPL", "MSFT"), date(2026, 5, 15), 1, True)]


def test_live_stock_trade_loader_uses_latest_slice_when_cycle_runs_on_weekend() -> None:
    loader = _WeekendAwareTradeLoader()
    wrapped = _LiveStockTradeLoader(loader)

    wrapped.stock_trade_activity_frames(["AAPL", "MSFT"], date(2026, 5, 17), 1)

    assert loader.activity_requests == [(("AAPL", "MSFT"), date(2026, 5, 15), 1, True)]


def test_live_stock_trade_loader_reads_latest_slice_with_runtime_knowledge_cutoff() -> None:
    loader = _KnowledgeWindowTradeLoader()
    wrapped = _LiveStockTradeLoader(loader)

    wrapped.stock_trade_activity_frames(["AAPL", "MSFT"], date(2026, 5, 22), 3)

    assert loader.window_requests == [
        (("AAPL", "MSFT"), date(2026, 5, 21), date(2026, 5, 22), 1, True)
    ]
    assert loader.activity_requests == []


def test_runtime_market_flow_zero_activity_rows_are_context_only() -> None:
    generated_at = date(2026, 5, 22)
    signals = build_runtime_signals(
        cycle_id="cycle-1",
        as_of=generated_at,
        as_of_text=generated_at.isoformat(),
        generated_at=_datetime_utc(2026, 5, 22, 21, 0),
        tickers={"AAPL", "BK"},
        lanes=("buy_sell_pressure",),
        loader=_ZeroActivityTradeLoader(),
        registry=_ManifestRegistry(),
    )
    by_ticker = {str(signal["ticker"]): signal for signal in signals}

    assert set(by_ticker) == {"AAPL", "BK"}
    assert by_ticker["BK"]["score"] == 0.0
    assert by_ticker["BK"]["direction"] == "NEUTRAL"
    assert by_ticker["BK"]["actionability"] == "CONTEXT_ONLY"
    assert by_ticker["BK"]["reason_codes"] == ["buy_sell_pressure_neutral"]


class _WindowAwareTradeLoader:
    def __init__(self) -> None:
        self.activity_requests: list[tuple[tuple[str, ...], date, int, bool]] = []

    def complete_stock_trade_tickers(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> list[str]:
        del as_of, allow_partial_coverage
        if lookback_days == 1:
            return sorted(tickers)
        return ["AAPL"]

    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        self.activity_requests.append(
            (tuple(sorted(tickers)), as_of, lookback_days, allow_partial_coverage)
        )
        return (
            pl.DataFrame(
                {
                    "ticker": tickers,
                    "trade_count": [1 for _ticker in tickers],
                    "total_volume": [100.0 for _ticker in tickers],
                    "total_notional": [1000.0 for _ticker in tickers],
                    "signed_volume": [10.0 for _ticker in tickers],
                    "signed_notional": [100.0 for _ticker in tickers],
                    "pre_market_volume": [0.0 for _ticker in tickers],
                    "pre_market_signed_volume": [0.0 for _ticker in tickers],
                    "focus_trade_count": [0 for _ticker in tickers],
                    "block_count": [0 for _ticker in tickers],
                    "off_exchange_count": [0 for _ticker in tickers],
                    "focus_notional": [0.0 for _ticker in tickers],
                    "signed_focus_notional": [0.0 for _ticker in tickers],
                }
            ),
            pl.DataFrame(
                {
                    "ticker": tickers,
                    "date": [as_of for _ticker in tickers],
                    "trade_count": [1 for _ticker in tickers],
                    "notional": [1000.0 for _ticker in tickers],
                    "volume": [100.0 for _ticker in tickers],
                    "signed_notional": [100.0 for _ticker in tickers],
                    "pre_market_count": [0 for _ticker in tickers],
                    "pre_market_notional": [0.0 for _ticker in tickers],
                    "pre_market_volume": [0.0 for _ticker in tickers],
                    "pre_market_signed_notional": [0.0 for _ticker in tickers],
                    "net_notional_pressure": [0.1 for _ticker in tickers],
                    "pre_market_pressure": [0.0 for _ticker in tickers],
                }
            ),
        )


class _WeekendAwareTradeLoader(_WindowAwareTradeLoader):
    def complete_stock_trade_tickers(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> list[str]:
        del lookback_days, allow_partial_coverage
        if as_of in {date(2026, 5, 15), date(2026, 5, 17)}:
            return sorted(tickers)
        return []


class _KnowledgeWindowTradeLoader(_WindowAwareTradeLoader):
    def __init__(self) -> None:
        super().__init__()
        self.window_requests: list[tuple[tuple[str, ...], date, date, int, bool]] = []

    def complete_stock_trade_tickers(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> list[str]:
        del allow_partial_coverage
        if as_of == date(2026, 5, 22):
            return ["AAPL"] if lookback_days > 1 else []
        if as_of == date(2026, 5, 21) and lookback_days == 1:
            return sorted(tickers)
        return []

    def stock_trade_activity_frames_for_trade_window(
        self,
        tickers: list[str],
        *,
        trade_end: date,
        knowledge_as_of: date,
        lookback_days: int,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        self.window_requests.append(
            (
                tuple(sorted(tickers)),
                trade_end,
                knowledge_as_of,
                lookback_days,
                allow_partial_coverage,
            )
        )
        return (
            pl.DataFrame(
                {
                    "ticker": tickers,
                    "trade_count": [1 for _ticker in tickers],
                    "total_volume": [100.0 for _ticker in tickers],
                    "total_notional": [1000.0 for _ticker in tickers],
                    "signed_volume": [10.0 for _ticker in tickers],
                    "signed_notional": [100.0 for _ticker in tickers],
                    "pre_market_volume": [0.0 for _ticker in tickers],
                    "pre_market_signed_volume": [0.0 for _ticker in tickers],
                    "focus_trade_count": [0 for _ticker in tickers],
                    "block_count": [0 for _ticker in tickers],
                    "off_exchange_count": [0 for _ticker in tickers],
                    "focus_notional": [0.0 for _ticker in tickers],
                    "signed_focus_notional": [0.0 for _ticker in tickers],
                }
            ),
            pl.DataFrame(
                {
                    "ticker": tickers,
                    "date": [trade_end for _ticker in tickers],
                    "trade_count": [1 for _ticker in tickers],
                    "notional": [1000.0 for _ticker in tickers],
                    "volume": [100.0 for _ticker in tickers],
                    "signed_notional": [100.0 for _ticker in tickers],
                    "pre_market_count": [0 for _ticker in tickers],
                    "pre_market_notional": [0.0 for _ticker in tickers],
                    "pre_market_volume": [0.0 for _ticker in tickers],
                    "pre_market_signed_notional": [0.0 for _ticker in tickers],
                    "net_notional_pressure": [0.1 for _ticker in tickers],
                    "pre_market_pressure": [0.0 for _ticker in tickers],
                }
            ),
        )


class _ZeroActivityTradeLoader(_WindowAwareTradeLoader):
    def complete_stock_trade_tickers(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> list[str]:
        del as_of, lookback_days, allow_partial_coverage
        return sorted(tickers)

    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        del lookback_days, allow_partial_coverage
        total_rows: list[dict[str, object]] = []
        daily_rows: list[dict[str, object]] = []
        if "AAPL" in tickers:
            total_rows.append(
                {
                    "ticker": "AAPL",
                    "trade_count": 1,
                    "total_volume": 100.0,
                    "total_notional": 1000.0,
                    "signed_volume": 10.0,
                    "signed_notional": 100.0,
                    "net_volume_pressure": 0.1,
                    "net_notional_pressure": 0.1,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_volume": 0.0,
                    "focus_trade_count": 0,
                    "block_count": 0,
                    "off_exchange_count": 0,
                    "focus_notional": 0.0,
                    "signed_focus_notional": 0.0,
                }
            )
            daily_rows.append(
                {
                    "ticker": "AAPL",
                    "date": as_of,
                    "trade_count": 1,
                    "notional": 1000.0,
                    "volume": 100.0,
                    "signed_notional": 100.0,
                    "pre_market_count": 0,
                    "pre_market_notional": 0.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_notional": 0.0,
                    "net_notional_pressure": 0.1,
                    "pre_market_pressure": 0.0,
                }
            )
        if "BK" in tickers:
            total_rows.append(
                {
                    "ticker": "BK",
                    "trade_count": 0,
                    "total_volume": 0.0,
                    "total_notional": 0.0,
                    "signed_volume": 0.0,
                    "signed_notional": 0.0,
                    "net_volume_pressure": 0.0,
                    "net_notional_pressure": 0.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_volume": 0.0,
                    "focus_trade_count": 0,
                    "block_count": 0,
                    "off_exchange_count": 0,
                    "focus_notional": 0.0,
                    "signed_focus_notional": 0.0,
                }
            )
        return pl.DataFrame(total_rows), pl.DataFrame(daily_rows)


class _ManifestRegistry:
    def require(
        self,
        dataset: DatasetName,
        *,
        as_of: date | None = None,
        allow_stale: bool = False,
    ) -> DataManifest:
        del as_of, allow_stale
        timestamp = _datetime_utc(2026, 5, 22, 20, 0)
        return DataManifest(
            dataset=dataset,
            path=Path("unused.parquet"),
            schema_version=1,
            row_count=1,
            checksum="a" * 64,
            fetched_at=timestamp,
            max_timestamp_as_of=timestamp,
            stale_after=_datetime_utc(2099, 1, 1, 0, 0),
            source_url=None,
            provider=None,
        )


def _datetime_utc(year: int, month: int, day: int, hour: int, minute: int):
    from datetime import UTC, datetime

    return datetime(year, month, day, hour, minute, tzinfo=UTC)
