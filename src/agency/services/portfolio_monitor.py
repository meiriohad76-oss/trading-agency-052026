from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agency.contracts import validate_contract
from agency.services.risk import PortfolioPolicy


def build_portfolio_monitor(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    positions: Sequence[str] | None = None,
    broker_positions: Sequence[Mapping[str, object]] = (),
    account: Mapping[str, object] | None = None,
    gross_exposure_pct: float | None = None,
    portfolio_snapshots: Sequence[Mapping[str, object]] = (),
    policy: PortfolioPolicy | None = None,
    generated_at: str | None = None,
    high_water_marks: Mapping[str, float] = {},
    high_water_marks_path: Path | str | None = None,
    persist_high_water_marks: bool = True,
) -> dict[str, object]:
    """Build a read-only position review snapshot from current selection reports."""
    normalized_policy = policy or PortfolioPolicy()
    generated = generated_at or _now_utc()

    # Resolve high-water marks: path overrides the in-memory dict when provided.
    effective_marks: Mapping[str, float] = high_water_marks
    if high_water_marks_path is not None:
        effective_marks = _load_high_water_marks(Path(high_water_marks_path))

    reports_by_ticker = {
        str(report["ticker"]): report
        for report in selection_reports
    }
    tickers = _position_tickers(positions=positions, broker_positions=broker_positions)
    broker_by_ticker = _broker_position_index(broker_positions)
    position_rows = []
    for ticker in tickers:
        normalized_ticker = ticker.upper()
        row = _position_review(
            normalized_ticker,
            reports_by_ticker.get(normalized_ticker),
            broker_by_ticker.get(normalized_ticker),
            policy=normalized_policy,
            high_water_marks=effective_marks,
        )
        position_rows.append(
            _portfolio_position_ux_fields(
                row,
                policy=normalized_policy,
                high_water_marks=effective_marks,
            )
        )
    snapshot: dict[str, object] = {
        "schema_version": "0.1.0",
        "generated_at": generated,
        "mode": "PAPER" if broker_positions else "READ_ONLY",
        "positions": position_rows,
        "summary": _summary(
            position_rows,
            account=account,
            gross_exposure_pct=gross_exposure_pct,
            portfolio_snapshots=portfolio_snapshots,
            policy=normalized_policy,
            generated_at=generated,
        ),
    }
    validate_contract("portfolio-monitor", snapshot)

    # Persist updated marks when a path was supplied.
    if high_water_marks_path is not None and persist_high_water_marks:
        updated_marks = update_high_water_marks(dict(effective_marks), list(broker_positions))
        _save_high_water_marks(Path(high_water_marks_path), updated_marks)

    return snapshot


def update_high_water_marks(
    current_marks: dict[str, float],
    position_rows: list[Mapping[str, object]],
) -> dict[str, float]:
    """Return a new dict with the peak unrealized P&L pct updated for each ticker.

    ``current_marks`` is never mutated; a fresh dict is returned.
    ``position_rows`` should contain dicts with ``ticker`` and optionally
    ``unrealized_plpc`` (as a fraction, e.g. 0.08 for 8%).
    """
    result = dict(current_marks)
    for row in position_rows:
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        plpc = row.get("unrealized_plpc")
        if plpc is None or not isinstance(plpc, int | float):
            continue
        pnl_pct = float(plpc) * 100.0
        result[ticker] = max(result.get(ticker, pnl_pct), pnl_pct)
    return result


def _load_high_water_marks(path: Path) -> dict[str, float]:
    """Load high-water marks from a JSON file. Returns empty dict if file is missing."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, float] = {}
    for k, v in payload.items():
        if isinstance(v, int | float) and not isinstance(v, bool):
            result[str(k).upper()] = float(v)
    return result


def _save_high_water_marks(path: Path, marks: dict[str, float]) -> None:
    """Save high-water marks to a JSON file, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marks, indent=2), encoding="utf-8")


def _position_review(
    ticker: str,
    report: Mapping[str, object] | None,
    broker_position: Mapping[str, object] | None,
    *,
    policy: PortfolioPolicy,
    high_water_marks: Mapping[str, float] = {},
) -> dict[str, object]:
    broker_fields = _broker_position_fields(broker_position)
    exit_result = _exit_rule_result(
        ticker=ticker,
        report=report,
        broker_position=broker_position,
        policy=policy,
        high_water_marks=high_water_marks,
    )
    if report is None:
        return {
            "ticker": ticker,
            "classification": exit_result["classification"],
            "reason": exit_result["reason"],
            "current_action": None,
            "conviction": None,
            **broker_fields,
            **exit_result,
        }
    if exit_result["exit_signal"] != "NONE":
        return {
            "ticker": ticker,
            "classification": exit_result["classification"],
            "reason": exit_result["reason"],
            "current_action": str(report["final_action"]),
            "conviction": _float_field(report, "final_conviction"),
            **broker_fields,
            **exit_result,
        }
    action = str(report["final_action"])
    risk_flags = _string_list(report, "risk_flags")
    if action in {"NO_TRADE", "CLOSE_REVIEW"}:
        classification = "CLOSE_CANDIDATE"
        reason = "current setup is no-trade or close-review"
    elif risk_flags or _gate_status(report) == "WARN":
        classification = "REVIEW"
        reason = "current setup carries warnings"
    else:
        classification = "HOLD"
        reason = "current setup remains aligned"
    return {
        "ticker": ticker,
        "classification": classification,
        "reason": reason,
        "current_action": action,
        "conviction": _float_field(report, "final_conviction"),
        **broker_fields,
        "exit_signal": "NONE",
        "exit_priority": "NONE",
        "exit_reason": "No exit rule is triggered.",
        "policy_take_profit_pct": policy.take_profit_pct,
        "policy_stop_loss_pct": policy.stop_loss_pct,
        "policy_trailing_stop_pct": policy.trailing_stop_pct,
    }


def _summary(
    rows: Sequence[Mapping[str, object]],
    *,
    account: Mapping[str, object] | None,
    gross_exposure_pct: float | None,
    portfolio_snapshots: Sequence[Mapping[str, object]],
    policy: PortfolioPolicy,
    generated_at: str,
) -> dict[str, object]:
    max_allowed = policy.max_gross_exposure_pct
    exposure = gross_exposure_pct
    policy_state = (
        "UNKNOWN"
        if exposure is None
        else "OVER_EXPOSURE"
        if exposure > max_allowed
        else "WITHIN_LIMITS"
    )
    return {
        "position_count": len(rows),
        "hold_count": _count(rows, "HOLD"),
        "review_count": _count(rows, "REVIEW"),
        "close_candidate_count": _count(rows, "CLOSE_CANDIDATE"),
        "equity": _optional_float(account, "equity"),
        "cash": _optional_float(account, "cash"),
        "buying_power": _optional_float(account, "buying_power"),
        "gross_exposure_pct": gross_exposure_pct,
        "max_gross_exposure_pct": max_allowed,
        "available_exposure_pct": (
            None if exposure is None else round(max(max_allowed - exposure, 0.0), 4)
        ),
        "policy_compliance_state": policy_state,
        "policy_compliance_label": (
            "Exposure unknown"
            if policy_state == "UNKNOWN"
            else "Over exposure"
            if policy_state == "OVER_EXPOSURE"
            else "Within limits"
        ),
        "policy_compliance_class": (
            "neutral"
            if policy_state == "UNKNOWN"
            else "block"
            if policy_state == "OVER_EXPOSURE"
            else "pass"
        ),
        "take_profit_pct": policy.take_profit_pct,
        "stop_loss_pct": policy.stop_loss_pct,
        "trailing_stop_pct": policy.trailing_stop_pct,
        "hourly_loss_alert_pct": policy.hourly_loss_alert_pct,
        **_hourly_performance(
            account=account,
            snapshots=portfolio_snapshots,
            generated_at=generated_at,
            policy=policy,
        ),
    }


def _portfolio_position_ux_fields(
    row: Mapping[str, object],
    *,
    policy: PortfolioPolicy,
    high_water_marks: Mapping[str, float],
) -> dict[str, object]:
    output = dict(row)
    ticker = str(output["ticker"]).upper()
    pnl_pct = _coerced_optional_float(output.get("unrealized_plpc"))
    pnl_pct = None if pnl_pct is None else pnl_pct * 100.0
    high_water_mark = high_water_marks.get(ticker)
    drawdown = (
        None
        if pnl_pct is None or high_water_mark is None
        else round(high_water_mark - pnl_pct, 4)
    )
    distance = (
        None
        if drawdown is None
        else round(max(policy.trailing_stop_pct - drawdown, 0.0), 4)
    )
    proximity_alert = (
        bool(
            distance is not None
            and distance > 0
            and distance <= 5.0
            and str(output["exit_signal"]) != "TRAILING_STOP"
        )
    )
    market_value = _coerced_optional_float(output.get("market_value"))
    exposure_freed_pct = (
        None
        if market_value is None or market_value <= 0
        else round(min(policy.default_position_pct, policy.max_single_name_pct), 4)
    )
    pnl_value = _coerced_optional_float(output.get("unrealized_pl"))
    output.update(
        {
            "pnl_class": (
                "pass" if pnl_value is not None and pnl_value > 0 else
                "block" if pnl_value is not None and pnl_value < 0 else
                "neutral"
            ),
            "pnl_label": _pnl_label(
                _coerced_optional_float(output.get("unrealized_pl")),
                pnl_pct,
            ),
            "thesis_validity_label": _thesis_validity_label(output),
            "stop_distance_label": _stop_distance_label(output, distance),
            "trailing_stop_drawdown_pct": drawdown,
            "trailing_stop_distance_pct": distance,
            "trailing_stop_proximity_alert": proximity_alert,
            "urgency_label": _urgency_label(output, proximity_alert),
            "exposure_freed_label": (
                "Estimate after broker sizing"
                if exposure_freed_pct is None
                else f"{exposure_freed_pct:.1f}% capacity"
            ),
            "confirm_exit_action": f"/portfolio-monitor/exits/{ticker}/confirm",
            "downstream_effect": (
                f"Exiting {ticker} frees capacity for review before the next entry."
            ),
        }
    )
    return output


def _pnl_label(value: float | None, pct: float | None) -> str:
    if value is None or pct is None:
        return "No P/L data"
    return f"${value:.2f} / {pct:.2f}%"


def _thesis_validity_label(row: Mapping[str, object]) -> str:
    classification = str(row["classification"])
    if classification == "HOLD":
        return "Thesis still valid"
    if classification == "REVIEW":
        return "Thesis needs review"
    if classification == "CLOSE_CANDIDATE":
        return "Exit thesis active"
    return "No current thesis"


def _stop_distance_label(row: Mapping[str, object], distance: float | None) -> str:
    if str(row["exit_signal"]) == "TRAILING_STOP":
        return "Trailing stop triggered"
    if distance is None:
        return "No trailing-stop baseline"
    return f"{distance:.2f}% from trailing stop"


def _urgency_label(row: Mapping[str, object], proximity_alert: bool) -> str:
    if str(row["exit_priority"]) == "URGENT":
        return "Now"
    if str(row["classification"]) == "CLOSE_CANDIDATE":
        return "Soon"
    if proximity_alert:
        return "Soon"
    return "Optional"


def _exit_rule_result(
    *,
    ticker: str,
    report: Mapping[str, object] | None,
    broker_position: Mapping[str, object] | None,
    policy: PortfolioPolicy,
    high_water_marks: Mapping[str, float] = {},
) -> dict[str, object]:
    pnl_pct = _position_pnl_pct(broker_position)
    thresholds = {
        "policy_take_profit_pct": policy.take_profit_pct,
        "policy_stop_loss_pct": policy.stop_loss_pct,
        "policy_trailing_stop_pct": policy.trailing_stop_pct,
    }
    if pnl_pct is not None and pnl_pct <= -policy.stop_loss_pct:
        return {
            "classification": "CLOSE_CANDIDATE",
            "reason": (
                f"{ticker} unrealized loss is {pnl_pct:.2f}%, beyond the "
                f"{policy.stop_loss_pct:.2f}% stop-loss rule"
            ),
            "exit_signal": "STOP_LOSS",
            "exit_priority": "URGENT",
            "exit_reason": (
                "Loss control is triggered. Review for a SELL/COVER close "
                "before adding any new exposure."
            ),
            **thresholds,
        }
    high_water_mark = high_water_marks.get(ticker.upper())
    if (
        pnl_pct is not None
        and high_water_mark is not None
        and (high_water_mark - pnl_pct) >= policy.trailing_stop_pct
    ):
        drawdown = high_water_mark - pnl_pct
        return {
            "classification": "CLOSE_CANDIDATE",
            "reason": (
                f"{ticker} has drawn down {drawdown:.2f}% from its peak of "
                f"{high_water_mark:.2f}%, exceeding the "
                f"{policy.trailing_stop_pct:.2f}% trailing-stop rule"
            ),
            "exit_signal": "TRAILING_STOP",
            "exit_priority": "NORMAL",
            "exit_reason": (
                "Trailing stop is triggered. The position has retraced "
                "significantly from its peak unrealized gain. Review for a "
                "SELL/COVER close."
            ),
            **thresholds,
        }
    if pnl_pct is not None and pnl_pct >= policy.take_profit_pct:
        return {
            "classification": "CLOSE_CANDIDATE",
            "reason": (
                f"{ticker} unrealized gain is {pnl_pct:.2f}%, above the "
                f"{policy.take_profit_pct:.2f}% take-profit rule"
            ),
            "exit_signal": "TAKE_PROFIT",
            "exit_priority": "NORMAL",
            "exit_reason": (
                "Profit target is reached. Review whether to close, trim, "
                "or keep the position only if the current thesis remains strong."
            ),
            **thresholds,
        }
    if report is None:
        return {
            "classification": "NO_CURRENT_SETUP",
            "reason": "no current selection report",
            "exit_signal": "NO_CURRENT_SETUP",
            "exit_priority": "NORMAL",
            "exit_reason": (
                "The portfolio holds this ticker, but the latest cycle did not "
                "produce a current thesis for it."
            ),
            **thresholds,
        }
    action = str(report["final_action"])
    if action in {"NO_TRADE", "CLOSE_REVIEW"}:
        return {
            "classification": "CLOSE_CANDIDATE",
            "reason": "current setup is no-trade or close-review",
            "exit_signal": "THESIS_BROKEN",
            "exit_priority": "NORMAL",
            "exit_reason": (
                "The active selection thesis no longer supports holding the "
                "position without manual review."
            ),
            **thresholds,
        }
    if _string_list(report, "risk_flags") or _gate_status(report) == "WARN":
        return {
            "classification": "REVIEW",
            "reason": "current setup carries warnings",
            "exit_signal": "SETUP_WARNING",
            "exit_priority": "NORMAL",
            "exit_reason": (
                "The position is not an automatic exit, but the current setup has "
                "warnings that should be reviewed before increasing exposure."
            ),
            **thresholds,
        }
    return {
        "classification": "HOLD",
        "reason": "current setup remains aligned",
        "exit_signal": "NONE",
        "exit_priority": "NONE",
        "exit_reason": "No exit rule is triggered.",
        **thresholds,
    }


def _position_pnl_pct(position: Mapping[str, object] | None) -> float | None:
    if position is None:
        return None
    return _float_field(position, "unrealized_plpc") * 100.0


def _hourly_performance(
    *,
    account: Mapping[str, object] | None,
    snapshots: Sequence[Mapping[str, object]],
    generated_at: str,
    policy: PortfolioPolicy,
) -> dict[str, object]:
    current = _current_portfolio_point(
        account=account,
        snapshots=snapshots,
        generated_at=generated_at,
    )
    if current is None:
        return _unknown_hourly_performance("No broker account or portfolio snapshot is available.")
    current_at, current_value = current
    reference = _hourly_reference_point(snapshots, current_at=current_at)
    if reference is None:
        return _unknown_hourly_performance(
            "Hourly performance needs a snapshot from at least 60 minutes ago."
        )
    reference_at, reference_value = reference
    if reference_value <= 0:
        return _unknown_hourly_performance("Hourly reference portfolio value is zero.")
    hourly_pl = round(current_value - reference_value, 2)
    hourly_return_pct = round((current_value / reference_value - 1.0) * 100.0, 4)
    status = "WARN" if hourly_return_pct <= -policy.hourly_loss_alert_pct else "PASS"
    return {
        "hourly_return_pct": hourly_return_pct,
        "hourly_pl": hourly_pl,
        "hourly_reference_at": reference_at.isoformat().replace("+00:00", "Z"),
        "hourly_current_value": round(current_value, 2),
        "hourly_status": status,
        "hourly_status_class": "warn" if status == "WARN" else "pass",
        "hourly_status_label": (
            "Loss alert" if status == "WARN" else "Within hourly guardrail"
        ),
        "hourly_reason": (
            f"Portfolio changed {hourly_return_pct:.2f}% since "
            f"{reference_at.isoformat().replace('+00:00', 'Z')}."
        ),
    }


def _unknown_hourly_performance(reason: str) -> dict[str, object]:
    return {
        "hourly_return_pct": None,
        "hourly_pl": None,
        "hourly_reference_at": None,
        "hourly_current_value": None,
        "hourly_status": "UNKNOWN",
        "hourly_status_class": "neutral",
        "hourly_status_label": "Needs baseline",
        "hourly_reason": reason,
    }


def _current_portfolio_point(
    *,
    account: Mapping[str, object] | None,
    snapshots: Sequence[Mapping[str, object]],
    generated_at: str,
) -> tuple[datetime, float] | None:
    account_value = _portfolio_value_from_account(account)
    generated_time = _parse_time(generated_at) or datetime.now(UTC)
    if account_value is not None:
        return generated_time, account_value
    points = _snapshot_points(snapshots)
    return points[-1] if points else None


def _hourly_reference_point(
    snapshots: Sequence[Mapping[str, object]],
    *,
    current_at: datetime,
) -> tuple[datetime, float] | None:
    cutoff = current_at - timedelta(hours=1)
    candidates = [point for point in _snapshot_points(snapshots) if point[0] <= cutoff]
    return candidates[-1] if candidates else None


def _snapshot_points(
    snapshots: Sequence[Mapping[str, object]],
) -> list[tuple[datetime, float]]:
    points: list[tuple[datetime, float]] = []
    for snapshot in snapshots:
        captured_at = _parse_time(snapshot.get("captured_at"))
        value = _portfolio_value_from_snapshot(snapshot)
        if captured_at is not None and value is not None:
            points.append((captured_at, value))
    return sorted(points, key=lambda point: point[0])


def _portfolio_value_from_account(account: Mapping[str, object] | None) -> float | None:
    value = _optional_float(account, "portfolio_value")
    if value is not None and value > 0:
        return value
    equity = _optional_float(account, "equity")
    return equity if equity is not None and equity > 0 else None


def _portfolio_value_from_snapshot(snapshot: Mapping[str, object]) -> float | None:
    value = _coerced_optional_float(snapshot.get("portfolio_value"))
    if value is not None and value > 0:
        return value
    equity = _coerced_optional_float(snapshot.get("equity"))
    return equity if equity is not None and equity > 0 else None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _count(rows: Sequence[Mapping[str, object]], classification: str) -> int:
    return sum(1 for row in rows if row["classification"] == classification)


def _position_tickers(
    *,
    positions: Sequence[str] | None,
    broker_positions: Sequence[Mapping[str, object]],
) -> list[str]:
    if broker_positions:
        return [str(position["ticker"]).upper() for position in broker_positions]
    return [ticker.upper() for ticker in positions or []]


def _broker_position_index(
    positions: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    return {str(position["ticker"]).upper(): position for position in positions}


def _broker_position_fields(position: Mapping[str, object] | None) -> dict[str, object]:
    if position is None:
        return {
            "quantity": None,
            "market_value": None,
            "unrealized_pl": None,
            "unrealized_plpc": None,
            "side": None,
        }
    return {
        "quantity": _float_field(position, "qty"),
        "market_value": _float_field(position, "market_value"),
        "unrealized_pl": _float_field(position, "unrealized_pl"),
        "unrealized_plpc": _float_field(position, "unrealized_plpc"),
        "side": str(position["side"]),
    }


def _gate_status(report: Mapping[str, object]) -> str:
    statuses = [
        str(gate["status"])
        for gate in _mapping_list(report, "policy_gates")
    ]
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARN" in statuses:
        return "WARN"
    if "PASS" in statuses:
        return "PASS"
    return "UNKNOWN"


def _mapping_list(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [
        item
        for item in _list_field(payload, key)
        if isinstance(item, Mapping)
    ]


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _optional_float(payload: Mapping[str, object] | None, key: str) -> float | None:
    if payload is None:
        return None
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _coerced_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    return float(value)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
