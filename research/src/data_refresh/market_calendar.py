from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
PRE_MARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
EXTENDED_CLOSE = time(20, 0)
WEEKEND_START = 5
SATURDAY = 5
SUNDAY = 6
DECEMBER = 12


@dataclass(frozen=True)
class MarketSession:
    phase: str
    market_date: date
    is_trading_day: bool
    is_early_close: bool
    is_open_for_core: bool
    is_open_for_extended: bool
    regular_open_at: datetime | None
    regular_close_at: datetime | None
    next_regular_open_at: datetime | None
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "market_date": self.market_date.isoformat(),
            "is_trading_day": self.is_trading_day,
            "is_early_close": self.is_early_close,
            "is_open_for_core": self.is_open_for_core,
            "is_open_for_extended": self.is_open_for_extended,
            "regular_open_at": _dt_text(self.regular_open_at),
            "regular_close_at": _dt_text(self.regular_close_at),
            "next_regular_open_at": _dt_text(self.next_regular_open_at),
            "reason": self.reason,
        }


def classify_market_session(moment: datetime) -> MarketSession:
    eastern = _as_eastern(moment)
    market_date = eastern.date()
    trading_day = is_trading_day(market_date)
    early = is_early_close_day(market_date)
    close = EARLY_CLOSE if early else REGULAR_CLOSE
    regular_open_at = _combine(market_date, REGULAR_OPEN) if trading_day else None
    regular_close_at = _combine(market_date, close) if trading_day else None
    next_open = next_regular_open(eastern)
    current_time = eastern.time()

    if not trading_day:
        phase = "closed_holiday" if market_date in market_holidays(market_date.year) else "closed"
        if market_date.weekday() >= WEEKEND_START:
            phase = "closed_weekend"
        return MarketSession(
            phase=phase,
            market_date=market_date,
            is_trading_day=False,
            is_early_close=False,
            is_open_for_core=False,
            is_open_for_extended=False,
            regular_open_at=None,
            regular_close_at=None,
            next_regular_open_at=next_open,
            reason="market is closed; run maintenance-only batches",
        )

    if current_time < PRE_MARKET_START:
        phase = "overnight_before_pre_market"
        core = False
        extended = False
        reason = "before pre-market; defer trade-print polling until pre-market starts"
    elif current_time < REGULAR_OPEN:
        phase = "pre_market"
        core = False
        extended = True
        reason = "pre-market is active; prioritize current-day trade prints and alerts"
    elif current_time < close:
        phase = "regular_market"
        core = True
        extended = True
        reason = "regular market is open; keep high-frequency market-flow batches small"
    elif current_time < EXTENDED_CLOSE:
        phase = "after_hours"
        core = False
        extended = True
        reason = "after-hours is active; reconcile market-flow and prepare end-of-day batches"
    else:
        phase = "overnight_after_hours"
        core = False
        extended = False
        reason = "after extended hours; run daily bars, slow data, and research maintenance"

    return MarketSession(
        phase=phase,
        market_date=market_date,
        is_trading_day=True,
        is_early_close=early,
        is_open_for_core=core,
        is_open_for_extended=extended,
        regular_open_at=regular_open_at,
        regular_close_at=regular_close_at,
        next_regular_open_at=next_open,
        reason=reason,
    )


def is_trading_day(value: date) -> bool:
    return value.weekday() < WEEKEND_START and value not in market_holidays(value.year)


def is_early_close_day(value: date) -> bool:
    return is_trading_day(value) and value in early_close_days(value.year)


def next_regular_open(moment: datetime) -> datetime:
    eastern = _as_eastern(moment)
    candidate = eastern.date()
    if is_trading_day(candidate) and eastern.time() < REGULAR_OPEN:
        return _combine(candidate, REGULAR_OPEN)
    candidate += timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return _combine(candidate, REGULAR_OPEN)


def next_pre_market_start(moment: datetime) -> datetime:
    eastern = _as_eastern(moment)
    candidate = eastern.date()
    if is_trading_day(candidate) and eastern.time() < PRE_MARKET_START:
        return _combine(candidate, PRE_MARKET_START)
    candidate += timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return _combine(candidate, PRE_MARKET_START)


def previous_trading_day(value: date) -> date:
    candidate = value - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed_date(year, 1, 1),
        _nth_weekday(year, 1, weekday=0, occurrence=3),
        _nth_weekday(year, 2, weekday=0, occurrence=3),
        _easter_date(year) - timedelta(days=2),
        _last_weekday(year, 5, weekday=0),
        _observed_fixed_date(year, 6, 19),
        _observed_fixed_date(year, 7, 4),
        _nth_weekday(year, 9, weekday=0, occurrence=1),
        _nth_weekday(year, 11, weekday=3, occurrence=4),
        _observed_fixed_date(year, 12, 25),
    }
    return {day for day in holidays if day.year == year}


def early_close_days(year: int) -> set[date]:
    holidays = market_holidays(year)
    candidates = {
        date(year, 7, 3),
        _nth_weekday(year, 11, weekday=3, occurrence=4) + timedelta(days=1),
        date(year, 12, 24),
    }
    return {
        day
        for day in candidates
        if day.year == year and day.weekday() < WEEKEND_START and day not in holidays
    }


def _as_eastern(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        return moment.replace(tzinfo=EASTERN)
    return moment.astimezone(EASTERN)


def _combine(value: date, value_time: time) -> datetime:
    return datetime.combine(value, value_time, tzinfo=EASTERN)


def _observed_fixed_date(year: int, month: int, day: int) -> date:
    value = date(year, month, day)
    if value.weekday() == SATURDAY:
        return value - timedelta(days=1)
    if value.weekday() == SUNDAY:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, *, weekday: int, occurrence: int) -> date:
    value = date(year, month, 1)
    while value.weekday() != weekday:
        value += timedelta(days=1)
    return value + timedelta(days=7 * (occurrence - 1))


def _last_weekday(year: int, month: int, *, weekday: int) -> date:
    if month == DECEMBER:
        value = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        value = date(year, month + 1, 1) - timedelta(days=1)
    while value.weekday() != weekday:
        value -= timedelta(days=1)
    return value


def _easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    month = (h + correction - 7 * m + 114) // 31
    day = ((h + correction - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _dt_text(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
