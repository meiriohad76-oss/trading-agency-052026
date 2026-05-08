from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from signals.options_anomaly import options_anomaly_frame, options_anomaly_score

AS_OF = date(2026, 5, 8)
LOOKBACK_DAYS = 7
EXPECTED_UNUSUAL_CONTRACTS = 2


def test_options_anomaly_score_rewards_large_call_premium_and_penalizes_puts() -> None:
    loader = _FakeOptionsLoader(
        [
            _option("AAPL", "call", volume=500, open_interest=100, bid=2.0, ask=2.2),
            _option("AAPL", "put", volume=20, open_interest=100, bid=1.0, ask=1.2),
            _option("MSFT", "call", volume=50, open_interest=100, bid=1.0, ask=1.2),
            _option("MSFT", "put", volume=500, open_interest=100, bid=2.0, ask=2.2),
        ]
    )

    scores = options_anomaly_score(AS_OF, {"msft", "aapl"}, loader)

    assert list(scores) == ["AAPL", "MSFT"]
    assert scores["AAPL"] > scores["MSFT"]


def test_options_anomaly_frame_tracks_unusual_contracts_and_premium() -> None:
    loader = _FakeOptionsLoader(
        [
            _option("AAPL", "call", volume=500, open_interest=100, bid=2.0, ask=2.0),
            _option("AAPL", "call", volume=150, open_interest=0, bid=1.0, ask=1.0),
            _option("AAPL", "put", volume=10, open_interest=100, bid=1.0, ask=1.0),
        ]
    )

    frame = options_anomaly_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["unusual_contract_count"] == EXPECTED_UNUSUAL_CONTRACTS
    assert frame.iloc[0]["call_premium"] == pytest.approx(115_000.0)
    assert frame.iloc[0]["options_anomaly_score"] == pytest.approx(0.0)


def test_options_anomaly_score_is_empty_without_chain_coverage() -> None:
    loader = _FailingOptionsLoader()

    assert options_anomaly_score(AS_OF, {"AAPL"}, loader) == {}


class _FakeOptionsLoader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[list[str], date, int]] = []

    def option_chains(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        self.calls.append((tickers, as_of, lookback_days))
        requested = set(tickers)
        return pl.DataFrame([row for row in self._rows if row["ticker"] in requested])


class _FailingOptionsLoader:
    def option_chains(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del tickers, as_of, lookback_days
        raise RuntimeError("no coverage")


def _option(
    ticker: str,
    option_type: str,
    *,
    volume: int,
    open_interest: int,
    bid: float,
    ask: float,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "snapshot_date": AS_OF,
        "expiration": date(2026, 6, 19),
        "option_type": option_type,
        "strike": 100.0,
        "last_price": 0.0,
        "bid": bid,
        "ask": ask,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": 0.3,
    }
