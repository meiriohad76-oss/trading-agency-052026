from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from service_fixtures import provenance, source_health
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.services import (
    PaperTradePromotionConfig,
    PortfolioPolicy,
    RuntimeCycleResult,
    build_human_review_event,
    build_runtime_cycle,
    build_runtime_cycle_from_evidence_packs,
    build_runtime_cycle_from_payload,
    build_signal_result,
    persist_runtime_cycle,
    selection_report_hash,
)
from agency.services.selection_events import build_lifecycle_event

CYCLE_ID = "cycle-2026-05-07T143000Z"
AS_OF = "2026-05-07T14:30:00Z"
GENERATED_AT = "2026-05-07T14:31:00Z"
PROJECTED_EXPOSURE_PCT = 5.0
BROKER_EXPOSURE_PCT = 25.0


def test_runtime_cycle_builds_contract_valid_artifacts() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[
            _signal("AAPL", 0.7, "fundamentals"),
            _signal("AAPL", 0.7, "insider"),
            _signal("MSFT", -0.8, "fundamentals"),
        ],
    )

    assert [pack["ticker"] for pack in cycle.evidence_packs] == ["AAPL", "MSFT"]
    assert [report["final_action"] for report in cycle.selection_reports] == [
        "WATCH",
        "NO_TRADE",
    ]
    assert {preview["preview_state"] for preview in cycle.execution_previews} == {
        "BLOCKED",
        "DISABLED",
    }
    _assert_contracts(cycle)


def test_runtime_cycle_records_requested_tickers_without_signals() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[],
        tickers=["AAPL"],
    )

    assert cycle.evidence_packs[0]["ticker"] == "AAPL"
    assert cycle.selection_reports[0]["final_action"] == "NO_TRADE"
    assert cycle.risk_decisions[0]["decision"] == "BLOCK"
    assert cycle.execution_previews[0]["preview_state"] == "BLOCKED"


def test_runtime_cycle_risk_ignores_unused_stale_sources() -> None:
    unused_source = source_health(status="STALE", freshness="STALE")
    unused_source["source"] = "rss-news"
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health(), unused_source],
        signals=[_signal("AAPL", 0.7)],
    )

    assert "runtime source degradation present" not in cycle.risk_decisions[0]["reasons"]


def test_runtime_cycle_from_payload_accepts_json_compatible_inputs() -> None:
    cycle = build_runtime_cycle_from_payload(
        {
            "cycle_id": CYCLE_ID,
            "as_of": AS_OF,
            "generated_at": GENERATED_AT,
            "tickers": ["aapl"],
            "source_health": [source_health()],
            "signals": [_signal("AAPL", 0.7)],
            "current_gross_exposure_pct": 5.0,
        }
    )

    assert cycle.selection_reports[0]["ticker"] == "AAPL"
    assert cycle.risk_decisions[0]["projected_gross_exposure_pct"] == PROJECTED_EXPOSURE_PCT


def test_runtime_cycle_from_payload_threads_market_regime_into_risk_checks() -> None:
    cycle = build_runtime_cycle_from_payload(
        {
            "cycle_id": CYCLE_ID,
            "as_of": AS_OF,
            "generated_at": GENERATED_AT,
            "tickers": ["aapl"],
            "source_health": [source_health()],
            "signals": [_signal("AAPL", 0.7)],
            "market_regime_snapshot": {
                "market_backdrop": {"regime": "RISK_OFF", "vol_regime": "HIGH"},
                "per_stock_context": {
                    "AAPL": {
                        "sector": "XLK",
                        "sector_bias": "HEADWIND",
                        "sector_state": "DECLINING",
                        "conviction_boost": -0.05,
                    }
                },
            },
        }
    )

    check = _risk_check(cycle, "market_regime")
    assert check["status"] == "WARN"
    assert "RISK_OFF" in check["reason"]
    assert "XLK" in check["reason"]


def test_runtime_cycle_threads_broker_exposure_into_risk() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7), _signal("AAPL", 0.7, "insider")],
        current_gross_exposure_pct=BROKER_EXPOSURE_PCT,
        account={"equity": 1000.0},
        llm_reviews={
            "AAPL": {
                "action": "BUY",
                "confidence": 0.8,
                "rationale": "LLM promotes the paper setup.",
                "supporting_factors": ["two confirmed sources"],
                "concerns": [],
            }
        },
    )

    assert cycle.selection_reports[0]["final_action"] == "WATCH"
    assert cycle.risk_decisions[0]["projected_gross_exposure_pct"] == BROKER_EXPOSURE_PCT
    assert cycle.execution_previews[0]["preview_state"] == "DISABLED"


def test_runtime_cycle_promotes_approved_watch_for_paper_execution_only() -> None:
    base_cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.95), _signal("AAPL", 0.95, "insider")],
    )
    report = base_cycle.selection_reports[0]
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        event_time="2026-05-07T14:32:00Z",
        selection_report_hash=selection_report_hash(report),
    )

    cycle = build_runtime_cycle_from_evidence_packs(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        evidence_packs=base_cycle.evidence_packs,
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
        paper_trade_review_states={_review_key(review): review},
        paper_trade_broker_ready=True,
        paper_trade_promotion_config=PaperTradePromotionConfig(
            enabled=True,
            min_conviction=0.1,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert cycle.selection_reports[0]["final_action"] == "WATCH"
    assert cycle.risk_decisions[0]["final_action"] == "BUY"
    assert cycle.risk_decisions[0]["decision"] == "ALLOW"
    assert cycle.execution_previews[0]["preview_state"] == "READY"
    assert cycle.execution_previews[0]["side"] == "BUY"
    assert cycle.execution_previews[0]["notional"] == 1000.0


def test_runtime_cycle_preserves_provider_llm_lifecycle_error() -> None:
    llm_review = {
        "action": "NO_REVIEW",
        "confidence": 0.0,
        "rationale": "LLM review was requested, but OPENAI_API_KEY is not configured.",
        "supporting_factors": [],
        "concerns": ["missing_openai_api_key"],
    }
    llm_event = build_lifecycle_event(
        cycle_id=CYCLE_ID,
        ticker="AAPL",
        event_type="LLM_ACTION",
        event_time=GENERATED_AT,
        status="ERROR",
        reason="llm review missing api key",
        payload={
            "llm_review": llm_review,
            "deterministic_action": "WATCH",
        },
    )

    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7), _signal("AAPL", 0.7, "insider")],
        llm_reviews={"AAPL": llm_review},
        llm_lifecycle_events=[llm_event],
    )
    llm_events = [
        event
        for event in cycle.selection_lifecycle_events
        if event["event_type"] == "LLM_ACTION"
    ]

    assert llm_events[0]["status"] == "ERROR"
    assert llm_events[0]["reason"] == "llm review missing api key"


def test_runtime_cycle_rejects_stale_llm_lifecycle_event_cycle() -> None:
    event = build_lifecycle_event(
        cycle_id="older-cycle",
        ticker="AAPL",
        event_type="LLM_ACTION",
        event_time=GENERATED_AT,
        status="ERROR",
        reason="stale llm event",
        payload={"llm_review": {"action": "NO_REVIEW"}},
    )

    with pytest.raises(ValueError, match="cycle_id does not match"):
        build_runtime_cycle(
            cycle_id=CYCLE_ID,
            as_of=AS_OF,
            generated_at=GENERATED_AT,
            source_health=[source_health()],
            signals=[_signal("AAPL", 0.7)],
            llm_lifecycle_events=[event],
        )


def test_runtime_cycle_normalizes_raw_llm_review_payload() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7), _signal("AAPL", 0.7, "insider")],
        llm_reviews={
            "AAPL": {
                "action": "BUY",
                "confidence": 0.9,
                "rationale": "Provider bypass should not allow BUY.",
                "supporting_factors": [],
                "concerns": [],
            }
        },
    )

    review = cycle.selection_reports[0]["llm_review"]
    assert isinstance(review, dict)
    assert review["action"] == "NO_REVIEW"
    assert "unsupported_action:BUY" in review["concerns"]


async def test_persist_runtime_cycle_writes_persistent_artifacts_and_audit_events() -> None:
    writes: list[tuple[str, str]] = []

    async def source_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("source", str(payload["source"])))

    async def report_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("report", str(payload["ticker"])))

    async def risk_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("risk", str(payload["decision"])))

    async def lifecycle_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("event", str(payload["event_type"])))

    async def agent_run_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("agent-run", str(payload["trigger"])))

    async def risk_snapshot_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("risk-snapshot", str(payload["risk_level"])))

    async def execution_state_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("execution-state", str(payload["state"])))

    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7)],
    )

    persisted = await persist_runtime_cycle(
        _session(),
        cycle,
        source_writer=source_writer,
        report_writer=report_writer,
        risk_writer=risk_writer,
        lifecycle_writer=lifecycle_writer,
        agent_run_writer=agent_run_writer,
        risk_snapshot_writer=risk_snapshot_writer,
        execution_state_writer=execution_state_writer,
        audit_trigger="TEST",
    )

    assert persisted is cycle
    assert len([kind for kind, _value in writes if kind == "source"]) == 1
    assert len([kind for kind, _value in writes if kind == "report"]) == 1
    assert len([kind for kind, _value in writes if kind == "risk"]) == 1
    assert len([kind for kind, _value in writes if kind == "event"]) == len(
        cycle.all_lifecycle_events
    )
    assert len([kind for kind, _value in writes if kind == "agent-run"]) == 1
    assert len([kind for kind, _value in writes if kind == "risk-snapshot"]) == len(
        cycle.risk_decisions
    )
    assert len([kind for kind, _value in writes if kind == "execution-state"]) == len(
        cycle.execution_previews
    )


async def test_runtime_cycle_persists_llm_prompt_audits_with_run_id() -> None:
    writes: list[dict[str, object]] = []

    async def noop_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        assert payload

    async def prompt_audit_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(dict(payload))

    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7), _signal("AAPL", 0.7, "insider")],
        llm_reviews={
            "AAPL": {
                "action": "AGREE",
                "confidence": 0.8,
                "rationale": "LLM agrees with the deterministic watch decision.",
                "supporting_factors": ["two confirmed sources"],
                "concerns": [],
            }
        },
        llm_prompt_audits=[_prompt_audit()],
    )

    await persist_runtime_cycle(
        _session(),
        cycle,
        source_writer=noop_writer,
        report_writer=noop_writer,
        risk_writer=noop_writer,
        lifecycle_writer=noop_writer,
        agent_run_writer=noop_writer,
        risk_snapshot_writer=noop_writer,
        execution_state_writer=noop_writer,
        prompt_audit_writer=prompt_audit_writer,
        audit_trigger="TEST",
    )

    assert len(writes) == 1
    assert writes[0]["run_id"] == f"{CYCLE_ID}:test:runtime-cycle"
    assert writes[0]["payload"]["llm_action"] == "AGREE"


def _signal(ticker: str, score: float, lane: str = "fundamentals") -> dict[str, object]:
    return build_signal_result(
        cycle_id=CYCLE_ID,
        ticker=ticker,
        as_of=AS_OF,
        lane=lane,
        score=score,
        provenance=provenance(source_id=f"{ticker}-{lane}"),
        confidence=0.9,
    )


def _assert_contracts(cycle: RuntimeCycleResult) -> None:
    for source in cycle.source_health:
        validate_contract("data-source-health", source)
    for pack in cycle.evidence_packs:
        validate_contract("evidence-pack", pack)
    for report in cycle.selection_reports:
        validate_contract("selection-report", report)
    for decision in cycle.risk_decisions:
        validate_contract("risk-decision", decision)
    for preview in cycle.execution_previews:
        validate_contract("execution-preview", preview)
    for event in cycle.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)


def _risk_check(cycle: RuntimeCycleResult, name: str) -> dict[str, str]:
    checks = cycle.risk_decisions[0]["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        if check.get("name") == name:
            return {str(key): str(value) for key, value in check.items()}
    raise AssertionError(f"missing risk check {name}")


def _review_key(event: Mapping[str, object]) -> tuple[str, str, str]:
    payload = event["payload"]
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    return (
        str(event["cycle_id"]),
        str(event["ticker"]).upper(),
        str(payload["as_of"]),
    )


def _session() -> AsyncSession:
    return cast(AsyncSession, _SESSION)


_SESSION = object()


def _prompt_audit() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "prompt_id": "prompt-llm-aapl",
        "run_id": None,
        "cycle_id": CYCLE_ID,
        "agent_name": "llm-review",
        "model": "gpt-test",
        "prompt_class": "candidate-review-v1",
        "prompt_hash": "c" * 64,
        "created_at": GENERATED_AT,
        "redaction_status": "NO_SECRETS",
        "payload": {
            "ticker": "AAPL",
            "response_status": "succeeded",
            "llm_action": "AGREE",
            "llm_confidence": 0.8,
            "llm_rationale": "LLM agrees with the deterministic watch decision.",
        },
    }
