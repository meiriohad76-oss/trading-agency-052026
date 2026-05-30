from __future__ import annotations

from datetime import date, timedelta

import polars as pl
from pit.exceptions import DataNotAvailableAt

from agency.runtime.signal_evidence import enrich_signal_rows_with_evidence

AS_OF = date(2026, 5, 8)
BULLISH_SORT_VALUE = 2


class FakePriceLoader:
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del as_of, lookback_days
        rows = [
            *_price_rows("AAPL", volumes=[100.0, 100.0, 500.0], closes=[100.0, 101.0, 104.0]),
            *_price_rows("MSFT", volumes=[100.0, 100.0, 100.0], closes=[100.0, 99.0, 98.0]),
        ]
        return pl.DataFrame(rows).filter(pl.col("ticker").is_in(tickers))


class BrokenPriceLoader:
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del tickers, as_of, lookback_days
        raise RuntimeError("price detail unavailable")


class FakeMarketFlowLoader:
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        rows = [
            {
                "ticker": "AAPL",
                "trade_date": as_of,
                "trade_ts": f"{as_of.isoformat()}T14:00:00Z",
                "price": 100.0,
                "size": 100.0,
                "notional": 10_000.0,
                "direction": 1,
                "signed_volume": 100.0,
                "signed_notional": 10_000.0,
                "session": "REGULAR",
                "is_block_trade": False,
                "is_off_exchange": False,
                "is_trf_off_exchange": False,
                "trf_venue": "",
                "sequence_number": 1,
                "source_id": "baseline",
                "timestamp_as_of": as_of,
            },
            {
                "ticker": "AAPL",
                "trade_date": as_of,
                "trade_ts": f"{as_of.isoformat()}T14:01:00Z",
                "price": 100.0,
                "size": 2_500.0,
                "notional": 250_000.0,
                "direction": 1,
                "signed_volume": 2_500.0,
                "signed_notional": 250_000.0,
                "session": "REGULAR",
                "is_block_trade": True,
                "is_off_exchange": True,
                "is_trf_off_exchange": True,
                "trf_venue": "FINRA/NASDAQ TRF Carteret",
                "sequence_number": 2,
                "source_id": "trf",
                "timestamp_as_of": as_of,
            },
            {
                "ticker": "AAPL",
                "trade_date": as_of,
                "trade_ts": f"{as_of.isoformat()}T14:02:00Z",
                "price": 100.0,
                "size": 100.0,
                "notional": 10_000.0,
                "direction": 1,
                "signed_volume": 100.0,
                "signed_notional": 10_000.0,
                "session": "REGULAR",
                "is_block_trade": False,
                "is_off_exchange": False,
                "is_trf_off_exchange": False,
                "trf_venue": "",
                "sequence_number": 3,
                "source_id": "baseline-2",
                "timestamp_as_of": as_of,
            },
        ]
        return pl.DataFrame(rows).filter(pl.col("ticker").is_in(tickers))


class KnowledgeCutoffMarketFlowLoader:
    def __init__(self) -> None:
        self.trade_window_calls: list[tuple[date, date, int, tuple[str, ...]]] = []

    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        del tickers, lookback_days
        raise DataNotAvailableAt("stock_trades", as_of, "requires later knowledge cutoff")

    def complete_stock_trade_tickers(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> tuple[str, ...]:
        del as_of, lookback_days
        assert allow_partial_coverage is True
        return tuple(ticker for ticker in tickers if ticker.upper() != "BA")

    def stock_trade_activity_frames_for_trade_window(
        self,
        tickers: list[str],
        *,
        trade_end: date,
        knowledge_as_of: date,
        lookback_days: int,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        normalized = tuple(sorted(ticker.upper() for ticker in tickers))
        assert allow_partial_coverage is True
        self.trade_window_calls.append((trade_end, knowledge_as_of, lookback_days, normalized))
        total = pl.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "trade_count": 3,
                    "total_volume": 2_700.0,
                    "total_notional": 270_000.0,
                    "signed_volume": 2_700.0,
                    "signed_notional": 270_000.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_volume": 0.0,
                    "focus_trade_count": 1,
                    "absolute_block_count": 1,
                    "relative_block_count": 1,
                    "block_count": 1,
                    "off_exchange_count": 1,
                    "trf_off_exchange_count": 1,
                    "trf_off_exchange_notional": 250_000.0,
                    "large_print_count": 1,
                    "large_print_notional": 250_000.0,
                    "block_notional_threshold": 250_000.0,
                    "block_size_threshold": 10_000.0,
                    "focus_notional": 250_000.0,
                    "signed_focus_notional": 250_000.0,
                    "largest_focus_notional": 250_000.0,
                    "largest_focus_notional_multiple": 25.0,
                    "net_volume_pressure": 1.0,
                    "net_notional_pressure": 1.0,
                }
            ]
        )
        daily = pl.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "date": trade_end,
                    "trade_count": 3,
                    "notional": 270_000.0,
                    "volume": 2_700.0,
                    "signed_notional": 270_000.0,
                    "pre_market_count": 0,
                    "pre_market_notional": 0.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_notional": 0.0,
                    "net_notional_pressure": 1.0,
                    "pre_market_pressure": 0.0,
                }
            ]
        )
        return total.filter(pl.col("ticker").is_in(normalized)), daily

    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del tickers, lookback_days
        raise DataNotAvailableAt("stock_trades", as_of, "raw rows are not used")


class FakeUnusualTradeLoader:
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        prior_day = as_of - timedelta(days=1)
        rows = [
            *_trade_rows("AAPL", prior_day, count=2, notional=10_000.0, direction=-1),
            *_trade_rows("AAPL", as_of, count=8, notional=30_000.0, direction=1),
        ]
        return pl.DataFrame(rows).filter(pl.col("ticker").is_in(tickers))


class CountingTechnicalPriceLoader:
    def __init__(self) -> None:
        self.price_calls = 0

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        self.price_calls += 1
        start = as_of - timedelta(days=lookback_days - 1)
        rows = []
        for ticker in tickers:
            for offset in range(lookback_days):
                close = 100.0 + offset
                rows.append(
                    {
                        "ticker": ticker.upper(),
                        "date": start + timedelta(days=offset),
                        "open": close - 0.5,
                        "high": close + 1.0,
                        "low": close - 1.0,
                        "close": close,
                        "volume": 1_000_000 + offset,
                        "timestamp_as_of": start + timedelta(days=offset),
                    }
                )
        return pl.DataFrame(rows)

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del tickers, as_of, lookback_days
        raise DataNotAvailableAt("stock_trades", AS_OF, "not needed for this unit test")


def test_abnormal_volume_signal_inspector_explains_trigger_metrics() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "abnormal_volume",
            "lane": "Abnormal Volume",
            "direction": "BULLISH",
            "source": "Daily Market Bars / Inferred From Bars",
            "score": "+2.00 bullish",
            "score_value": 2.0,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 70,
            "reason_codes_label": "Abnormal Volume Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakePriceLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "AAPL triggered abnormal volume" in row["trigger_headline"]
    assert "5.00x" in row["trigger_headline"]
    assert "accumulation pressure" in row["trigger_detail"]
    assert "2026-05-08" in row["trigger_window"]
    assert labels["Latest volume"]["value"] == "500"
    assert labels["Baseline volume"]["value"] == "100"
    assert labels["Volume ratio"]["value"] == "5.00x"
    assert labels["Latest return"]["value"] == "+3.0%"
    assert row["sort_direction"] == BULLISH_SORT_VALUE
    assert row["inspect_id"].startswith("signal-inspect-0-aapl-abnormal-volume")


def test_signal_inspector_marks_detail_reconstruction_failures() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "abnormal_volume",
            "lane": "Abnormal Volume",
            "direction": "BULLISH",
            "source": "Daily Market Bars / Inferred From Bars",
            "score": "+2.00 bullish",
            "score_value": 2.0,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 70,
            "reason_codes_label": "Abnormal Volume Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=BrokenPriceLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "Local metric reconstruction failed" in row["trigger_detail"]
    assert labels["Reconstruction"]["value"] == "Unavailable"
    assert "RuntimeError" in labels["Reconstruction"]["detail"]


def test_signal_inspector_reuses_wide_price_window_for_daily_bar_lanes() -> None:
    loader = CountingTechnicalPriceLoader()
    rows = [
        _signal_row("technical_analysis", "Technical Analysis"),
        _signal_row("abnormal_volume", "Abnormal Volume"),
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=loader)

    assert loader.price_calls == 1
    assert len(enriched) == 2
    assert enriched[0]["trigger_cards"]
    assert "AAPL triggered abnormal volume" in enriched[1]["trigger_headline"]


def test_signal_inspector_explains_trf_off_exchange_block_evidence() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "block_trade_pressure",
            "lane": "Block Trade Pressure",
            "direction": "BULLISH",
            "source": "Massive Live Trade Slices / Derived Block Feed",
            "score": "+1.00 bullish",
            "score_value": 1.0,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 70,
            "reason_codes_label": "Block Trade Pressure",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeMarketFlowLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "TRF/off-exchange" in row["trigger_headline"]
    assert "not proof of a dark-pool venue" in row["trigger_detail"]
    assert labels["TRF/off-exchange"]["value"] == "1 / $250.0K"
    assert labels["Largest focused print"]["value"] == "$250.0K"
    assert labels["Largest multiple"]["value"] == "25.00x"


def test_signal_inspector_reconstructs_trade_session_with_later_source_timestamp() -> None:
    loader = KnowledgeCutoffMarketFlowLoader()
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "block_trade_pressure",
            "lane": "Block Trade Pressure",
            "direction": "BULLISH",
            "source": "Massive Live Trade Slices / Derived Block Feed",
            "score": "+1.00 bullish",
            "score_value": 1.0,
            "signal_as_of": "2026-05-29",
            "timestamp_as_of": "2026-05-30T08:43:39+00:00",
            "confidence_pct": 70,
            "reason_codes_label": "Block Trade Pressure",
        },
        {
            "ticker": "BA",
            "lane_key": "block_trade_pressure",
            "lane": "Block Trade Pressure",
            "direction": "BULLISH",
            "source": "Massive Live Trade Slices / Derived Block Feed",
            "score": "+0.80 bullish",
            "score_value": 0.8,
            "signal_as_of": "2026-05-29",
            "timestamp_as_of": "2026-05-30T08:43:39+00:00",
            "confidence_pct": 70,
            "reason_codes_label": "Block Trade Pressure",
        },
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=loader)

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert loader.trade_window_calls == [
        (date(2026, 5, 29), date(2026, 5, 30), 3, ("AAPL",))
    ]
    assert "TRF/off-exchange" in row["trigger_headline"]
    assert labels["Largest multiple"]["value"] == "25.00x"


def test_signal_inspector_explains_unusual_trade_identification() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "unusual_trade_activity",
            "lane": "Unusual Trade Activity",
            "direction": "BULLISH",
            "source": "Massive Live Trade Slices / Derived Trade Activity",
            "score": "+1.40 bullish",
            "score_value": 1.4,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": "2026-05-08T14:15:00+00:00",
            "confidence_pct": 82,
            "reason_codes_label": "Unusual Trade Activity Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeUnusualTradeLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "AAPL identified unusual trade activity" in row["trigger_headline"]
    assert "bullish" in row["trigger_detail"]
    assert labels["What was identified"]["value"] == "Strong unusual trade activity"
    assert labels["Data source"]["value"] == "Massive Live Trade Slices / Derived Trade Activity"
    assert labels["Evidence time"]["value"] == "2026-05-08 14:15 UTC"
    assert labels["Conviction"]["value"] == "82%"
    assert labels["Meaning"]["value"] == "Bullish"
    assert labels["Trade count anomaly"]["value"] == "4.00x"
    assert labels["Notional anomaly"]["value"] == "12.00x"
    assert labels["Net notional pressure"]["value"] == "+100.0%"


def _signal_row(lane_key: str, lane: str) -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "lane_key": lane_key,
        "lane": lane,
        "direction": "BULLISH",
        "source": "Daily Market Bars / Inferred From Bars",
        "score": "+1.00 bullish",
        "score_value": 1.0,
        "signal_as_of": AS_OF.isoformat(),
        "timestamp_as_of": AS_OF.isoformat(),
        "confidence_pct": 70,
        "reason_codes_label": lane,
    }


def _price_rows(
    ticker: str,
    *,
    volumes: list[float],
    closes: list[float],
) -> list[dict[str, object]]:
    start = AS_OF - timedelta(days=len(volumes) - 1)
    return [
        {
            "ticker": ticker,
            "date": start + timedelta(days=offset),
            "close": closes[offset],
            "volume": volumes[offset],
            "timestamp_as_of": start + timedelta(days=offset),
        }
        for offset in range(len(volumes))
    ]


def _trade_rows(
    ticker: str,
    trade_date: date,
    *,
    count: int,
    notional: float,
    direction: int,
) -> list[dict[str, object]]:
    size = notional / 100.0
    return [
        {
            "ticker": ticker,
            "trade_date": trade_date,
            "trade_ts": f"{trade_date.isoformat()}T14:{index:02d}:00Z",
            "price": 100.0,
            "size": size,
            "notional": notional,
            "direction": direction,
            "signed_volume": direction * size,
            "signed_notional": direction * notional,
            "session": "REGULAR",
            "is_block_trade": False,
            "is_off_exchange": False,
            "sequence_number": index,
            "source_id": f"{ticker}-{trade_date.isoformat()}-{index}",
            "timestamp_as_of": trade_date,
        }
        for index in range(count)
    ]
