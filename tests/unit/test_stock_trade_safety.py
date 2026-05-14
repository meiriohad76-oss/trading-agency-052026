"""Tests for StockTradeSafetyLimits and the --full-universe bypass path (T151)."""
from __future__ import annotations

from datetime import date

from data_refresh.stock_trade_safety import (
    StockTradeSafetyLimits,
    stock_trade_safety_reasons,
)

# ---------------------------------------------------------------------------
# Sentinel value mirrored from the pull script
# ---------------------------------------------------------------------------
_FULL_UNIVERSE_SENTINEL = 10_000_000

# A large universe typical of a full-universe pull
_FULL_UNIVERSE_TICKERS = tuple(f"T{i}" for i in range(500))
_YEAR_START = date(2024, 1, 1)
_YEAR_END = date(2024, 12, 31)


def test_full_universe_flag_disables_safety_limits() -> None:
    """When allow_large_window=True the guard returns no blocking reasons."""
    reasons = stock_trade_safety_reasons(
        tickers=_FULL_UNIVERSE_TICKERS,
        start=_YEAR_START,
        end=_YEAR_END,
        limits=StockTradeSafetyLimits(
            max_trading_days=_FULL_UNIVERSE_SENTINEL,
            max_ticker_days=_FULL_UNIVERSE_SENTINEL,
        ),
        allow_large_window=True,
        unbounded_pages=True,
    )

    assert reasons == (), f"Expected no safety reasons but got: {reasons}"


def test_full_universe_sentinel_limits_alone_would_still_be_bypassed() -> None:
    """Sentinel limits without allow_large_window are permissive enough for a year pull."""
    reasons = stock_trade_safety_reasons(
        tickers=_FULL_UNIVERSE_TICKERS,
        start=_YEAR_START,
        end=_YEAR_END,
        limits=StockTradeSafetyLimits(
            max_trading_days=_FULL_UNIVERSE_SENTINEL,
            max_ticker_days=_FULL_UNIVERSE_SENTINEL,
        ),
        allow_large_window=False,
        unbounded_pages=False,
    )

    # Sentinel limits are large enough that no trading-day or ticker-day
    # reason fires; the uncapped-ticker guard is also not triggered when
    # unbounded_pages=False.
    assert reasons == (), f"Expected no safety reasons but got: {reasons}"


def test_default_limits_block_large_window() -> None:
    """Default limits still block a full-year pull when allow_large_window is False."""
    reasons = stock_trade_safety_reasons(
        tickers=("AAPL", "MSFT"),
        start=_YEAR_START,
        end=_YEAR_END,
        allow_large_window=False,
    )

    assert len(reasons) > 0, "Expected at least one safety reason for a year-long window"
    assert any("direct live refresh spans" in r for r in reasons)


def test_allow_large_window_overrides_default_limits_regardless_of_ticker_count() -> None:
    """allow_large_window=True short-circuits all checks, even with many tickers."""
    reasons = stock_trade_safety_reasons(
        tickers=_FULL_UNIVERSE_TICKERS,
        start=_YEAR_START,
        end=_YEAR_END,
        allow_large_window=True,
        unbounded_pages=True,
    )

    assert reasons == ()
