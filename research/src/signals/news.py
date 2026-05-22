from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol

import pandas as pd
from pit.exceptions import DataNotAvailableAt
from signals._common import payload_dict, score_dict, zscore

DEFAULT_LOOKBACK_DAYS = 3
MIN_TICKER_MATCH_CONFIDENCE = 0.70
SCORABLE_MATCH_STATUSES = frozenset({"resolved", "feed_ticker"})
POSITIVE_TERMS = frozenset(
    {"upgrade", "beats", "beat", "raises", "raised", "buy", "outperform", "surges", "approval"}
)
NEGATIVE_TERMS = frozenset(
    {"downgrade", "misses", "miss", "cuts", "cut", "sell", "lawsuit", "probe", "falls"}
)


class NewsLoader(Protocol):
    def news(
        self,
        as_of: date,
        lookback_days: int,
        tickers: list[str] | None = None,
    ) -> Sequence[object]: ...


def news_score(
    as_of: date,
    universe: set[str],
    loader: NewsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a forward RSS headline sentiment/breadth score per ticker."""
    return score_dict(news_factor_frame(as_of, universe, loader, lookback_days), "news_score")


def news_factor_frame(
    as_of: date,
    universe: Iterable[str],
    loader: NewsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the ticker-tagged RSS headline cross-section known at `as_of`."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        items = loader.news(as_of, lookback_days, tickers)
    except DataNotAvailableAt:
        return _empty_frame()
    rows = _rows(tickers, items)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_frame()
    frame["news_score"] = zscore(frame["sentiment_score"])
    return frame.sort_values(["news_score", "ticker"], ascending=[False, True]).reset_index(
        drop=True
    )


def _rows(tickers: list[str], items: Sequence[object]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {ticker: [] for ticker in tickers}
    for item in items:
        payload = payload_dict(item, "news")
        if not _scorable_news_row(payload):
            continue
        ticker = str(payload.get("ticker", "")).upper()
        if ticker in grouped:
            grouped[ticker].append(payload)
    return [_factor_row(ticker, values) for ticker, values in grouped.items() if values]


def _factor_row(ticker: str, items: list[dict[str, object]]) -> dict[str, object]:
    sentiments = [_headline_sentiment(item) for item in items]
    confidences = [_ticker_match_confidence(item) for item in items]
    sources = {
        str(item.get("feed_name") or item.get("url"))
        for item in items
        if item.get("feed_name") or item.get("url")
    }
    weighted_headline_count = float(sum(confidences))
    sentiment_score = (
        float(
            sum(sentiment * confidence for sentiment, confidence in zip(sentiments, confidences, strict=True))
            / weighted_headline_count
        )
        if weighted_headline_count > 0
        else 0.0
    )
    return {
        "ticker": ticker,
        "headline_count": len(items),
        "weighted_headline_count": weighted_headline_count,
        "match_confidence_avg": float(sum(confidences) / len(confidences)),
        "source_count": len(sources),
        "positive_count": sum(1 for value in sentiments if value > 0),
        "negative_count": sum(1 for value in sentiments if value < 0),
        "sentiment_score": sentiment_score,
    }


def _headline_sentiment(item: dict[str, object]) -> int:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    positive = sum(_term_count(text, term) for term in POSITIVE_TERMS)
    negative = sum(_term_count(text, term) for term in NEGATIVE_TERMS)
    if positive > negative:
        return 1
    if negative > positive:
        return -1
    return 0


def _term_count(text: str, term: str) -> int:
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))


def _scorable_news_row(item: dict[str, object]) -> bool:
    status = _match_status(item)
    return status in SCORABLE_MATCH_STATUSES and (
        _ticker_match_confidence(item) >= MIN_TICKER_MATCH_CONFIDENCE
    )


def _match_status(item: dict[str, object]) -> str:
    value = item.get("ticker_match_status")
    if value is None or str(value).strip() == "":
        return "feed_ticker"
    return str(value).strip()


def _ticker_match_confidence(item: dict[str, object]) -> float:
    value = item.get("ticker_match_confidence")
    if value is None or str(value).strip() == "":
        return 1.0
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "headline_count",
            "weighted_headline_count",
            "match_confidence_avg",
            "source_count",
            "positive_count",
            "negative_count",
            "sentiment_score",
            "news_score",
        ]
    )
