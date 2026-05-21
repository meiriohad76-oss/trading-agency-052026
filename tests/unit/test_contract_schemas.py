from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from agency.contracts import validation as validation_module

SCHEMA_DIR = Path("schemas")
SCHEMA_NAMES = [
    "provenance.schema.json",
    "signal-result.schema.json",
    "evidence-pack.schema.json",
    "selection-report.schema.json",
    "data-source-health.schema.json",
    "candidate-lifecycle-event.schema.json",
    "risk-decision.schema.json",
    "agent-run.schema.json",
    "prompt-audit.schema.json",
    "execution-state.schema.json",
    "risk-snapshot.schema.json",
    "portfolio-snapshot.schema.json",
    "execution-preview.schema.json",
    "portfolio-monitor.schema.json",
    "learning-outcome.schema.json",
]


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    for schema in _schemas().values():
        Draft202012Validator.check_schema(schema)


def test_runtime_contract_validators_are_cached() -> None:
    first = validation_module._validator_for("execution-preview", SCHEMA_DIR)
    second = validation_module._validator_for("execution-preview", SCHEMA_DIR)

    assert first is second


def test_selection_report_validates_nested_evidence_pack() -> None:
    _validator("selection-report.schema.json").validate(_selection_report())


def test_data_source_health_validates_dashboard_status_payload() -> None:
    _validator("data-source-health.schema.json").validate(
        {
            "schema_version": "0.1.0",
            "source": "sec-edgar",
            "source_tier": "OFFICIAL_FILING",
            "status": "HEALTHY",
            "checked_at": "2026-05-07T09:30:00Z",
            "freshness": "FRESH",
            "last_success_at": "2026-05-07T09:29:00Z",
            "observed_lag_seconds": 60,
            "error_count": 0,
            "reliability_score": 1.0,
            "rate_limit_reset_at": None,
            "notes": [],
        }
    )


def test_candidate_lifecycle_event_validates_audit_payload() -> None:
    _validator("candidate-lifecycle-event.schema.json").validate(_candidate_lifecycle_event())
    _validator("candidate-lifecycle-event.schema.json").validate(_human_review_event())
    _validator("candidate-lifecycle-event.schema.json").validate(_order_approval_event())
    _validator("candidate-lifecycle-event.schema.json").validate(_operator_manual_advance_event())


def test_risk_decision_validates_runtime_payload() -> None:
    _validator("risk-decision.schema.json").validate(_risk_decision())


def test_runtime_audit_contracts_validate_payloads() -> None:
    _validator("agent-run.schema.json").validate(_agent_run())
    _validator("prompt-audit.schema.json").validate(_prompt_audit())
    _validator("execution-state.schema.json").validate(_execution_state())
    _validator("risk-snapshot.schema.json").validate(_risk_snapshot())
    _validator("portfolio-snapshot.schema.json").validate(_portfolio_snapshot())


def test_execution_preview_validates_no_submit_payload() -> None:
    _validator("execution-preview.schema.json").validate(_execution_preview())


def test_portfolio_monitor_validates_read_only_snapshot() -> None:
    _validator("portfolio-monitor.schema.json").validate(_portfolio_monitor())


def test_learning_outcome_validates_advisory_snapshot() -> None:
    _validator("learning-outcome.schema.json").validate(_learning_outcome())


def test_signal_result_rejects_unknown_fields() -> None:
    invalid = _signal_result()
    invalid["unexpected"] = True

    with pytest.raises(ValidationError):
        _validator("signal-result.schema.json").validate(invalid)


def test_signal_result_allows_safe_summary_field() -> None:
    signal = _signal_result()
    signal["summary"] = "Subscription article thesis: context only."

    _validator("signal-result.schema.json").validate(signal)


def _validator(schema_name: str) -> Draft202012Validator:
    schemas = _schemas()
    resources = [
        (str(schema["$id"]), Resource.from_contents(schema)) for schema in schemas.values()
    ]
    return Draft202012Validator(schemas[schema_name], registry=Registry().with_resources(resources))


def _schemas() -> dict[str, dict[str, object]]:
    return {
        name: json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        for name in SCHEMA_NAMES
    }


def _selection_report() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "final_action": "WATCH",
        "final_conviction": 0.62,
        "deterministic": _engine_decision(),
        "llm_review": {
            "action": "WATCH",
            "confidence": 0.55,
            "rationale": "Evidence is constructive but incomplete.",
            "supporting_factors": ["fundamentals_positive"],
            "concerns": ["news_breadth_low"],
        },
        "policy_gates": [{"name": "evidence_breadth", "status": "WARN", "reason": "one source"}],
        "risk_flags": [],
        "evidence_pack": _evidence_pack(),
        "trade_plan": {
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "position_size": 0,
            "time_in_force": None,
            "notes": ["watch only"],
        },
    }


def _evidence_pack() -> dict[str, object]:
    signal = _signal_result()
    context = copy.deepcopy(signal)
    context["actionability"] = "CONTEXT_ONLY"
    context["suppression_reason"] = None
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "actionable_signals": [signal],
        "context_signals": [context],
        "suppressed_signals": [],
        "data_quality": {
            "freshness": "FRESH",
            "source_count": 1,
            "confirmed_signal_count": 1,
            "inferred_signal_count": 0,
            "blockers": [],
        },
    }


def _signal_result() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "lane": "fundamentals",
        "score": 0.7,
        "direction": "BULLISH",
        "actionability": "ACTIONABLE",
        "source_tier": "OFFICIAL_FILING",
        "verification_level": "CONFIRMED",
        "freshness": "FRESH",
        "confidence": 0.9,
        "provenance": _provenance(),
        "reason_codes": ["quality_positive"],
        "suppression_reason": None,
    }


def _engine_decision() -> dict[str, object]:
    return {
        "action": "WATCH",
        "score": 0.4,
        "conviction": 0.62,
        "reason_codes": ["quality_positive"],
        "blockers": [],
    }


def _candidate_lifecycle_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "b" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "FINAL_ACTION",
        "event_time": "2026-05-07T09:31:00Z",
        "status": "RECORDED",
        "reason": "selection report persisted",
        "payload": {"final_action": "WATCH"},
    }


def _human_review_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "c" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "HUMAN_REVIEW",
        "event_time": "2026-05-07T10:00:00Z",
        "status": "PASSED",
        "reason": "paper review approved",
        "payload": {
            "review_decision": "APPROVE",
            "reviewed_by": "local-user",
            "paper_only": True,
            "as_of": "2026-05-07T09:30:00Z",
        },
    }


def _order_approval_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "d" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "ORDER_APPROVAL",
        "event_time": "2026-05-07T10:01:00Z",
        "status": "PASSED",
        "reason": "paper order intent approved",
        "payload": {
            "approval_type": "ORDER_APPROVAL",
            "reviewed_by": "local-user",
            "paper_only": True,
            "as_of": "2026-05-07T09:30:00Z",
            "order_intent_version": "0.1.0",
            "order_intent_hash": "a" * 64,
        },
    }


def _operator_manual_advance_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "e" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "OPERATOR_MANUAL_ADVANCE",
        "event_time": "2026-05-07T10:02:00Z",
        "status": "PASSED",
        "reason": "operator manual paper-promotion advance approved",
        "payload": {
            "advance_type": "PAPER_PROMOTION_OVERRIDE",
            "reviewed_by": "local-user",
            "paper_only": True,
            "acknowledged": True,
            "as_of": "2026-05-07T09:30:00Z",
            "selection_report_hash": "a" * 64,
            "selection_report_hash_version": "0.1.0",
            "override_reason": "Operator accepted the policy block for paper rehearsal.",
            "blocked_reason": "selection policy gate blocked: evidence_breadth",
        },
    }


def _risk_decision() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:32:00Z",
        "decision": "ALLOW",
        "final_action": "BUY",
        "final_conviction": 0.72,
        "position_size_pct": 10.0,
        "projected_gross_exposure_pct": 40.0,
        "checks": [{"name": "gross_exposure", "status": "PASS", "reason": "within cap"}],
        "reasons": ["AAPL passed v0 risk checks"],
        "risk_flags": [],
        "source_health": {"source_count": 1, "degraded_source_count": 0},
    }


def _agent_run() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "agent_name": "deterministic-selection",
        "status": "SUCCEEDED",
        "trigger": "MANUAL",
        "started_at": "2026-05-07T09:30:00Z",
        "finished_at": "2026-05-07T09:31:00Z",
        "payload": {"selection_count": 1},
    }


def _prompt_audit() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "prompt_id": "prompt-1",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "agent_name": "llm-review",
        "model": "gpt-test",
        "prompt_class": "candidate-review",
        "prompt_hash": "a" * 64,
        "created_at": "2026-05-07T09:31:00Z",
        "redaction_status": "NO_SECRETS",
        "payload": {"template": "candidate-review-v1"},
    }


def _execution_state() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "state_id": "state-1",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "execution_id": "exec-1",
        "state": "READY",
        "event_time": "2026-05-07T09:33:00Z",
        "reason": "paper preview ready",
        "payload": {"submit_enabled": False},
    }


def _risk_snapshot() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "snapshot_id": "risk-snap-1",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:32:00Z",
        "gross_exposure_pct": 30.0,
        "risk_level": "LOW",
        "payload": {"source_count": 1},
    }


def _portfolio_snapshot() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "snapshot_id": "portfolio-snap-1",
        "provider": "alpaca",
        "mode": "paper",
        "captured_at": "2026-05-07T09:34:00Z",
        "account_status": "ACTIVE",
        "equity": 100000.0,
        "cash": 99000.0,
        "buying_power": 198000.0,
        "portfolio_value": 100000.0,
        "position_count": 1,
        "open_order_count": 0,
        "gross_exposure_pct": 1.0,
        "payload": {"positions": []},
    }


def _execution_preview() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:33:00Z",
        "preview_state": "READY",
        "side": "BUY",
        "quantity": None,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "notional": None,
        "position_size_pct": 10.0,
        "time_in_force": "DAY",
        "risk_decision": "ALLOW",
        "order_intent_version": "0.1.0",
        "order_intent_hash": "a" * 64,
        "submit_enabled": False,
        "reasons": ["paper preview generated"],
    }


def _portfolio_monitor() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-07T09:34:00Z",
        "mode": "READ_ONLY",
        "positions": [],
        "summary": {
            "position_count": 0,
            "hold_count": 0,
            "review_count": 0,
            "close_candidate_count": 0,
            "equity": None,
            "cash": None,
            "buying_power": None,
            "gross_exposure_pct": None,
            "max_gross_exposure_pct": 25.0,
            "available_exposure_pct": None,
            "policy_compliance_state": "UNKNOWN",
            "policy_compliance_label": "Exposure unknown",
            "policy_compliance_class": "neutral",
            "take_profit_pct": 8.0,
            "stop_loss_pct": 4.0,
            "trailing_stop_pct": 3.0,
            "hourly_loss_alert_pct": 1.0,
            "hourly_return_pct": None,
            "hourly_pl": None,
            "hourly_reference_at": None,
            "hourly_current_value": None,
            "hourly_status": "UNKNOWN",
            "hourly_status_class": "neutral",
            "hourly_status_label": "Needs baseline",
            "hourly_reason": "Hourly performance needs a baseline.",
        },
    }


def _learning_outcome() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-07T09:35:00Z",
        "status": "PREMATURE",
        "sample_count": 0,
        "required_sample_count": 50,
        "message": "Sample size is below threshold.",
        "requirements": [
            {"name": "closed_trade_samples", "status": "WARN", "reason": "0 of 50"}
        ],
    }


def _provenance() -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": "CIK0000320193",
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
