from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

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

    min_final_conviction: float = 0.62
    max_new_positions_per_cycle: int = 3
    max_gross_exposure_pct: float = 100.0
    default_position_pct: float = 10.0
    take_profit_pct: float = 8.0
    stop_loss_pct: float = 4.0
    trailing_stop_pct: float = 3.0
    hourly_loss_alert_pct: float = 1.0
    broker_submit_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PortfolioPolicy:
        if env is None:
            load_dotenv()
        values = os.environ if env is None else env
        defaults = cls()
        policy = cls(
            min_final_conviction=_env_float(
                values.get("AGENCY_MIN_FINAL_CONVICTION"),
                default=defaults.min_final_conviction,
            ),
            max_new_positions_per_cycle=_env_int(
                values.get("AGENCY_MAX_NEW_POSITIONS_PER_CYCLE"),
                default=defaults.max_new_positions_per_cycle,
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
            broker_submit_enabled=_env_bool(values.get("AGENCY_BROKER_SUBMIT_ENABLED")),
        )
        return _policy_with_file_overrides(policy, values)

    def as_dict(self) -> dict[str, object]:
        return {
            "min_final_conviction": self.min_final_conviction,
            "max_new_positions_per_cycle": self.max_new_positions_per_cycle,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "default_position_pct": self.default_position_pct,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "hourly_loss_alert_pct": self.hourly_loss_alert_pct,
            "broker_submit_enabled": self.broker_submit_enabled,
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
        min_final_conviction=_payload_float(
            data, "min_final_conviction", default=defaults.min_final_conviction
        ),
        max_new_positions_per_cycle=_payload_int(
            data, "max_new_positions_per_cycle", default=defaults.max_new_positions_per_cycle
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
        broker_submit_enabled=_payload_bool(
            data, "broker_submit_enabled", default=defaults.broker_submit_enabled
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
) -> RiskDecisionResult:
    """Build one schema-valid v0 risk decision and audit event."""
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
    validate_contract("risk-decision", risk_decision)
    lifecycle_event = build_report_lifecycle_event(
        risk_decision,
        event_type="RISK_DECISION",
        status=_lifecycle_status(decision),
        reason=reasons[0],
        payload={"risk_decision": dict(risk_decision)},
    )
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
    return [
        _action_check(selection_report),
        _policy_gate_check(selection_report),
        _conviction_check(selection_report, policy),
        _runtime_source_check(source_health_summary),
        _capacity_check(selection_report, candidate_index, policy),
        _gross_exposure_check(selection_report, projected_gross_exposure_pct, policy),
        _risk_flag_check(selection_report),
    ]


def _action_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    action = str(selection_report["final_action"])
    if action in TRADE_ACTIONS:
        return _check("final_action", "PASS", f"{action} is eligible for preview")
    if action in REVIEW_ACTIONS:
        return _check("final_action", "WARN", f"{action} is review-only")
    return _check("final_action", "BLOCK", f"{action} is not orderable")


def _policy_gate_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    statuses = [
        str(gate["status"])
        for gate in _mapping_list(selection_report, "policy_gates")
    ]
    if "BLOCK" in statuses:
        return _check("policy_gates", "BLOCK", "selection policy gate blocked")
    if "WARN" in statuses:
        return _check("policy_gates", "WARN", "selection policy gate warned")
    return _check("policy_gates", "PASS", "selection policy gates passed")


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
    missing_count = missing_value if isinstance(missing_value, int) else 0
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


def _is_opening_trade_action(selection_report: Mapping[str, object]) -> bool:
    return str(selection_report["final_action"]) in OPENING_TRADE_ACTIONS


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


def _env_bool(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


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
        min_final_conviction=_payload_float(
            payload,
            "min_final_conviction",
            default=policy.min_final_conviction,
        ),
        max_new_positions_per_cycle=_payload_int(
            payload,
            "max_new_positions_per_cycle",
            default=policy.max_new_positions_per_cycle,
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
        broker_submit_enabled=policy.broker_submit_enabled and file_broker_submit_enabled,
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
