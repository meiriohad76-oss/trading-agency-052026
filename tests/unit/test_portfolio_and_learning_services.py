from __future__ import annotations

from pathlib import Path

from service_fixtures import selection_report

from agency.contracts import validate_contract
from agency.services import (
    PortfolioPolicy,
    build_learning_outcome,
    build_near_miss_journal,
    build_portfolio_monitor,
)

EXPECTED_BROKER_QUANTITY = 2.0
EXPECTED_BROKER_EQUITY = 10000.0
EXPECTED_BROKER_EXPOSURE = 5.0
OVERRIDE_CONVICTION = 0.7
OVERRIDE_MAX_NEW_POSITIONS = 2
OVERRIDE_MAX_EXPOSURE = 80.0
OVERRIDE_POSITION_SIZE = 5.0
OVERRIDE_TAKE_PROFIT = 7.5
OVERRIDE_STOP_LOSS = 3.5
OVERRIDE_TRAILING_STOP = 2.5
OVERRIDE_HOURLY_ALERT = 0.75
EXPECTED_HOURLY_RETURN = -1.0
EXPECTED_HOURLY_PL = -100.0
NEAR_MISS_SCORE = 0.42
SECOND_NEAR_MISS_SCORE = 0.48
EXPECTED_INCLUSION_GAP = 0.08
EXPECTED_WHAT_IF_RETURN = 3.0


def test_portfolio_monitor_reports_empty_read_only_snapshot() -> None:
    snapshot = build_portfolio_monitor([], generated_at="2026-05-07T09:34:00Z")

    validate_contract("portfolio-monitor", snapshot)
    assert snapshot["summary"]["position_count"] == 0
    assert snapshot["positions"] == []


def test_portfolio_monitor_classifies_existing_position_against_report() -> None:
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        positions=["AAPL", "MSFT"],
        generated_at="2026-05-07T09:34:00Z",
    )

    rows = snapshot["positions"]
    assert rows[0]["classification"] == "HOLD"
    assert rows[1]["classification"] == "NO_CURRENT_SETUP"
    assert snapshot["summary"]["hold_count"] == 1


def test_portfolio_monitor_uses_broker_positions_and_account_summary() -> None:
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[
            {
                "ticker": "AAPL",
                "qty": EXPECTED_BROKER_QUANTITY,
                "market_value": 500.0,
                "unrealized_pl": 50.0,
                "unrealized_plpc": 0.1,
                "side": "LONG",
            }
        ],
        account={"equity": EXPECTED_BROKER_EQUITY, "cash": 9500.0, "buying_power": 19000.0},
        gross_exposure_pct=EXPECTED_BROKER_EXPOSURE,
        generated_at="2026-05-07T09:34:00Z",
    )

    validate_contract("portfolio-monitor", snapshot)
    assert snapshot["mode"] == "PAPER"
    assert snapshot["positions"][0]["quantity"] == EXPECTED_BROKER_QUANTITY
    assert snapshot["summary"]["equity"] == EXPECTED_BROKER_EQUITY
    assert snapshot["summary"]["gross_exposure_pct"] == EXPECTED_BROKER_EXPOSURE


def test_portfolio_monitor_flags_take_profit_and_stop_loss_rules() -> None:
    take_profit = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[
            {
                "ticker": "AAPL",
                "qty": 1.0,
                "market_value": 1080.0,
                "unrealized_pl": 80.0,
                "unrealized_plpc": 0.08,
                "side": "LONG",
            }
        ],
        policy=PortfolioPolicy(take_profit_pct=7.0, stop_loss_pct=4.0),
        generated_at="2026-05-07T09:34:00Z",
    )
    stop_loss = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[
            {
                "ticker": "AAPL",
                "qty": 1.0,
                "market_value": 950.0,
                "unrealized_pl": -50.0,
                "unrealized_plpc": -0.05,
                "side": "LONG",
            }
        ],
        policy=PortfolioPolicy(take_profit_pct=8.0, stop_loss_pct=4.0),
        generated_at="2026-05-07T09:34:00Z",
    )

    assert take_profit["positions"][0]["exit_signal"] == "TAKE_PROFIT"
    assert take_profit["positions"][0]["classification"] == "CLOSE_CANDIDATE"
    assert stop_loss["positions"][0]["exit_signal"] == "STOP_LOSS"
    assert stop_loss["positions"][0]["exit_priority"] == "URGENT"


def test_portfolio_monitor_measures_hourly_performance_from_snapshots() -> None:
    snapshot = build_portfolio_monitor(
        [],
        account={
            "equity": 9900.0,
            "portfolio_value": 9900.0,
            "cash": 5000.0,
            "buying_power": 10000.0,
        },
        portfolio_snapshots=[
            {
                "captured_at": "2026-05-07T08:30:00Z",
                "portfolio_value": 10000.0,
                "equity": 10000.0,
            }
        ],
        policy=PortfolioPolicy(hourly_loss_alert_pct=0.5),
        generated_at="2026-05-07T09:35:00Z",
    )

    assert snapshot["summary"]["hourly_return_pct"] == EXPECTED_HOURLY_RETURN
    assert snapshot["summary"]["hourly_pl"] == EXPECTED_HOURLY_PL
    assert snapshot["summary"]["hourly_status"] == "WARN"


def test_learning_outcome_is_premature_until_enough_samples() -> None:
    outcome = build_learning_outcome(generated_at="2026-05-07T09:35:00Z")

    validate_contract("learning-outcome", outcome)
    assert outcome["status"] == "PREMATURE"
    assert outcome["sample_count"] == 0


def test_learning_outcome_can_be_ready_for_review() -> None:
    outcome = build_learning_outcome(
        [{"ticker": "AAPL", "review_decision": "APPROVE", "return_pct": 1.2}],
        generated_at="2026-05-07T09:35:00Z",
        required_sample_count=1,
    )

    assert outcome["status"] == "READY"
    assert outcome["requirements"][0]["status"] == "PASS"
    assert outcome["metrics"]["win_count"] == 1
    assert outcome["metrics"]["decision_counts"] == {"APPROVE": 1}
    assert outcome["recommendations"][0]["status"] == "DISABLED"


def test_near_miss_journal_logs_close_rejects_and_what_if_returns() -> None:
    report = selection_report(action="NO_TRADE", score=NEAR_MISS_SCORE)
    deterministic = report["deterministic"]
    assert isinstance(deterministic, dict)
    deterministic["score"] = NEAR_MISS_SCORE
    deterministic["reason_codes"] = ["signal_strength_below_threshold"]
    deterministic["blockers"] = []

    journal = build_near_miss_journal(
        [report],
        price_history=[
            {"ticker": "AAPL", "date": "2026-05-07", "close": 100.0},
            {"ticker": "AAPL", "date": "2026-05-08", "close": 103.0},
            {"ticker": "AAPL", "date": "2026-05-11", "close": 105.0},
        ],
        watch_threshold=0.5,
        near_miss_margin=0.1,
        horizons=(1, 2),
    )

    row = journal["rows"][0]
    assert journal["near_miss_count"] == 1
    assert row["ticker"] == "AAPL"
    assert row["inclusion_gap"] == EXPECTED_INCLUSION_GAP
    assert row["what_if"]["horizons"][0]["return_pct"] == EXPECTED_WHAT_IF_RETURN
    assert journal["summary"]["evaluated_count"] == 1


def test_learning_outcome_includes_near_miss_journal() -> None:
    report = selection_report(action="NO_TRADE", score=SECOND_NEAR_MISS_SCORE)
    deterministic = report["deterministic"]
    assert isinstance(deterministic, dict)
    deterministic["score"] = SECOND_NEAR_MISS_SCORE
    deterministic["reason_codes"] = ["signal_strength_below_threshold"]
    deterministic["blockers"] = []

    outcome = build_learning_outcome(
        selection_reports=[report],
        price_history=[
            {"ticker": "AAPL", "date": "2026-05-07", "close": 100.0},
            {"ticker": "AAPL", "date": "2026-05-08", "close": 99.0},
        ],
        generated_at="2026-05-07T09:35:00Z",
    )

    validate_contract("learning-outcome", outcome)
    assert outcome["near_miss_journal"]["near_miss_count"] == 1


def test_portfolio_policy_can_load_local_json_override(tmp_path: Path) -> None:
    policy_path = tmp_path / "portfolio-policy.local.json"
    policy_path.write_text(
        '{"min_final_conviction": 0.7, "max_new_positions_per_cycle": 2, '
        '"max_gross_exposure_pct": 80, "default_position_pct": 5, '
        '"take_profit_pct": 7.5, "stop_loss_pct": 3.5, '
        '"trailing_stop_pct": 2.5, "hourly_loss_alert_pct": 0.75, '
        '"broker_submit_enabled": true}',
        encoding="utf-8",
    )

    policy = PortfolioPolicy.from_env(
        {
            "AGENCY_PORTFOLIO_POLICY_PATH": str(policy_path),
            "AGENCY_BROKER_SUBMIT_ENABLED": "true",
        }
    )

    assert policy.min_final_conviction == OVERRIDE_CONVICTION
    assert policy.max_new_positions_per_cycle == OVERRIDE_MAX_NEW_POSITIONS
    assert policy.max_gross_exposure_pct == OVERRIDE_MAX_EXPOSURE
    assert policy.default_position_pct == OVERRIDE_POSITION_SIZE
    assert policy.take_profit_pct == OVERRIDE_TAKE_PROFIT
    assert policy.stop_loss_pct == OVERRIDE_STOP_LOSS
    assert policy.trailing_stop_pct == OVERRIDE_TRAILING_STOP
    assert policy.hourly_loss_alert_pct == OVERRIDE_HOURLY_ALERT
    assert policy.broker_submit_enabled is True


def test_portfolio_policy_env_submit_kill_switch_wins_over_json(tmp_path: Path) -> None:
    policy_path = tmp_path / "portfolio-policy.local.json"
    policy_path.write_text('{"broker_submit_enabled": true}', encoding="utf-8")

    policy = PortfolioPolicy.from_env(
        {
            "AGENCY_PORTFOLIO_POLICY_PATH": str(policy_path),
            "AGENCY_BROKER_SUBMIT_ENABLED": "false",
        }
    )

    assert policy.broker_submit_enabled is False
