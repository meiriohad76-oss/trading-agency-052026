"""Tests for T134: trailing stop exit using persisted high-water marks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service_fixtures import selection_report

from agency.services import PortfolioPolicy, build_portfolio_monitor
from agency.services.portfolio_monitor import update_high_water_marks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _broker_position(ticker: str, unrealized_plpc: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "qty": 1.0,
        "market_value": 1000.0,
        "unrealized_pl": unrealized_plpc * 1000.0,
        "unrealized_plpc": unrealized_plpc,
        "side": "LONG",
    }


# ---------------------------------------------------------------------------
# Trailing stop – triggers
# ---------------------------------------------------------------------------

def test_trailing_stop_triggers_when_drawdown_exceeds_threshold() -> None:
    """high_water_mark=10.0%, pnl=-2.0%, trailing_stop=8.0% → drawdown 12% ≥ 8% → TRAILING_STOP."""
    policy = PortfolioPolicy(
        take_profit_pct=15.0,
        stop_loss_pct=10.0,
        trailing_stop_pct=8.0,
    )
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", -0.02)],  # pnl = -2%
        high_water_marks={"AAPL": 10.0},  # peak = 10%
        policy=policy,
        generated_at="2026-05-07T09:34:00Z",
    )

    row = snapshot["positions"][0]
    assert row["exit_signal"] == "TRAILING_STOP", (
        f"Expected TRAILING_STOP but got {row['exit_signal']!r}. "
        "Drawdown of 12% should exceed trailing_stop_pct=8%."
    )
    assert row["exit_priority"] == "NORMAL"
    assert row["classification"] == "CLOSE_CANDIDATE"


def test_trailing_stop_triggers_exactly_at_threshold() -> None:
    """Drawdown exactly equal to trailing_stop_pct should trigger (>=)."""
    policy = PortfolioPolicy(
        take_profit_pct=15.0,
        stop_loss_pct=10.0,
        trailing_stop_pct=5.0,
    )
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", 0.0)],  # pnl = 0%
        high_water_marks={"AAPL": 5.0},  # peak = 5%  → drawdown = 5% = threshold
        policy=policy,
        generated_at="2026-05-07T09:34:00Z",
    )

    assert snapshot["positions"][0]["exit_signal"] == "TRAILING_STOP"


# ---------------------------------------------------------------------------
# Trailing stop – does NOT trigger
# ---------------------------------------------------------------------------

def test_trailing_stop_not_triggered_when_below_threshold() -> None:
    """high_water_mark=5.0%, pnl=3.0%, trailing_stop=8.0% → drawdown 2% < 8% → no exit."""
    policy = PortfolioPolicy(
        take_profit_pct=15.0,
        stop_loss_pct=10.0,
        trailing_stop_pct=8.0,
    )
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", 0.03)],  # pnl = 3%
        high_water_marks={"AAPL": 5.0},  # peak = 5%  → drawdown = 2%
        policy=policy,
        generated_at="2026-05-07T09:34:00Z",
    )

    row = snapshot["positions"][0]
    assert row["exit_signal"] != "TRAILING_STOP", (
        "Drawdown of 2% is below trailing_stop_pct=8% – should not trigger."
    )


def test_trailing_stop_not_triggered_without_high_water_mark() -> None:
    """No entry in high_water_marks for the ticker → trailing stop cannot fire."""
    policy = PortfolioPolicy(
        take_profit_pct=15.0,
        stop_loss_pct=10.0,
        trailing_stop_pct=3.0,
    )
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", -0.05)],  # pnl = -5%
        high_water_marks={},  # no mark → can't compute drawdown
        policy=policy,
        generated_at="2026-05-07T09:34:00Z",
    )

    row = snapshot["positions"][0]
    # With no high-water mark the trailing stop must not fire (stop_loss would fire here
    # because -5% > stop_loss_pct=4% default, so override stop_loss_pct high enough).
    assert row["exit_signal"] != "TRAILING_STOP"


def test_trailing_stop_not_triggered_when_no_broker_position() -> None:
    """No broker position means pnl_pct is None → trailing stop cannot fire."""
    policy = PortfolioPolicy(trailing_stop_pct=1.0)
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        positions=["AAPL"],
        high_water_marks={"AAPL": 10.0},
        policy=policy,
        generated_at="2026-05-07T09:34:00Z",
    )

    assert snapshot["positions"][0]["exit_signal"] != "TRAILING_STOP"


# ---------------------------------------------------------------------------
# Trailing stop check order: stop-loss wins over trailing stop
# ---------------------------------------------------------------------------

def test_stop_loss_takes_priority_over_trailing_stop() -> None:
    """When both stop_loss and trailing_stop would trigger, stop_loss (URGENT) wins."""
    policy = PortfolioPolicy(
        take_profit_pct=15.0,
        stop_loss_pct=4.0,
        trailing_stop_pct=3.0,
    )
    # pnl = -5% → stop_loss triggers; drawdown vs peak=0% is only 5% > 3% but stop_loss fires first
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", -0.05)],
        high_water_marks={"AAPL": 0.0},
        policy=policy,
        generated_at="2026-05-07T09:34:00Z",
    )

    assert snapshot["positions"][0]["exit_signal"] == "STOP_LOSS"
    assert snapshot["positions"][0]["exit_priority"] == "URGENT"


# ---------------------------------------------------------------------------
# update_high_water_marks helper
# ---------------------------------------------------------------------------

def test_update_high_water_marks_updates_peak() -> None:
    """Marks should increase to the new pnl_pct but never decrease."""
    rows = [
        {
            "ticker": "AAPL",
            "unrealized_plpc": 0.12,  # 12%
        },
        {
            "ticker": "MSFT",
            "unrealized_plpc": 0.05,  # 5%
        },
    ]
    updated = update_high_water_marks({"AAPL": 10.0, "MSFT": 8.0}, rows)

    assert updated["AAPL"] == pytest.approx(12.0)  # 12% > 10% → update
    assert updated["MSFT"] == pytest.approx(8.0)   # 5% < 8%  → keep old peak


def test_update_high_water_marks_adds_new_tickers() -> None:
    """A ticker not yet in the marks dict gets added."""
    rows = [{"ticker": "nvda", "unrealized_plpc": 0.07}]
    updated = update_high_water_marks({}, rows)

    assert "NVDA" in updated
    assert updated["NVDA"] == pytest.approx(7.0)


def test_update_high_water_marks_skips_rows_without_plpc() -> None:
    """Rows that lack unrealized_plpc are silently ignored."""
    rows = [{"ticker": "AAPL"}]  # no unrealized_plpc key
    updated = update_high_water_marks({"AAPL": 5.0}, rows)

    assert updated["AAPL"] == pytest.approx(5.0)


def test_update_high_water_marks_does_not_mutate_input() -> None:
    """The original dict passed in must not be modified."""
    original = {"AAPL": 5.0}
    rows = [{"ticker": "AAPL", "unrealized_plpc": 0.08}]
    _ = update_high_water_marks(original, rows)

    assert original == {"AAPL": 5.0}


# ---------------------------------------------------------------------------
# high_water_marks_path persistence
# ---------------------------------------------------------------------------

def test_high_water_marks_path_loads_and_saves(tmp_path: Path) -> None:
    """If high_water_marks_path is given, marks are loaded then saved after the call."""
    marks_file = tmp_path / "hwm.json"
    marks_file.write_text(json.dumps({"AAPL": 6.0}), encoding="utf-8")

    policy = PortfolioPolicy(
        take_profit_pct=15.0,
        stop_loss_pct=10.0,
        trailing_stop_pct=8.0,
    )
    build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", 0.09)],  # 9% – new peak
        policy=policy,
        high_water_marks_path=marks_file,
        generated_at="2026-05-07T09:34:00Z",
    )

    saved = json.loads(marks_file.read_text(encoding="utf-8"))
    assert saved["AAPL"] == pytest.approx(9.0)


def test_high_water_marks_path_missing_file_does_not_crash(tmp_path: Path) -> None:
    """If the path doesn't exist yet, treat marks as empty and save after."""
    marks_file = tmp_path / "hwm.json"

    build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", 0.05)],  # 5%
        high_water_marks_path=marks_file,
        generated_at="2026-05-07T09:34:00Z",
    )

    assert marks_file.exists()
    saved = json.loads(marks_file.read_text(encoding="utf-8"))
    assert saved.get("AAPL") == pytest.approx(5.0)


def test_high_water_marks_path_can_be_read_without_dashboard_write(tmp_path: Path) -> None:
    marks_file = tmp_path / "hwm.json"
    marks_file.write_text(json.dumps({"AAPL": 6.0}), encoding="utf-8")

    build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[_broker_position("AAPL", 0.09)],
        high_water_marks_path=marks_file,
        persist_high_water_marks=False,
        generated_at="2026-05-07T09:34:00Z",
    )

    assert json.loads(marks_file.read_text(encoding="utf-8")) == {"AAPL": 6.0}
