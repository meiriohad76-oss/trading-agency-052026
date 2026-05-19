from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from pit.exceptions import DataNotAvailableAt
from signals.news import news_factor_frame, news_score

AS_OF = date(2026, 5, 7)
LOOKBACK_DAYS = 3


def test_news_score_ranks_positive_neutral_and_negative_headlines() -> None:
    loader = _FakeNewsLoader(
        [
            _item("AAPL", "AAPL upgrade as earnings beat estimates", "Yahoo"),
            _item("MSFT", "MSFT announces developer event", "Yahoo"),
            _item("TSLA", "TSLA downgrade after delivery miss", "Google"),
        ]
    )

    scores = news_score(AS_OF, {"tsla", "AAPL", "MSFT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "TSLA"]
    assert scores["AAPL"] > scores["MSFT"] > scores["TSLA"]


def test_news_factor_frame_returns_empty_on_missing_news() -> None:
    loader = _FailingNewsLoader()

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.empty


def test_news_factor_frame_propagates_loader_bugs() -> None:
    with pytest.raises(KeyError):
        news_factor_frame(AS_OF, {"AAPL"}, _BuggyNewsLoader())


def test_news_sentiment_is_normalized_by_headline_coverage() -> None:
    loader = _FakeNewsLoader(
        [
            _item("AAPL", "AAPL upgrade", "Feed 1"),
            _item("AAPL", "AAPL announces developer event", "Feed 2"),
            _item("AAPL", "AAPL opens new campus", "Feed 3"),
            _item("AAPL", "AAPL appoints new director", "Feed 4"),
            _item("MSFT", "MSFT upgrade", "Feed 1"),
        ]
    )

    frame = news_factor_frame(AS_OF, {"AAPL", "MSFT"}, loader)
    by_ticker = frame.set_index("ticker")

    assert by_ticker.loc["AAPL", "sentiment_score"] == pytest.approx(0.25)
    assert by_ticker.loc["MSFT", "sentiment_score"] == pytest.approx(1.0)
    assert by_ticker.loc["MSFT", "news_score"] > by_ticker.loc["AAPL", "news_score"]


def test_news_sentiment_uses_word_boundaries() -> None:
    loader = _FakeNewsLoader([_item("AAPL", "AAPL opens Mississippi campus", "Yahoo")])

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["sentiment_score"] == 0.0


def test_news_score_is_deterministic_uppercases_and_forwards_lookback() -> None:
    loader = _FakeNewsLoader(
        [
            _item("AAPL", "AAPL upgrade", "Yahoo"),
            _item("MSFT", "MSFT downgrade", "Google"),
        ]
    )

    first = news_score(AS_OF, {"msft", "aapl"}, loader, LOOKBACK_DAYS)
    second = news_score(AS_OF, {"aapl", "msft"}, loader, LOOKBACK_DAYS)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}
    assert loader.calls == [
        (AS_OF, LOOKBACK_DAYS, ["AAPL", "MSFT"]),
        (AS_OF, LOOKBACK_DAYS, ["AAPL", "MSFT"]),
    ]


@dataclass(frozen=True)
class _ProvenancedValue:
    value: dict[str, object]


class _FakeNewsLoader:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = [_ProvenancedValue(item) for item in items]
        self.calls: list[tuple[date, int, list[str] | None]] = []

    def news(
        self,
        as_of: date,
        lookback_days: int,
        tickers: list[str] | None = None,
    ) -> list[_ProvenancedValue]:
        self.calls.append((as_of, lookback_days, tickers))
        requested = set(tickers or [])
        return [item for item in self._items if item.value["ticker"] in requested]


class _FailingNewsLoader:
    def news(self, as_of: date, lookback_days: int, tickers: list[str] | None = None) -> object:
        raise DataNotAvailableAt("news_rss", as_of, str((lookback_days, tickers)))


class _BuggyNewsLoader:
    def news(self, as_of: date, lookback_days: int, tickers: list[str] | None = None) -> object:
        raise KeyError((as_of, lookback_days, tickers))


def _item(ticker: str, title: str, feed_name: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "title": title,
        "summary": "",
        "feed_name": feed_name,
        "url": f"https://example.test/{ticker}",
    }
