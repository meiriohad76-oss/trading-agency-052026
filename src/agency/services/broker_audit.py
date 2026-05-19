from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.runtime import record_execution_state, record_portfolio_snapshot

ORDER_STATE_MAP = {
    "ACCEPTED": "ACCEPTED",
    "ACCEPTED_FOR_BIDDING": "ACCEPTED",
    "NEW": "ACCEPTED",
    "PENDING_NEW": "ACCEPTED",
    "PARTIALLY_FILLED": "ACCEPTED",
    "PENDING_CANCEL": "PENDING_CANCEL",
    "FILLED": "FILLED",
    "CANCELED": "CANCELED",
    "CANCELLED": "CANCELED",
    "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED",
}


def build_order_execution_state(
    *,
    cycle_id: str,
    order: Mapping[str, object],
    event_time: str | None = None,
    reason: str | None = None,
    payload_extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    ticker = str(order.get("ticker", "")).upper() or None
    status = _order_status(order)
    normalized_state = ORDER_STATE_MAP.get(status, "SUBMITTED")
    order_id_hash = _stable_hash(str(order.get("order_id", "")))
    recorded_at = event_time or _order_event_time(order)
    payload: dict[str, object] = {
        "broker": "alpaca",
        "mode": "paper",
        "order": safe_order(order),
        "raw_status": status,
    }
    if payload_extra is not None:
        payload.update(payload_extra)
    state: dict[str, object] = {
        "schema_version": "0.1.0",
        "state_id": _state_id(
            cycle_id=cycle_id,
            ticker=ticker or "ALL",
            order_id_hash=order_id_hash,
            state=normalized_state,
            event_time=recorded_at,
        ),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "execution_id": order_id_hash,
        "state": normalized_state,
        "event_time": recorded_at,
        "reason": reason or _order_reason(normalized_state),
        "payload": payload,
    }
    validate_contract("execution-state", state)
    return state


async def persist_order_execution_state(
    session: AsyncSession,
    *,
    cycle_id: str,
    order: Mapping[str, object],
    event_time: str | None = None,
    reason: str | None = None,
    payload_extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    state = build_order_execution_state(
        cycle_id=cycle_id,
        order=order,
        event_time=event_time,
        reason=reason,
        payload_extra=payload_extra,
    )
    await record_execution_state(session, state)
    return state


def build_order_intent_execution_state(
    *,
    cycle_id: str,
    preview: Mapping[str, object],
    order_payload: Mapping[str, object],
    event_time: str | None = None,
    state: str = "READY",
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    ticker = str(preview.get("ticker", "")).upper() or None
    order_intent_hash = str(preview.get("order_intent_hash", "") or "")
    client_order_id = str(order_payload.get("client_order_id", "") or "")
    execution_id = order_intent_hash or _stable_hash(client_order_id, length=32)
    if not execution_id:
        execution_id = _stable_hash(
            f"{cycle_id}:{ticker}:{state}:{event_time or _now_utc()}",
            length=32,
        )
    recorded_at = event_time or _now_utc()
    payload: dict[str, object] = {
        "broker": "alpaca",
        "mode": "paper",
        "order_intent_hash": order_intent_hash,
        "order_intent_version": str(preview.get("order_intent_version", "")),
        "client_order_id": client_order_id,
        "order_payload": dict(order_payload),
        "preview": dict(preview),
        "reconciliation_state": _intent_reconciliation_state(state),
    }
    if error:
        payload["error"] = error
    state_payload: dict[str, object] = {
        "schema_version": "0.1.0",
        "state_id": _state_id(
            cycle_id=cycle_id,
            ticker=ticker or "ALL",
            order_id_hash=execution_id,
            state=state,
            event_time=recorded_at,
        ),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "execution_id": execution_id,
        "state": state,
        "event_time": recorded_at,
        "reason": reason or _intent_reason(state),
        "payload": payload,
    }
    validate_contract("execution-state", state_payload)
    return state_payload


async def persist_order_intent_execution_state(
    session: AsyncSession,
    *,
    cycle_id: str,
    preview: Mapping[str, object],
    order_payload: Mapping[str, object],
    event_time: str | None = None,
    state: str = "READY",
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    execution_state = build_order_intent_execution_state(
        cycle_id=cycle_id,
        preview=preview,
        order_payload=order_payload,
        event_time=event_time,
        state=state,
        reason=reason,
        error=error,
    )
    await record_execution_state(session, execution_state)
    return execution_state


def build_portfolio_snapshot(
    broker: Mapping[str, object],
    *,
    captured_at: str | None = None,
) -> dict[str, object]:
    account = _mapping_or_empty(broker.get("account"))
    positions = _mapping_sequence(broker.get("positions", []))
    orders = _mapping_sequence(broker.get("orders", []))
    captured = captured_at or _now_utc()
    snapshot = {
        "schema_version": "0.1.0",
        "snapshot_id": _snapshot_id(broker=broker, captured_at=captured),
        "provider": str(broker.get("provider", "alpaca")),
        "mode": str(broker.get("mode", "paper")),
        "captured_at": captured,
        "account_status": str(account.get("status", "")),
        "equity": _float_value(account.get("equity")),
        "cash": _float_value(account.get("cash")),
        "buying_power": _float_value(account.get("buying_power")),
        "portfolio_value": _float_value(account.get("portfolio_value")),
        "position_count": len(positions),
        "open_order_count": len(orders),
        "gross_exposure_pct": _float_value(broker.get("gross_exposure_pct")),
        "payload": {
            "provider": broker.get("provider", "alpaca"),
            "mode": broker.get("mode", "paper"),
            "account": dict(account),
            "positions": [dict(position) for position in positions],
            "orders": [safe_order(order) for order in orders],
        },
    }
    validate_contract("portfolio-snapshot", snapshot)
    return snapshot


async def persist_portfolio_snapshot(
    session: AsyncSession,
    broker: Mapping[str, object],
    *,
    captured_at: str | None = None,
) -> dict[str, object]:
    snapshot = build_portfolio_snapshot(broker, captured_at=captured_at)
    await record_portfolio_snapshot(session, snapshot)
    return snapshot


def safe_order(order: Mapping[str, object]) -> dict[str, object]:
    return {
        "order_id_hash": _stable_hash(str(order.get("order_id", ""))),
        "client_order_id": str(order.get("client_order_id", "")),
        "ticker": str(order.get("ticker", "")),
        "side": str(order.get("side", "")),
        "type": str(order.get("type", "")),
        "time_in_force": str(order.get("time_in_force", "")),
        "status": _order_status(order),
        "qty": _optional_float(order.get("qty")),
        "notional": _optional_float(order.get("notional")),
        "filled_qty": _optional_float(order.get("filled_qty")),
        "filled_avg_price": _optional_float(order.get("filled_avg_price")),
        "submitted_at": str(order.get("submitted_at", "")),
        "filled_at": str(order.get("filled_at", "")),
    }


def _order_status(order: Mapping[str, object]) -> str:
    return str(order.get("status", "")).upper()


def _order_event_time(order: Mapping[str, object]) -> str:
    filled_at = str(order.get("filled_at", "") or "")
    submitted_at = str(order.get("submitted_at", "") or "")
    return filled_at or submitted_at or _now_utc()


def _order_reason(state: str) -> str:
    labels = {
        "ACCEPTED": "Alpaca paper order accepted",
        "PENDING_CANCEL": "Alpaca paper order cancellation pending",
        "FILLED": "Alpaca paper order filled",
        "CANCELED": "Alpaca paper order canceled",
        "REJECTED": "Alpaca paper order rejected",
        "EXPIRED": "Alpaca paper order expired",
        "SUBMITTED": "Alpaca paper order submitted",
    }
    return labels.get(state, "Alpaca paper order state recorded")


def _intent_reason(state: str) -> str:
    labels = {
        "READY": "Paper order intent recorded before broker submit",
        "FAILED": "Paper order submission failed after intent recording",
    }
    return labels.get(state, "Paper order intent state recorded")


def _intent_reconciliation_state(state: str) -> str:
    if state == "FAILED":
        return "broker_submit_failed"
    return "intent_recorded_before_broker_submit"


def _state_id(
    *,
    cycle_id: str,
    ticker: str,
    order_id_hash: str,
    state: str,
    event_time: str,
) -> str:
    raw = f"{cycle_id}:{ticker}:{order_id_hash}:{state}:{event_time}"
    return _stable_hash(raw, length=32)


def _snapshot_id(*, broker: Mapping[str, object], captured_at: str) -> str:
    provider = str(broker.get("provider", "alpaca"))
    mode = str(broker.get("mode", "paper"))
    account_hash = str(_mapping_or_empty(broker.get("account")).get("account_id_hash", ""))
    return _stable_hash(f"{provider}:{mode}:{account_hash}:{captured_at}", length=32)


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _float_value(value: object) -> float:
    if value is None or value == "":
        return 0.0
    if not isinstance(value, int | float | str):
        raise TypeError("expected numeric broker value")
    return float(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return _float_value(value)


def _stable_hash(value: str, *, length: int = 16) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
