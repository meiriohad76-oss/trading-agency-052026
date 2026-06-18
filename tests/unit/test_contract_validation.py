from __future__ import annotations

import copy
from pathlib import Path

import pytest

import agency.contracts.validation as validation_module
from agency.contracts import (
    ContractValidationError,
    is_valid_contract,
    load_contract_schema,
    validate_contract,
)


def test_validate_contract_accepts_nested_selection_report() -> None:
    validate_contract("selection-report", _selection_report())


def test_validate_contract_accepts_candidate_lifecycle_event() -> None:
    validate_contract("candidate-lifecycle-event", _candidate_lifecycle_event())


def test_validate_contract_accepts_risk_decision() -> None:
    validate_contract("risk-decision", _risk_decision())


def test_validate_contract_accepts_runtime_audit_payloads() -> None:
    validate_contract("agent-run", _agent_run())
    validate_contract("prompt-audit", _prompt_audit())
    validate_contract("execution-state", _execution_state())
    validate_contract("risk-snapshot", _risk_snapshot())


def test_validate_contract_reports_payload_path() -> None:
    payload = _source_health()
    payload["status"] = "BROKEN"

    with pytest.raises(ContractValidationError, match="at status"):
        validate_contract("data-source-health", payload)


def test_is_valid_contract_returns_false_for_invalid_payload() -> None:
    payload = _signal_result()
    payload["unexpected"] = True

    assert not is_valid_contract("signal-result", payload)


def test_load_contract_schema_returns_schema_by_name() -> None:
    schema = load_contract_schema("risk-decision")

    assert schema["title"] == "RiskDecision"
    assert schema["x-version"] == "0.1.0"


def test_schema_dir_falls_back_to_runtime_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_source_tree = tmp_path / "installed" / "schemas"
    runtime_schema_dir = tmp_path / "runtime" / "schemas"
    runtime_schema_dir.mkdir(parents=True)

    monkeypatch.setattr(
        validation_module,
        "__file__",
        str(
            tmp_path
            / "installed"
            / "site-packages"
            / "agency"
            / "contracts"
            / "validation.py"
        ),
    )
    monkeypatch.setattr(
        validation_module.Path,
        "cwd",
        staticmethod(lambda: tmp_path / "runtime"),
    )

    assert validation_module._resolve_schema_dir(None) == runtime_schema_dir
    assert validation_module._resolve_schema_dir(missing_source_tree) == missing_source_tree


def _source_health() -> dict[str, object]:
    return {
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


def _candidate_lifecycle_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "c" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "FINAL_ACTION",
        "event_time": "2026-05-07T09:31:00Z",
        "status": "RECORDED",
        "reason": "selection report persisted",
        "payload": {"final_action": "WATCH"},
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
        "agent_name": "runtime-cycle",
        "status": "SUCCEEDED",
        "trigger": "MANUAL",
        "started_at": "2026-05-07T09:30:00Z",
        "finished_at": "2026-05-07T09:31:00Z",
        "payload": {"candidate_count": 1},
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
        "prompt_hash": "b" * 64,
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
        "snapshot_id": "snap-1",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:32:00Z",
        "gross_exposure_pct": 40.0,
        "risk_level": "LOW",
        "payload": {"degraded_source_count": 0},
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
            "rationale": "Constructive but incomplete.",
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
        },
    }


def _evidence_pack() -> dict[str, object]:
    signal = _signal_result()
    context = copy.deepcopy(signal)
    context["actionability"] = "CONTEXT_ONLY"
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
