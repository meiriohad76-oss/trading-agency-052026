from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.dashboard as dashboard_module
import agency.views.candidates as candidates_view
import agency.views.cockpit as cockpit_view
import agency.views.command as command_view
import agency.views.execution as execution_view
import agency.views.portfolio as portfolio_view
from agency.app import create_app
from agency.views.cockpit import _scrub_secrets


def test_cockpit_route_timeout_budget_fits_first_byte_gate() -> None:
    assert cockpit_view.DEFAULT_ROUTE_CONTEXT_TIMEOUT_SECONDS < 12.0
    assert cockpit_view.DEFAULT_ROUTE_CONTEXT_TIMEOUT_SECONDS > 0.0


def _context() -> dict[str, object]:
    return {
        "cycle": {"id": "cycle-route-test", "mode": "PAPER"},
        "market": {"regime": "balanced"},
        "engines": [{"name": "Runtime", "state": "live", "age": "just checked"}],
        "funnel": {"final": 1, "actionable": 1},
        "candidates": [
            {
                "ticker": "ROUT",
                "final_conviction": 0.74,
                "status": "approved",
                "actionable": True,
                "evidence": [{"tier": "confirmed", "text": "Real route fixture evidence."}],
            }
        ],
        "positions": [],
        "account": {"buying_power": 1000.0},
        "sectors": [],
        "sources": [],
        "universe_blocked": [],
        "signals": [],
        "audit_lifecycle": {"traces": {}},
        "policy": {
            "mode": "paper",
            "apply_label": "Apply next cycle",
            "deployed_values": {"min_final_conviction": 0.62},
            "staged_values": {"min_final_conviction": 0.62},
            "dangerous_flags": {
                "live_trading": {
                    "locked": True,
                    "value": "locked off",
                    "risk": "Live trading cannot be enabled from the cockpit.",
                }
            },
        },
        "monitor_events": [],
        "monitor": {"live": False, "label": "Monitor updates not observed", "last_update": "not reported"},
        "data_health": {
            "page_label": "Cockpit",
            "status_class": "pass",
            "status_label": "Ready",
            "headline": "Displayed data is ready for review.",
            "tooltip": "Live monitor proof is current.",
            "overall_percent": 100,
            "progress_style": "width: 100%",
            "meaning": "The cockpit is using current production data.",
            "recommended_action": "Continue to candidate review.",
            "primary_blocker_detail": "No blocking issue.",
            "action_buttons": [],
            "summary_items": [],
            "detail": "Cockpit data health is verified.",
            "monitor_live": True,
            "monitor_label": "Live Health Monitor",
            "visible_row_count": 1,
            "hidden_row_count": 0,
            "diagnostics_items": [],
            "rows": [
                {
                    "kind": "Market data",
                    "name": "Massive trade prints",
                    "status_class": "pass",
                    "status_label": "Ready",
                    "tooltip": "Coverage, freshness, and last update are verified.",
                    "coverage_label": "2/2 tickers",
                    "freshness_label": "Latest session",
                    "last_update": "2026-05-22 19:12 UTC",
                    "why_it_matters": "Trade prints feed the market-flow signals.",
                    "blocking_reason": "No blocking issue.",
                    "recommended_action": "No refresh needed.",
                    "diagnostic_detail": "Live lane proof is current.",
                    "detail": "Live lane proof is current.",
                }
            ],
        },
        "data_state": {
            "status_label": "Ready",
            "status_class": "pass",
            "headline": "Review ready; Paper execution gated.",
            "overall_percent": 100,
            "critical_lane_percent": 100,
            "active_universe_count": 168,
            "active_universe_label": "168 active-universe tickers",
            "review": {"ready": True, "label": "Review ready", "status_class": "pass"},
            "paper": {"ready": False, "label": "Paper execution gated", "status_class": "warn"},
            "top_gaps": [],
            "lane_rows": [],
            "as_of_label": "2026-05-22",
            "proof_label": "2026-05-22 19:12 UTC",
        },
        "preferences": {"color_preset": "amber", "theme": "accent", "density": "full"},
        "qa_scenarios_enabled": False,
        "qa_scenarios": [],
        "scenario": {"state": "normal", "headline": "1 trade ready."},
    }


def _client(monkeypatch: MonkeyPatch) -> TestClient:
    async def fake_cockpit_context(**_kwargs: object) -> dict[str, object]:
        return _context()

    monkeypatch.setattr(dashboard_module, "cockpit_context", fake_cockpit_context)
    monkeypatch.setattr(dashboard_module, "cached_cockpit_context", fake_cockpit_context)
    monkeypatch.setattr(
        dashboard_module,
        "cached_cockpit_context_with_timeout",
        fake_cockpit_context,
    )
    cockpit_view._cockpit_context_cache.clear()
    cockpit_view._cockpit_context_inflight.clear()
    return TestClient(create_app())


def test_cockpit_route_renders(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/cockpit")

    assert response.status_code == 200
    assert "Today&#39;s Cockpit" in response.text or "Today&apos;s Cockpit" in response.text
    assert 'data-cockpit-ready="true"' not in response.text
    assert 'data-ux-feature="rich-ticker-detail"' in response.text
    assert "1 trade ready" in response.text
    assert "ROUT" in response.text


def test_cockpit_route_uses_default_cache_key_when_qa_is_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    async def fake_cockpit_context(**kwargs: object) -> dict[str, object]:
        captured_kwargs.update(kwargs)
        return _context()

    monkeypatch.delenv("AGENCY_COCKPIT_QA_SCENARIOS", raising=False)
    monkeypatch.setattr(
        dashboard_module,
        "cached_cockpit_context_with_timeout",
        fake_cockpit_context,
    )
    cockpit_view._cockpit_context_cache.clear()
    cockpit_view._cockpit_context_inflight.clear()
    client = TestClient(create_app())

    response = client.get("/cockpit?scenario=outage")

    assert response.status_code == 200
    assert captured_kwargs == {
        "qa_scenario": None,
        "qa_scenarios_enabled": None,
    }


async def test_cockpit_context_timeout_returns_conservative_same_shape_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    async def slow_cockpit_context(**_kwargs: object) -> dict[str, object]:
        await asyncio.sleep(1.0)
        return _context()

    monkeypatch.setattr(cockpit_view, "cached_cockpit_context", slow_cockpit_context)

    context = await cockpit_view.cached_cockpit_context_with_timeout(timeout_seconds=0.01)

    assert context["cockpit_context_freshness"]["status_label"] == "Cockpit shell loading"  # type: ignore[index]
    assert context["data_state"]["review"]["ready"] is False  # type: ignore[index]
    assert context["data_state"]["paper"]["ready"] is False  # type: ignore[index]
    assert context["status_delayed"] is True
    assert context["scenario"]["state"] == "status-delayed"  # type: ignore[index]
    assert "still loading" in str(context["scenario"]["headline"]).lower()  # type: ignore[index]
    assert "not a no-candidate verdict" in str(context["scenario"]["detail"]).lower()  # type: ignore[index]


async def test_cockpit_context_timeout_does_not_cancel_warming_context(
    monkeypatch: MonkeyPatch,
) -> None:
    completed = asyncio.Event()
    cancelled = False

    async def slow_cockpit_context(**_kwargs: object) -> dict[str, object]:
        nonlocal cancelled
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancelled = True
            raise
        completed.set()
        return _context()

    monkeypatch.setattr(cockpit_view, "cached_cockpit_context", slow_cockpit_context)

    context = await cockpit_view.cached_cockpit_context_with_timeout(timeout_seconds=0.01)
    await asyncio.wait_for(completed.wait(), timeout=0.5)

    assert context["cockpit_context_freshness"]["status_label"] == "Cockpit shell loading"  # type: ignore[index]
    assert cancelled is False


def test_cockpit_status_delayed_context_is_not_cacheable_universe_proof() -> None:
    context = cockpit_view.cockpit_status_delayed_context(timeout_seconds=0.01)

    assert context["status_delayed"] is True
    assert context["scenario"]["state"] == "status-delayed"  # type: ignore[index]
    assert cockpit_view._cockpit_context_has_universe_proof(context) is False


def test_cockpit_scenario_does_not_hide_review_ready_state_behind_delay() -> None:
    context = {
        "status_delayed": True,
        "engines": [],
        "candidates": [],
        "data_state": {
            "review": {"ready": True, "label": "Review ready"},
            "paper": {"ready": False, "label": "Paper execution gated"},
            "top_gaps": [],
        },
    }

    scenario = cockpit_view._scenario_from_context(context, {})

    assert scenario["state"] == "no-actionable"
    assert "still loading" not in str(scenario["headline"]).lower()


def test_root_route_redirects_to_cockpit_without_legacy_context(monkeypatch: MonkeyPatch) -> None:
    async def fail_command_context() -> dict[str, object]:
        raise AssertionError("root should not build the legacy command dashboard")

    async def fail_execution_context() -> dict[str, object]:
        raise AssertionError("root should not build the legacy execution dashboard")

    monkeypatch.setattr(dashboard_module, "_command_dashboard_route_context", fail_command_context)
    monkeypatch.setattr(dashboard_module, "_execution_preview_route_base_context", fail_execution_context)
    client = TestClient(create_app())

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/cockpit"


def test_root_cockpit_exposes_displayed_data_health(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/cockpit")

    assert response.status_code == 200
    assert 'class="cockpit-data-state-strip"' in response.text
    assert "Session Readiness" in response.text
    assert "Review data sources" in response.text
    assert "Lane State Board" in response.text
    assert "Latest proof/as-of" in response.text


def test_cockpit_payload_scrubber_removes_common_secret_aliases() -> None:
    payload = {
        "token": "bearer-secret",
        "access_token": "access-secret",
        "refreshToken": "refresh-secret",
        "Authorization": "Bearer secret",
        "credentials": {"username": "paper", "password": "hidden"},
        "private_key": "key-secret",
        "certificate": "cert-secret",
        "author": "research desk",
        "visible": [{"ticker": "AAPL"}],
    }

    scrubbed = _scrub_secrets(payload)

    assert scrubbed == {"author": "research desk", "visible": [{"ticker": "AAPL"}]}


def test_cockpit_is_primary_operating_entrypoint(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/cockpit")

    assert response.status_code == 200
    assert '<a class="brand" href="/cockpit">' in response.text
    nav = response.text.split('<nav class="nav-list">', 1)[1].split("</nav>", 1)[0]
    assert nav.index('href="/cockpit"') < nav.index('href="/command"')
    assert "System Status" in nav


def test_command_dashboard_has_explicit_parallel_route() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}

    assert "/" in paths
    assert "/command" in paths
    assert "/cockpit" in paths


def test_api_cockpit_returns_contract(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/cockpit")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cycle"]["id"] == "cycle-route-test"
    assert payload["candidates"][0]["ticker"] == "ROUT"


def test_api_cycle_returns_lightweight_sections(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/cycle")

    assert response.status_code == 200
    assert set(response.json()) == {"cycle", "market", "engines", "scenario"}


def test_api_payloads_are_bounded_and_secret_free(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/cockpit")
    payload = response.text

    assert response.status_code == 200
    assert len(response.json()["candidates"]) <= 25
    assert "ALPACA_SECRET_KEY" not in payload
    assert "DATABASE_URL" not in payload
    assert "api_key" not in payload.lower()


def test_api_routes_do_not_collide_with_existing_namespaces(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    assert client.get("/status/full-live-readiness").status_code in {200, 500}
    assert client.get("/api/cockpit").status_code == 200


def test_api_audit_rejects_invalid_ticker(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/audit/../BAD")

    assert response.status_code == 404


def test_api_audit_normalizes_ticker(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/audit/rout")

    assert response.status_code == 200
    assert response.json()["ticker"] == "ROUT"


def test_api_audit_returns_trace_for_known_ticker(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/audit/ROUT")

    assert response.status_code == 200
    events = response.json()["events"]
    assert events[0]["title"] == "Current cockpit status"
    assert events[0]["message"] == "Approved by current cockpit context."
    assert "ROUT is shown as approved" in events[0]["detail"]
    assert any(event["message"] == "Real route fixture evidence." for event in events)


def test_api_cockpit_ticker_detail_returns_rich_payload(monkeypatch: MonkeyPatch) -> None:
    async def fake_ticker_detail(ticker: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "headline": f"{ticker} rich detail",
            "llm": {"status_label": "Included"},
            "support_cards": [{"label": "Buy Sell Pressure", "detail": "Hard evidence."}],
            "data_health": {"status_label": "Usable With Gaps"},
        }

    monkeypatch.setattr(dashboard_module, "cockpit_ticker_detail_payload", fake_ticker_detail)
    client = _client(monkeypatch)

    response = client.get("/api/cockpit/ticker/rout")

    assert response.status_code == 200
    assert response.json()["ticker"] == "ROUT"
    assert response.json()["headline"] == "ROUT rich detail"


async def test_cockpit_ticker_detail_uses_light_candidate_context(
    monkeypatch: MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def fake_candidate_detail_context(
        ticker: str,
        *,
        include_rich_signal_evidence: bool = True,
        return_source: str | None = None,
    ) -> dict[str, object]:
        observed["ticker"] = ticker
        observed["include_rich_signal_evidence"] = include_rich_signal_evidence
        observed["return_source"] = return_source
        if include_rich_signal_evidence:
            raise AssertionError("cockpit drawer must not load rich candidate detail")
        return {
            "ticker": ticker,
            "decision_brief": {
                "headline": "Light drawer headline",
                "detail": "Light drawer summary",
                "next_step": "Open the full candidate page for heavy evidence.",
            },
            "latest_report": {
                "ticker": ticker,
                "final_action": "WATCH",
                "conviction_pct": 72,
            },
            "review": {"decision": "Pending"},
            "data_health": {"status_label": "Light", "status_class": "neutral"},
            "email_evidence": {},
            "news_evidence": {},
        }

    monkeypatch.setattr(
        candidates_view,
        "candidate_detail_context",
        fake_candidate_detail_context,
    )

    payload = await cockpit_view.cockpit_ticker_detail_payload("rout")

    assert observed == {
        "ticker": "ROUT",
        "include_rich_signal_evidence": False,
        "return_source": "cockpit",
    }
    assert payload["ticker"] == "ROUT"
    assert payload["headline"] == "Light drawer headline"
    assert payload["data_health"]["status_label"] == "Light"  # type: ignore[index]


async def test_cockpit_ticker_detail_has_bounded_timeout(
    monkeypatch: MonkeyPatch,
) -> None:
    async def slow_candidate_detail_context(
        ticker: str,
        *,
        include_rich_signal_evidence: bool = True,
        return_source: str | None = None,
    ) -> dict[str, object]:
        del ticker, include_rich_signal_evidence, return_source
        await asyncio.sleep(0.20)
        return {"ticker": "SLOW"}

    monkeypatch.setenv("AGENCY_COCKPIT_TICKER_DETAIL_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        candidates_view,
        "candidate_detail_context",
        slow_candidate_detail_context,
    )

    payload = await cockpit_view.cockpit_ticker_detail_payload("slow")

    assert payload["ticker"] == "SLOW"
    assert payload["data_health"]["status_label"] == "Detail delayed"  # type: ignore[index]
    assert "Open the full candidate page" in payload["next_step"]


async def test_cockpit_context_does_not_block_on_slow_optional_sections(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_dashboard_context() -> dict[str, object]:
        return {
            "review_queue": [
                {
                    "ticker": "FAST",
                    "action": "WATCH",
                    "conviction_pct": 81,
                    "gate_status": "PASS",
                    "risk_decision": "WARN",
                    "source_count": 2,
                    "confirmed_signal_count": 1,
                    "reason": "Queue proof.",
                }
            ],
            "review_progress": {"total_count": 1},
            "data_sources": [],
            "broker_status": {},
        }

    async def fake_paper_review_status_context() -> dict[str, object]:
        return {
            "queue": [
                {
                    "ticker": "FAST",
                    "action": "WATCH",
                    "conviction_pct": 81,
                    "gate_status": "PASS",
                    "risk_decision": "WARN",
                    "source_count": 2,
                    "confirmed_signal_count": 1,
                    "reason": "Queue proof.",
                }
            ],
            "progress": {"total_count": 1},
        }

    async def slow_optional_context() -> dict[str, object]:
        await asyncio.sleep(0.25)
        return {}

    monkeypatch.setenv("AGENCY_COCKPIT_OPTIONAL_CONTEXT_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setattr(command_view, "dashboard_context", fake_dashboard_context)
    monkeypatch.setattr(command_view, "paper_review_status_context", fake_paper_review_status_context)
    monkeypatch.setattr(cockpit_view, "_cockpit_execution_preview_context", slow_optional_context)
    monkeypatch.setattr(portfolio_view, "portfolio_monitor_context", slow_optional_context)

    context = await cockpit_view.cockpit_context()

    assert context["candidates"][0]["ticker"] == "FAST"  # type: ignore[index]
    assert context["portfolio_phase"]["status_label"] == "Portfolio Check Delayed"  # type: ignore[index]


async def test_cockpit_context_keeps_lane_state_when_dashboard_context_is_partial(
    monkeypatch: MonkeyPatch,
) -> None:
    async def partial_dashboard_context() -> dict[str, object]:
        return {
            "context_status": {
                "status": "delayed",
                "status_label": "Command Dashboard Check Delayed",
                "status_class": "warn",
            }
        }

    async def fake_source_status() -> dict[str, object]:
        return {
            "data_sources": [
                {
                    "source": "massive-stock-trades",
                    "name": "Massive live trade slices",
                    "lane_id": "massive_live_trade_slices",
                    "status": "OK",
                    "freshness": "FRESH",
                    "status_label": "Loaded",
                    "status_class": "pass",
                    "reliability_score": 1.0,
                    "checked_at": "2026-05-22T14:01:00+00:00",
                    "last_update": "2026-05-22T14:00:00+00:00",
                }
            ],
            "data_load_status": {
                "status_label": "Review ready",
                "status_class": "pass",
                "overall_percent": 100,
                "latest_checked_at": "2026-05-22T14:01:00+00:00",
                "datasets": [],
                "lanes": [],
                "blockers": [],
                "warnings": [],
                "lane_states": [
                    {
                        "lane_id": "massive_live_trade_slices",
                        "label": "Massive live trade slices",
                        "lane_kind": "raw",
                        "state": "ready_for_review",
                        "status_label": "Ready for review",
                        "status_class": "pass",
                        "progress_label": "1/1 ticker-days",
                        "required_now": True,
                        "blocks_execution": True,
                        "ready_for_review": True,
                        "ready_for_paper_execution": True,
                        "latest_as_of": "2026-05-22T14:00:00+00:00",
                        "checked_at": "2026-05-22T14:01:00+00:00",
                        "operator_message": "Current live slice is loaded.",
                        "recommended_action": "No action needed.",
                    }
                ],
            },
        }

    async def fake_paper_review_status_context() -> dict[str, object]:
        return {"queue": [], "progress": {"total_count": 0}}

    async def empty_context() -> dict[str, object]:
        return {}

    monkeypatch.setattr(command_view, "dashboard_context", partial_dashboard_context)
    monkeypatch.setattr(
        command_view,
        "_runtime_data_source_status_with_load_status_live",
        fake_source_status,
    )
    monkeypatch.setattr(command_view, "paper_review_status_context", fake_paper_review_status_context)
    monkeypatch.setattr(execution_view, "execution_preview_context", empty_context)
    monkeypatch.setattr(portfolio_view, "portfolio_monitor_context", empty_context)

    context = await cockpit_view.cockpit_context()

    assert context["data_health"]["rows"]  # type: ignore[index]
    assert context["data_state"]["lane_rows"][0]["name"] == "Massive Live Trade Slices"  # type: ignore[index]


async def test_cockpit_data_proof_fallback_has_bounded_timeout(
    monkeypatch: MonkeyPatch,
) -> None:
    async def slow_source_status() -> dict[str, object]:
        await asyncio.sleep(0.25)
        return {"data_sources": [], "data_load_status": {}}

    monkeypatch.setenv("AGENCY_COCKPIT_SOURCE_LOAD_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setattr("agency.runtime.data_load_status.load_data_load_status", dict)
    context = await cockpit_view._dashboard_with_cockpit_data_proof(
        {
            "context_status": {
                "status": "delayed",
                "status_label": "Command Dashboard Check Delayed",
                "status_class": "warn",
            }
        },
        source_load_status_builder=slow_source_status,
        data_load_status_view_builder=command_view.data_load_status_view,
        source_status_rows_builder=command_view.source_status_rows,
    )

    assert context["context_status"]["status"] == "delayed"  # type: ignore[index]
    assert "data_health" not in context


async def test_cockpit_data_proof_timeout_uses_direct_lane_registry(
    monkeypatch: MonkeyPatch,
) -> None:
    async def slow_source_status() -> dict[str, object]:
        await asyncio.sleep(0.25)
        return {"data_sources": [], "data_load_status": {}}

    monkeypatch.setenv("AGENCY_COCKPIT_SOURCE_LOAD_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setattr(
        "agency.runtime.data_load_status.load_data_load_status",
        lambda: {
            "status_label": "Loaded With Gaps",
            "status_class": "warn",
            "overall_percent": 84,
            "critical_lane_percent": 55,
            "expected_ticker_count": 168,
            "review_operational_ready": True,
            "tradable_ready": False,
            "lane_states": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive live trade slices",
                    "lane_kind": "raw",
                    "state": "ready_for_review",
                    "status_label": "Ready for review",
                    "status_class": "pass",
                    "progress_label": "168/168 ticker-days",
                    "required_now": True,
                    "blocks_execution": True,
                    "ready_for_review": True,
                    "ready_for_paper_execution": False,
                    "latest_as_of": "2026-06-01T22:20:48+00:00",
                    "checked_at": "2026-06-01T22:21:00+00:00",
                    "operator_message": "Current live slice is loaded.",
                    "recommended_action": "Use for review.",
                }
            ],
            "freshness_rows": [
                {
                    "source": "massive-stock-trades",
                    "label": "Massive Stock Trades",
                    "status": "HEALTHY",
                    "freshness": "FRESH",
                    "status_class": "pass",
                    "checked_at": "2026-06-01T22:21:00+00:00",
                    "coverage_label": "168/168 ticker-days",
                    "detail": "Live trade lane is current.",
                }
            ],
        },
    )

    context = await cockpit_view._dashboard_with_cockpit_data_proof(
        {
            "context_status": {
                "status": "delayed",
                "status_label": "Command Dashboard Check Delayed",
                "status_class": "warn",
            }
        },
        source_load_status_builder=slow_source_status,
        data_load_status_view_builder=command_view.data_load_status_view,
        source_status_rows_builder=command_view.source_status_rows,
    )

    assert context["data_load_status"]["lane_state_rows"]  # type: ignore[index]
    assert context["data_sources"][0]["source"] == "massive-stock-trades"  # type: ignore[index]
    assert context["data_health"]["rows"]  # type: ignore[index]
