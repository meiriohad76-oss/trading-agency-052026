from __future__ import annotations

from datetime import datetime

from data_refresh.market_calendar import (
    EASTERN,
    classify_market_session,
    is_early_close_day,
    is_trading_day,
    next_pre_market_start,
    next_regular_open,
)

REGULAR_CLOSE_HOUR = 16
EARLY_CLOSE_HOUR = 13
REGULAR_OPEN_HOUR = 9
REGULAR_OPEN_MINUTE = 30


def test_market_session_identifies_regular_market_window() -> None:
    session = classify_market_session(datetime(2026, 5, 11, 10, 15, tzinfo=EASTERN))

    assert session.phase == "regular_market"
    assert session.is_trading_day is True
    assert session.is_open_for_core is True
    assert session.regular_close_at is not None
    assert session.regular_close_at.hour == REGULAR_CLOSE_HOUR


def test_market_session_identifies_pre_market_window() -> None:
    session = classify_market_session(datetime(2026, 5, 11, 8, 0, tzinfo=EASTERN))

    assert session.phase == "pre_market"
    assert session.is_open_for_core is False
    assert session.is_open_for_extended is True


def test_market_calendar_handles_2026_independence_observed_holiday() -> None:
    session = classify_market_session(datetime(2026, 7, 3, 11, 0, tzinfo=EASTERN))

    assert is_trading_day(session.market_date) is False
    assert session.phase == "closed_holiday"


def test_market_calendar_handles_black_friday_early_close() -> None:
    session = classify_market_session(datetime(2026, 11, 27, 12, 30, tzinfo=EASTERN))

    assert is_early_close_day(session.market_date) is True
    assert session.phase == "regular_market"
    assert session.regular_close_at is not None
    assert session.regular_close_at.hour == EARLY_CLOSE_HOUR


def test_next_regular_open_skips_weekend() -> None:
    opening = next_regular_open(datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN))

    assert opening.date().isoformat() == "2026-05-11"
    assert opening.hour == REGULAR_OPEN_HOUR
    assert opening.minute == REGULAR_OPEN_MINUTE


def test_next_pre_market_start_uses_next_tradeable_0400_window() -> None:
    before_premarket = next_pre_market_start(
        datetime(2026, 5, 11, 3, 15, tzinfo=EASTERN)
    )
    weekend = next_pre_market_start(datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN))

    assert before_premarket.date().isoformat() == "2026-05-11"
    assert before_premarket.hour == 4
    assert before_premarket.minute == 0
    assert weekend.date().isoformat() == "2026-05-11"
    assert weekend.hour == 4
