from __future__ import annotations

import json
from pathlib import Path

import pytest

from agency.portfolio.policy import PortfolioPolicy


def test_policy_defaults_match_spec() -> None:
    policy = PortfolioPolicy()

    assert policy.stop_loss_pct == 2.0
    assert policy.take_profit_stage1_pct == 2.0
    assert policy.take_profit_stage2_pct == 4.0
    assert policy.trailing_stop_pct == 1.5
    assert policy.trailing_stop_activates_at_pct == 1.5
    assert policy.suggested_stage1_trim_pct == 0.50
    assert policy.minimum_hold_days == 2
    assert policy.time_stop_days == 4
    assert policy.time_stop_flat_threshold_pct == 0.5
    assert policy.reentry_cooldown_hours == 24
    assert policy.weekly_target_pct == 3.0
    assert policy.weekly_target_approach_pct == 2.5
    assert policy.weekly_drawdown_limit_pct == 6.0
    assert policy.daily_circuit_breaker_pct == 3.0
    assert policy.max_positions == 8
    assert policy.cash_reserve_pct == 20.0
    assert policy.max_gross_exposure_pct == 80.0
    assert policy.thesis_broken_conviction_floor == 0.40
    assert policy.live_trading_enabled is False
    assert policy.broker_submit_enabled is False
    assert policy.allow_short_trades is False


def test_policy_from_env_loads_all_env_overrides() -> None:
    env = {
        "AGENCY_WEEKLY_TARGET_PCT": "3.5",
        "AGENCY_WEEKLY_TARGET_APPROACH_PCT": "2.8",
        "AGENCY_WEEKLY_DRAWDOWN_LIMIT_PCT": "5.5",
        "AGENCY_DAILY_CIRCUIT_BREAKER_PCT": "2.5",
        "AGENCY_MAX_POSITIONS": "7",
        "AGENCY_MAX_NEW_POSITIONS_PER_DAY": "3",
        "AGENCY_DEFAULT_POSITION_PCT": "9.0",
        "AGENCY_REDUCED_POSITION_PCT": "4.0",
        "AGENCY_MAX_SINGLE_NAME_PCT": "18.0",
        "AGENCY_MAX_SECTOR_EXPOSURE_PCT": "28.0",
        "AGENCY_CASH_RESERVE_PCT": "25.0",
        "AGENCY_MAX_GROSS_EXPOSURE_PCT": "75.0",
        "AGENCY_STOP_LOSS_PCT": "1.8",
        "AGENCY_TAKE_PROFIT_STAGE1_PCT": "2.4",
        "AGENCY_TAKE_PROFIT_STAGE2_PCT": "4.8",
        "AGENCY_TRAILING_STOP_PCT": "1.2",
        "AGENCY_TRAILING_STOP_ACTIVATES_AT_PCT": "1.6",
        "AGENCY_SUGGESTED_STAGE1_TRIM_PCT": "0.4",
        "AGENCY_THESIS_BROKEN_CONVICTION_FLOOR": "0.45",
        "AGENCY_MIN_FINAL_CONVICTION": "0.7",
        "AGENCY_MINIMUM_HOLD_DAYS": "3",
        "AGENCY_TIME_STOP_DAYS": "5",
        "AGENCY_TIME_STOP_FLAT_THRESHOLD_PCT": "0.7",
        "AGENCY_REENTRY_COOLDOWN_HOURS": "36",
        "AGENCY_LIVE_TRADING_ENABLED": "true",
        "AGENCY_BROKER_SUBMIT_ENABLED": "yes",
        "AGENCY_ALLOW_SHORT_TRADES": "1",
    }

    policy = PortfolioPolicy.from_env(env)

    assert policy.weekly_target_pct == pytest.approx(3.5)
    assert policy.weekly_target_approach_pct == pytest.approx(2.8)
    assert policy.weekly_drawdown_limit_pct == pytest.approx(5.5)
    assert policy.daily_circuit_breaker_pct == pytest.approx(2.5)
    assert policy.max_positions == 7
    assert policy.max_new_positions_per_day == 3
    assert policy.default_position_pct == pytest.approx(9.0)
    assert policy.reduced_position_pct == pytest.approx(4.0)
    assert policy.max_single_name_pct == pytest.approx(18.0)
    assert policy.max_sector_exposure_pct == pytest.approx(28.0)
    assert policy.cash_reserve_pct == pytest.approx(25.0)
    assert policy.max_gross_exposure_pct == pytest.approx(75.0)
    assert policy.stop_loss_pct == pytest.approx(1.8)
    assert policy.take_profit_stage1_pct == pytest.approx(2.4)
    assert policy.take_profit_stage2_pct == pytest.approx(4.8)
    assert policy.trailing_stop_pct == pytest.approx(1.2)
    assert policy.trailing_stop_activates_at_pct == pytest.approx(1.6)
    assert policy.suggested_stage1_trim_pct == pytest.approx(0.4)
    assert policy.thesis_broken_conviction_floor == pytest.approx(0.45)
    assert policy.min_final_conviction == pytest.approx(0.7)
    assert policy.minimum_hold_days == 3
    assert policy.time_stop_days == 5
    assert policy.time_stop_flat_threshold_pct == pytest.approx(0.7)
    assert policy.reentry_cooldown_hours == 36
    assert policy.live_trading_enabled is True
    assert policy.broker_submit_enabled is True
    assert policy.allow_short_trades is True


def test_policy_loads_local_json_override(tmp_path: Path) -> None:
    policy_path = tmp_path / "portfolio-policy.local.json"
    policy_path.write_text(
        json.dumps(
            {
                "weekly_target_pct": 4.0,
                "max_positions": 6,
                "default_position_pct": 8.5,
                "broker_submit_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    policy = PortfolioPolicy.from_env({"AGENCY_PORTFOLIO_POLICY_PATH": str(policy_path)})

    assert policy.weekly_target_pct == pytest.approx(4.0)
    assert policy.max_positions == 6
    assert policy.default_position_pct == pytest.approx(8.5)
    assert policy.broker_submit_enabled is True


def test_policy_env_safety_flags_win_over_json(tmp_path: Path) -> None:
    policy_path = tmp_path / "portfolio-policy.local.json"
    policy_path.write_text(
        json.dumps(
            {
                "live_trading_enabled": True,
                "broker_submit_enabled": True,
                "allow_short_trades": True,
            }
        ),
        encoding="utf-8",
    )

    policy = PortfolioPolicy.from_env(
        {
            "AGENCY_PORTFOLIO_POLICY_PATH": str(policy_path),
            "AGENCY_LIVE_TRADING_ENABLED": "false",
            "AGENCY_BROKER_SUBMIT_ENABLED": "false",
            "AGENCY_ALLOW_SHORT_TRADES": "false",
        }
    )

    assert policy.live_trading_enabled is False
    assert policy.broker_submit_enabled is False
    assert policy.allow_short_trades is False


def test_high_water_marks_missing_file_returns_empty(tmp_path: Path) -> None:
    from agency.portfolio.state import load_high_water_marks

    marks = load_high_water_marks(tmp_path)

    assert marks == {}


def test_high_water_marks_roundtrip(tmp_path: Path) -> None:
    from agency.portfolio.state import load_high_water_marks, save_high_water_marks

    data = {"AAPL": 3.45, "MSFT": 1.20}

    save_high_water_marks(tmp_path, data)
    loaded = load_high_water_marks(tmp_path)

    assert loaded == {"AAPL": 3.45, "MSFT": 1.20}


def test_weekly_performance_no_baseline() -> None:
    from agency.portfolio.performance import compute_weekly_performance

    result = compute_weekly_performance(
        account={"equity": 100000.0},
        weekly_baseline=None,
        policy=PortfolioPolicy(),
    )

    assert result["weekly_return_pct"] is None
    assert result["baseline_equity"] is None


def test_weekly_performance_gain() -> None:
    from agency.portfolio.performance import compute_weekly_performance

    result = compute_weekly_performance(
        account={"equity": 103000.0},
        weekly_baseline={"week_start": "2026-05-26", "equity": 100000.0},
        policy=PortfolioPolicy(),
    )

    assert result["weekly_return_pct"] == pytest.approx(3.0, abs=0.01)
    assert result["weekly_pl"] == pytest.approx(3000.0, abs=0.01)
    assert result["pct_of_target_reached"] == pytest.approx(100.0, abs=0.1)


def test_daily_performance_loss() -> None:
    from agency.portfolio.performance import compute_daily_performance

    result = compute_daily_performance(
        account={"equity": 97000.0},
        daily_baseline={"date": "2026-05-29", "equity": 100000.0},
    )

    assert result["daily_return_pct"] == pytest.approx(-3.0, abs=0.01)
    assert result["daily_pl"] == pytest.approx(-3000.0, abs=0.01)
