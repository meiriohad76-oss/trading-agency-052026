from __future__ import annotations

from agency.services.broker_audit import (
    build_order_execution_state,
    build_order_intent_execution_state,
    build_portfolio_snapshot,
)


def test_build_order_execution_state_redacts_order_identity() -> None:
    state = build_order_execution_state(
        cycle_id="cycle-1",
        order={
            "order_id": "raw-order-id",
            "client_order_id": "client-1",
            "ticker": "AAPL",
            "side": "BUY",
            "type": "MARKET",
            "time_in_force": "DAY",
            "status": "accepted",
            "notional": 5.0,
            "submitted_at": "2026-05-10T09:30:00Z",
            "filled_qty": 0.0,
        },
    )

    payload = state["payload"]
    assert state["state"] == "ACCEPTED"
    assert state["ticker"] == "AAPL"
    assert "raw-order-id" not in str(state)
    assert isinstance(payload, dict)
    assert payload["order"]["order_id_hash"]


def test_build_order_intent_execution_state_is_recoverable_before_submit() -> None:
    state = build_order_intent_execution_state(
        cycle_id="cycle-1",
        preview={
            "cycle_id": "cycle-1",
            "ticker": "AAPL",
            "as_of": "2026-05-10T09:30:00Z",
            "order_intent_hash": "a" * 64,
            "order_intent_version": "0.1.0",
        },
        order_payload={
            "symbol": "AAPL",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": "client-1",
            "notional": 1000.0,
        },
        event_time="2026-05-10T09:30:01Z",
    )

    payload = state["payload"]
    assert state["state"] == "READY"
    assert state["execution_id"] == "a" * 64
    assert payload["client_order_id"] == "client-1"  # type: ignore[index]
    assert payload["reconciliation_state"] == "intent_recorded_before_broker_submit"  # type: ignore[index]


def test_build_portfolio_snapshot_summarizes_broker_state() -> None:
    snapshot = build_portfolio_snapshot(
        {
            "provider": "alpaca",
            "mode": "paper",
            "account": {
                "account_id_hash": "account-hash",
                "status": "ACTIVE",
                "equity": 100000.0,
                "cash": 99000.0,
                "buying_power": 198000.0,
                "portfolio_value": 100000.0,
            },
            "positions": [{"ticker": "AAPL", "qty": 1.0}],
            "orders": [{"order_id": "order-1", "ticker": "AAPL", "status": "accepted"}],
            "gross_exposure_pct": 1.0,
        },
        captured_at="2026-05-10T09:31:00Z",
    )

    assert snapshot["position_count"] == 1
    assert snapshot["open_order_count"] == 1
    assert snapshot["payload"]["orders"][0]["order_id_hash"]  # type: ignore[index]
