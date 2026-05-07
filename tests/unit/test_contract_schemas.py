from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

SCHEMA_DIR = Path("schemas")
SCHEMA_NAMES = [
    "provenance.schema.json",
    "signal-result.schema.json",
    "evidence-pack.schema.json",
    "selection-report.schema.json",
    "data-source-health.schema.json",
]


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    for schema in _schemas().values():
        Draft202012Validator.check_schema(schema)


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


def test_signal_result_rejects_unknown_fields() -> None:
    invalid = _signal_result()
    invalid["unexpected"] = True

    with pytest.raises(ValidationError):
        _validator("signal-result.schema.json").validate(invalid)


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
