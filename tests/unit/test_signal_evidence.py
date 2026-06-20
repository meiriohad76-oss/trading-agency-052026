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


class FakeOptionsLoader(FakePriceLoader):
    def option_chains(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        rows = [
            {
                "ticker": "AAPL",
                "snapshot_date": as_of.isoformat(),
                "option_type": "call",
                "volume": 500,
                "open_interest": 1_000,
                "implied_volatility": 0.45,
                "bid": 2.0,
                "ask": 2.2,
                "last_price": 2.1,
                "timestamp_as_of": AS_OF,
            },
            {
                "ticker": "AAPL",
                "snapshot_date": as_of.isoformat(),
                "option_type": "put",
                "volume": 100,
                "open_interest": 900,
                "implied_volatility": 0.42,
                "bid": 1.0,
                "ask": 1.2,
                "last_price": 1.1,
                "timestamp_as_of": AS_OF,
            },
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


class FakePreMarketUnusualTradeLoader:
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        prior_day = as_of - timedelta(days=1)
        rows = [
            *_trade_rows(
                "AAPL",
                prior_day,
                count=2,
                notional=10_000.0,
                direction=-1,
                session="PRE_MARKET",
            ),
            *_trade_rows(
                "AAPL",
                prior_day,
                count=6,
                notional=20_000.0,
                direction=1,
            ),
            *_trade_rows(
                "AAPL",
                as_of,
                count=8,
                notional=10_000.0,
                direction=1,
                session="PRE_MARKET",
            ),
            *_trade_rows(
                "AAPL",
                as_of,
                count=6,
                notional=40_000.0,
                direction=-1,
            ),
        ]
        return pl.DataFrame(rows).filter(pl.col("ticker").is_in(tickers))


class FakeTrendMarketFlowLoader:
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        prior_two = as_of - timedelta(days=2)
        prior_one = as_of - timedelta(days=1)
        rows = [
            *_trade_rows("AAPL", prior_two, count=3, notional=10_000.0, direction=-1),
            *_trade_rows("AAPL", prior_one, count=3, notional=10_000.0, direction=-1),
            *_trade_rows("AAPL", as_of, count=6, notional=25_000.0, direction=1),
        ]
        return pl.DataFrame(rows).filter(pl.col("ticker").is_in(tickers))


class FakeNewsLoader:
    def news(
        self,
        as_of: date,
        lookback_days: int,
        tickers: list[str] | None = None,
    ) -> list[dict[str, object]]:
        del as_of, lookback_days
        rows = [
            {
                "ticker": "AAPL",
                "title": "AAPL raises outlook after earnings beat",
                "summary": "Management raises outlook for the year.",
                "feed_name": "RSS Guidance",
                "ticker_match_status": "resolved",
                "ticker_match_confidence": 0.8,
                "source_id": "rss-guidance-aapl",
            },
            {
                "ticker": "AAPL",
                "title": "AAPL faces lawsuit probe",
                "summary": "Regulatory probe creates legal risk.",
                "feed_name": "RSS Legal",
                "ticker_match_status": "resolved",
                "ticker_match_confidence": 1.0,
                "source_id": "rss-legal-aapl",
            },
        ]
        wanted = {ticker.upper() for ticker in tickers or []}
        return [row for row in rows if not wanted or str(row["ticker"]).upper() in wanted]


class FakeInsiderLoader:
    def insider_transactions(
        self,
        ticker: str,
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        del as_of, lookback_days
        if ticker.upper() == "AAPL":
            return [
                {
                    "transaction_type": "P",
                    "shares": 2_000,
                    "price": 100.0,
                    "filer_name": "Jane CFO",
                    "transaction_date": "2026-05-06",
                },
                {
                    "transaction_type": "S",
                    "shares": 500,
                    "price": 110.0,
                    "filer_name": "John Director",
                    "transaction_date": "2026-05-07",
                },
            ]
        if ticker.upper() == "MSFT":
            return [
                {
                    "transaction_type": "S",
                    "shares": 100,
                    "price": 100.0,
                    "filer_name": "MSFT Insider",
                    "transaction_date": "2026-05-07",
                }
            ]
        return []


class FakeInstitutionalLoader:
    def institutional_holdings(self, ticker: str, as_of: date) -> object:
        del as_of
        assert ticker.upper() == "AAPL"
        return _ProvenancedValue(
            {
                "quarter_end_date": date(2025, 12, 31),
                "holder_count": 4,
                "total_shares_held": 1_000.0,
                "previous_shares_held": 700.0,
                "total_change_from_prev_quarter": 300.0,
                "net_change_current_share_ratio": 0.30,
                "net_change_prior_share_ratio": 300.0 / 700.0,
                "total_value_usd_thousands": 100.0,
                "implied_value_per_share": 100.0,
                "holder_changes": [
                    {
                        "holder_name": "Alpha Capital",
                        "holder_cik": "0001",
                        "current_shares": 600.0,
                        "previous_shares": 350.0,
                        "change_from_prev_quarter": 250.0,
                        "value_usd_thousands": 60.0,
                        "implied_value_per_share": 100.0,
                    },
                    {
                        "holder_name": "Beta Partners",
                        "holder_cik": "0002",
                        "current_shares": 400.0,
                        "previous_shares": 350.0,
                        "change_from_prev_quarter": 50.0,
                        "value_usd_thousands": 40.0,
                        "implied_value_per_share": 100.0,
                    },
                ],
            }
        )


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
    assert "median of 2 prior daily bars" in row["trigger_headline"]
    assert "price increased +3.0%" in row["trigger_headline"]
    assert "60-day price lookback" in row["trigger_detail"]
    assert "accumulation pressure" in row["trigger_detail"]
    assert "2026-05-08" in row["trigger_window"]
    assert labels["Latest volume"]["value"] == "500"
    assert labels["Baseline volume"]["value"] == "100"
    assert labels["Baseline window"]["value"] == "2 bars"
    assert "median, not a simple average" in labels["Baseline window"]["detail"]
    assert labels["Volume ratio"]["value"] == "5.00x"
    assert labels["Latest return"]["value"] == "+3.0%"
    assert "same daily bar as the abnormal volume" in labels["Latest return"]["detail"]
    assert row["sort_direction"] == BULLISH_SORT_VALUE
    assert row["inspect_id"].startswith("signal-inspect-0-aapl-abnormal-volume")


def test_signal_inspector_rewrites_table_text_with_hard_evidence() -> None:
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
            "summary": "Abnormal volume was constructive.",
            "bucket": "Actionable",
            "report_action": "WATCH",
            "report_conviction_pct": 68,
            "report_gate_status": "PASS",
            "interpretation_text": "Abnormal Volume produced a bullish signal.",
            "decision_effect_text": "Included in latest evidence pack.",
            "quality_text": "Confirmed evidence.",
        }
    ]

    row = enrich_signal_rows_with_evidence(rows, loader=FakePriceLoader())[0]

    assert "latest volume was 5.00x the median" in row["interpretation_text"]
    assert "price increased +3.0%" in row["interpretation_text"]
    assert "Actionable signal for AAPL" in row["decision_effect_text"]
    assert "WATCH" in row["decision_effect_text"]
    assert "68%" in row["decision_effect_text"]
    assert "source data 2026-05-08 00:00 UTC" in row["quality_text"]
    assert row["interpretation_text"] != "Abnormal Volume produced a bullish signal."


def test_signal_inspector_overrides_generic_summary_with_trigger_headline() -> None:
    row = enrich_signal_rows_with_evidence(
        [
            _signal_row(
                "abnormal_volume",
                "Abnormal Volume",
                summary=(
                    "Abnormal Volume: direction bullish; no lane summary was persisted "
                    "for this row."
                ),
            )
        ],
        loader=FakePriceLoader(),
    )[0]

    assert row["summary"].startswith("AAPL triggered abnormal volume")
    assert "no lane summary was persisted" not in row["summary"]


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
    assert labels["Direction"]["value"] == "BULLISH"
    assert labels["Source as-of"]["value"] == "2026-05-08 00:00 UTC"


def test_signal_inspector_fallback_preserves_options_reason_and_provenance() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "options_flow",
            "lane": "Options Flow",
            "direction": "BULLISH",
            "source": "Options Provider / Optional",
            "source_id": "opt-aapl-1",
            "score": "+0.60 bullish",
            "score_value": 0.6,
            "summary": "Call premium exceeded put premium in the available chain sample.",
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": "2026-05-08T14:30:00+00:00",
            "confidence_pct": 40,
            "reason_codes_label": "Options Flow Bullish",
        }
    ]

    row = enrich_signal_rows_with_evidence(rows, loader=FakePriceLoader())[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}

    assert "Options Flow" in row["trigger_headline"]
    assert "Call premium exceeded put premium" in row["trigger_detail"]
    assert "call-side versus put-side premium" in row["trigger_detail"]
    assert "Detailed contract reconstruction" not in row["trigger_detail"]
    assert labels["Stored summary"]["value"] == (
        "Call premium exceeded put premium in the available chain sample."
    )
    assert labels["Direction"]["value"] == "BULLISH"
    assert labels["Source ID"]["value"] == "opt-aapl-1"


def test_options_flow_inspector_reconstructs_call_put_metrics() -> None:
    row = enrich_signal_rows_with_evidence(
        [_signal_row("options_flow", "Options Flow")],
        loader=FakeOptionsLoader(),
    )[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}

    assert "call volume" in row["trigger_headline"].lower()
    assert labels["Call volume"]["value"] == "500"
    assert labels["Put volume"]["value"] == "100"
    assert labels["Put/call volume ratio"]["value"] == "0.20"


def test_options_anomaly_inspector_reconstructs_premium_and_oi_metrics() -> None:
    row = enrich_signal_rows_with_evidence(
        [_signal_row("options_anomaly", "Options Anomaly")],
        loader=FakeOptionsLoader(),
    )[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}

    assert "option premium" in row["trigger_headline"].lower()
    assert labels["Call premium"]["value"].startswith("$")
    assert labels["Put premium"]["value"].startswith("$")
    assert "volume divided by open interest" in labels["Volume/OI"]["detail"]


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


def test_signal_inspector_explains_technical_analysis_driver_metrics() -> None:
    rows = [_signal_row("technical_analysis", "Technical Analysis")]

    enriched = enrich_signal_rows_with_evidence(rows, loader=CountingTechnicalPriceLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "close" in row["trigger_headline"].lower()
    assert "SMA20/SMA50/SMA200" in labels["SMA levels"]["detail"]
    assert labels["Price vs SMA stack"]["detail"].startswith("Latest close")
    assert "trend" in labels["Driver mix"]["detail"]
    assert "momentum" in labels["Driver mix"]["detail"]
    assert "trade pressure" in labels["Driver mix"]["detail"]
    assert labels["Volatility risk"]["detail"].startswith("ATR")
    assert "sma20_50_200_trend" in labels["Methodology"]["detail"]


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
    assert "1 focused large/off-exchange print" in row["trigger_headline"]
    assert "$250.0K buy-leaning focused notional" in row["trigger_headline"]
    assert "92.6% of analyzed notional" in row["trigger_headline"]
    assert "bullish because focused block/off-exchange notional was buy-leaning" in row[
        "trigger_detail"
    ]
    assert "not proof of a dark-pool venue" in row["trigger_detail"]
    assert labels["TRF/off-exchange"]["value"] == "1 / $250.0K"
    assert labels["Largest focused print"]["value"] == "$250.0K"
    assert labels["Largest multiple"]["value"] == "25.00x"
    assert labels["Focused notional"]["value"] == "$250.0K"
    assert "92.6% of all analyzed notional" in labels["Focused notional"]["detail"]
    assert labels["Directional read"]["value"] == "buy-leaning"
    assert "+$250.0K signed focused notional" in labels["Directional read"]["detail"]
    assert labels["Analyzed volume"]["value"] == "2,700"
    assert labels["Average print price"]["value"] == "$100.00"
    assert "not the largest block price" in labels["Average print price"]["detail"]
    assert "absolute floor and 5x ticker median" in labels["Threshold basis"]["detail"]


def test_signal_inspector_explains_buy_sell_pressure_notional_and_off_exchange_scope() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "buy_sell_pressure",
            "lane": "Buy/Sell Pressure",
            "direction": "BULLISH",
            "source": "Massive Live Trade Slices",
            "score": "+0.80 bullish",
            "score_value": 0.8,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 70,
            "reason_codes_label": "Buy Sell Pressure Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeMarketFlowLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "AAPL buy/sell pressure is bullish" in row["trigger_headline"]
    assert "$270.0K total analyzed notional" in row["trigger_headline"]
    assert "not off-exchange-only" in row["trigger_headline"]
    assert "buy-leaning signed notional" in row["trigger_headline"]
    assert "trade signing inference" in row["trigger_detail"]
    assert "not a confirmed buyer identity" in row["trigger_detail"]
    assert labels["Total analyzed notional"]["value"] == "$270.0K"
    assert "all delayed prints, not off-exchange-only dollars" in labels[
        "Total analyzed notional"
    ]["detail"]
    assert labels["Signed notional"]["value"] == "+$270.0K"
    assert labels["Inferred buy/sell notional"]["value"] == "$270.0K / $0.00"
    assert labels["Large/off-exchange subset"]["value"] == "$250.0K"
    assert "subset of total analyzed notional" in labels["Large/off-exchange subset"]["detail"]
    assert labels["Block / off-exchange counts"]["value"] == "1 / 1"
    assert "counts, not dollar amount" in labels["Block / off-exchange counts"]["detail"]


def test_signal_inspector_explains_market_flow_trend_pressure_delta() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "market_flow_trend",
            "lane": "Market Flow Trend",
            "direction": "BULLISH",
            "source": "Massive Live Trade Slices",
            "score": "+0.50 bullish",
            "score_value": 0.5,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 70,
            "reason_codes_label": "Market Flow Trend Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeTrendMarketFlowLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "latest signed notional pressure" in row["trigger_headline"]
    assert labels["Latest pressure"]["value"] == "+100.0%"
    assert labels["Prior pressure median"]["value"] == "-100.0%"
    assert labels["Pressure delta"]["value"] == "+200.0%"
    assert "latest pressure minus prior median pressure" in labels["Pressure delta"]["detail"]
    assert "Trend participation" in labels


def test_signal_inspector_explains_news_taxonomy_and_confidence_weighting() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "news",
            "lane": "News",
            "direction": "BEARISH",
            "source": "RSS News",
            "score": "-0.30 bearish",
            "score_value": -0.3,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 55,
            "reason_codes_label": "News Bearish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeNewsLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "dominant event guidance" in row["trigger_headline"]
    assert labels["Weighted headlines"]["value"] == "1.80"
    assert "confidence-weighted ticker matches" in labels["Weighted headlines"]["detail"]
    assert labels["Match confidence"]["value"] == "90.0%"
    assert "guidance: 1" in labels["Event mix"]["detail"]
    assert "litigation regulatory: 1" in labels["Event mix"]["detail"]
    assert "rss-guidance-aapl" in labels["Source IDs"]["detail"]
    assert "keyword taxonomy" in row["trigger_detail"].lower()
    assert "not full article llm sentiment" in row["trigger_detail"].lower()


def test_signal_inspector_explains_insider_buys_sells_and_lookback() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "insider",
            "lane": "Insider",
            "direction": "BULLISH",
            "source": "SEC Form 4",
            "score": "+1.00 bullish",
            "score_value": 1.0,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": AS_OF.isoformat(),
            "confidence_pct": 75,
            "reason_codes_label": "Insider Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeInsiderLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "purchase value $200.0K versus sale value $55.0K" in row["trigger_headline"]
    assert "90-day Form 4 lookback" in row["trigger_detail"]
    assert labels["Buy / sell value"]["value"] == "$200.0K / $55.0K"
    assert labels["Net value"]["value"] == "$145.0K"
    assert labels["Directional transactions"]["value"] == "2"
    assert "purchase(s), 1 sale(s)" in labels["Directional transactions"]["detail"]
    assert labels["Largest purchase"]["value"] == "$200.0K"
    assert labels["Latest transaction"]["value"] == "2026-05-07"


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
    assert labels["Most unusual metric"]["value"] == "Notional and share volume"
    assert "$240.0K latest vs $20.0K median" in labels["Most unusual metric"]["detail"]
    assert "share volume 2,400 latest vs 200 median" in labels["Most unusual metric"]["detail"]
    assert labels["What was identified"]["detail"] == (
        "The agent checks latest-period trade count, dollar notional, and share volume "
        "against this ticker's recent median baseline."
    )
    assert labels["Timing role"]["value"] == "Latest activity period"
    assert "not a clock-time anomaly" in labels["Timing role"]["detail"]
    assert labels["Block/off-exchange role"]["value"] == "0 block / 0 off-exchange"
    assert "separate block-trade signal" in labels["Block/off-exchange role"]["detail"]
    assert labels["Trade count anomaly"]["value"] == "4.00x"
    assert labels["Trade count anomaly"]["detail"] == (
        "8 latest-period trades versus 2 median baseline trades."
    )
    assert labels["Notional anomaly"]["value"] == "12.00x"
    assert labels["Notional anomaly"]["detail"] == (
        "$240.0K latest-period notional versus $20.0K median baseline notional."
    )
    assert labels["Volume anomaly"]["detail"] == (
        "2,400 latest-period shares versus 200 median baseline shares."
    )
    assert labels["Net notional pressure"]["value"] == "+100.0%"
    assert "inferred buy notional $240.0K versus sell notional $0.00" in labels[
        "Net notional pressure"
    ]["detail"]
    assert "buy-side share 100.0%; sell-side share 0.0%" in labels[
        "Net notional pressure"
    ]["detail"]
    assert "large focused prints" not in labels["Net notional pressure"]["detail"]
    assert "trade-signing inference" in labels["Net notional pressure"]["detail"]


def test_signal_inspector_explains_pre_market_unusual_activity_baseline() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "pre_market_unusual_activity",
            "lane": "Pre-Market Unusual Activity",
            "direction": "BULLISH",
            "source": "Massive Premarket Trade Slices / Derived Trade Activity",
            "score": "+1.60 bullish",
            "score_value": 1.6,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": "2026-05-08T09:15:00+00:00",
            "confidence_pct": 82,
            "reason_codes_label": "Pre-Market Unusual Activity Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(
        rows,
        loader=FakePreMarketUnusualTradeLoader(),
    )

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "pre-market unusual activity" in row["trigger_headline"]
    assert "pre-market volume 4.00x" in row["trigger_headline"]
    assert "pre-market notional 4.00x" in row["trigger_headline"]
    assert "pre-market pressure +100.0% buy-leaning" in row["trigger_headline"]
    assert "pre-market signed notional was +$80.0K" in row["trigger_detail"]
    assert labels["What was identified"]["detail"] == (
        "The agent checks pre-market trade count, dollar notional, and share volume "
        "against this ticker's recent pre-market median baseline."
    )
    assert labels["Pre-market notional anomaly"]["value"] == "4.00x"
    assert labels["Pre-market notional anomaly"]["detail"] == (
        "$80.0K latest pre-market notional versus $20.0K median pre-market baseline."
    )
    assert labels["Pre-market volume anomaly"]["value"] == "4.00x"
    assert labels["Pre-market volume anomaly"]["detail"] == (
        "800 latest pre-market shares versus 200 median pre-market baseline shares."
    )
    assert labels["Pre-market pressure"]["value"] == "+100.0%"
    assert "buy-side share 100.0%" in labels["Pre-market pressure"]["detail"]
    assert "Net notional pressure" not in labels
    assert "Notional anomaly" not in labels


def test_institutional_signal_inspector_names_holder_changes_and_ratio_basis() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "lane_key": "institutional",
            "lane": "Institutional Flow",
            "direction": "BULLISH",
            "source": "Sec 13F / Official Filing",
            "score": "+1.20 bullish",
            "score_value": 1.2,
            "signal_as_of": AS_OF.isoformat(),
            "timestamp_as_of": "2026-02-17T00:00:00+00:00",
            "confidence_pct": 80,
            "reason_codes_label": "Institutional Bullish",
        }
    ]

    enriched = enrich_signal_rows_with_evidence(rows, loader=FakeInstitutionalLoader())

    row = enriched[0]
    labels = {card["label"]: card for card in row["trigger_cards"]}
    assert "Alpha Capital" in row["trigger_headline"]
    assert "Beta Partners" in labels["Top holder changes"]["detail"]
    assert "+250" in labels["Top holder changes"]["detail"]
    assert labels["Previous shares"]["value"] == "700"
    assert labels["Position size change"]["value"] == "+30.0%"
    assert "not stock-price return" in labels["Position size change"]["detail"]
    assert labels["Prior-basis change"]["value"] == "+42.9%"
    assert "Implied value/share" not in labels


def _signal_row(lane_key: str, lane: str, *, summary: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {
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
    if summary is not None:
        row["summary"] = summary
    return row


class _ProvenancedValue:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value


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
    session: str = "REGULAR",
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
            "session": session,
            "is_block_trade": False,
            "is_off_exchange": False,
            "sequence_number": index,
            "source_id": f"{ticker}-{trade_date.isoformat()}-{index}",
            "timestamp_as_of": trade_date,
        }
        for index in range(count)
    ]
