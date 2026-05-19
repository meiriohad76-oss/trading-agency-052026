from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from agency.contracts import validate_contract
from agency.services.risk import PortfolioPolicy
from agency.services.selection_events import build_lifecycle_event

ORDER_SIDES = {"BUY", "SELL", "SHORT", "COVER"}
ORDER_INTENT_HASH_VERSION = "0.1.0"


@dataclass(frozen=True)
class ExecutionPreviewResult:
    """Execution preview plus lifecycle audit event."""

    preview: dict[str, object]
    lifecycle_event: dict[str, object]


def build_execution_previews(
    risk_decisions: Sequence[Mapping[str, object]],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
    account: Mapping[str, object] | None = None,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    research_approval_required: bool = False,
    research_approval_records: Mapping[tuple[str, str, str], bool] | None = None,
) -> list[ExecutionPreviewResult]:
    approvals = {} if research_approval_records is None else research_approval_records
    return [
        build_execution_preview(
            risk_decision,
            generated_at=generated_at,
            policy=policy,
            account=account,
            positions=positions,
            open_orders=open_orders,
            research_approval_required=research_approval_required,
            research_approval_recorded=approvals.get(_runtime_key(risk_decision), False),
        )
        for risk_decision in risk_decisions
    ]


def build_execution_preview(
    risk_decision: Mapping[str, object],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
    account: Mapping[str, object] | None = None,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    research_approval_required: bool = False,
    research_approval_recorded: bool = False,
) -> ExecutionPreviewResult:
    """Build a no-submit paper execution preview from a risk decision."""
    validate_contract("risk-decision", risk_decision)
    normalized_policy = policy or PortfolioPolicy()
    final_action = str(risk_decision["final_action"])
    risk_state = str(risk_decision["decision"])
    side = final_action if final_action in ORDER_SIDES else "NONE"
    preview_state = _preview_state(risk_state, side)
    generated = generated_at or _now_utc()
    ticker = str(risk_decision["ticker"])
    order_conflict = _order_conflict(
        side=side,
        ticker=ticker,
        positions=positions,
        open_orders=open_orders,
    )
    quantity = _order_quantity(side=side, ticker=ticker, positions=positions)
    if preview_state == "READY" and side in {"SELL", "COVER"} and quantity is None:
        preview_state = "BLOCKED"
        reasons = [_missing_close_position_reason(side)]
    else:
        reasons = _preview_reasons(
            risk_decision,
            preview_state,
            side,
            order_conflict=order_conflict,
        )
    if (
        research_approval_required
        and not research_approval_recorded
        and preview_state == "READY"
    ):
        reasons = ["current human approval required", *reasons]
    notional = _order_notional(
        side=side,
        preview_state=preview_state,
        position_size_pct=_float_field(risk_decision, "position_size_pct"),
        account=account,
        quantity=quantity,
    )
    entry = _entry_price(ticker=ticker, positions=positions)
    intent_payload = _order_intent_payload(
        risk_decision=risk_decision,
        side=side,
        quantity=quantity,
        notional=notional,
        position_size_pct=_float_field(risk_decision, "position_size_pct"),
        time_in_force="DAY" if preview_state == "READY" else None,
        policy=normalized_policy,
        account=account,
        positions=positions,
        open_orders=open_orders,
    )
    preview: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": str(risk_decision["cycle_id"]),
        "ticker": ticker,
        "as_of": str(risk_decision["as_of"]),
        "generated_at": generated,
        "preview_state": preview_state,
        "side": side,
        "quantity": quantity,
        "entry": entry,
        "stop_loss": None,
        "take_profit": None,
        "notional": notional,
        "position_size_pct": risk_decision["position_size_pct"],
        "time_in_force": "DAY" if preview_state == "READY" else None,
        "risk_decision": risk_state,
        "order_intent_version": ORDER_INTENT_HASH_VERSION,
        "order_intent_hash": _stable_hash(intent_payload),
        "submit_enabled": (
            normalized_policy.broker_submit_enabled
            and preview_state == "READY"
            and (not research_approval_required or research_approval_recorded)
            and _policy_allows_side(side=side, policy=normalized_policy)
            and _has_order_size(quantity=quantity, notional=notional)
            and _broker_account_allows_submit(side=side, account=account, notional=notional)
            and not order_conflict
        ),
        "reasons": reasons,
    }
    validate_contract("execution-preview", preview)
    lifecycle_event = build_lifecycle_event(
        cycle_id=str(preview["cycle_id"]),
        ticker=str(preview["ticker"]),
        event_type="EXECUTION_PREVIEW",
        event_time=generated,
        status=_lifecycle_status(preview_state),
        reason=reasons[0],
        payload={"execution_preview": dict(preview)},
    )
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return ExecutionPreviewResult(preview, lifecycle_event)


def build_order_approval_event(
    preview: Mapping[str, object],
    *,
    reviewed_by: str = "local-user",
    notes: str | None = None,
    event_time: str | None = None,
) -> dict[str, object]:
    """Build the hash-bound approval that authorizes a specific order intent."""
    validate_contract("execution-preview", preview)
    if preview.get("preview_state") != "READY" or preview.get("side") not in ORDER_SIDES:
        raise ValueError("only READY order previews can be approved for submission")
    if not _has_order_size(
        quantity=_optional_float_from_preview(preview, "quantity"),
        notional=_optional_float_from_preview(preview, "notional"),
    ):
        raise ValueError("order approval requires a concrete order size")
    order_hash = str(preview.get("order_intent_hash") or "")
    if not order_hash:
        raise ValueError("execution preview is missing order_intent_hash")
    event = build_lifecycle_event(
        cycle_id=str(preview["cycle_id"]),
        ticker=str(preview["ticker"]),
        event_type="ORDER_APPROVAL",
        event_time=event_time or _now_utc(),
        status="PASSED",
        reason="paper order intent approved",
        payload={
            "approval_type": "ORDER_APPROVAL",
            "reviewed_by": reviewed_by,
            "notes": _clean_optional(notes),
            "paper_only": True,
            "as_of": str(preview["as_of"]),
            "order_intent_hash": order_hash,
            "order_intent_version": str(preview["order_intent_version"]),
            "order_intent": _public_order_intent(preview),
        },
    )
    validate_contract("candidate-lifecycle-event", event)
    return event


def _preview_state(risk_state: str, side: str) -> str:
    if risk_state == "BLOCK":
        return "BLOCKED"
    if side == "NONE":
        return "DISABLED"
    if risk_state in {"ALLOW", "WARN"}:
        return "READY"
    return "BLOCKED"


def _order_intent_payload(
    *,
    risk_decision: Mapping[str, object],
    side: str,
    quantity: float | None,
    notional: float | None,
    position_size_pct: float,
    time_in_force: str | None,
    policy: PortfolioPolicy,
    account: Mapping[str, object] | None,
    positions: Sequence[Mapping[str, object]],
    open_orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    ticker = str(risk_decision["ticker"]).upper()
    return {
        "version": ORDER_INTENT_HASH_VERSION,
        "cycle_id": str(risk_decision["cycle_id"]),
        "ticker": ticker,
        "as_of": str(risk_decision["as_of"]),
        "final_action": str(risk_decision["final_action"]),
        "risk_decision": str(risk_decision["decision"]),
        "side": side,
        "quantity": _round_optional(quantity, 6),
        "notional": _round_optional(notional, 2),
        "position_size_pct": round(position_size_pct, 6),
        "time_in_force": time_in_force,
        "risk_reasons": sorted(str(reason) for reason in _list_field(risk_decision, "reasons")),
        "policy": {
            "default_position_pct": policy.default_position_pct,
            "max_positions": policy.max_positions,
            "max_gross_exposure_pct": policy.max_gross_exposure_pct,
            "max_single_name_pct": policy.max_single_name_pct,
            "max_sector_exposure_pct": policy.max_sector_exposure_pct,
            "cash_reserve_pct": policy.cash_reserve_pct,
            "max_new_positions_per_cycle": policy.max_new_positions_per_cycle,
            "min_final_conviction": policy.min_final_conviction,
            "take_profit_pct": policy.take_profit_pct,
            "stop_loss_pct": policy.stop_loss_pct,
            "trailing_stop_pct": policy.trailing_stop_pct,
            "bracket_orders_enabled": policy.bracket_orders_enabled,
            "live_trading_enabled": policy.live_trading_enabled,
            "broker_submit_enabled": policy.broker_submit_enabled,
            "allow_short_trades": policy.allow_short_trades,
        },
        "broker_account": _account_intent(account),
        "ticker_position": _matching_mapping(positions, ticker=ticker),
        "ticker_open_orders": [
            _order_intent(order)
            for order in open_orders
            if _order_is_active_for_ticker(order, ticker=ticker)
        ],
    }


def _stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_key(payload: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(payload.get("cycle_id", "")),
        str(payload.get("ticker", "")),
        str(payload.get("as_of", "")),
    )


def _round_optional(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _account_intent(account: Mapping[str, object] | None) -> dict[str, object] | None:
    if account is None:
        return None
    return {
        "status": account.get("status"),
        "trading_blocked": _bool_field(account, "trading_blocked"),
        "account_blocked": _bool_field(account, "account_blocked"),
    }


def _matching_mapping(
    items: Sequence[Mapping[str, object]],
    *,
    ticker: str,
) -> dict[str, object] | None:
    for item in items:
        if str(item.get("ticker") or item.get("symbol") or "").upper() == ticker:
            return {
                key: item.get(key)
                for key in (
                    "ticker",
                    "symbol",
                    "side",
                    "qty",
                    "market_value",
                    "current_price",
                )
                if key in item
            }
    return None


def _order_intent(order: Mapping[str, object]) -> dict[str, object]:
    return {
        key: order.get(key)
        for key in ("ticker", "symbol", "side", "qty", "notional", "status", "type")
        if key in order
    }


def _public_order_intent(preview: Mapping[str, object]) -> dict[str, object]:
    return {
        "cycle_id": str(preview["cycle_id"]),
        "ticker": str(preview["ticker"]),
        "as_of": str(preview["as_of"]),
        "side": str(preview["side"]),
        "quantity": preview.get("quantity"),
        "notional": preview.get("notional"),
        "time_in_force": preview.get("time_in_force"),
        "position_size_pct": preview.get("position_size_pct"),
        "risk_decision": preview.get("risk_decision"),
    }


def _preview_reasons(
    risk_decision: Mapping[str, object],
    preview_state: str,
    side: str,
    *,
    order_conflict: bool = False,
) -> list[str]:
    if preview_state == "READY":
        if order_conflict:
            return ["active broker order already exists for this ticker"]
        risk_reasons = [str(reason) for reason in _list_field(risk_decision, "reasons")]
        promotion_reason = _paper_promotion_reason(risk_decision)
        if promotion_reason is not None:
            return [
                promotion_reason,
                *[reason for reason in risk_reasons if reason != promotion_reason],
            ]
        if risk_reasons:
            return risk_reasons
        return ["paper preview generated; broker submission remains gated"]
    if side == "NONE":
        cautions = [
            str(reason)
            for reason in _list_field(risk_decision, "reasons")
            if str(reason).startswith("Caution:")
        ]
        if cautions:
            return [
                (
                    f"{risk_decision['final_action']} is review-only and has no paper "
                    f"order. {cautions[0]}"
                ),
                *cautions[1:],
            ]
        return [f"{risk_decision['final_action']} has no order side"]
    return [str(reason) for reason in _list_field(risk_decision, "reasons")]


def _missing_close_position_reason(side: str) -> str:
    if side == "SELL":
        return "no existing long position is available to sell"
    return "no existing short position is available to cover"


def _policy_allows_side(*, side: str, policy: PortfolioPolicy) -> bool:
    if side == "SHORT":
        return policy.allow_short_trades
    return True


def _paper_promotion_reason(risk_decision: Mapping[str, object]) -> str | None:
    for reason in _list_field(risk_decision, "reasons"):
        text = str(reason)
        if text.startswith("paper trade promotion:"):
            return text
    return None


def _lifecycle_status(preview_state: str) -> str:
    if preview_state == "READY":
        return "RECORDED"
    if preview_state == "DISABLED":
        return "SUPPRESSED"
    return "BLOCKED"


def _order_notional(
    *,
    side: str,
    preview_state: str,
    position_size_pct: float,
    account: Mapping[str, object] | None,
    quantity: float | None,
) -> float | None:
    if preview_state != "READY" or side not in {"BUY", "SHORT"} or quantity is not None:
        return None
    if account is None:
        return None
    equity = _float_field(account, "equity")
    buying_power = _float_field(account, "buying_power")
    if equity <= 0:
        return None
    notional = round(equity * position_size_pct / 100.0, 2)
    if buying_power > 0:
        notional = min(notional, buying_power)
    if notional >= 100:
        return float(math.floor(notional))
    return notional


def _order_quantity(
    *,
    side: str,
    ticker: str,
    positions: Sequence[Mapping[str, object]],
) -> float | None:
    if side not in {"SELL", "COVER"}:
        return None
    position = _position_for_ticker(ticker=ticker, positions=positions)
    if position is None:
        return None
    raw_quantity = _float_field(position, "qty")
    position_side = str(position.get("side", "")).lower()
    if position_side == "long":
        is_long = True
        is_short = False
    elif position_side == "short":
        is_long = False
        is_short = True
    else:
        is_long = raw_quantity > 0
        is_short = raw_quantity < 0
    if side == "SELL" and not is_long:
        return None
    if side == "COVER" and not is_short:
        return None
    quantity = abs(raw_quantity)
    return round(quantity, 6) if quantity > 0 else None


def _entry_price(
    *,
    ticker: str,
    positions: Sequence[Mapping[str, object]],
) -> float | None:
    position = _position_for_ticker(ticker=ticker, positions=positions)
    if position is None:
        return None
    price = _float_field(position, "current_price")
    return price if price > 0 else None


def _position_for_ticker(
    *,
    ticker: str,
    positions: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    normalized = ticker.upper()
    for position in positions:
        if str(position.get("ticker") or position.get("symbol") or "").upper() == normalized:
            return position
    return None


def _has_order_size(*, quantity: float | None, notional: float | None) -> bool:
    return (quantity is not None and quantity > 0) or (notional is not None and notional > 0)


def _broker_account_allows_submit(
    *,
    side: str,
    account: Mapping[str, object] | None,
    notional: float | None,
) -> bool:
    if account is None:
        return False
    status = str(account.get("status", "")).upper()
    if status and status != "ACTIVE":
        return False
    if _bool_field(account, "trading_blocked") or _bool_field(account, "account_blocked"):
        return False
    if side not in {"BUY", "SHORT"}:
        return True
    buying_power = _float_field(account, "buying_power")
    return notional is not None and buying_power >= notional > 0


def _order_conflict(
    *,
    side: str,
    ticker: str,
    positions: Sequence[Mapping[str, object]],
    open_orders: Sequence[Mapping[str, object]],
) -> bool:
    if side in {"BUY", "SHORT"} and _position_for_ticker(ticker=ticker, positions=positions):
        return True
    if side not in ORDER_SIDES:
        return False
    return any(_order_is_active_for_ticker(order, ticker=ticker) for order in open_orders)


def _order_is_active_for_ticker(order: Mapping[str, object], *, ticker: str) -> bool:
    inactive_statuses = {"CANCELED", "EXPIRED", "FILLED", "REJECTED"}
    symbol = str(order.get("ticker") or order.get("symbol") or "").upper()
    if symbol != ticker.upper():
        return False
    return str(order.get("status", "")).upper() not in inactive_statuses


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _optional_float_from_preview(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _bool_field(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None
