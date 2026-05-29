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


def _weekly_perf(return_pct: float) -> dict[str, float]:
    return {
        "weekly_return_pct": return_pct,
        "target_pct": 3.0,
        "pct_of_target_reached": return_pct / 3.0 * 100.0,
    }


def _daily_perf(return_pct: float) -> dict[str, float]:
    return {"daily_return_pct": return_pct}


def test_circuit_breaker_weekly_target_reached() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers

    result = evaluate_circuit_breakers(
        _weekly_perf(3.0),
        _daily_perf(0.5),
        PortfolioPolicy(),
    )

    assert result["new_entries_blocked"] is True
    assert "WEEKLY_TARGET_REACHED" in result["signals"]


def test_circuit_breaker_weekly_target_approach() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers

    result = evaluate_circuit_breakers(
        _weekly_perf(2.6),
        _daily_perf(0.5),
        PortfolioPolicy(),
    )

    assert result["new_entries_blocked"] is False
    assert result["reduced_sizing_active"] is True
    assert "WEEKLY_TARGET_APPROACH" in result["signals"]
    assert result["recommended_position_pct"] == PortfolioPolicy().reduced_position_pct


def test_circuit_breaker_daily_loss() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers

    result = evaluate_circuit_breakers(
        _weekly_perf(0.5),
        _daily_perf(-3.0),
        PortfolioPolicy(),
    )

    assert result["new_entries_blocked"] is True
    assert "DAILY_CIRCUIT_BREAKER" in result["signals"]


def test_circuit_breaker_weekly_drawdown_limit() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers

    result = evaluate_circuit_breakers(
        _weekly_perf(-6.0),
        _daily_perf(-1.0),
        PortfolioPolicy(),
    )

    assert result["new_entries_blocked"] is True
    assert "WEEKLY_DRAWDOWN_LIMIT" in result["signals"]


def test_circuit_breaker_all_clear() -> None:
    from agency.portfolio.circuit_breaker import evaluate_circuit_breakers

    result = evaluate_circuit_breakers(
        _weekly_perf(1.0),
        _daily_perf(0.5),
        PortfolioPolicy(),
    )

    assert result["new_entries_blocked"] is False
    assert result["reduced_sizing_active"] is False
    assert result["signals"] == []
    assert result["recommended_position_pct"] == PortfolioPolicy().default_position_pct


def test_stop_loss_fires_on_day_1() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=-2.0,
        quantity=10.0,
        trading_days_held=0,
        high_water_mark_pct=0.0,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "STOP_LOSS"
    assert result["exit_priority"] == "URGENT"
    assert result["recommendation"]["action"] == "CLOSE"


def test_stop_loss_keeps_lower_priority_thesis_secondary() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=-2.2,
        quantity=10.0,
        trading_days_held=0,
        high_water_mark_pct=0.0,
        stage1_executed=False,
        selection_report={"final_action": "NO_TRADE", "final_conviction": 0.20},
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "STOP_LOSS"
    assert result["secondary_signals"] == ["THESIS_BROKEN"]


def test_thesis_broken_fires_on_day_1() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    report = {
        "final_action": "NO_TRADE",
        "final_conviction": 0.80,
        "risk_flags": [],
        "policy_gates": [],
    }

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.0,
        quantity=10.0,
        trading_days_held=0,
        high_water_mark_pct=1.0,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "THESIS_BROKEN"
    assert result["exit_priority"] == "HIGH"
    assert result["recommendation"]["action"] == "CLOSE"


def test_thesis_broken_fires_on_low_conviction() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    report = {
        "final_action": "WATCH",
        "final_conviction": 0.35,
        "risk_flags": [],
        "policy_gates": [],
    }

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "THESIS_BROKEN"


def test_thesis_broken_uses_action_fallback_and_normalizes_case() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report={"action": " no_trade ", "final_conviction": "not-a-number"},
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "THESIS_BROKEN"


def test_malformed_selection_report_does_not_crash() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report={"final_action": None, "final_conviction": None},
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_trailing_stop_dormant_below_activation_gate() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.2,
        quantity=10.0,
        trading_days_held=3,
        high_water_mark_pct=0.8,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_trailing_stop_activates_after_gate() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.9,
        quantity=10.0,
        trading_days_held=3,
        high_water_mark_pct=2.5,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "TRAILING_STOP"
    assert result["exit_priority"] == "NORMAL"
    assert result["recommendation"]["action"] == "CLOSE"


def test_trailing_stop_requires_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.9,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=2.5,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_trailing_stop_does_not_fire_below_drawback_threshold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.2,
        quantity=10.0,
        trading_days_held=3,
        high_water_mark_pct=2.5,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_take_profit_stage2_fires_after_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=4.1,
        quantity=10.0,
        trading_days_held=2,
        high_water_mark_pct=4.1,
        stage1_executed=True,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "TAKE_PROFIT_STAGE_2"
    assert result["recommendation"]["action"] == "CLOSE"


def test_take_profit_stage2_does_not_require_stage1() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=4.1,
        quantity=10.0,
        trading_days_held=2,
        high_water_mark_pct=4.1,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "TAKE_PROFIT_STAGE_2"


def test_take_profit_stage1_requires_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=2.5,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_take_profit_stage1_fires_after_minimum_hold() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.3,
        quantity=10.0,
        trading_days_held=2,
        high_water_mark_pct=2.3,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "TAKE_PROFIT_STAGE_1"
    assert result["exit_priority"] == "NORMAL"
    assert result["recommendation"]["action"] == "TRIM"
    assert result["recommendation"]["suggested_trim_pct"] == 0.50
    assert result["recommendation"]["suggested_trim_qty"] == 5.0
    assert result["recommendation"]["breakeven_stop_recommendation"] is True


def test_take_profit_stage1_preserves_fractional_quantity() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.3,
        quantity=3.75,
        trading_days_held=2,
        high_water_mark_pct=2.3,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["recommendation"]["suggested_trim_qty"] == pytest.approx(1.875)


def test_take_profit_stage1_ignores_zero_quantity() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.3,
        quantity=0.0,
        trading_days_held=2,
        high_water_mark_pct=2.3,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_stage1_suppressed_when_already_executed() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=2.5,
        quantity=5.0,
        trading_days_held=2,
        high_water_mark_pct=2.5,
        stage1_executed=True,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_time_stop_fires_after_flat_days() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.3,
        quantity=10.0,
        trading_days_held=5,
        high_water_mark_pct=0.4,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "TIME_STOP"
    assert result["exit_priority"] == "LOW"
    assert result["recommendation"]["action"] == "REVIEW"


def test_time_stop_boundary_does_not_fire_at_exact_limit() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.3,
        quantity=10.0,
        trading_days_held=4,
        high_water_mark_pct=0.4,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_time_stop_does_not_fire_if_moving() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.2,
        quantity=10.0,
        trading_days_held=5,
        high_water_mark_pct=1.2,
        stage1_executed=False,
        selection_report=None,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"


def test_setup_warning_surfaces_as_hold_with_secondary_signal() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    report = {
        "final_action": "WATCH",
        "final_conviction": 0.70,
        "risk_flags": ["low_volume"],
        "policy_gates": [],
    }

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"
    assert result["exit_priority"] == "NONE"
    assert result["secondary_signals"] == ["SETUP_WARNING"]


def test_setup_warning_fires_on_warn_policy_gate() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    report = {
        "final_action": "WATCH",
        "final_conviction": 0.70,
        "risk_flags": [],
        "policy_gates": [{"name": "liquidity", "status": "warn"}],
    }

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=0.5,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=0.5,
        stage1_executed=False,
        selection_report=report,
        policy=PortfolioPolicy(),
    )

    assert result["secondary_signals"] == ["SETUP_WARNING"]


def test_hold_when_no_rules_triggered() -> None:
    from agency.portfolio.exit_rules import evaluate_exit_signal

    result = evaluate_exit_signal(
        ticker="AAPL",
        unrealized_pct=1.0,
        quantity=10.0,
        trading_days_held=1,
        high_water_mark_pct=1.0,
        stage1_executed=False,
        selection_report={
            "final_action": "WATCH",
            "final_conviction": 0.75,
            "risk_flags": [],
            "policy_gates": [],
        },
        policy=PortfolioPolicy(),
    )

    assert result["exit_signal"] == "HOLD"
    assert result["exit_priority"] == "NONE"
