from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from dotenv import load_dotenv

from agency.contracts import validate_contract
from agency.services.selection_events import build_report_lifecycle_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TRADE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}
OPENING_TRADE_ACTIONS = {"BUY", "SHORT"}
REVIEW_ACTIONS = {"WATCH", "HOLD"}
DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}
POLICY_PATH_ENV = "AGENCY_PORTFOLIO_POLICY_PATH"
DEFAULT_POLICY_PATH = Path("research/config/portfolio-policy.local.json")


@dataclass(frozen=True)
class PortfolioPolicy:
    """Conservative v0 policy values used before editable policy persistence exists."""

    weekly_planning_target_pct: float = 3.0
    min_final_conviction: float = 0.62
    max_weekly_drawdown_pct: float = 6.0
    minimum_hold_days: int = 2
    max_positions: int = 10
    max_new_positions_per_cycle: int = 3
    max_single_name_pct: float = 25.0
    max_sector_exposure_pct: float = 30.0
    cash_reserve_pct: float = 10.0
    max_gross_exposure_pct: float = 100.0
    default_position_pct: float = 10.0
    take_profit_pct: float = 8.0
    stop_loss_pct: float = 4.0
    trailing_stop_pct: float = 3.0
    hourly_loss_alert_pct: float = 1.0
    bracket_orders_enabled: bool = True
    live_trading_enabled: bool = False
    broker_submit_enabled: bool = False
    allow_short_trades: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PortfolioPolicy:
        if env is None:
            load_dotenv()
        values = os.environ if env is None else env
        defaults = cls()
        policy = cls(
            weekly_planning_target_pct=_env_float(
                values.get("AGENCY_WEEKLY_PLANNING_TARGET_PCT"),
                default=defaults.weekly_planning_target_pct,
            ),
            min_final_conviction=_env_float(
                values.get("AGENCY_MIN_FINAL_CONVICTION"),
                default=defaults.min_final_conviction,
            ),
            max_weekly_drawdown_pct=_env_float(
                values.get("AGENCY_MAX_WEEKLY_DRAWDOWN_PCT"),
                default=defaults.max_weekly_drawdown_pct,
            ),
            minimum_hold_days=_env_int(
                values.get("AGENCY_MINIMUM_HOLD_DAYS"),
                default=defaults.minimum_hold_days,
            ),
            max_positions=_env_int(
                values.get("AGENCY_MAX_POSITIONS"),
                default=defaults.max_positions,
            ),
            max_new_positions_per_cycle=_env_int(
                values.get("AGENCY_MAX_NEW_POSITIONS_PER_CYCLE"),
                default=defaults.max_new_positions_per_cycle,
            ),
            max_single_name_pct=_env_float(
                values.get("AGENCY_MAX_SINGLE_NAME_PCT"),
                default=defaults.max_single_name_pct,
            ),
            max_sector_exposure_pct=_env_float(
                values.get("AGENCY_MAX_SECTOR_EXPOSURE_PCT"),
                default=defaults.max_sector_exposure_pct,
            ),
            cash_reserve_pct=_env_float(
                values.get("AGENCY_CASH_RESERVE_PCT"),
                default=defaults.cash_reserve_pct,
            ),
            max_gross_exposure_pct=_env_float(
                values.get("AGENCY_MAX_GROSS_EXPOSURE_PCT"),
                default=defaults.max_gross_exposure_pct,
            ),
            default_position_pct=_env_float(
                values.get("AGENCY_DEFAULT_POSITION_PCT"),
                default=defaults.default_position_pct,
            ),
            take_profit_pct=_env_float(
                values.get("AGENCY_TAKE_PROFIT_PCT"),
                default=defaults.take_profit_pct,
            ),
            stop_loss_pct=_env_float(
                values.get("AGENCY_STOP_LOSS_PCT"),
                default=defaults.stop_loss_pct,
            ),
            trailing_stop_pct=_env_float(
                values.get("AGENCY_TRAILING_STOP_PCT"),
                default=defaults.trailing_stop_pct,
            ),
            hourly_loss_alert_pct=_env_float(
                values.get("AGENCY_HOURLY_LOSS_ALERT_PCT"),
                default=defaults.hourly_loss_alert_pct,
            ),
            bracket_orders_enabled=_env_bool(
                values.get("AGENCY_BRACKET_ORDERS_ENABLED"),
                default=defaults.bracket_orders_enabled,
            ),
            live_trading_enabled=_env_bool(
                values.get("AGENCY_LIVE_TRADING_ENABLED"),
                default=defaults.live_trading_enabled,
            ),
            broker_submit_enabled=_env_bool(
                values.get("AGENCY_BROKER_SUBMIT_ENABLED"),
                default=defaults.broker_submit_enabled,
            ),
            allow_short_trades=_env_bool(
                values.get("AGENCY_ALLOW_SHORT_TRADES"),
                default=defaults.allow_short_trades,
            ),
        )
        return _policy_with_file_overrides(policy, values)

    def as_dict(self) -> dict[str, object]:
        return {
            "weekly_planning_target_pct": self.weekly_planning_target_pct,
            "min_final_conviction": self.min_final_conviction,
            "max_weekly_drawdown_pct": self.max_weekly_drawdown_pct,
            "minimum_hold_days": self.minimum_hold_days,
            "max_positions": self.max_positions,
            "max_new_positions_per_cycle": self.max_new_positions_per_cycle,
            "max_single_name_pct": self.max_single_name_pct,
            "max_sector_exposure_pct": self.max_sector_exposure_pct,
            "cash_reserve_pct": self.cash_reserve_pct,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "default_position_pct": self.default_position_pct,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "hourly_loss_alert_pct": self.hourly_loss_alert_pct,
            "bracket_orders_enabled": self.bracket_orders_enabled,
            "live_trading_enabled": self.live_trading_enabled,
            "broker_submit_enabled": self.broker_submit_enabled,
            "allow_short_trades": self.allow_short_trades,
        }


async def load_policy_from_db(session: AsyncSession) -> PortfolioPolicy | None:
    """Return the DB-persisted policy, or None if the table is empty."""
    from sqlalchemy import select

    from agency.persistence import portfolio_policy as _policy_table

    result = await session.execute(select(_policy_table).where(_policy_table.c.id == 1))
    row = result.mappings().first()
    if row is None:
        return None
    data = row["data"]
    if not isinstance(data, Mapping):
        return None
    defaults = PortfolioPolicy()
    return PortfolioPolicy(
        weekly_planning_target_pct=_payload_float(
            data,
            "weekly_planning_target_pct",
            default=defaults.weekly_planning_target_pct,
        ),
        min_final_conviction=_payload_float(
            data, "min_final_conviction", default=defaults.min_final_conviction
        ),
        max_weekly_drawdown_pct=_payload_float(
            data,
            "max_weekly_drawdown_pct",
            default=defaults.max_weekly_drawdown_pct,
        ),
        minimum_hold_days=_payload_int(
            data, "minimum_hold_days", default=defaults.minimum_hold_days
        ),
        max_positions=_payload_int(
            data, "max_positions", default=defaults.max_positions
        ),
        max_new_positions_per_cycle=_payload_int(
            data, "max_new_positions_per_cycle", default=defaults.max_new_positions_per_cycle
        ),
        max_single_name_pct=_payload_float(
            data, "max_single_name_pct", default=defaults.max_single_name_pct
        ),
        max_sector_exposure_pct=_payload_float(
            data,
            "max_sector_exposure_pct",
            default=defaults.max_sector_exposure_pct,
        ),
        cash_reserve_pct=_payload_float(
            data, "cash_reserve_pct", default=defaults.cash_reserve_pct
        ),
        max_gross_exposure_pct=_payload_float(
            data, "max_gross_exposure_pct", default=defaults.max_gross_exposure_pct
        ),
        default_position_pct=_payload_float(
            data, "default_position_pct", default=defaults.default_position_pct
        ),
        take_profit_pct=_payload_float(
            data, "take_profit_pct", default=defaults.take_profit_pct
        ),
        stop_loss_pct=_payload_float(
            data, "stop_loss_pct", default=defaults.stop_loss_pct
        ),
        trailing_stop_pct=_payload_float(
            data, "trailing_stop_pct", default=defaults.trailing_stop_pct
        ),
        hourly_loss_alert_pct=_payload_float(
            data, "hourly_loss_alert_pct", default=defaults.hourly_loss_alert_pct
        ),
        bracket_orders_enabled=_payload_bool(
            data,
            "bracket_orders_enabled",
            default=defaults.bracket_orders_enabled,
        ),
        live_trading_enabled=_payload_bool(
            data, "live_trading_enabled", default=defaults.live_trading_enabled
        ),
        broker_submit_enabled=_payload_bool(
            data, "broker_submit_enabled", default=defaults.broker_submit_enabled
        ),
        allow_short_trades=_payload_bool(
            data, "allow_short_trades", default=defaults.allow_short_trades
        ),
    )


async def save_policy_to_db(session: AsyncSession, policy: PortfolioPolicy) -> None:
    """Upsert the policy into the single-row portfolio_policy table (id=1)."""
    from sqlalchemy.dialects.postgresql import insert

    from agency.persistence import portfolio_policy as _policy_table

    stmt = (
        insert(_policy_table)
        .values(id=1, data=policy.as_dict(), updated_at=datetime.now(UTC))
        .on_conflict_do_update(
            index_elements=["id"],
            set_={"data": policy.as_dict(), "updated_at": datetime.now(UTC)},
        )
    )
    await session.execute(stmt)


async def load_active_portfolio_policy(
    *,
    session_provider: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
) -> PortfolioPolicy:
    """Load the policy used by risk/execution, with env-only safety controls.

    Editable sizing and exit rules may come from the database. Broker submission
    and short-sale permissions stay controlled by local env/file policy so the
    UI cannot silently enable a dangerous execution mode.
    """
    env_policy = PortfolioPolicy.from_env()
    try:
        if session_provider is None:
            from agency.db import get_session

            resolved_provider = cast(
                Callable[[], AbstractAsyncContextManager[Any]],
                get_session,
            )
        else:
            resolved_provider = session_provider
        async with resolved_provider() as session:
            db_policy = await load_policy_from_db(session)
    except Exception:  # noqa: BLE001 - policy persistence failure must not break local runtime
        return env_policy
    if db_policy is None:
        return env_policy
    env_values = os.environ
    broker_submit_enabled = (
        env_policy.broker_submit_enabled
        if _env_bool_is_configured(env_values, "AGENCY_BROKER_SUBMIT_ENABLED")
        else db_policy.broker_submit_enabled
    )
    allow_short_trades = (
        env_policy.allow_short_trades
        if _env_bool_is_configured(env_values, "AGENCY_ALLOW_SHORT_TRADES")
        else db_policy.allow_short_trades
    )
    return replace(
        db_policy,
        broker_submit_enabled=broker_submit_enabled,
        allow_short_trades=allow_short_trades,
    )


@dataclass(frozen=True)
class RiskDecisionResult:
    """Risk decision plus lifecycle audit event."""

    risk_decision: dict[str, object]
    lifecycle_event: dict[str, object]


def build_risk_decisions(
    selection_reports: Sequence[Mapping[str, object]],
    source_health: Sequence[Mapping[str, object]],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
    current_gross_exposure_pct: float = 0.0,
    pending_opening_order_exposure_pct: float = 0.0,
    validate_contracts: bool = True,
) -> list[RiskDecisionResult]:
    """Build v0 risk decisions for selection reports without broker calls."""
    normalized_policy = policy or PortfolioPolicy()
    source_summaries = _source_health_by_report(source_health, selection_reports)
    results: list[RiskDecisionResult] = []
    opening_trade_index = 0
    for index, report in enumerate(selection_reports):
        is_opening_trade = _is_opening_trade_action(report)
        projected_exposure = current_gross_exposure_pct + pending_opening_order_exposure_pct
        if is_opening_trade:
            projected_exposure += (
                opening_trade_index + 1
            ) * normalized_policy.default_position_pct
        result = build_risk_decision(
            report,
            source_summaries[index],
            generated_at=generated_at,
            policy=normalized_policy,
            candidate_index=opening_trade_index,
            projected_gross_exposure_pct=projected_exposure,
            validate_contracts=validate_contracts,
        )
        results.append(result)
        if is_opening_trade and result.risk_decision["decision"] == "ALLOW":
            opening_trade_index += 1
    return results


def build_risk_decision(
    selection_report: Mapping[str, object],
    source_health_summary: Mapping[str, object],
    *,
    generated_at: str | None = None,
    policy: PortfolioPolicy | None = None,
    candidate_index: int = 0,
    projected_gross_exposure_pct: float | None = None,
    validate_contracts: bool = True,
) -> RiskDecisionResult:
    """Build one schema-valid v0 risk decision and audit event."""
    if validate_contracts:
        validate_contract("selection-report", selection_report)
    normalized_policy = policy or PortfolioPolicy()
    projected_exposure = (
        normalized_policy.default_position_pct
        if projected_gross_exposure_pct is None and _is_opening_trade_action(selection_report)
        else 0.0
        if projected_gross_exposure_pct is None
        else projected_gross_exposure_pct
    )
    checks = _risk_checks(
        selection_report,
        source_health_summary,
        policy=normalized_policy,
        candidate_index=candidate_index,
        projected_gross_exposure_pct=projected_exposure,
    )
    decision = _decision_from_checks(checks, selection_report)
    reasons = _decision_reasons(checks, selection_report)
    risk_decision: dict[str, object] = {
        "schema_version": "0.1.0",
        "cycle_id": str(selection_report["cycle_id"]),
        "ticker": str(selection_report["ticker"]),
        "as_of": str(selection_report["as_of"]),
        "generated_at": generated_at or _now_utc(),
        "decision": decision,
        "final_action": str(selection_report["final_action"]),
        "final_conviction": _float_field(selection_report, "final_conviction"),
        "position_size_pct": normalized_policy.default_position_pct,
        "projected_gross_exposure_pct": round(projected_exposure, 6),
        "checks": checks,
        "reasons": reasons,
        "risk_flags": _string_list(selection_report, "risk_flags"),
        "source_health": dict(source_health_summary),
    }
    if validate_contracts:
        validate_contract("risk-decision", risk_decision)
    lifecycle_event = build_report_lifecycle_event(
        risk_decision,
        event_type="RISK_DECISION",
        status=_lifecycle_status(decision),
        reason=reasons[0],
        payload={"risk_decision": dict(risk_decision)},
    )
    if validate_contracts:
        validate_contract("candidate-lifecycle-event", lifecycle_event)
    return RiskDecisionResult(risk_decision, lifecycle_event)


def _risk_checks(
    selection_report: Mapping[str, object],
    source_health_summary: Mapping[str, object],
    *,
    policy: PortfolioPolicy,
    candidate_index: int,
    projected_gross_exposure_pct: float,
) -> list[dict[str, str]]:
    checks = [
        _action_check(selection_report),
        _short_policy_check(selection_report, policy),
        _policy_gate_check(selection_report),
        _conviction_check(selection_report, policy),
        _runtime_source_check(source_health_summary),
        _capacity_check(selection_report, candidate_index, policy),
        _gross_exposure_check(selection_report, projected_gross_exposure_pct, policy),
        _risk_flag_check(selection_report),
    ]
    if _is_review_action(selection_report):
        return [_review_only_caution_check(check, selection_report) for check in checks]
    return checks


def _action_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    action = str(selection_report["final_action"])
    if action in TRADE_ACTIONS:
        return _check("final_action", "PASS", f"{action} is eligible for preview")
    if action in REVIEW_ACTIONS:
        return _check("final_action", "WARN", f"{action} is review-only")
    return _check("final_action", "BLOCK", f"{action} is not orderable")


def _short_policy_check(
    selection_report: Mapping[str, object],
    policy: PortfolioPolicy,
) -> dict[str, str]:
    action = str(selection_report["final_action"])
    if action not in {"SHORT", "COVER"}:
        return _check("short_policy", "PASS", "short-sale policy not applicable")
    if policy.allow_short_trades:
        return _check("short_policy", "PASS", "short-sale policy explicitly enabled")
    return _check("short_policy", "BLOCK", f"{action} orders are disabled by short-sale policy")


def _policy_gate_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    gates = _mapping_list(selection_report, "policy_gates")
    statuses = [str(gate["status"]) for gate in gates]
    if "BLOCK" in statuses:
        reason = _first_gate_reason(gates, "BLOCK")
        detail = f": {reason}" if reason else ""
        return _check("policy_gates", "BLOCK", f"selection policy gate blocked{detail}")
    if "WARN" in statuses:
        reason = _first_gate_reason(gates, "WARN")
        detail = f": {reason}" if reason else ""
        if _is_approved_watch_promotion(selection_report):
            return _check(
                "policy_gates",
                "PASS",
                (
                    "selection policy warning acknowledged during approved WATCH "
                    f"paper eligibility review{detail}"
                ),
            )
        return _check("policy_gates", "WARN", f"selection policy gate warned{detail}")
    return _check("policy_gates", "PASS", "selection policy gates passed")


def _is_approved_watch_promotion(selection_report: Mapping[str, object]) -> bool:
    trade_plan = selection_report.get("trade_plan")
    if not isinstance(trade_plan, Mapping):
        return False
    notes = trade_plan.get("notes", [])
    if not isinstance(notes, list):
        return False
    return any(
        isinstance(note, str)
        and note.startswith(
            ("paper trade promotion: approved WATCH", "paper eligibility: approved WATCH")
        )
        for note in notes
    )


def _first_gate_reason(gates: Sequence[Mapping[str, object]], status: str) -> str:
    for gate in gates:
        if str(gate.get("status")) != status:
            continue
        reason = str(gate.get("reason") or "").strip()
        if reason:
            return reason
    return ""


def _conviction_check(
    selection_report: Mapping[str, object],
    policy: PortfolioPolicy,
) -> dict[str, str]:
    conviction = _float_field(selection_report, "final_conviction")
    if conviction < policy.min_final_conviction:
        return _check("min_conviction", "BLOCK", "below minimum final conviction")
    return _check("min_conviction", "PASS", "minimum final conviction met")


def _runtime_source_check(source_health_summary: Mapping[str, object]) -> dict[str, str]:
    source_count = _int_field(source_health_summary, "source_count")
    degraded_count = _int_field(source_health_summary, "degraded_source_count")
    missing_value = source_health_summary.get("missing_source_count", 0)
    missing_count = (
        float(missing_value)
        if isinstance(missing_value, int | float) and not isinstance(missing_value, bool)
        else 0.0
    )
    missing_sources = (
        _string_list(source_health_summary, "missing_sources")
        if "missing_sources" in source_health_summary
        else []
    )
    if missing_count > 0:
        missing = ", ".join(missing_sources[:3])
        suffix = f": {missing}" if missing else ""
        return _check("runtime_sources", "BLOCK", f"missing runtime source health{suffix}")
    if source_count == 0:
        return _check("runtime_sources", "BLOCK", "no runtime source health available")
    if degraded_count > 0:
        return _check("runtime_sources", "WARN", "runtime source degradation present")
    return _check("runtime_sources", "PASS", "runtime sources healthy")


def _capacity_check(
    selection_report: Mapping[str, object],
    candidate_index: int,
    policy: PortfolioPolicy,
) -> dict[str, str]:
    if not _is_opening_trade_action(selection_report):
        return _check("cycle_capacity", "PASS", "no trade capacity required")
    if candidate_index >= policy.max_new_positions_per_cycle:
        return _check("cycle_capacity", "BLOCK", "new candidate capacity exceeded")
    return _check("cycle_capacity", "PASS", "within new candidate capacity")


def _gross_exposure_check(
    selection_report: Mapping[str, object],
    projected_gross_exposure_pct: float,
    policy: PortfolioPolicy,
) -> dict[str, str]:
    if not _is_opening_trade_action(selection_report):
        return _check("gross_exposure", "PASS", "no trade exposure added")
    if projected_gross_exposure_pct > policy.max_gross_exposure_pct:
        return _check("gross_exposure", "BLOCK", "projected gross exposure exceeds cap")
    return _check("gross_exposure", "PASS", "projected gross exposure within cap")


def _risk_flag_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    risk_flags = _string_list(selection_report, "risk_flags")
    if risk_flags:
        return _check("risk_flags", "WARN", "selection report has risk flags")
    return _check("risk_flags", "PASS", "no selection risk flags")


def _source_health_summary(
    source_health: Sequence[Mapping[str, object]],
    *,
    expected_sources: set[str] | None = None,
) -> dict[str, object]:
    for source in source_health:
        validate_contract("data-source-health", source)
    present_sources = {str(source.get("source")) for source in source_health}
    missing_sources = sorted((expected_sources or set()).difference(present_sources))
    return {
        "source_count": len(source_health),
        "degraded_source_count": sum(1 for source in source_health if _source_is_degraded(source)),
        "missing_source_count": len(missing_sources),
        "missing_sources": missing_sources,
    }


def _source_health_by_report(
    source_health: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for report in selection_reports:
        used = _used_sources(report)
        summaries.append(
            _source_health_summary(
                _relevant_source_health(source_health, report, used_sources=used),
                expected_sources=used,
            )
        )
    return summaries


def _relevant_source_health(
    source_health: Sequence[Mapping[str, object]],
    report: Mapping[str, object],
    *,
    used_sources: set[str] | None = None,
) -> list[Mapping[str, object]]:
    used = _used_sources(report) if used_sources is None else used_sources
    if not used:
        return list(source_health)
    return [source for source in source_health if str(source.get("source")) in used]


def _used_sources(report: Mapping[str, object]) -> set[str]:
    pack = report.get("evidence_pack")
    if not isinstance(pack, Mapping):
        return set()
    sources: set[str] = set()
    for key in ("actionable_signals", "context_signals", "suppressed_signals"):
        values = pack.get(key, [])
        if not isinstance(values, list):
            continue
        for signal in values:
            if not isinstance(signal, Mapping):
                continue
            provenance = signal.get("provenance")
            if not isinstance(provenance, Mapping):
                continue
            source = provenance.get("source")
            if isinstance(source, str) and source:
                sources.add(source)
    return sources


def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source["status"]) in DEGRADED_SOURCE_STATUSES
        or str(source["freshness"]) in DEGRADED_FRESHNESS
    )


def _is_trade_action(selection_report: Mapping[str, object]) -> bool:
    return str(selection_report["final_action"]) in TRADE_ACTIONS


def _is_review_action(selection_report: Mapping[str, object]) -> bool:
    return str(selection_report["final_action"]) in REVIEW_ACTIONS


def _is_opening_trade_action(selection_report: Mapping[str, object]) -> bool:
    return str(selection_report["final_action"]) in OPENING_TRADE_ACTIONS


def _review_only_caution_check(
    check: Mapping[str, str],
    selection_report: Mapping[str, object],
) -> dict[str, str]:
    if check["status"] != "BLOCK":
        return dict(check)
    action = str(selection_report["final_action"])
    return _check(
        check["name"],
        "WARN",
        (
            f"Caution: {check['reason']}. {action} is a review/watch-list candidate, "
            "so this does not block human review and it does not create a paper order. "
            "Recommendation: acknowledge the caution, inspect the underlying gate or "
            "data issue, and wait for a later BUY, SELL, SHORT, or COVER cycle before "
            "trading it."
        ),
    )


def _decision_from_checks(
    checks: Sequence[Mapping[str, str]],
    selection_report: Mapping[str, object],
) -> str:
    statuses = [check["status"] for check in checks]
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARN" in statuses or _string_list(selection_report, "risk_flags"):
        return "WARN"
    return "ALLOW"


def _decision_reasons(
    checks: Sequence[Mapping[str, str]],
    selection_report: Mapping[str, object],
) -> list[str]:
    reasons = [
        check["reason"]
        for check in checks
        if check["status"] in {"BLOCK", "WARN"}
    ]
    if reasons:
        return reasons
    note = _trade_plan_note(selection_report)
    if note is not None:
        return [note]
    return [f"{selection_report['ticker']} passed v0 risk checks"]


def _trade_plan_note(selection_report: Mapping[str, object]) -> str | None:
    trade_plan = selection_report.get("trade_plan")
    if not isinstance(trade_plan, Mapping):
        return None
    notes = trade_plan.get("notes", [])
    if not isinstance(notes, list):
        return None
    for note in notes:
        if isinstance(note, str) and note:
            return note
    return None


def _lifecycle_status(decision: str) -> str:
    if decision == "ALLOW":
        return "PASSED"
    if decision == "WARN":
        return "WARN"
    return "BLOCKED"


def _check(name: str, status: str, reason: str) -> dict[str, str]:
    return {"name": name, "status": status, "reason": reason}


def _mapping_list(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [cast(Mapping[str, object], item) for item in _list_field(payload, key)]


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


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _env_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_bool_is_configured(values: Mapping[str, str], key: str) -> bool:
    value = values.get(key)
    return value is not None and bool(value.strip())


def _env_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def _env_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def _policy_with_file_overrides(
    policy: PortfolioPolicy,
    env: Mapping[str, str],
) -> PortfolioPolicy:
    path = Path(env.get(POLICY_PATH_ENV, DEFAULT_POLICY_PATH.as_posix()))
    if not path.is_file():
        return policy
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return policy
    if not isinstance(payload, Mapping):
        return policy
    file_broker_submit_enabled = _payload_bool(
        payload,
        "broker_submit_enabled",
        default=policy.broker_submit_enabled,
    )
    return PortfolioPolicy(
        weekly_planning_target_pct=_payload_float(
            payload,
            "weekly_planning_target_pct",
            default=policy.weekly_planning_target_pct,
        ),
        min_final_conviction=_payload_float(
            payload,
            "min_final_conviction",
            default=policy.min_final_conviction,
        ),
        max_weekly_drawdown_pct=_payload_float(
            payload,
            "max_weekly_drawdown_pct",
            default=policy.max_weekly_drawdown_pct,
        ),
        minimum_hold_days=_payload_int(
            payload,
            "minimum_hold_days",
            default=policy.minimum_hold_days,
        ),
        max_positions=_payload_int(
            payload,
            "max_positions",
            default=policy.max_positions,
        ),
        max_new_positions_per_cycle=_payload_int(
            payload,
            "max_new_positions_per_cycle",
            default=policy.max_new_positions_per_cycle,
        ),
        max_single_name_pct=_payload_float(
            payload,
            "max_single_name_pct",
            default=policy.max_single_name_pct,
        ),
        max_sector_exposure_pct=_payload_float(
            payload,
            "max_sector_exposure_pct",
            default=policy.max_sector_exposure_pct,
        ),
        cash_reserve_pct=_payload_float(
            payload,
            "cash_reserve_pct",
            default=policy.cash_reserve_pct,
        ),
        max_gross_exposure_pct=_payload_float(
            payload,
            "max_gross_exposure_pct",
            default=policy.max_gross_exposure_pct,
        ),
        default_position_pct=_payload_float(
            payload,
            "default_position_pct",
            default=policy.default_position_pct,
        ),
        take_profit_pct=_payload_float(
            payload,
            "take_profit_pct",
            default=policy.take_profit_pct,
        ),
        stop_loss_pct=_payload_float(
            payload,
            "stop_loss_pct",
            default=policy.stop_loss_pct,
        ),
        trailing_stop_pct=_payload_float(
            payload,
            "trailing_stop_pct",
            default=policy.trailing_stop_pct,
        ),
        hourly_loss_alert_pct=_payload_float(
            payload,
            "hourly_loss_alert_pct",
            default=policy.hourly_loss_alert_pct,
        ),
        bracket_orders_enabled=_payload_bool(
            payload,
            "bracket_orders_enabled",
            default=policy.bracket_orders_enabled,
        ),
        live_trading_enabled=_payload_bool(
            payload,
            "live_trading_enabled",
            default=policy.live_trading_enabled,
        ),
        broker_submit_enabled=policy.broker_submit_enabled and file_broker_submit_enabled,
        allow_short_trades=_payload_bool(
            payload,
            "allow_short_trades",
            default=policy.allow_short_trades,
        ),
    )


def _payload_float(payload: Mapping[str, object], key: str, *, default: float) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _payload_int(payload: Mapping[str, object], key: str, *, default: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _payload_bool(payload: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else default
