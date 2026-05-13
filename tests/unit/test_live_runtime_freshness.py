from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from live_runtime.freshness import effective_freshness_timestamp, next_quarterly_filing_date
from pit.manifest import DatasetName


def _dt(d: date, hour: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=UTC)


TODAY = date(2026, 5, 13)
NOW = _dt(TODAY, hour=15)  # 15:00 UTC = 11:00 ET (market hours)


# ── PRICES_DAILY ──────────────────────────────────────────────────────────────

def test_prices_daily_today_returns_checked_at_after_close() -> None:
    checked_at = _dt(TODAY, hour=22)  # 22:00 UTC = 18:00 ET (after close)
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(TODAY), checked_at
    )
    assert ts == checked_at


def test_prices_daily_today_returns_yesterday_before_close() -> None:
    """Before 21:15 UTC (17:15 ET), today's bars are not published yet."""
    checked_at = _dt(TODAY, hour=19)  # 19:00 UTC = 15:00 ET (market hours)
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(TODAY), checked_at
    )
    assert ts.date() < TODAY


# ── STOCK_TRADES ──────────────────────────────────────────────────────────────

def test_stock_trades_before_post_market_window_uses_yesterday() -> None:
    """Delayed prints for today are not reliable before 21:15 UTC."""
    checked_at = _dt(TODAY, hour=19)  # before 21:15 UTC
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES, _dt(TODAY), checked_at
    )
    assert ts.date() < TODAY


def test_stock_trades_after_post_market_window_returns_checked_at() -> None:
    checked_at = _dt(TODAY, hour=22)  # after 21:15 UTC
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES, _dt(TODAY), checked_at
    )
    assert ts == checked_at


# ── SUBSCRIPTION_EMAILS ───────────────────────────────────────────────────────

def test_subscription_emails_applies_delivery_lag() -> None:
    """A 20-minute delivery lag is subtracted from checked_at."""
    ts_as_of = _dt(TODAY, hour=14)
    checked_at = _dt(TODAY, hour=14)
    ts = effective_freshness_timestamp(
        DatasetName.SUBSCRIPTION_EMAILS, ts_as_of, checked_at
    )
    assert ts <= checked_at - timedelta(minutes=20)


# ── SEC_13F ────────────────────────────────────────────────────────────────────

def test_sec_13f_returns_fresh_between_quarters() -> None:
    """13F is FRESH between filing periods — it's current as of last filing."""
    ts_as_of = _dt(date(2026, 3, 31))
    checked_at = _dt(date(2026, 5, 13))
    ts = effective_freshness_timestamp(
        DatasetName.SEC_13F, ts_as_of, checked_at
    )
    assert ts == checked_at


def test_next_quarterly_filing_date_after_q1() -> None:
    assert next_quarterly_filing_date(date(2026, 3, 31)) == date(2026, 6, 30)


def test_next_quarterly_filing_date_after_q2() -> None:
    assert next_quarterly_filing_date(date(2026, 6, 30)) == date(2026, 9, 30)


def test_next_quarterly_filing_date_after_q3() -> None:
    assert next_quarterly_filing_date(date(2026, 9, 30)) == date(2026, 12, 31)


def test_next_quarterly_filing_date_after_q4() -> None:
    assert next_quarterly_filing_date(date(2026, 12, 31)) == date(2027, 3, 31)
