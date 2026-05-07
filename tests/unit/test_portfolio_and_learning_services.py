from __future__ import annotations

from service_fixtures import selection_report

from agency.contracts import validate_contract
from agency.services import build_learning_outcome, build_portfolio_monitor


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


def test_learning_outcome_is_premature_until_enough_samples() -> None:
    outcome = build_learning_outcome(generated_at="2026-05-07T09:35:00Z")

    validate_contract("learning-outcome", outcome)
    assert outcome["status"] == "PREMATURE"
    assert outcome["sample_count"] == 0


def test_learning_outcome_can_be_ready_for_review() -> None:
    outcome = build_learning_outcome(
        [{"ticker": "AAPL"}],
        generated_at="2026-05-07T09:35:00Z",
        required_sample_count=1,
    )

    assert outcome["status"] == "READY"
    assert outcome["requirements"][0]["status"] == "PASS"
