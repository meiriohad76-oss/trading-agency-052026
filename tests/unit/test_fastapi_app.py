from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.dashboard as dashboard_module
from agency.api.health import runtime_data_source_status
from agency.app import create_app
from agency.dashboard import (
    candidate_detail_summary,
    candidate_review_summary,
    candidate_rows,
    command_summary,
    data_refresh_progress_view,
    execution_preview_rows,
    final_selection_rows,
    human_review_events_for_reports,
    learning_summary,
    live_config_view,
    paper_review_progress,
    paper_review_queue,
    policy_sections,
    portfolio_monitor_summary,
    readiness_view,
    risk_decision_rows,
    risk_summary,
    source_status_rows,
    timeline_rows,
)
from agency.services import (
    build_evidence_pack,
    build_execution_preview,
    build_final_selection,
    build_learning_outcome,
    build_portfolio_monitor,
    build_risk_decision,
    build_signal_result,
)

HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_SEE_OTHER = 303
EXPECTED_SOURCE_COUNT = 2
EXPECTED_CONFIRMED_SIGNAL_COUNT = 2
FULL_RELIABILITY_PERCENT = 100
EXPECTED_TIMELINE_LIMIT = 50
EXPECTED_REVIEW_QUEUE_COUNT = 4
EXPECTED_REVIEWED_COUNT = 3


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
    assert "Live Readiness" in response.text
    assert "Live Config" in response.text
    assert "Review Queue" in response.text
    assert "Review config" in response.text
    assert "Data Loading" in response.text
    assert "Review data sources" in response.text
    assert "Degraded Sources" in response.text
    assert "No reviewable paper candidates" in response.text
    assert "No candidates yet" in response.text
    assert "SelectionReport" in response.text


def test_final_selection_page_renders_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/final-selection")

    assert response.status_code == HTTP_OK
    assert "Final Selection" in response.text
    assert "No final selection reports yet" in response.text
    assert "Read-only" in response.text


def test_risk_and_execution_pages_render_runtime_states() -> None:
    client = TestClient(create_app())

    risk_response = client.get("/risk")
    execution_response = client.get("/execution-preview")

    assert risk_response.status_code == HTTP_OK
    assert "Risk Decisions" in risk_response.text
    assert "No risk decisions yet" in risk_response.text
    assert execution_response.status_code == HTTP_OK
    assert "No execution previews yet" in execution_response.text
    assert "Submission disabled" in execution_response.text


def test_portfolio_and_learning_pages_render_empty_states() -> None:
    client = TestClient(create_app())

    portfolio_response = client.get("/portfolio-monitor")
    learning_response = client.get("/learning")

    assert portfolio_response.status_code == HTTP_OK
    assert "Portfolio Monitor" in portfolio_response.text
    assert "No portfolio positions are tracked yet" in portfolio_response.text
    assert learning_response.status_code == HTTP_OK
    assert "Learning Requirements" in learning_response.text
    assert "No auto-tuning" in learning_response.text


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


def test_static_progress_script_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/data-refresh-progress.js")

    assert response.status_code == HTTP_OK
    assert "data-progress-panel" in response.text


def test_candidate_review_post_records_human_review(monkeypatch: MonkeyPatch) -> None:
    writes: list[dict[str, object]] = []
    session = _FakeSession()

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_persist(session_arg: object, **kwargs: object) -> dict[str, object]:
        assert session_arg is session
        writes.append(dict(kwargs))
        return {"event_type": "HUMAN_REVIEW"}

    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(
        dashboard_module,
        "build_and_persist_human_review_event",
        fake_persist,
    )
    client = TestClient(create_app())

    response = client.post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/candidates/AAPL"
    assert session.committed is True
    assert writes == [
        {
            "cycle_id": "cycle-1",
            "ticker": "aapl",
            "as_of": "2026-05-07T09:30:00Z",
            "decision": "APPROVE",
        }
    ]


def test_candidate_detail_renders_audit_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/candidates/AAPL")

    assert response.status_code == HTTP_OK
    assert "Candidate Audit" in response.text
    assert "AAPL" in response.text
    assert "Paper Review" in response.text
    assert "No selection report available for review" in response.text
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
    assert summary["headline"] == "Runtime online. 1 actionable candidate across 1 report."


def test_source_status_rows_add_status_classes() -> None:
    rows = source_status_rows([_source_health("sec-edgar"), _degraded_source_health()])

    assert rows[0]["status_class"] == "pass"
    assert rows[0]["reliability_pct"] == FULL_RELIABILITY_PERCENT
    assert rows[1]["status_class"] == "warn"
    assert rows[1]["reliability_pct"] == 0


def test_readiness_view_adds_status_classes() -> None:
    view = readiness_view(
        {
            "ready": False,
            "verdict": "context_only_source_health",
            "blockers": [
                {
                    "kind": "source_health",
                    "item": "activity-alerts",
                    "reason": "UNAVAILABLE",
                }
            ],
        }
    )

    assert view["verdict_label"] == "Context Only Source Health"
    assert view["status_class"] == "warn"
    assert view["blocker_rows"] == [
        {
            "kind": "Source Health",
            "item": "activity-alerts",
            "reason": "UNAVAILABLE",
            "status_class": "warn",
        }
    ]


def test_data_refresh_progress_view_adds_width_style() -> None:
    view = data_refresh_progress_view(
        {
            "percent_complete": 42,
            "state": "running",
            "status_label": "Loading",
            "status_class": "warn",
        }
    )

    assert view["progress_style"] == "width: 42%"


def test_live_config_view_exposes_check_rows() -> None:
    view = live_config_view(
        {
            "state": "blocked",
            "checks": [{"label": "Market data", "status": "BLOCK"}],
        }
    )

    assert view["check_rows"] == [{"label": "Market data", "status": "BLOCK"}]


def test_final_selection_rows_follow_service_contract() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = final_selection_rows([report])

    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["action"] == "WATCH"
    assert rows[0]["deterministic_action"] == "WATCH"
    assert rows[0]["llm_action"] == "NO_REVIEW"
    assert rows[0]["confirmed_signal_count"] == EXPECTED_CONFIRMED_SIGNAL_COUNT
    assert rows[0]["policy_gates"][0]["status"] == "PASS"


def test_risk_decision_rows_summarize_risk_contract() -> None:
    decision = _risk_decision()

    rows = risk_decision_rows([decision])
    summary = risk_summary(rows, [_source_health("sec-edgar")])

    assert rows[0]["cycle_id"] == "cycle-1"
    assert rows[0]["decision"] == "ALLOW"
    assert rows[0]["decision_class"] == "pass"
    assert summary["allow_count"] == 1


def test_paper_review_queue_pairs_latest_cycle_with_risk_decision() -> None:
    report = build_final_selection(_evidence_pack()).selection_report
    decision = build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision

    rows = paper_review_queue([report], [decision], {"cycle_id": "cycle-1"})

    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["review_state"] == "Ready"
    assert rows[0]["risk_decision"] == "WARN"
    assert rows[0]["human_review_decision"] == "Pending"
    assert rows[0]["human_review_class"] == "neutral"
    assert rows[0]["candidate_href"] == "/candidates/AAPL"
    assert "decision=APPROVE" in str(rows[0]["approve_review_action"])
    assert rows[0]["source_count"] == EXPECTED_SOURCE_COUNT
    assert rows[0]["confirmed_signal_count"] == EXPECTED_CONFIRMED_SIGNAL_COUNT


def test_paper_review_queue_shows_latest_human_review_state() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = paper_review_queue(
        [report],
        [],
        {"cycle_id": "cycle-1"},
        review_events=[_human_review_event()],
    )

    assert rows[0]["human_review_decision"] == "Defer"
    assert rows[0]["human_review_class"] == "warn"
    assert rows[0]["human_review_reason"] == "paper review deferred"


def test_paper_review_progress_counts_review_states() -> None:
    progress = paper_review_progress(
        [
            {"human_review_decision": "Pending"},
            {"human_review_decision": "Approve"},
            {"human_review_decision": "Defer"},
            {"human_review_decision": "Reject"},
        ]
    )

    assert progress["total_count"] == EXPECTED_REVIEW_QUEUE_COUNT
    assert progress["reviewed_count"] == EXPECTED_REVIEWED_COUNT
    assert progress["pending_count"] == 1
    assert progress["approve_count"] == 1
    assert progress["defer_count"] == 1
    assert progress["reject_count"] == 1
    assert progress["reviewed_label"] == "3/4"
    assert progress["status_label"] == "1 Pending"
    assert progress["status_class"] == "warn"


def test_paper_review_progress_reports_complete_state() -> None:
    progress = paper_review_progress(
        [
            {"human_review_decision": "Approve"},
            {"human_review_decision": "Defer"},
        ]
    )

    assert progress["reviewed_label"] == "2/2"
    assert progress["status_label"] == "Review Complete"
    assert progress["status_class"] == "pass"


async def test_human_review_events_for_reports_filters_latest_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    async def fake_timeline(
        *,
        ticker: str,
        cycle_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        assert ticker == "AAPL"
        assert cycle_id == "cycle-1"
        assert limit == EXPECTED_TIMELINE_LIMIT
        return [_human_review_event(), _lifecycle_event()]

    monkeypatch.setattr(dashboard_module, "runtime_candidate_timeline", fake_timeline)

    events = await human_review_events_for_reports([report], {"cycle_id": "cycle-1"})

    assert events == [_human_review_event()]


def test_execution_preview_rows_summarize_preview_contract() -> None:
    preview = build_execution_preview(_risk_decision()).preview

    rows = execution_preview_rows([preview])

    assert rows[0]["preview_state"] == "READY"
    assert rows[0]["state_class"] == "pass"
    assert rows[0]["side"] == "BUY"


def test_portfolio_and_learning_summaries_use_contract_payloads() -> None:
    portfolio = build_portfolio_monitor([], generated_at="2026-05-07T09:34:00Z")
    learning = build_learning_outcome(generated_at="2026-05-07T09:35:00Z")

    assert portfolio_monitor_summary(portfolio)["position_count"] == 0
    assert learning_summary(learning)["status"] == "PREMATURE"


def test_candidate_detail_summary_uses_latest_report() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])
    summary = candidate_detail_summary("AAPL", reports, [_lifecycle_event()])

    assert summary["report_count"] == 1
    assert summary["event_count"] == 1
    assert summary["latest_action"] == "WATCH"


def test_candidate_review_summary_uses_latest_human_review_event() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])

    review = candidate_review_summary(reports, [_human_review_event()])

    assert review["can_record"] is True
    assert review["decision"] == "Defer"
    assert review["status_class"] == "warn"
    assert review["reason"] == "paper review deferred"
    assert "decision=APPROVE" in str(review["approve_action"])
    assert "decision=DEFER" in str(review["defer_action"])
    assert "decision=REJECT" in str(review["reject_action"])


def test_candidate_review_summary_handles_missing_report() -> None:
    review = candidate_review_summary([], [])

    assert review["can_record"] is False
    assert review["decision"] == "No Report"
    assert review["status_class"] == "neutral"


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
    assert {
        "selection-report",
        "evidence-pack",
        "data-source-health",
        "risk-decision",
        "execution-preview",
    }.issubset(names)


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


def test_live_readiness_status_endpoint_returns_gate() -> None:
    client = TestClient(create_app())

    response = client.get("/status/live-readiness")

    assert response.status_code == HTTP_OK
    assert response.json()["ready"] is False
    assert "verdict" in response.json()


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


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


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
                provenance=_provenance("fundamentals"),
                confidence=0.9,
            ),
            build_signal_result(
                cycle_id="cycle-1",
                ticker="AAPL",
                as_of="2026-05-07T09:30:00Z",
                lane="insider",
                score=0.7,
                provenance=_provenance("insider"),
                confidence=0.9,
            )
        ],
    )


def _risk_decision() -> dict[str, object]:
    report = build_final_selection(_evidence_pack()).selection_report
    report["final_action"] = "BUY"
    return build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision


def _provenance(source_id: str) -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": source_id,
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


def _human_review_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "d" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "HUMAN_REVIEW",
        "event_time": "2026-05-07T10:00:00Z",
        "status": "WARN",
        "reason": "paper review deferred",
        "payload": {
            "review_decision": "DEFER",
            "reviewed_by": "local-user",
            "paper_only": True,
            "as_of": "2026-05-07T09:30:00Z",
        },
    }
