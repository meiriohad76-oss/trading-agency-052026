from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from agency.api.health import runtime_data_source_status
from agency.app import create_app
from agency.dashboard import (
    candidate_detail_summary,
    candidate_rows,
    command_summary,
    final_selection_rows,
    policy_sections,
    source_status_rows,
    timeline_rows,
)
from agency.services import build_evidence_pack, build_final_selection, build_signal_result

HTTP_OK = 200
HTTP_NOT_FOUND = 404
EXPECTED_SOURCE_COUNT = 2
FULL_RELIABILITY_PERCENT = 100


def test_health_endpoint_reports_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok", "service": "trading-agency-v2"}


def test_dashboard_renders_status_overview() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == HTTP_OK
    assert "Command" in response.text
    assert "Paper trading" in response.text
    assert "Candidates" in response.text
    assert "Review data sources" in response.text
    assert "Degraded Sources" in response.text
    assert "No candidates yet" in response.text
    assert "SelectionReport" in response.text


def test_final_selection_page_renders_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/final-selection")

    assert response.status_code == HTTP_OK
    assert "Final Selection" in response.text
    assert "No final selection reports yet" in response.text
    assert "Read-only" in response.text


def test_risk_and_execution_pages_are_disabled() -> None:
    client = TestClient(create_app())

    risk_response = client.get("/risk")
    execution_response = client.get("/execution-preview")

    assert risk_response.status_code == HTTP_OK
    assert "Risk aggregation is read-only" in risk_response.text
    assert "No risk page action can approve an order" in risk_response.text
    assert execution_response.status_code == HTTP_OK
    assert "Execution preview is read-only" in execution_response.text
    assert "Submission disabled" in execution_response.text


def test_policy_page_is_read_only() -> None:
    client = TestClient(create_app())

    response = client.get("/policy")

    assert response.status_code == HTTP_OK
    assert "Portfolio policy is read-only" in response.text
    assert "Save disabled" in response.text
    assert "Audit Log" in response.text


def test_static_styles_are_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/styles.css")

    assert response.status_code == HTTP_OK
    assert "summary-band" in response.text
    assert "action-ribbon" in response.text


def test_candidate_detail_renders_audit_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/candidates/AAPL")

    assert response.status_code == HTTP_OK
    assert "Candidate Audit" in response.text
    assert "AAPL" in response.text
    assert "No lifecycle events yet" in response.text


def test_candidate_rows_summarize_selection_reports() -> None:
    rows = candidate_rows([_selection_report()])

    assert rows == [
        {
            "ticker": "AAPL",
            "action": "WATCH",
            "conviction_pct": 62,
            "gate_status": "WARN",
            "as_of": "2026-05-07T09:30:00Z",
            "risk_flag_count": 1,
        }
    ]


def test_command_summary_counts_runtime_rows() -> None:
    summary = command_summary(
        candidates=candidate_rows([_selection_report()]),
        data_sources=[_source_health("sec-edgar"), _degraded_source_health()],
        contracts=[{"name": "selection-report"}],
    )

    assert summary["candidate_count"] == 1
    assert summary["actionable_candidate_count"] == 1
    assert summary["degraded_source_count"] == 1
    assert summary["source_count"] == EXPECTED_SOURCE_COUNT
    assert summary["contract_count"] == 1


def test_source_status_rows_add_status_classes() -> None:
    rows = source_status_rows([_source_health("sec-edgar"), _degraded_source_health()])

    assert rows[0]["status_class"] == "pass"
    assert rows[0]["reliability_pct"] == FULL_RELIABILITY_PERCENT
    assert rows[1]["status_class"] == "warn"
    assert rows[1]["reliability_pct"] == 0


def test_final_selection_rows_follow_service_contract() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = final_selection_rows([report])

    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["action"] == "WATCH"
    assert rows[0]["deterministic_action"] == "WATCH"
    assert rows[0]["llm_action"] == "NO_REVIEW"
    assert rows[0]["confirmed_signal_count"] == 1
    assert rows[0]["policy_gates"][0]["status"] == "PASS"


def test_candidate_detail_summary_uses_latest_report() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])
    summary = candidate_detail_summary("AAPL", reports, [_lifecycle_event()])

    assert summary["report_count"] == 1
    assert summary["event_count"] == 1
    assert summary["latest_action"] == "WATCH"


def test_policy_sections_are_read_only_groups() -> None:
    sections = policy_sections()

    assert sections[0]["title"] == "Targets and Discipline"
    assert sections[-1]["title"] == "Permissions"


def test_timeline_rows_summarize_lifecycle_events() -> None:
    rows = timeline_rows([_lifecycle_event()])

    assert rows == [
        {
            "event_type": "DETERMINISTIC_ACTION",
            "event_time": "2026-05-07T09:31:00Z",
            "status": "ACTIONABLE",
            "reason": "quality_positive",
        }
    ]


def test_contracts_endpoint_lists_contracts() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts")

    assert response.status_code == HTTP_OK
    names = {item["name"] for item in response.json()}
    assert {"selection-report", "evidence-pack", "data-source-health"}.issubset(names)


def test_contract_schema_endpoint_returns_json_schema() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/selection-report")

    assert response.status_code == HTTP_OK
    assert response.json()["title"] == "SelectionReport"


def test_contract_schema_endpoint_rejects_unknown_contract() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/unknown")

    assert response.status_code == HTTP_NOT_FOUND


def test_data_source_status_endpoint_returns_valid_status_payload() -> None:
    client = TestClient(create_app())

    response = client.get("/status/data-sources")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload[0]["source"] == "bootstrap"
    assert payload[0]["status"] == "DEGRADED"


async def test_runtime_data_source_status_uses_repository_payloads() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        assert session == "fake-session"
        return [_source_health("sec-edgar")]

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "sec-edgar"
    assert payloads[0]["status"] == "HEALTHY"


async def test_runtime_data_source_status_falls_back_for_empty_repository() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        del session
        return []

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "bootstrap"


async def test_runtime_data_source_status_falls_back_for_missing_db() -> None:
    payloads = await runtime_data_source_status(session_provider=_raising_session_provider)

    assert payloads[0]["source"] == "bootstrap"


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _source_health(source: str) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": source,
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


def _degraded_source_health() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": "bootstrap",
        "source_tier": "MARKET_DATA",
        "status": "DEGRADED",
        "checked_at": "2026-05-07T09:30:00Z",
        "freshness": "UNAVAILABLE",
        "last_success_at": None,
        "observed_lag_seconds": None,
        "error_count": 0,
        "reliability_score": 0.0,
        "rate_limit_reset_at": None,
        "notes": ["runtime source monitors are not wired yet"],
    }


def _selection_report() -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "final_action": "WATCH",
        "final_conviction": 0.62,
        "as_of": "2026-05-07T09:30:00Z",
        "policy_gates": [{"name": "evidence_breadth", "status": "WARN", "reason": "one source"}],
        "risk_flags": ["news_breadth_low"],
    }


def _evidence_pack() -> dict[str, object]:
    return build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[
            build_signal_result(
                cycle_id="cycle-1",
                ticker="AAPL",
                as_of="2026-05-07T09:30:00Z",
                lane="fundamentals",
                score=0.7,
                provenance=_provenance(),
                confidence=0.9,
            )
        ],
    )


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


def _lifecycle_event() -> dict[str, object]:
    return {
        "event_type": "DETERMINISTIC_ACTION",
        "event_time": "2026-05-07T09:31:00Z",
        "status": "ACTIONABLE",
        "reason": "quality_positive",
    }
