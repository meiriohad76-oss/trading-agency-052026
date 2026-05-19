from __future__ import annotations

from datetime import date

import pytest
from pit.exceptions import DataNotAvailableAt
from signals.activity_alerts import activity_alert_frame, activity_alert_score

AS_OF = date(2026, 5, 8)
LOOKBACK_DAYS = 5
EXPECTED_SOURCE_COUNT = 2
EXPECTED_OPTIONS_ACTIVITY_COUNT = 1


def test_activity_alert_score_rewards_bullish_block_prints_and_penalizes_bearish() -> None:
    loader = _FakeActivityLoader(
        [
            _alert("AAPL", "block_trade", "BULLISH", notional=5_000_000.0),
            _alert("MSFT", "dark_pool", "BEARISH", notional=4_000_000.0),
        ]
    )

    scores = activity_alert_score(AS_OF, {"msft", "aapl"}, loader)

    assert scores["AAPL"] == pytest.approx(1.0)
    assert scores["MSFT"] < 0.0


def test_activity_alert_score_preserves_sign_when_all_alerts_are_bearish() -> None:
    loader = _FakeActivityLoader(
        [
            _alert("AAPL", "dark_pool", "BEARISH", notional=1_000_000.0),
            _alert("MSFT", "dark_pool", "BEARISH", notional=10_000_000.0),
        ]
    )

    scores = activity_alert_score(AS_OF, {"msft", "aapl"}, loader)

    assert scores["AAPL"] < 0.0
    assert scores["MSFT"] < scores["AAPL"]


def test_activity_alert_frame_tracks_sources_and_block_trade_counts() -> None:
    loader = _FakeActivityLoader(
        [
            _alert("AAPL", "block_trade", "BULLISH", source="one"),
            _alert("AAPL", "unusual_options_activity", "BULLISH", source="two", premium=50_000.0),
        ]
    )

    frame = activity_alert_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["source_count"] == EXPECTED_SOURCE_COUNT
    assert frame.iloc[0]["block_trade_count"] == 1
    assert frame.iloc[0]["options_activity_count"] == EXPECTED_OPTIONS_ACTIVITY_COUNT
    assert frame.iloc[0]["activity_alert_score"] == pytest.approx(1.0)


def test_activity_alert_frame_tracks_dark_pool_and_sweep_counts() -> None:
    loader = _FakeActivityLoader(
        [
            _alert("MSFT", "dark_pool", "BEARISH"),
            _alert("MSFT", "options_sweep", "BULLISH", premium=120_000.0),
        ]
    )

    frame = activity_alert_frame(AS_OF, {"MSFT"}, loader)

    assert frame.iloc[0]["dark_pool_count"] == 1
    assert frame.iloc[0]["sweep_count"] == 1
    assert frame.iloc[0]["options_activity_count"] == 1


def test_activity_alert_score_is_empty_when_loader_has_no_coverage() -> None:
    loader = _UnavailableActivityLoader()

    assert activity_alert_score(AS_OF, {"AAPL"}, loader) == {}


def test_activity_alert_score_raises_loader_bugs() -> None:
    loader = _BuggyActivityLoader()

    with pytest.raises(RuntimeError, match="bug"):
        activity_alert_score(AS_OF, {"AAPL"}, loader)


class _FakeActivityLoader:
    def __init__(self, alerts: list[dict[str, object]]) -> None:
        self.alerts = alerts
        self.calls: list[tuple[list[str], date, int]] = []

    def activity_alerts(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        self.calls.append((tickers, as_of, lookback_days))
        return [alert for alert in self.alerts if alert["ticker"] in tickers]


class _UnavailableActivityLoader:
    def activity_alerts(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        del tickers, lookback_days
        raise DataNotAvailableAt("activity_alerts", as_of, "no coverage")


class _BuggyActivityLoader:
    def activity_alerts(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[dict[str, object]]:
        del tickers, as_of, lookback_days
        raise RuntimeError("bug in loader")


def _alert(
    ticker: str,
    alert_type: str,
    direction: str,
    *,
    source: str = "fixture",
    notional: float | None = None,
    premium: float | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "alert_type": alert_type,
        "direction": direction,
        "notional": notional,
        "premium": premium,
        "volume": None,
        "source": source,
        "confidence": 1.0,
    }
