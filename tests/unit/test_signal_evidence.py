from __future__ import annotations

from datetime import date, timedelta

import polars as pl

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
