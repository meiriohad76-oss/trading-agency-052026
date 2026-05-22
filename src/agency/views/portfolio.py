"""View-model constructors for the portfolio page."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from agency.api.audit import runtime_portfolio_snapshots
from agency.services import PortfolioPolicy, build_portfolio_monitor, load_active_portfolio_policy
from agency.views._shared import (
    _dashboard_selection_reports,
    _env_bool_text,
    _float_field,
    _int_field,
    _mapping_field,
    dashboard_data_health,
    live_dashboard_data_load_status,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
HIGH_WATER_MARKS_PATH = REPO_ROOT / "research" / "data" / "portfolio-high-water-marks.json"


async def portfolio_monitor_context() -> dict[str, object]:
    from agency.views.market_regime import broker_status_context
    policy = await load_active_portfolio_policy()
    reports, broker, snapshots = await asyncio.gather(
        _dashboard_selection_reports(limit=25),
        broker_status_context(),
        runtime_portfolio_snapshots(limit=50),
    )
    snapshot = build_portfolio_monitor(
        reports,
        broker_positions=_broker_positions(broker),
        account=_broker_account(broker),
        gross_exposure_pct=_broker_gross_exposure_pct(broker),
        portfolio_snapshots=snapshots,
        policy=policy,
        high_water_marks_path=HIGH_WATER_MARKS_PATH,
        persist_high_water_marks=False,
    )
    data_load_status = await live_dashboard_data_load_status()
    return {
        "broker": broker,
        "data_health": dashboard_data_health(
            "Portfolio monitor dashboard",
            data_load_status=data_load_status,
            extra_rows=(
                {
                    "kind": "Broker",
                    "name": "Alpaca paper account and positions",
                    "status_label": str(broker.get("status_label") or "Broker unknown"),
                    "status_class": str(broker.get("status_class") or "neutral"),
                    "coverage_label": f"{len(_broker_positions(broker))} positions / {len(_broker_orders(broker))} open orders",
                    "freshness_label": "broker snapshot",
                    "last_update": str(broker.get("checked_at") or "not checked"),
                    "detail": str(broker.get("detail") or "No broker detail available."),
                },
                {
                    "kind": "Audit",
                    "name": "Portfolio snapshot history",
                    "status_label": "Snapshots recorded" if snapshots else "No snapshots yet",
                    "status_class": "pass" if snapshots else "warn",
                    "coverage_label": f"{len(snapshots)} stored snapshot(s)",
                    "freshness_label": "latest audit row",
                    "last_update": str(snapshots[0].get("captured_at")) if snapshots else "not recorded",
                    "detail": "Snapshots let the portfolio manager measure hourly performance and rule triggers.",
                },
            ),
        ),
        "positions": snapshot["positions"],
        "snapshot_rows": portfolio_snapshot_rows(snapshots[:5]),
        "summary": portfolio_monitor_summary(snapshot),
    }

def portfolio_monitor_summary(snapshot: Mapping[str, object]) -> dict[str, object]:
    summary = _mapping_field(snapshot, "summary")
    position_count = _int_field(summary, "position_count")
    return {
        **dict(summary),
        "headline": _portfolio_headline(position_count),
        "detail": (
            "Portfolio Manager checks Alpaca paper positions against profit, loss, "
            "setup, and hourly performance rules. It recommends review or close "
            "actions; broker submission still requires the execution gate."
        ),
    }

def portfolio_snapshot_rows(snapshots: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "captured_at": str(snapshot["captured_at"]),
            "mode": str(snapshot["mode"]),
            "account_status": str(snapshot["account_status"]),
            "equity": _float_field(snapshot, "equity"),
            "cash": _float_field(snapshot, "cash"),
            "portfolio_value": _float_field(snapshot, "portfolio_value"),
            "buying_power": _float_field(snapshot, "buying_power"),
            "position_count": _int_field(snapshot, "position_count"),
            "open_order_count": _int_field(snapshot, "open_order_count"),
            "gross_exposure_pct": _float_field(snapshot, "gross_exposure_pct"),
        }
        for snapshot in snapshots
    ]

def _broker_account(broker: Mapping[str, object]) -> Mapping[str, object] | None:
    account = broker.get("account")
    return cast(Mapping[str, object], account) if isinstance(account, Mapping) else None

def _broker_positions(broker: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = broker.get("positions", [])
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]

def _broker_orders(broker: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = broker.get("orders", [])
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]

def _broker_gross_exposure_pct(broker: Mapping[str, object]) -> float:
    value = broker.get("gross_exposure_pct", 0.0)
    if isinstance(value, int | float):
        return float(value)
    return 0.0

def _pending_opening_order_exposure_pct(broker: Mapping[str, object]) -> float:
    account = _broker_account(broker)
    if account is None:
        return 0.0
    equity = _numeric_mapping_field(account, "equity")
    if equity <= 0:
        return 0.0
    positions = _broker_positions(broker)
    pending_notional = sum(
        _order_pending_notional(order)
        for order in _broker_orders(broker)
        if _order_is_pending_opening(order, positions=positions)
    )
    return round(pending_notional / equity * 100.0, 6)

def _order_is_pending_opening(
    order: Mapping[str, object],
    *,
    positions: Sequence[Mapping[str, object]],
) -> bool:
    side = str(order.get("side", "")).upper()
    status = str(order.get("status", "")).upper()
    if status in {
        "CANCELED",
        "EXPIRED",
        "FILLED",
        "REJECTED",
    }:
        return False
    position = _position_for_order(order, positions)
    if side == "BUY":
        return not _position_is_short(position)
    if side == "SELL":
        return not _position_is_long(position)
    return side == "SHORT"

def _order_pending_notional(order: Mapping[str, object]) -> float:
    notional = _numeric_mapping_field(order, "notional")
    if notional > 0:
        return abs(notional)
    quantity = _numeric_mapping_field(order, "qty")
    price = max(
        _numeric_mapping_field(order, "limit_price"),
        _numeric_mapping_field(order, "stop_price"),
        _numeric_mapping_field(order, "filled_avg_price"),
    )
    return abs(quantity * price) if quantity > 0 and price > 0 else 0.0

def _position_for_order(
    order: Mapping[str, object],
    positions: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    ticker = str(order.get("ticker") or order.get("symbol") or "").upper()
    if not ticker:
        return None
    return next(
        (
            position
            for position in positions
            if str(position.get("ticker") or position.get("symbol") or "").upper() == ticker
        ),
        None,
    )

def _position_is_long(position: Mapping[str, object] | None) -> bool:
    if position is None:
        return False
    side = str(position.get("side", "")).upper()
    if side:
        return side == "LONG"
    return _numeric_mapping_field(position, "qty") > 0

def _position_is_short(position: Mapping[str, object] | None) -> bool:
    if position is None:
        return False
    side = str(position.get("side", "")).upper()
    if side:
        return side == "SHORT"
    return _numeric_mapping_field(position, "qty") < 0

def _numeric_mapping_field(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key, 0.0)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return 0.0

def _broker_ready_for_paper_promotion(broker: Mapping[str, object]) -> bool:
    if broker.get("connected") is not True or str(broker.get("mode")) != "paper":
        return False
    account = _broker_account(broker)
    if account is None:
        return False
    return not (
        account.get("trading_blocked") is True
        or account.get("account_blocked") is True
    )

def _portfolio_execution_detail(
    *,
    broker_connected: bool,
    position_count: int,
    gross_exposure_pct: float,
    policy: PortfolioPolicy,
) -> str:
    if not broker_connected:
        return (
            "Portfolio manager cannot size orders until the Alpaca paper account "
            "is connected."
        )
    return (
        "Portfolio manager used the current Alpaca paper account, "
        f"{position_count} open position(s), {gross_exposure_pct:.2f}% gross exposure, "
        f"{policy.default_position_pct:.1f}% default position size, and "
        f"{policy.max_gross_exposure_pct:.1f}% max gross exposure."
    )

def _portfolio_headline(position_count: int) -> str:
    if position_count == 0:
        return "No portfolio positions are tracked yet."
    return f"{position_count} positions reviewed."

def _broker_execution_enabled() -> bool:
    return (
        _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED")
        and PortfolioPolicy.from_env().broker_submit_enabled
    )
