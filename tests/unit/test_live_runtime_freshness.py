from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from live_runtime.freshness import effective_freshness_timestamp, next_quarterly_filing_date
from pit.manifest import DatasetName


def _dt(d: date, hour: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=UTC)


TODAY = date(2026, 5, 13)  # Wednesday
YESTERDAY = date(2026, 5, 12)  # Tuesday
SATURDAY = date(2026, 5, 16)  # Saturday (weekday=5)
FRIDAY = date(2026, 5, 15)  # Friday (last trading day before that Saturday)
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


def test_prices_daily_returns_yesterday_during_market_hours() -> None:
    """Cycle run at 14:30 ET (18:30 UTC) finds today's prices_daily timestamp.
    The 21:15 UTC post-market bar publication window has not passed yet, so the
    effective date must be yesterday — today's close bar is not yet available.
    """
    # 18:30 UTC = 14:30 ET — market is open, bars not published
    checked_at = datetime(TODAY.year, TODAY.month, TODAY.day, 18, 30, 0, tzinfo=UTC)
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(TODAY), checked_at
    )
    assert ts.date() == YESTERDAY, (
        f"Expected yesterday ({YESTERDAY}) but got {ts.date()}; "
        "post-market bar publication window (21:15 UTC) has not passed yet"
    )


def test_prices_daily_returns_checked_at_after_publication_window() -> None:
    """At 22:00 UTC (18:00 ET) today's bar has been published; effective
    timestamp should equal checked_at (the data is as fresh as now).
    """
    checked_at = _dt(TODAY, hour=22)  # 22:00 UTC — after 21:15 UTC window
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(TODAY), checked_at
    )
    assert ts == checked_at


def test_prices_daily_weekend_returns_friday() -> None:
    """On Saturday (or Sunday) the last published bar is Friday's close,
    regardless of UTC hour — no bar publishes on a non-trading day.
    """
    # Saturday before the publication window
    checked_before = _dt(SATURDAY, hour=18)
    ts_before = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(SATURDAY), checked_before
    )
    assert ts_before.date() == FRIDAY, (
        f"Expected Friday ({FRIDAY}) before window but got {ts_before.date()}"
    )

    # Saturday after the publication window — still Friday
    checked_after = _dt(SATURDAY, hour=22)
    ts_after = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, _dt(SATURDAY), checked_after
    )
    assert ts_after.date() == FRIDAY, (
        f"Expected Friday ({FRIDAY}) after window but got {ts_after.date()}"
    )


def test_prices_daily_stale_timestamp_returned_as_is() -> None:
    """If the stored timestamp is older than the latest published bar the raw
    timestamp is returned unchanged (the data is genuinely stale).
    """
    checked_at = _dt(TODAY, hour=22)
    two_days_ago = _dt(date(2026, 5, 11))  # Monday
    ts = effective_freshness_timestamp(
        DatasetName.PRICES_DAILY, two_days_ago, checked_at
    )
    assert ts == two_days_ago


# ── STOCK_TRADES ──────────────────────────────────────────────────────────────

def test_stock_trades_before_post_market_window_uses_yesterday() -> None:
    """Delayed prints for today are not reliable before 21:15 UTC."""
    checked_at = _dt(TODAY, hour=19)  # before 21:15 UTC
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES, _dt(TODAY), checked_at
    )
    assert ts.date() < TODAY


def test_stock_trades_recent_same_day_tape_is_live_fresh_during_market() -> None:
    checked_at = _dt(TODAY, hour=15)
    timestamp_as_of = checked_at - timedelta(minutes=10)

    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES,
        timestamp_as_of,
        checked_at,
    )

    assert ts == timestamp_as_of


def test_stock_trades_after_post_market_window_returns_checked_at() -> None:
    checked_at = _dt(TODAY, hour=22)  # after 21:15 UTC
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES, _dt(TODAY), checked_at
    )
    assert ts == checked_at


# ── SUBSCRIPTION_EMAILS ───────────────────────────────────────────────────────

def test_stock_trades_before_pre_market_accepts_previous_completed_day() -> None:
    checked_at = _dt(date(2026, 5, 14), hour=6)  # 02:00 ET, before pre-market
    ts = effective_freshness_timestamp(
        DatasetName.STOCK_TRADES,
        _dt(date(2026, 5, 13), hour=23),
        checked_at,
    )
    assert ts == checked_at


def test_stock_trades_before_pre_market_rejects_older_completed_day() -> None:
    checked_at = _dt(date(2026, 5, 14), hour=6)  # 02:00 ET, before pre-market
    stale = _dt(date(2026, 5, 12), hour=23)
    ts = effective_freshness_timestamp(DatasetName.STOCK_TRADES, stale, checked_at)
    assert ts == stale


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
