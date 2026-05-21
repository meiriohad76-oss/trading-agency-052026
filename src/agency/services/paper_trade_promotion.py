from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agency.contracts import validate_contract
from agency.services.human_review import (
    OPERATOR_MANUAL_ADVANCE_TYPE,
    selection_report_hash,
)

TRADE_PROMOTION_NOTE = (
    "paper trade promotion: approved WATCH creates a paper BUY order-intent preview"
)
TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG = "paper_trade_promotion_requires_order_approval"
TRADE_PROMOTION_APPROVAL_NOTE = (
    "candidate approval records the research decision only; broker submission requires "
    "a separate hash-bound order-intent approval after risk, policy, and freshness pass"
)
DEFAULT_MIN_CONVICTION = 0.9
DEFAULT_MIN_SOURCE_COUNT = 2
DEFAULT_MIN_CONFIRMED_SIGNALS = 2
DEFAULT_MAX_PROMOTIONS = 1
OPERATOR_OVERRIDABLE_CHECKS = {
    "conviction",
    "risk_flags",
    "policy_gates",
    "source_count",
    "confirmed_signal_count",
    "freshness",
}


@dataclass(frozen=True)
class PaperTradePromotionConfig:
    """Guardrails for paper-only WATCH-to-BUY execution promotion."""

    enabled: bool = False
    min_conviction: float = DEFAULT_MIN_CONVICTION
    min_source_count: int = DEFAULT_MIN_SOURCE_COUNT
    min_confirmed_signals: int = DEFAULT_MIN_CONFIRMED_SIGNALS
    max_promotions_per_cycle: int = DEFAULT_MAX_PROMOTIONS
    require_policy_pass: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PaperTradePromotionConfig:
        values = os.environ if env is None else env
        defaults = cls()
        return cls(
            enabled=_env_bool(values.get("AGENCY_PAPER_TRADE_PROMOTION_ENABLED")),
            min_conviction=_env_float(
                values.get("AGENCY_PAPER_TRADE_MIN_CONVICTION"),
                default=defaults.min_conviction,
            ),
            min_source_count=_env_int(
                values.get("AGENCY_PAPER_TRADE_MIN_SOURCE_COUNT"),
                default=defaults.min_source_count,
            ),
            min_confirmed_signals=_env_int(
                values.get("AGENCY_PAPER_TRADE_MIN_CONFIRMED_SIGNALS"),
                default=defaults.min_confirmed_signals,
            ),
            max_promotions_per_cycle=_env_int(
                values.get("AGENCY_PAPER_TRADE_MAX_PER_CYCLE"),
                default=defaults.max_promotions_per_cycle,
            ),
            require_policy_pass=_env_bool(
                values.get("AGENCY_PAPER_TRADE_REQUIRE_POLICY_PASS"),
                default=defaults.require_policy_pass,
            ),
        )


def promote_paper_trade_reports(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    operator_advance_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    broker_ready: bool = False,
    config: PaperTradePromotionConfig | None = None,
) -> list[dict[str, object]]:
    """Return report copies with eligible approved WATCH rows promoted to paper BUY."""
    normalized_config = config or PaperTradePromotionConfig()
    reports = [_validated_report(report) for report in selection_reports]
    advances = {} if operator_advance_states is None else operator_advance_states
    evaluations = _paper_trade_promotion_evaluation_list(
        reports,
        review_states=review_states,
        operator_advance_states=advances,
        positions=positions,
        open_orders=open_orders,
        broker_ready=broker_ready,
        config=normalized_config,
    )
    selected_indices = _selected_promotion_indices(reports, evaluations, normalized_config)
    return [
        _promoted_report(
            report,
            operator_advance=_valid_operator_manual_advance(
                advances.get(_report_key(report)),
                report,
            ),
        )
        if index in selected_indices
        else dict(report)
        for index, report in enumerate(reports)
    ]


def paper_trade_promotion_evaluations(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    operator_advance_states: Mapping[tuple[str, str, str], Mapping[str, object]] | None = None,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    broker_ready: bool = False,
    config: PaperTradePromotionConfig | None = None,
) -> dict[tuple[str, str, str], dict[str, object]]:
    """Explain paper-only WATCH-to-BUY promotion eligibility for each report."""
    normalized_config = config or PaperTradePromotionConfig()
    reports = [_validated_report(report) for report in selection_reports]
    advances = {} if operator_advance_states is None else operator_advance_states
    base_evaluations = _paper_trade_promotion_evaluation_list(
        reports,
        review_states=review_states,
        operator_advance_states=advances,
        positions=positions,
        open_orders=open_orders,
        broker_ready=broker_ready,
        config=normalized_config,
    )
    selected_indices = _selected_promotion_indices(reports, base_evaluations, normalized_config)
    evaluations: dict[tuple[str, str, str], dict[str, object]] = {}
    for index, report in enumerate(reports):
        evaluation = dict(base_evaluations[index])
        if evaluation["eligible"] is True and index in selected_indices:
            evaluation.update(_promotion_state_fields("promoted", promoted=True))
        elif evaluation["eligible"] is True:
            evaluation.update(_promotion_state_fields("promotion_limit_reached"))
        evaluations[_report_key(report)] = evaluation
    return evaluations


def _paper_trade_promotion_evaluation_list(
    reports: Sequence[Mapping[str, object]],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    operator_advance_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    positions: Sequence[Mapping[str, object]],
    open_orders: Sequence[Mapping[str, object]],
    broker_ready: bool,
    config: PaperTradePromotionConfig,
) -> list[dict[str, object]]:
    held_tickers = _held_tickers(positions)
    open_order_tickers = _open_order_tickers(open_orders)
    return [
        _paper_trade_promotion_evaluation(
            report,
            review_states=review_states,
            operator_advance=operator_advance_states.get(_report_key(report)),
            held_tickers=held_tickers,
            open_order_tickers=open_order_tickers,
            broker_ready=broker_ready,
            config=config,
        )
        for report in reports
    ]


def _selected_promotion_indices(
    reports: Sequence[Mapping[str, object]],
    evaluations: Sequence[Mapping[str, object]],
    config: PaperTradePromotionConfig,
) -> set[int]:
    candidates = [
        (index, report)
        for index, report in enumerate(reports)
        if evaluations[index]["eligible"] is True
    ]
    return {
        index
        for index, _report in sorted(candidates, key=_indexed_promotion_sort_key)[
            : config.max_promotions_per_cycle
        ]
    }


def _paper_trade_promotion_evaluation(
    report: Mapping[str, object],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    operator_advance: Mapping[str, object] | None,
    held_tickers: set[str],
    open_order_tickers: set[str],
    broker_ready: bool,
    config: PaperTradePromotionConfig,
) -> dict[str, object]:
    valid_advance = _valid_operator_manual_advance(operator_advance, report)
    raw_checks = _promotion_checks(
        report,
        review_states=review_states,
        held_tickers=held_tickers,
        open_order_tickers=open_order_tickers,
        broker_ready=broker_ready,
        config=config,
    )
    manual_advance_available = (
        valid_advance is None and _manual_advance_can_help(raw_checks, report)
    )
    checks = _apply_operator_manual_advance(raw_checks, valid_advance)
    failed = [check for check in checks if check["status"] != "PASS"]
    advanced = [check for check in checks if check.get("operator_advanced") is True]
    eligible = not failed
    can_promote_after_approval = (
        not eligible
        and all(
            check["status"] == "PASS" or check["name"] == "human_approval"
            for check in checks
        )
        and _approval_can_be_recorded(checks)
    )
    state = (
        "eligible"
        if eligible
        else "awaiting_research_approval"
        if can_promote_after_approval
        else "not_eligible"
    )
    output = {
        "schema_version": "0.1.0",
        "ticker": str(report["ticker"]),
        "cycle_id": str(report["cycle_id"]),
        "as_of": str(report["as_of"]),
        "eligible": eligible,
        "promoted": False,
        "can_promote_after_approval": can_promote_after_approval,
        "checks": checks,
        "reasons": [str(check["detail"]) for check in failed],
        "operator_manual_advance": _operator_advance_summary(valid_advance),
        "operator_advanced_reasons": [str(check["detail"]) for check in advanced],
        "manual_advance_available": manual_advance_available,
        "manual_advance_blocked_reasons": _manual_advance_blocked_reasons(raw_checks),
    }
    output.update(_promotion_state_fields(state))
    return output


def _promotion_checks(
    report: Mapping[str, object],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    held_tickers: set[str],
    open_order_tickers: set[str],
    broker_ready: bool,
    config: PaperTradePromotionConfig,
) -> list[dict[str, object]]:
    ticker = str(report["ticker"]).upper()
    data_quality = _mapping_field(_mapping_field(report, "evidence_pack"), "data_quality")
    conviction = _float_field(report, "final_conviction")
    source_count = _int_field(data_quality, "source_count")
    confirmed_signal_count = _int_field(data_quality, "confirmed_signal_count")
    freshness = str(data_quality["freshness"])
    risk_flags = _string_list(report, "risk_flags")
    return [
        _check(
            "promotion_enabled",
            config.enabled and config.max_promotions_per_cycle >= 1,
            "paper trade promotion is enabled.",
            "paper trade promotion is disabled or the per-cycle promotion limit is zero.",
            label="Paper promotion switch",
            observed="enabled" if config.enabled else "disabled",
            required="enabled and limit >= 1",
        ),
        _check(
            "broker_ready",
            broker_ready,
            "Alpaca paper broker is connected and ready.",
            "Alpaca paper broker is not ready for paper promotion.",
            label="Paper broker readiness",
            observed="ready" if broker_ready else "not ready",
            required="ready",
        ),
        _check(
            "final_action",
            str(report["final_action"]) == "WATCH",
            "WATCH candidates can be promoted after approval.",
            f"{report['final_action']} is not a WATCH promotion candidate.",
            label="Final action",
            observed=str(report["final_action"]),
            required="WATCH",
        ),
        _check(
            "conviction",
            conviction >= config.min_conviction,
            (
                f"conviction {conviction:.2f} meets paper promotion threshold "
                f"{config.min_conviction:.2f}."
            ),
            (
                f"conviction {conviction:.2f} is below "
                f"paper promotion threshold {config.min_conviction:.2f}."
            ),
            label="Conviction threshold",
            observed=f"{conviction:.2f}",
            required=f">= {config.min_conviction:.2f}",
        ),
        _check(
            "risk_flags",
            not risk_flags,
            "selection report has no promotion-blocking risk flags.",
            (
                "selection report has risk flags that require research-only "
                f"handling: {', '.join(risk_flags)}."
            ),
            label="Risk flags",
            observed=", ".join(risk_flags) if risk_flags else "none",
            required="none",
        ),
        _check(
            "policy_gates",
            not config.require_policy_pass
            or _policy_gates_have_no_blocks(report),
            "selection policy gates have no hard blocks; warnings require human caution acknowledgement.",
            _policy_gate_block_detail(report),
            label="Selection policy gates",
            observed=_policy_gate_observed(report),
            required="no BLOCK gates",
        ),
        _check(
            "source_count",
            source_count >= config.min_source_count,
            (
                f"source count {source_count} meets required "
                f"{config.min_source_count}."
            ),
            (
                f"source count {source_count} is below "
                f"required {config.min_source_count}."
            ),
            label="Source count",
            observed=str(source_count),
            required=f">= {config.min_source_count}",
        ),
        _check(
            "confirmed_signal_count",
            confirmed_signal_count >= config.min_confirmed_signals,
            (
                f"confirmed signal count {confirmed_signal_count} meets required "
                f"{config.min_confirmed_signals}."
            ),
            (
                "confirmed signal count "
                f"{confirmed_signal_count} is below "
                f"required {config.min_confirmed_signals}."
            ),
            label="Confirmed signals",
            observed=str(confirmed_signal_count),
            required=f">= {config.min_confirmed_signals}",
        ),
        _check(
            "freshness",
            freshness == "FRESH",
            "critical evidence is fresh.",
            f"critical evidence freshness is {freshness}.",
            label="Evidence freshness",
            observed=freshness,
            required="FRESH",
        ),
        _check(
            "position_conflict",
            ticker not in held_tickers,
            "no existing position blocks a new paper BUY preview.",
            "portfolio already has an open position in this ticker.",
            label="Position conflict",
            observed="existing position" if ticker in held_tickers else "none",
            required="none",
        ),
        _check(
            "open_order_conflict",
            ticker not in open_order_tickers,
            "no active broker order blocks this ticker.",
            "an active broker order already exists for this ticker.",
            label="Open order conflict",
            observed="active order" if ticker in open_order_tickers else "none",
            required="none",
        ),
        _approval_check(review_states.get(_report_key(report)), report),
    ]


def _check(
    name: str,
    passed: bool,
    pass_detail: str,
    fail_detail: str,
    *,
    label: str,
    observed: str,
    required: str,
) -> dict[str, object]:
    status = "PASS" if passed else "BLOCK"
    return {
        "name": name,
        "label": label,
        "status": status,
        "status_class": "pass" if status == "PASS" else "block",
        "detail": pass_detail if passed else fail_detail,
        "observed": observed,
        "required": required,
        "value_detail": _check_value_detail(observed=observed, required=required),
    }


def _apply_operator_manual_advance(
    checks: Sequence[Mapping[str, object]],
    operator_advance: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    if operator_advance is None:
        return [dict(check) for check in checks]
    reason = _operator_advance_reason(operator_advance)
    advanced_checks: list[dict[str, object]] = []
    for check in checks:
        row = dict(check)
        name = str(row.get("name") or "")
        if name in OPERATOR_OVERRIDABLE_CHECKS and row.get("status") != "PASS":
            original_detail = str(row.get("detail") or "blocked")
            row.update(
                {
                    "status": "PASS",
                    "status_class": "warn",
                    "detail": (
                        "Operator manual advance accepted this paper-promotion "
                        f"block: {original_detail} Reason: {reason}"
                    ),
                    "required": "operator acknowledgement",
                    "value_detail": (
                        f"{row.get('observed', 'blocked')} / operator acknowledged"
                    ),
                    "operator_advanced": True,
                    "original_status": check.get("status"),
                    "original_detail": original_detail,
                }
            )
        advanced_checks.append(row)
    return advanced_checks


def _manual_advance_can_help(
    checks: Sequence[Mapping[str, object]],
    _report: Mapping[str, object],
) -> bool:
    approval = next(
        (check for check in checks if str(check.get("name") or "") == "human_approval"),
        None,
    )
    if approval is None or approval.get("status") != "PASS":
        return False
    failed = [check for check in checks if check.get("status") != "PASS"]
    if not failed:
        return False
    return all(str(check.get("name") or "") in OPERATOR_OVERRIDABLE_CHECKS for check in failed)


def _manual_advance_blocked_reasons(
    checks: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(check.get("detail") or "")
        for check in checks
        if check.get("status") != "PASS"
        and str(check.get("name") or "") not in OPERATOR_OVERRIDABLE_CHECKS
    ]


def _valid_operator_manual_advance(
    event: Mapping[str, object] | None,
    report: Mapping[str, object],
) -> Mapping[str, object] | None:
    if event is None:
        return None
    if str(event.get("event_type")) != "OPERATOR_MANUAL_ADVANCE":
        return None
    if str(event.get("status")) not in {"PASSED", "RECORDED"}:
        return None
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    if str(payload.get("advance_type")) != OPERATOR_MANUAL_ADVANCE_TYPE:
        return None
    if str(payload.get("scope") or "paper_trade_promotion") != "paper_trade_promotion":
        return None
    if payload.get("paper_only") is not True or payload.get("acknowledged") is not True:
        return None
    if str(payload.get("as_of") or "") != str(report["as_of"]):
        return None
    if str(payload.get("selection_report_hash") or "") != selection_report_hash(report):
        return None
    return event


def _operator_advance_summary(
    event: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if event is None:
        return None
    payload = _mapping_field(event, "payload")
    return {
        "status": "accepted",
        "reason": _operator_advance_reason(event),
        "reviewed_by": str(payload.get("reviewed_by") or "local-user"),
        "event_time": str(event.get("event_time") or ""),
        "selection_report_hash": str(payload.get("selection_report_hash") or ""),
    }


def _operator_advance_reason(event: Mapping[str, object]) -> str:
    payload = _mapping_field(event, "payload")
    return str(payload.get("override_reason") or "operator acknowledged this block")


def _approval_check(
    review: Mapping[str, object] | None,
    report: Mapping[str, object],
) -> dict[str, object]:
    if review is None:
        return _check(
            "human_approval",
            False,
            "current research report is approved.",
            "current human research approval is missing.",
            label="Human research approval",
            observed="missing",
            required="current APPROVE with matching report hash",
        )
    payload = _mapping_field(review, "payload")
    decision = str(payload.get("review_decision", "")).upper()
    if decision != "APPROVE":
        return _check(
            "human_approval",
            False,
            "current research report is approved.",
            f"human review decision is {decision or 'not recorded'}, not APPROVE.",
            label="Human research approval",
            observed=decision or "not recorded",
            required="APPROVE",
        )
    approved_hash = str(payload.get("selection_report_hash") or "")
    if not approved_hash:
        return _check(
            "human_approval",
            False,
            "current research report is approved.",
            "human approval is not hash-bound to the current selection report.",
            label="Human research approval",
            observed="APPROVE without report hash",
            required="matching report hash",
        )
    hash_matches = approved_hash == selection_report_hash(report)
    return _check(
        "human_approval",
        hash_matches,
        "current research report is approved.",
        "human approval belongs to an older or different selection report.",
        label="Human research approval",
        observed="APPROVE with matching hash" if hash_matches else "APPROVE with stale hash",
        required="current APPROVE with matching report hash",
    )


def _approval_can_be_recorded(checks: Sequence[Mapping[str, object]]) -> bool:
    approval = next(
        (check for check in checks if str(check["name"]) == "human_approval"),
        None,
    )
    if approval is None or str(approval["status"]) == "PASS":
        return False
    detail = str(approval["detail"]).lower()
    return (
        "missing" in detail
        or "older or different" in detail
        or "not hash-bound" in detail
    )


def _policy_gates_have_no_blocks(report: Mapping[str, object]) -> bool:
    return all(
        str(gate["status"]) != "BLOCK"
        for gate in _mapping_list(report, "policy_gates")
    )


def _policy_gate_block_detail(report: Mapping[str, object]) -> str:
    blockers = [
        _policy_gate_label(gate)
        for gate in _mapping_list(report, "policy_gates")
        if str(gate.get("status")) == "BLOCK"
    ]
    if not blockers:
        return "one or more selection policy gates blocked promotion."
    return "selection policy gate blocked promotion: " + "; ".join(blockers) + "."


def _policy_gate_observed(report: Mapping[str, object]) -> str:
    gates = _mapping_list(report, "policy_gates")
    if not gates:
        return "no gates reported"
    blocked = [gate for gate in gates if str(gate.get("status")) == "BLOCK"]
    if blocked:
        return "BLOCK: " + ", ".join(str(gate.get("name") or "unnamed") for gate in blocked)
    warned = [gate for gate in gates if str(gate.get("status")) == "WARN"]
    if warned:
        return "WARN: " + ", ".join(str(gate.get("name") or "unnamed") for gate in warned)
    return "no hard blocks"


def _policy_gate_label(gate: Mapping[str, object]) -> str:
    name = str(gate.get("name") or "policy gate")
    reason = str(gate.get("reason") or "blocked")
    return f"{name}: {reason}"


def _policy_warning_notes(report: Mapping[str, object]) -> list[str]:
    notes: list[str] = []
    for gate in _mapping_list(report, "policy_gates"):
        if str(gate.get("status")) != "WARN":
            continue
        name = str(gate.get("name") or "policy gate")
        reason = str(gate.get("reason") or "warning recorded")
        notes.append(f"policy warning acknowledged: {name}: {reason}")
    return notes


def _check_value_detail(*, observed: str, required: str) -> str:
    if observed and required:
        return f"{observed} / required {required}"
    return observed or required


def _promotion_state_fields(
    state: str,
    *,
    promoted: bool = False,
) -> dict[str, object]:
    labels = {
        "eligible": (
            "Eligible",
            "pass",
            "This WATCH has approval, broker readiness, data quality, and policy support.",
            "The portfolio manager can promote this WATCH to a paper BUY preview.",
        ),
        "promoted": (
            "Promoted",
            "pass",
            "Research approval and promotion checks passed; this row is promoted to a paper BUY preview.",
            "Approve the hash-bound order intent, then submit only if the broker submit gate is open.",
        ),
        "promotion_limit_reached": (
            "Promotion Limit",
            "warn",
            "This WATCH passed promotion checks, but a higher-priority approved row used the per-cycle promotion slot.",
            "Review the higher-conviction promoted order first or raise the per-cycle promotion limit intentionally.",
        ),
        "awaiting_research_approval": (
            "Approval Needed",
            "warn",
            "This WATCH passes paper-promotion checks except current human research approval.",
            "Approve the current research report; the portfolio manager will recalculate risk and create a paper BUY order-intent preview if the state remains fresh.",
        ),
        "not_eligible": (
            "Research Only",
            "neutral",
            "This WATCH is not eligible for paper promotion under the current policy and data checks.",
            "Keep this candidate in research review until the blocked checks change.",
        ),
    }
    label, status_class, detail, next_step = labels[state]
    return {
        "state": state,
        "promoted": promoted,
        "status_label": label,
        "status_class": status_class,
        "detail": detail,
        "next_step": next_step,
    }


def _is_promotable_report(
    report: Mapping[str, object],
    *,
    review_states: Mapping[tuple[str, str, str], Mapping[str, object]],
    held_tickers: set[str],
    open_order_tickers: set[str],
    config: PaperTradePromotionConfig,
) -> bool:
    ticker = str(report["ticker"]).upper()
    clean_policy = not config.require_policy_pass or _policy_gates_have_no_blocks(report)
    data_quality = _mapping_field(_mapping_field(report, "evidence_pack"), "data_quality")
    review = review_states.get(_report_key(report))
    approved = _review_approves_report(review, report)
    return (
        ticker not in held_tickers
        and ticker not in open_order_tickers
        and str(report["final_action"]) == "WATCH"
        and _float_field(report, "final_conviction") >= config.min_conviction
        and not _string_list(report, "risk_flags")
        and clean_policy
        and _int_field(data_quality, "source_count") >= config.min_source_count
        and _int_field(data_quality, "confirmed_signal_count")
        >= config.min_confirmed_signals
        and str(data_quality["freshness"]) == "FRESH"
        and approved
    )


def _review_approves_report(
    review: Mapping[str, object] | None,
    report: Mapping[str, object],
) -> bool:
    if review is None:
        return False
    payload = _mapping_field(review, "payload")
    if str(payload.get("review_decision", "")).upper() != "APPROVE":
        return False
    approved_hash = str(payload.get("selection_report_hash") or "")
    return bool(approved_hash) and approved_hash == selection_report_hash(report)


def _promoted_report(
    report: Mapping[str, object],
    *,
    operator_advance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    promoted = dict(report)
    promoted["final_action"] = "BUY"
    if operator_advance is not None:
        promoted["policy_gates"] = _operator_advanced_policy_gates(report, operator_advance)
    promoted["trade_plan"] = {
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "position_size": None,
        "time_in_force": "DAY",
        "notes": [
            TRADE_PROMOTION_NOTE,
            TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG,
            TRADE_PROMOTION_APPROVAL_NOTE,
            *_policy_warning_notes(report),
            *_operator_advance_notes(operator_advance),
        ],
    }
    validate_contract("selection-report", promoted)
    return promoted


def _operator_advanced_policy_gates(
    report: Mapping[str, object],
    operator_advance: Mapping[str, object],
) -> list[dict[str, object]]:
    reason = _operator_advance_reason(operator_advance)
    rows: list[dict[str, object]] = []
    for gate in _mapping_list(report, "policy_gates"):
        row = dict(gate)
        if str(row.get("status")) == "BLOCK":
            original_reason = str(row.get("reason") or "blocked")
            row["status"] = "WARN"
            row["reason"] = (
                "Operator manual advance acknowledged this policy block for paper "
                f"trading. Original: {original_reason}. Reason: {reason}"
            )
        rows.append(row)
    return rows


def _operator_advance_notes(
    operator_advance: Mapping[str, object] | None,
) -> list[str]:
    if operator_advance is None:
        return []
    return [
        (
            "operator manual advance: paper-promotion blockers were acknowledged "
            f"for this exact selection report. Reason: {_operator_advance_reason(operator_advance)}"
        )
    ]


def _promotion_sort_key(report: Mapping[str, object]) -> tuple[float, str]:
    return (-_float_field(report, "final_conviction"), str(report["ticker"]))


def _indexed_promotion_sort_key(
    item: tuple[int, Mapping[str, object]],
) -> tuple[float, str]:
    _index, report = item
    return _promotion_sort_key(report)


def _report_key(report: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(report["cycle_id"]),
        str(report["ticker"]).upper(),
        str(report["as_of"]),
    )


def _held_tickers(positions: Sequence[Mapping[str, object]]) -> set[str]:
    return {
        str(position.get("ticker") or position.get("symbol") or "").upper()
        for position in positions
        if _optional_float(position.get("qty")) != 0
        or str(position.get("side", "")).upper() in {"LONG", "SHORT"}
    }


def _open_order_tickers(open_orders: Sequence[Mapping[str, object]]) -> set[str]:
    inactive_statuses = {"CANCELED", "EXPIRED", "FILLED", "REJECTED"}
    return {
        str(order.get("ticker") or order.get("symbol") or "").upper()
        for order in open_orders
        if str(order.get("status", "")).upper() not in inactive_statuses
    }


def _validated_report(report: Mapping[str, object]) -> dict[str, object]:
    validate_contract("selection-report", report)
    return dict(report)


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return value


def _mapping_list(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [
        item
        for item in _list_field(payload, key)
        if isinstance(item, Mapping)
    ]


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]


def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _optional_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0.0
    return float(value)


def _env_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def _env_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)
