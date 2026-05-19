from __future__ import annotations

import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from scripts.run_paper_broker_validation import (
    CycleRecord,
    build_summary,
    configure_safe_broker_reads,
    configured_as_of,
    markdown_report,
    paper_trade_verdict,
    positive_float,
    require_safe_trade_test,
    report_run_slug,
    require_decisions,
    run_cycle,
    write_report,
)


def test_configure_safe_broker_reads_forces_paper_safety_flags(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("ALPACA_ALLOW_LIVE_TRADING", "true")

    configure_safe_broker_reads()

    assert os_env("AGENCY_ALPACA_BROKER_ENABLED") == "true"
    assert os_env("AGENCY_BROKER_SUBMIT_ENABLED") == "false"
    assert os_env("ALPACA_ALLOW_LIVE_TRADING") == "false"
    assert os_env("AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS") == "true"


def test_summary_counts_review_decisions_without_account_identifier() -> None:
    summary = build_summary(
        broker={
            "provider": "alpaca",
            "mode": "paper",
            "connected": True,
            "status_label": "Broker Connected",
            "account_status": "ACTIVE",
            "currency": "USD",
            "equity": 100000.0,
            "buying_power": 200000.0,
            "cash": 100000.0,
            "positions": 0,
            "open_orders": 0,
            "gross_exposure_pct": 0.0,
        },
        records=[
            CycleRecord(
                cycle_id="cycle-1",
                queue_count=3,
                decisions=[
                    _decision("AAPL", "APPROVE"),
                    _decision("MSFT", "DEFER"),
                    _decision("NVDA", "REJECT"),
                ],
            )
        ],
        started_at=datetime(2026, 5, 10, tzinfo=UTC),
        finished_at=datetime(2026, 5, 10, 0, 1, tzinfo=UTC),
    )

    assert summary["review_decision_counts"] == dict(
        Counter({"APPROVE": 1, "DEFER": 1, "REJECT": 1})
    )
    assert "account_id" not in summary["broker"]
    assert "AAPL" in markdown_report(summary)


def test_require_decisions_fails_when_one_review_state_is_missing() -> None:
    with pytest.raises(RuntimeError, match="REJECT"):
        require_decisions({"review_decision_counts": {"APPROVE": 1, "DEFER": 1}}, True)


def test_configured_as_of_reads_refresh_config_end(tmp_path: Path) -> None:
    config_path = tmp_path / "live-refresh.local.json"
    config_path.write_text('{"end": "2025-12-31"}', encoding="utf-8")

    assert configured_as_of(config_path) == "2025-12-31"


def test_paper_trade_verdict_handles_closed_market_cancel() -> None:
    verdict = paper_trade_verdict(
        market_open=False,
        buy_order={"status": "CANCELED"},
        buy_cancelled=True,
        cleanup_order=None,
        final_ticker_quantity=0.0,
        open_order_count=0,
    )

    assert verdict == "paper_order_submit_cancel_verified_market_closed"


def test_paper_trade_verdict_rejects_pending_cancel_as_safe_closed_market() -> None:
    verdict = paper_trade_verdict(
        market_open=False,
        buy_order={"status": "PENDING_CANCEL"},
        buy_cancelled=True,
        cleanup_order=None,
        final_ticker_quantity=0.0,
        open_order_count=1,
    )

    assert verdict == "paper_trade_attention_required"


def test_paper_trade_verdict_requires_flat_final_quantity() -> None:
    verdict = paper_trade_verdict(
        market_open=True,
        buy_order={"status": "FILLED"},
        buy_cancelled=False,
        cleanup_order={"status": "FILLED"},
        final_ticker_quantity=0.01,
        open_order_count=0,
    )

    assert verdict == "paper_trade_attention_required"


def test_positive_float_rejects_non_positive_trade_notional() -> None:
    assert positive_float("5.5") == 5.5
    with pytest.raises(Exception, match="positive"):
        positive_float("0")


def test_validation_runtime_cycle_uses_no_persist_artifacts(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(command, **_kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return Result()

    monkeypatch.setattr("scripts.run_paper_broker_validation.subprocess.run", fake_run)
    args = type(
        "Args",
        (),
        {
            "output_root": tmp_path,
            "config": tmp_path / "config.json",
            "max_tickers": 2,
            "as_of": None,
            "replay_freshness": True,
            "enable_llm_review": False,
        },
    )()

    output_root = run_cycle(args, cycle_id="cycle-1", index=1)

    assert output_root == tmp_path / "cycle-1"
    assert "--no-persist" in commands[0]
    assert "--persist" not in commands[0]


def test_summary_flags_unsafe_paper_trade_test() -> None:
    summary = build_summary(
        broker={
            "provider": "alpaca",
            "mode": "paper",
            "connected": True,
            "status_label": "Broker Connected",
            "account_status": "ACTIVE",
            "currency": "USD",
            "equity": 100000.0,
            "buying_power": 200000.0,
            "cash": 100000.0,
            "positions": 0,
            "open_orders": 0,
            "gross_exposure_pct": 0.0,
        },
        records=[],
        trade_test={"verdict": "paper_trade_attention_required"},
        started_at=datetime(2026, 5, 10, tzinfo=UTC),
        finished_at=datetime(2026, 5, 10, 0, 1, tzinfo=UTC),
    )

    assert summary["verdict"] == "paper_broker_validation_attention_required"
    with pytest.raises(RuntimeError, match="did not finish safely"):
        require_safe_trade_test(summary)


def test_safe_trade_test_allows_refused_precondition_outcomes() -> None:
    for verdict in (
        "paper_trade_refused_existing_position",
        "paper_trade_refused_existing_open_order",
    ):
        summary = build_summary(
            broker={
                "provider": "alpaca",
                "mode": "paper",
                "connected": True,
                "status_label": "Broker Connected",
                "account_status": "ACTIVE",
                "currency": "USD",
                "equity": 100000.0,
                "buying_power": 200000.0,
                "cash": 100000.0,
                "positions": 0,
                "open_orders": 0,
                "gross_exposure_pct": 0.0,
            },
            records=[],
            trade_test={"verdict": verdict},
            started_at=datetime(2026, 5, 10, tzinfo=UTC),
            finished_at=datetime(2026, 5, 10, 0, 1, tzinfo=UTC),
        )

        assert summary["verdict"] == "paper_broker_validation_passed"
        require_safe_trade_test(summary)


def test_write_report_keeps_latest_and_timestamped_run(tmp_path: Path) -> None:
    summary = build_summary(
        broker={
            "provider": "alpaca",
            "mode": "paper",
            "connected": True,
            "status_label": "Broker Connected",
            "account_status": "ACTIVE",
            "currency": "USD",
            "equity": 100000.0,
            "buying_power": 200000.0,
            "cash": 100000.0,
            "positions": 0,
            "open_orders": 0,
            "gross_exposure_pct": 0.0,
        },
        records=[
            CycleRecord(
                cycle_id="cycle-1",
                queue_count=1,
                decisions=[_decision("AAPL", "APPROVE")],
            )
        ],
        started_at=datetime(2026, 5, 10, 9, 15, tzinfo=UTC),
        finished_at=datetime(2026, 5, 10, 9, 16, tzinfo=UTC),
    )

    write_report(summary, tmp_path)
    run_slug = report_run_slug(summary)

    assert (tmp_path / "paper-broker-validation.json").exists()
    assert (tmp_path / "paper-broker-validation.md").exists()
    assert (tmp_path / "runs" / f"{run_slug}.json").exists()
    assert (tmp_path / "runs" / f"{run_slug}.md").exists()


def os_env(name: str) -> str:
    return os.environ[name]


def _decision(ticker: str, decision: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "as_of": "2026-05-10T00:00:00Z",
        "decision": decision,
        "risk_decision": "WARN",
    }
