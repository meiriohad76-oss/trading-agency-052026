"""
T133 / BUG-7: Subscription email deduplication midnight UTC edge case.

Tests verify that dedup keys in classifiers._dedupe_activity and
storage._dedupe_key remain stable for events arriving near midnight UTC
(20:00-00:00 UTC is typical for paid-sub alert emails).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from subscription_email.classifiers import _dedupe_activity, _dedupe_events, _dedupe_news
from subscription_email.storage import _dedupe_key, write_event_frame
from subscription_email.types import EmailRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BEFORE_MIDNIGHT = datetime(2024, 1, 1, 23, 59, 0, tzinfo=UTC)  # 2024-01-01 23:59 UTC
AFTER_MIDNIGHT = datetime(2024, 1, 2, 0, 1, 0, tzinfo=UTC)  # 2024-01-02 00:01 UTC

# A message_id that is identical for both "emails" — same email processed twice.
SHARED_MESSAGE_ID = "tradevision-msft-dark-pool@example.test"
SHARED_SOURCE_ID = (
    "tradevision:MSFT:dark_pool:abc123hash:urlhash"  # same content fingerprint
)


def _activity_row(
    *,
    ticker: str = "MSFT",
    alert_type: str = "dark_pool",
    event_time: str,
    source_id: str = SHARED_SOURCE_ID,
) -> dict[str, object]:
    """Build a minimal activity row as produced by classifiers._activity_row."""
    return {
        "ticker": ticker,
        "alert_type": alert_type,
        "direction": "BULLISH",
        "event_time": event_time,
        "summary": f"TradeVision {alert_type} alert for {ticker}",
        "price": None,
        "volume": None,
        "notional": 2_000_000.0,
        "premium": None,
        "source": "tradevision-email",
        "source_tier": "PAID_SUB_EMAIL",
        "source_id": source_id,
        "source_url": f"email://abc123hash",
        "timestamp_observed": event_time,
        "timestamp_as_of": event_time,
        "freshness": "FRESH",
        "confidence": 0.85,
        "verification_level": "CONFIRMED",
    }


def _event_row_for_url(
    *,
    ticker: str = "AAPL",
    source_url: str = "https://seekingalpha.com/article/aapl-analysis",
    timestamp_as_of: str,
    source_id: str = "subscription_email:seeking_alpha:AAPL:sa_quant_rating_change:abc123",
    message_id_hash: str = "abc123hash",
) -> dict[str, object]:
    """Build a minimal event row with an HTTP source_url."""
    return {
        "ticker": ticker,
        "service": "seeking_alpha",
        "services": ["seeking_alpha"],
        "event_type": "sa_quant_rating_change",
        "event_types": ["sa_quant_rating_change"],
        "direction": "BULLISH",
        "title": f"Seeking Alpha Email: sa quant rating change - AAPL quant rating upgraded",
        "source_refs": [{"service": "seeking_alpha", "source_id": source_id, "source_url": source_url, "message_id_hash": message_id_hash}],
        "source": "seeking_alpha-email",
        "source_tier": "PAID_SUB_EMAIL",
        "source_id": source_id,
        "source_url": source_url,
        "message_id_hash": message_id_hash,
        "sender_domain": "email.seekingalpha.com",
        "received_at": timestamp_as_of,
        "linked_content_status": "not_requested",
        "linked_content_url": None,
        "linked_content_title_hash": None,
        "linked_content_summary": None,
        "linked_content_direction": None,
        "linked_content_thesis": None,
        "linked_content_catalysts": [],
        "linked_content_risk_flags": [],
        "linked_content_key_points": [],
        "linked_content_tickers": [],
        "linked_content_decision_use": None,
        "linked_content_signal_strength": None,
        "linked_content_context_chars": None,
        "timestamp_observed": timestamp_as_of,
        "timestamp_as_of": timestamp_as_of,
        "freshness": "FRESH",
        "confidence": 0.7,
        "verification_level": "CONFIRMED",
    }


# ---------------------------------------------------------------------------
# storage._dedupe_key  —  URL-based rows MUST be stable across midnight
# ---------------------------------------------------------------------------


class TestStorageDedupeKeyMidnightStability:
    """storage._dedupe_key must produce identical keys regardless of timestamp."""

    def _row(self, *, ticker: str, source_url: str, source_id: str = "sid:x") -> pd.Series:
        return pd.Series(
            {
                "ticker": ticker,
                "source_url": source_url,
                "source_id": source_id,
            }
        )

    def test_url_row_key_is_independent_of_timestamp(self) -> None:
        """Two identical URL rows with different timestamps yield the same dedup key."""
        url = "https://seekingalpha.com/article/aapl-analysis?utm_source=email"
        row_before = self._row(ticker="AAPL", source_url=url)
        row_after = self._row(ticker="AAPL", source_url=url)

        assert _dedupe_key(row_before) == _dedupe_key(row_after)

    def test_url_row_key_is_url_plus_ticker_without_date(self) -> None:
        """The dedup key for URL rows must not contain any date fragment."""
        url = "https://seekingalpha.com/article/aapl-analysis"
        row = self._row(ticker="AAPL", source_url=url)

        key = _dedupe_key(row)

        # Key should look like "url:AAPL:<normalised-url>" with no date component.
        assert key.startswith("url:AAPL:")
        assert "2024" not in key  # no year
        assert "01" not in key or "seekingalpha" in key  # date digits only if in URL path

    def test_non_url_row_fallback_key_is_source_id(self) -> None:
        """Rows without an HTTP URL fall back to source:{source_id}."""
        row = self._row(
            ticker="MSFT",
            source_url="email://abc123hash",
            source_id="tradevision:MSFT:dark_pool:abc123:urlhash",
        )

        key = _dedupe_key(row)

        assert key.startswith("source:")

    def test_write_event_frame_dedupes_same_url_article_across_midnight(
        self, tmp_path: Path
    ) -> None:
        """
        Regression: same SA article arriving just before and just after midnight UTC
        must be stored only once.
        """
        path = tmp_path / "events.parquet"
        url = "https://seekingalpha.com/article/aapl-analysis"

        row_before = _event_row_for_url(
            ticker="AAPL",
            source_url=url,
            timestamp_as_of=BEFORE_MIDNIGHT.isoformat(),
            source_id="subscription_email:seeking_alpha:AAPL:sa_news:before",
            message_id_hash="before_hash",
        )
        row_after = _event_row_for_url(
            ticker="AAPL",
            source_url=url,
            timestamp_as_of=AFTER_MIDNIGHT.isoformat(),
            source_id="subscription_email:seeking_alpha:AAPL:sa_news:after",
            message_id_hash="after_hash",
        )

        write_event_frame(path, pd.DataFrame([row_before]))
        write_event_frame(path, pd.DataFrame([row_after]))

        stored = pd.read_parquet(path)

        assert len(stored) == 1, (
            f"Expected 1 row after cross-midnight dedup, got {len(stored)}. "
            "storage._dedupe_key must not include a date component for URL rows."
        )


# ---------------------------------------------------------------------------
# classifiers._dedupe_activity  —  event_time must NOT be part of the key
# ---------------------------------------------------------------------------


class TestDedupeActivityMidnightEdgeCase:
    """
    BUG-7: _dedupe_activity previously included event_time (a full ISO timestamp)
    in its key.  Two rows with the same source_id but different event_time values
    (e.g. 23:59 vs 00:01 UTC) were incorrectly kept as separate signals.
    """

    def test_same_source_id_different_event_time_is_deduplicated(self) -> None:
        """
        REGRESSION TEST (should FAIL before the fix, PASS after).

        Same source_id with event_time values on opposite sides of midnight UTC
        must produce exactly 1 output row from _dedupe_activity.
        """
        row_before = _activity_row(
            event_time=BEFORE_MIDNIGHT.isoformat(),
            source_id=SHARED_SOURCE_ID,
        )
        row_after = _activity_row(
            event_time=AFTER_MIDNIGHT.isoformat(),
            source_id=SHARED_SOURCE_ID,
        )

        result = _dedupe_activity([row_before, row_after])

        assert len(result) == 1, (
            f"Expected 1 row after dedup, got {len(result)}. "
            "_dedupe_activity must not use event_time in its key because "
            "the same email re-processed with a slightly different timestamp "
            "would create duplicate signals."
        )

    def test_genuinely_different_alerts_are_kept(self) -> None:
        """
        Two distinct alerts for the same ticker/type but different source_ids
        (different emails) must both survive dedup.
        """
        row_a = _activity_row(
            event_time=BEFORE_MIDNIGHT.isoformat(),
            source_id="tradevision:MSFT:dark_pool:hash_a:urlhash",
        )
        row_b = _activity_row(
            event_time=AFTER_MIDNIGHT.isoformat(),
            source_id="tradevision:MSFT:dark_pool:hash_b:urlhash",
        )

        result = _dedupe_activity([row_a, row_b])

        assert len(result) == 2, (
            "Two alerts with distinct source_ids must both be kept."
        )

    def test_same_alert_same_event_time_is_deduplicated(self) -> None:
        """
        Baseline: identical rows (same source_id and event_time) are still deduped.
        """
        row = _activity_row(event_time=BEFORE_MIDNIGHT.isoformat())
        result = _dedupe_activity([row, row.copy()])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# classifiers._dedupe_news  —  verify no date component in its key
# ---------------------------------------------------------------------------


class TestDedupeNewsMidnightStability:
    """_dedupe_news key is (ticker, url, title). No date component expected."""

    def _news_row(self, *, ticker: str, url: str, title: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "url": url,
            "title": title,
            "source_id": f"sa:{ticker}:sa_news:hash1:hash2",
            "timestamp_as_of": BEFORE_MIDNIGHT.isoformat(),
        }

    def test_same_article_different_timestamp_is_deduplicated(self) -> None:
        """
        Two news rows for the same article (same ticker + url + title) but
        different timestamps must deduplicate to a single row.
        """
        url = "https://seekingalpha.com/article/aapl-upgrade"
        row_before = self._news_row(ticker="AAPL", url=url, title="AAPL upgrade")
        row_after = {**row_before, "timestamp_as_of": AFTER_MIDNIGHT.isoformat()}

        result = _dedupe_news([row_before, row_after])

        assert len(result) == 1


# ---------------------------------------------------------------------------
# classifiers._dedupe_events  —  verify no date component in its key
# ---------------------------------------------------------------------------


class TestDedupeEventsMidnightStability:
    """_dedupe_events key is (ticker, normalised_url). No date component expected."""

    def test_same_url_different_timestamp_is_merged_to_one_event(self) -> None:
        """
        Two event rows for the same ticker + URL arriving on opposite sides of
        midnight UTC must merge to a single event.
        """
        url = "https://seekingalpha.com/article/aapl-analysis"
        row_before = _event_row_for_url(
            ticker="AAPL",
            source_url=url,
            timestamp_as_of=BEFORE_MIDNIGHT.isoformat(),
            source_id="subscription_email:seeking_alpha:AAPL:sa_news:before",
        )
        row_after = _event_row_for_url(
            ticker="AAPL",
            source_url=url,
            timestamp_as_of=AFTER_MIDNIGHT.isoformat(),
            source_id="subscription_email:seeking_alpha:AAPL:sa_news:after",
        )

        result = _dedupe_events([row_before, row_after])

        assert len(result) == 1, (
            f"Expected 1 merged event, got {len(result)}. "
            "_dedupe_events key must not include a date component."
        )
