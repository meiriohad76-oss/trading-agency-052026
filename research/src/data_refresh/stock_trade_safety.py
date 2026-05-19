from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from data_refresh.market_calendar import is_trading_day

DEFAULT_MAX_DIRECT_TRADING_DAYS = 5
DEFAULT_MAX_DIRECT_TICKER_DAYS = 750
DEFAULT_MAX_UNCAPPED_TICKERS = 35


@dataclass(frozen=True)
class StockTradeSafetyLimits:
    max_trading_days: int = DEFAULT_MAX_DIRECT_TRADING_DAYS
    max_ticker_days: int = DEFAULT_MAX_DIRECT_TICKER_DAYS
    max_uncapped_tickers: int = DEFAULT_MAX_UNCAPPED_TICKERS


@dataclass(frozen=True)
class StockTradeSafetySummary:
    trading_days: int
    ticker_count: int
    ticker_days: int
    reasons: tuple[str, ...]

    @property
    def safe(self) -> bool:
        return not self.reasons


def stock_trade_safety_summary(
    *,
    tickers: tuple[str, ...],
    start: date,
    end: date,
    limits: StockTradeSafetyLimits | None = None,
    allow_large_window: bool = False,
    unbounded_pages: bool = False,
) -> StockTradeSafetySummary:
    active_limits = limits or StockTradeSafetyLimits()
    trading_days = _trading_day_count(start, end)
    ticker_count = len({ticker.upper() for ticker in tickers})
    ticker_days = trading_days * max(ticker_count, 1)
    if allow_large_window:
        return StockTradeSafetySummary(trading_days, ticker_count, ticker_days, ())
    reasons = _safety_reasons(
        start=start,
        end=end,
        trading_days=trading_days,
        ticker_count=ticker_count,
        ticker_days=ticker_days,
        limits=active_limits,
        unbounded_pages=unbounded_pages,
    )
    return StockTradeSafetySummary(trading_days, ticker_count, ticker_days, reasons)


def stock_trade_safety_reasons(
    *,
    tickers: tuple[str, ...],
    start: date,
    end: date,
    limits: StockTradeSafetyLimits | None = None,
    allow_large_window: bool = False,
    unbounded_pages: bool = False,
) -> tuple[str, ...]:
    return stock_trade_safety_summary(
        tickers=tickers,
        start=start,
        end=end,
        limits=limits,
        allow_large_window=allow_large_window,
        unbounded_pages=unbounded_pages,
    ).reasons


def _safety_reasons(
    *,
    start: date,
    end: date,
    trading_days: int,
    ticker_count: int,
    ticker_days: int,
    limits: StockTradeSafetyLimits,
    unbounded_pages: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if end < start:
        reasons.append("stock_trades_end must be on or after stock_trades_start")
    if trading_days > limits.max_trading_days:
        reasons.append(
            "stock_trades direct live refresh spans "
            f"{trading_days} trading day(s); use backfill_massive_stock_trades.py "
            "for historical repair."
        )
    if ticker_days > limits.max_ticker_days:
        reasons.append(
            "stock_trades direct live refresh would request "
            f"{ticker_days} ticker-day(s); split it into scheduler/backfill batches."
        )
    if unbounded_pages and ticker_count > limits.max_uncapped_tickers:
        reasons.append(
            "stock_trades direct live refresh is uncapped for "
            f"{ticker_count} ticker(s); use a page-capped live refresh or "
            "backfill_massive_stock_trades.py for full-depth repair."
        )
    return tuple(reasons)


def _trading_day_count(start: date, end: date) -> int:
    if end < start:
        return 0
    current = start
    count = 0
    while current <= end:
        if is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count
