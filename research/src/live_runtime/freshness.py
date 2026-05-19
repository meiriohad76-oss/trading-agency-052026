from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from data_refresh.market_calendar import (
    classify_market_session,
    previous_trading_day,
)
from pit.manifest import DatasetName

_STOCK_TRADES_POST_MARKET_UTC_HOUR = 21
_STOCK_TRADES_POST_MARKET_UTC_MINUTE = 15
_ACTIVE_STOCK_TRADE_MAX_LAG_MINUTES = 30

_EMAIL_DELIVERY_LAG_MINUTES = 20


def effective_freshness_timestamp(
    dataset: DatasetName,
    timestamp_as_of: datetime,
    checked_at: datetime,
) -> datetime:
    if dataset is DatasetName.PRICES_DAILY:
        latest_published = _latest_published_daily_bar_date(checked_at)
        timestamp_date = timestamp_as_of.date()
        if timestamp_date == latest_published:
            return checked_at
        if timestamp_date > latest_published:
            session = classify_market_session(checked_at)
            if session.is_trading_day and timestamp_date == session.market_date:
                return checked_at
            return datetime(
                latest_published.year,
                latest_published.month,
                latest_published.day,
                tzinfo=timestamp_as_of.tzinfo or UTC,
            )
        return timestamp_as_of

    if dataset is DatasetName.STOCK_TRADES:
        if _same_day_active_stock_trades_are_recent(timestamp_as_of, checked_at):
            return timestamp_as_of
        if _stock_trades_cover_required_closed_window(timestamp_as_of, checked_at):
            return checked_at
        if timestamp_as_of.date() >= checked_at.date():
            if _after_stock_trades_window(checked_at):
                return checked_at
            prev = checked_at.date() - timedelta(days=1)
            return datetime(prev.year, prev.month, prev.day, tzinfo=UTC)
        return timestamp_as_of

    if dataset is DatasetName.SUBSCRIPTION_EMAILS:
        return min(timestamp_as_of, checked_at - timedelta(minutes=_EMAIL_DELIVERY_LAG_MINUTES))

    if dataset is DatasetName.SEC_13F:
        return checked_at

    return timestamp_as_of


def next_quarterly_filing_date(last_filing_date: date) -> date:
    month = last_filing_date.month
    year = last_filing_date.year
    if month in (1, 2, 3):
        return date(year, 6, 30)
    if month in (4, 5, 6):
        return date(year, 9, 30)
    if month in (7, 8, 9):
        return date(year, 12, 31)
    return date(year + 1, 3, 31)


def _latest_completed_daily_bar_date(current: date) -> date:
    candidate = current - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _latest_published_daily_bar_date(checked_at: datetime) -> date:
    current = checked_at.date()
    if current.weekday() < 5 and _after_bar_publication_window(checked_at):
        return current
    return _latest_completed_daily_bar_date(current)


def _after_bar_publication_window(checked_at: datetime) -> bool:
    return (
        checked_at.hour > _STOCK_TRADES_POST_MARKET_UTC_HOUR
        or (
            checked_at.hour == _STOCK_TRADES_POST_MARKET_UTC_HOUR
            and checked_at.minute >= _STOCK_TRADES_POST_MARKET_UTC_MINUTE
        )
    )


def _after_stock_trades_window(checked_at: datetime) -> bool:
    return _after_bar_publication_window(checked_at)


def _same_day_active_stock_trades_are_recent(
    timestamp_as_of: datetime,
    checked_at: datetime,
) -> bool:
    if timestamp_as_of.date() != checked_at.date():
        return False
    lag = checked_at - timestamp_as_of
    if lag < timedelta(0):
        return False
    if lag > timedelta(minutes=_ACTIVE_STOCK_TRADE_MAX_LAG_MINUTES):
        return False
    session = classify_market_session(checked_at)
    return session.phase in {"pre_market", "regular_market", "after_hours"}


def _stock_trades_cover_required_closed_window(
    timestamp_as_of: datetime,
    checked_at: datetime,
) -> bool:
    session = classify_market_session(checked_at)
    if session.phase == "overnight_before_pre_market" or not session.is_trading_day:
        required = previous_trading_day(session.market_date)
    elif session.phase == "overnight_after_hours":
        required = session.market_date
    else:
        return False
    return timestamp_as_of.date() >= required
