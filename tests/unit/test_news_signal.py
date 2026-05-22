from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from pit.exceptions import DataNotAvailableAt
from signals.news import news_factor_frame, news_score

AS_OF = date(2026, 5, 7)
LOOKBACK_DAYS = 3
LOW_RESOLUTION_CONFIDENCE = 0.69
HIGH_RESOLUTION_CONFIDENCE = 0.90
LOW_WEIGHT_CONFIDENCE = 0.70
EXPECTED_WEIGHTED_SENTIMENT = 0.125
EXPECTED_WEIGHTED_HEADLINE_COUNT = 1.60
EXPECTED_MATCH_CONFIDENCE_AVG = 0.80


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


def test_news_signal_ignores_ambiguous_news_rows() -> None:
    loader = _FakeNewsLoader(
        [
            _item(
                "AAPL",
                "AAPL upgrade after product launch",
                "PRN",
                ticker_match_status="ambiguous",
                ticker_match_confidence=HIGH_RESOLUTION_CONFIDENCE,
            )
        ]
    )

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.empty


def test_news_signal_requires_min_resolution_confidence() -> None:
    loader = _FakeNewsLoader(
        [
            _item(
                "AAPL",
                "AAPL upgrade after product launch",
                "PRN",
                ticker_match_status="resolved",
                ticker_match_confidence=LOW_RESOLUTION_CONFIDENCE,
            )
        ]
    )

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.empty


def test_news_sentiment_is_weighted_by_match_confidence() -> None:
    loader = _FakeNewsLoader(
        [
            _item(
                "AAPL",
                "AAPL upgrade after product launch",
                "PRN",
                ticker_match_status="resolved",
                ticker_match_confidence=HIGH_RESOLUTION_CONFIDENCE,
            ),
            _item(
                "AAPL",
                "AAPL downgrade after regulatory probe",
                "PRN",
                ticker_match_status="resolved",
                ticker_match_confidence=LOW_WEIGHT_CONFIDENCE,
            ),
        ]
    )

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["sentiment_score"] == pytest.approx(EXPECTED_WEIGHTED_SENTIMENT)
    assert frame.iloc[0]["weighted_headline_count"] == pytest.approx(
        EXPECTED_WEIGHTED_HEADLINE_COUNT
    )
    assert frame.iloc[0]["match_confidence_avg"] == pytest.approx(
        EXPECTED_MATCH_CONFIDENCE_AVG
    )


def test_news_signal_keeps_source_count_by_unique_feed_or_url() -> None:
    loader = _FakeNewsLoader(
        [
            _item("AAPL", "AAPL upgrade", "", url="https://example.test/one"),
            _item("AAPL", "AAPL raises guidance", "", url="https://example.test/two"),
            _item("AAPL", "AAPL beats estimates", "PRN", url="https://example.test/three"),
            _item("AAPL", "AAPL approval expands", "PRN", url="https://example.test/four"),
        ]
    )

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["source_count"] == 3


def test_news_sentiment_uses_word_boundaries() -> None:
    loader = _FakeNewsLoader([_item("AAPL", "AAPL opens Mississippi campus", "Yahoo")])

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["sentiment_score"] == 0.0


def test_news_factor_frame_carries_scorable_source_ids_for_single_use_consumption() -> None:
    loader = _FakeNewsLoader(
        [
            _item("AAPL", "AAPL upgrade", "PRN", source_id="rss:aapl:1"),
            _item(
                "AAPL",
                "AAPL launches product",
                "PRN",
                source_id="rss:aapl:ambiguous",
                ticker_match_status="ambiguous",
                ticker_match_confidence=HIGH_RESOLUTION_CONFIDENCE,
            ),
            _item("AAPL", "AAPL raises guidance", "Yahoo", source_id="rss:aapl:2"),
        ]
    )

    frame = news_factor_frame(AS_OF, {"AAPL"}, loader)

    assert frame.iloc[0]["source_ids"] == ["rss:aapl:1", "rss:aapl:2"]


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


def _item(
    ticker: str,
    title: str,
    feed_name: str,
    *,
    url: str | None = None,
    source_id: str | None = None,
    ticker_match_status: str | None = None,
    ticker_match_confidence: float | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "title": title,
        "summary": "",
        "feed_name": feed_name,
        "url": url or f"https://example.test/{ticker}",
        **({"source_id": source_id} if source_id is not None else {}),
        **(
            {"ticker_match_status": ticker_match_status}
            if ticker_match_status is not None
            else {}
        ),
        **(
            {"ticker_match_confidence": ticker_match_confidence}
            if ticker_match_confidence is not None
            else {}
        ),
    }
