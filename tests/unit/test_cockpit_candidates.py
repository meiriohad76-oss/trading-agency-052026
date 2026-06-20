from __future__ import annotations

from pathlib import Path
from typing import Any

import agency.views.cockpit as cockpit_module
from agency.views.cockpit import (
    cockpit_context_from_sources,
    cockpit_ticker_detail_payload_from_context,
)
from agency.views.command import paper_review_queue
from tests.unit.test_cockpit_contract import _sample_sources

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT_ROOT / "src/agency/templates/cockpit.html"
PANELS_TEMPLATE = PROJECT_ROOT / "src/agency/templates/_cockpit_panels.html"
EVIDENCE_LEGEND = PROJECT_ROOT / "src/agency/templates/_evidence_legend.html"
STYLES = PROJECT_ROOT / "src/agency/static/styles.css"
V3_STYLES = PROJECT_ROOT / "src/agency/static/v3-screens.css"
COCKPIT_JS = PROJECT_ROOT / "src/agency/static/cockpit.js"


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _panels_template() -> str:
    return PANELS_TEMPLATE.read_text(encoding="utf-8")


def _evidence_legend() -> str:
    return EVIDENCE_LEGEND.read_text(encoding="utf-8")


def _styles() -> str:
    return STYLES.read_text(encoding="utf-8")


def _v3_styles() -> str:
    return V3_STYLES.read_text(encoding="utf-8")


def _cockpit_js() -> str:
    return COCKPIT_JS.read_text(encoding="utf-8")


def test_candidate_row_includes_concrete_evidence_not_generic_copy() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    rows = {row["ticker"]: row for row in context["candidates"]}

    assert "4.1%" in rows["AAA"]["evidence_line"]
    assert rows["AAA"]["evidence_hard_value"] == "4.1%"
    assert rows["AAA"]["evidence_line"] != "Bullish signal detected."


def test_candidate_row_includes_concrete_risk_or_clear_empty_state() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    rows = {row["ticker"]: row for row in context["candidates"]}

    assert rows["CCC"]["risk_hard_value"] == "4.0"
    assert rows["CCC"]["risk_line"] == "Position cap would be exceeded by 4.0 percentage points."
    assert rows["AAA"]["risk_line"] == "No major risk flag in current pack."


def test_candidate_row_missing_evidence_and_risk_uses_neutral_copy() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "NODATA",
            "company": "No Data Inc.",
            "sector": "Technology",
            "final_action": "WATCH",
            "final_score": 0.61,
            "risk_status_label": "",
            "is_reviewable": False,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:00+00:00",
        }
    ]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["evidence_tiers"] == ["suppressed"]
    assert row["evidence_line"] == (
        "No current signal evidence was attached for this ticker; open the audit "
        "to see whether source data is unavailable, still unanalyzed, or below "
        "the display threshold."
    )
    assert row["risk_line"] == "Risk check did not attach a specific finding."
    assert row["risk_status_label"] == "Risk proof not attached"


def test_candidate_row_uses_nested_selection_report_scores_and_llm_review() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "NEST",
            "final_action": "WATCH",
            "final_conviction": 0.73,
            "deterministic": {
                "action": "WATCH",
                "score": 0.73,
                "conviction": 0.73,
            },
            "llm_review": {
                "action": "AGREE",
                "confidence": 0.68,
                "rationale": "LLM agrees because abnormal volume and pressure corroborate.",
            },
            "policy_gates": [{"name": "freshness", "status": "PASS", "reason": "fresh"}],
            "evidence_pack": {
                "data_quality": {
                    "source_count": 4,
                    "confirmed_signal_count": 2,
                    "freshness": "FRESH",
                }
            },
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:00+00:00",
        }
    ]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["det_conviction"] == 0.73
    assert row["llm_conviction"] == 0.68
    assert row["llm_label"] == "LLM agrees"
    assert row["llm_rationale"] == "LLM agrees because abnormal volume and pressure corroborate."


def test_paper_review_queue_preserves_selection_scores_for_cockpit() -> None:
    sources = _sample_sources()
    report = {
        "ticker": "PRES",
        "cycle_id": "cycle-live-20260522-1530",
        "as_of": "2026-05-22T15:28:00+00:00",
        "generated_at": "2026-05-22T15:29:00+00:00",
        "final_action": "WATCH",
        "final_conviction": 0.74,
        "deterministic": {
            "action": "WATCH",
            "score": 0.74,
            "conviction": 0.74,
        },
        "llm_review": {
            "action": "NO_REVIEW",
            "confidence": 0.0,
            "rationale": "LLM review is not enabled for this run.",
        },
        "policy_gates": [{"name": "freshness", "status": "PASS", "reason": "fresh"}],
        "risk_flags": [],
        "evidence_pack": {
            "data_quality": {
                "source_count": 5,
                "confirmed_signal_count": 2,
                "freshness": "FRESH",
            }
        },
    }
    queue = paper_review_queue(
        [report],
        [],
        {"cycle_id": "cycle-live-20260522-1530"},
    )
    sources["dashboard"]["review_queue"] = queue  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["det_conviction"] == 0.74
    assert row["llm_conviction"] == 0.0
    assert row["llm_label"] == "LLM disabled for this run"
    assert row["llm_rationale"] == "LLM review is not enabled for this run."


def test_candidate_row_uses_reference_missing_copy_when_sector_is_absent() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "NOSEC",
            "company": "No Sector Inc.",
            "final_action": "WATCH",
            "final_score": 0.61,
            "risk_status_label": "PASS",
            "is_reviewable": True,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:00+00:00",
        }
    ]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["sector"] == "Reference data not loaded"


def test_candidate_row_uses_cached_ticker_reference_metadata() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "REF",
            "final_action": "WATCH",
            "final_score": 0.61,
            "risk_status_label": "PASS",
            "is_reviewable": True,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:00+00:00",
        }
    ]
    sources["dashboard"]["ticker_reference"] = {  # type: ignore[index]
        "REF": {
            "name": "Reference Corp",
            "sector": "Semiconductors and related devices",
        }
    }

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["name"] == "Reference Corp"
    assert row["sector"] == "Semiconductors and related devices"


def test_candidate_row_uses_conviction_dial_and_mono_score() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    row = context["candidates"][0]
    html = _template()

    assert row["score_display"] == "0.82"
    assert row["conviction_dial_degrees"] == 38
    assert "data-conviction-dial" in html
    assert "candidate.score_display" in html


def test_candidate_evidence_tiers_are_visually_distinct() -> None:
    css = _styles()
    html = _template()

    assert ".evidence-tier-confirmed" in css
    assert ".evidence-tier-inferred" in css
    assert ".evidence-tier-suppressed" in css
    assert "candidate.evidence_tiers" in html
    assert 'default(["confirmed"]' not in html
    assert "Evidence available in audit." not in html
    assert 'default("No major risk flag' not in html
    assert 'default("Ready for review"' not in html


def test_candidate_evidence_thresholds_have_whymark_tips() -> None:
    html = _template()
    legend = _evidence_legend()

    assert "{{ evidence_legend(compact=true) }}" in html
    assert "Evidence tiers" in legend
    assert "confirmed direct data" in legend
    assert "data-cockpit-tip=\"evidence-tier-thresholds\"" in legend


def test_candidate_row_layout_keeps_decision_controls_from_compressing_evidence() -> None:
    css = _styles()
    row_rule = css.split(".cockpit-candidate-row {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: 1fr;" in row_rule


def test_cockpit_declares_variation_a_shell_markers() -> None:
    html = _template()

    assert 'class="cockpit-shell vA"' in html
    assert 'data-ux-variation="variation-a-preflight"' in html
    for marker in (
        'data-tour="topline"',
        'data-tour="datastate"',
        'data-tour="cluster"',
        'data-tour="engines"',
        'data-tour="instruments"',
        'data-tour="phaserail"',
        'data-tour="candidates"',
    ):
        assert marker in html


def test_cockpit_variation_a_css_removes_legacy_chrome() -> None:
    css = _v3_styles()

    assert "Cockpit Variation A parity layer" in css
    assert ".v3-screen-cockpit .sidebar" in css
    assert "display: none;" in css
    assert 'width: min(1440px, 100%);' in css
    assert "--amber: #ffb845;" in css
    assert "--cyan: #5ad7f0;" in css
    assert "--green: #5fe49d;" in css
    assert "--red: #ff6868;" in css


def test_cockpit_candidate_actions_preserve_ticker_context() -> None:
    html = _template()
    js = _cockpit_js()
    css = _v3_styles()

    assert 'data-cockpit-focus-ticker="{{ candidate.ticker }}"' in html
    assert "#focused-preview-" in html
    assert "data-cockpit-manifest-row" in html
    assert "selectedTicker" in js
    assert "data-cockpit-flow-focus" in js
    assert ".cockpit-manifest-row[data-cockpit-flow-focus]" in css


def test_cockpit_ticker_drawer_has_concrete_detail_slots_and_manual_llm_action() -> None:
    panels = _panels_template()
    js = _cockpit_js()

    for marker in (
        "data-ticker-data-health-detail",
        "data-ticker-llm-action",
        "data-ticker-context",
        "data-ticker-evidence",
    ):
        assert marker in panels
    assert "manual_review_available" in js
    assert "dataHealthDetailText" in js
    assert "No primary signal evidence was returned for this ticker" not in js


def test_cockpit_portfolio_phase_has_guidance_and_local_decision_hooks() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    html = _template()
    js = _cockpit_js()

    assert context["portfolio_phase"]["portfolio_review_required"] is True  # type: ignore[index]
    assert "Review 1 open paper position" in str(context["portfolio_phase"]["guidance"])  # type: ignore[index]
    assert context["account"]["equity"] == 100000.0  # type: ignore[index]
    assert 'data-portfolio-decision-summary' in html
    assert 'data-capacity-impact' in html
    assert 'data-position-decision-state' in html
    assert 'data-position-notional="{{ position.market_value|default(0, true) }}"' in html
    assert "updateLocalExitManifest" in js
    assert "Operator marked Close in portfolio review" in js


def test_cockpit_empty_portfolio_can_advance_to_clearance() -> None:
    sources = _sample_sources()
    sources["portfolio"]["positions"] = []  # type: ignore[index]

    context = cockpit_context_from_sources(sources)

    assert context["positions"] == []
    assert context["portfolio_phase"]["portfolio_review_required"] is False  # type: ignore[index]
    assert "continue to clearance" in str(context["portfolio_phase"]["guidance"]).lower()  # type: ignore[index]
    assert "continue to clearance" in str(context["portfolio_phase"]["empty_state"]).lower()  # type: ignore[index]


def test_blocked_candidate_has_audit_link_not_approve_button() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    row = {row["ticker"]: row for row in context["candidates"]}["CCC"]

    assert row["actionable"] is False
    assert row["reviewable"] is False
    assert row["decision_controls"] == ["audit"]
    assert row["audit_url"] == "/api/audit/CCC"


def test_watch_candidate_with_pending_review_has_research_approval_controls() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Pending",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "approve_review_action": "/candidates/AMZN/reviews?cycle_id=cycle-live-20260522-1530&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=APPROVE",
            "defer_review_action": "/candidates/AMZN/reviews?cycle_id=cycle-live-20260522-1530&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=DEFER",
            "reject_review_action": "/candidates/AMZN/reviews?cycle_id=cycle-live-20260522-1530&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=REJECT",
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T00:00:00+00:00",
        }
    ]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["ticker"] == "AMZN"
    assert row["final_conviction"] == 0.69
    assert row["actionable"] is False
    assert row["reviewable"] is True
    assert row["decision_controls"] == ["approve", "defer", "reject"]
    assert row["approve_review_action"].startswith("/candidates/AMZN/reviews")
    assert row["evidence_line"] == "5 independent source(s); 2 confirmed signal(s)."


async def test_cockpit_context_retries_paper_review_when_first_queue_is_empty(
    monkeypatch,
) -> None:
    sources = _sample_sources()
    queue = [
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Pending",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "approve_review_action": "/candidates/AMZN/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=APPROVE",
            "defer_review_action": "/candidates/AMZN/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=DEFER",
            "reject_review_action": "/candidates/AMZN/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=REJECT",
            "cycle_id": "cycle-live",
            "as_of": "2026-05-22T00:00:00+00:00",
        }
    ]
    sources["dashboard"]["review_queue"] = []  # type: ignore[index]

    async def fake_dashboard_context() -> dict[str, object]:
        return dict(sources["dashboard"])  # type: ignore[arg-type]

    async def fake_execution_preview_context() -> dict[str, object]:
        return dict(sources["execution"])  # type: ignore[arg-type]

    async def fake_portfolio_monitor_context() -> dict[str, object]:
        return dict(sources["portfolio"])  # type: ignore[arg-type]

    calls = {"count": 0}

    async def fake_paper_review_status_context() -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "cycle_id": "cycle-live",
                "progress": {"total_count": 0},
                "queue": [],
            }
        return {
            "cycle_id": "cycle-live",
            "progress": {"total_count": 1, "pending_count": 1},
            "queue": queue,
        }

    monkeypatch.setattr("agency.views.command.dashboard_context", fake_dashboard_context)
    monkeypatch.setattr("agency.views.command.paper_review_status_context", fake_paper_review_status_context)
    monkeypatch.setattr(cockpit_module, "_cockpit_execution_preview_context", fake_execution_preview_context)
    monkeypatch.setattr("agency.views.portfolio.portfolio_monitor_context", fake_portfolio_monitor_context)

    context = await cockpit_module.cockpit_context()

    assert calls["count"] == 2
    assert [row["ticker"] for row in context["candidates"]] == ["AMZN"]
    assert context["scenario"]["headline"] == "1 candidates are ready for research review."


async def test_cockpit_context_retries_when_dashboard_queue_is_partial(
    monkeypatch,
) -> None:
    sources = _sample_sources()
    partial_queue = [
        {
            "ticker": "XEL",
            "action": "WATCH",
            "conviction_pct": 65,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Pending",
            "source_count": 4,
            "confirmed_signal_count": 2,
            "approve_review_action": "/candidates/XEL/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=APPROVE",
            "defer_review_action": "/candidates/XEL/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=DEFER",
            "reject_review_action": "/candidates/XEL/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=REJECT",
            "cycle_id": "cycle-live",
            "as_of": "2026-05-22T00:00:00+00:00",
        },
        {
            "ticker": "WDC",
            "action": "WATCH",
            "conviction_pct": 64,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Pending",
            "source_count": 4,
            "confirmed_signal_count": 2,
            "approve_review_action": "/candidates/WDC/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=APPROVE",
            "defer_review_action": "/candidates/WDC/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=DEFER",
            "reject_review_action": "/candidates/WDC/reviews?cycle_id=cycle-live&as_of=2026-05-22T00%3A00%3A00%2B00%3A00&decision=REJECT",
            "cycle_id": "cycle-live",
            "as_of": "2026-05-22T00:00:00+00:00",
        },
    ]
    full_queue = [
        {
            **partial_queue[0],
            "ticker": f"T{index:02d}",
            "conviction_pct": 80 - index,
        }
        for index in range(20)
    ]
    sources["dashboard"]["review_queue"] = partial_queue  # type: ignore[index]

    async def fake_dashboard_context() -> dict[str, object]:
        return dict(sources["dashboard"])  # type: ignore[arg-type]

    async def fake_execution_preview_context() -> dict[str, object]:
        return dict(sources["execution"])  # type: ignore[arg-type]

    async def fake_portfolio_monitor_context() -> dict[str, object]:
        return dict(sources["portfolio"])  # type: ignore[arg-type]

    calls = {"count": 0}

    async def fake_paper_review_status_context() -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "cycle_id": "cycle-live",
                "progress": {"total_count": 0},
                "queue": [],
            }
        return {
            "cycle_id": "cycle-live",
            "progress": {"total_count": 20, "pending_count": 20},
            "queue": full_queue,
        }

    monkeypatch.setattr("agency.views.command.dashboard_context", fake_dashboard_context)
    monkeypatch.setattr("agency.views.command.paper_review_status_context", fake_paper_review_status_context)
    monkeypatch.setattr(cockpit_module, "_cockpit_execution_preview_context", fake_execution_preview_context)
    monkeypatch.setattr("agency.views.portfolio.portfolio_monitor_context", fake_portfolio_monitor_context)

    context = await cockpit_module.cockpit_context()

    assert calls["count"] == 2
    assert len(context["candidates"]) == 20
    assert context["candidates"][0]["ticker"] == "T00"
    assert context["scenario"]["headline"] == "20 candidates are ready for research review."


async def test_cockpit_execution_context_limits_reports_and_supplies_dependencies(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    reports = [{"ticker": f"T{index:02d}"} for index in range(30)]
    data_sources = [{"dataset": "prices_daily", "status": "READY"}]
    broker = {
        "connected": True,
        "mode": "paper",
        "account": {"equity": 100000.0},
        "positions": [],
        "orders": [],
    }

    async def fake_dashboard_selection_reports(*, limit: int) -> list[dict[str, object]]:
        captured["limit"] = limit
        return reports[:limit]

    async def fake_live_runtime_source_health_rows(_reader: object) -> list[dict[str, object]]:
        return data_sources

    async def fake_broker_status_context(**kwargs: object) -> dict[str, object]:
        captured["broker_kwargs"] = kwargs
        return broker

    async def fake_execution_preview_context(**kwargs: object) -> dict[str, object]:
        captured["execution_kwargs"] = kwargs
        return {"preview_rows": [{"ticker": "T00"}]}

    monkeypatch.setattr(
        cockpit_module,
        "_dashboard_selection_reports",
        fake_dashboard_selection_reports,
    )
    monkeypatch.setattr(
        cockpit_module,
        "live_runtime_source_health_rows",
        fake_live_runtime_source_health_rows,
    )
    monkeypatch.setattr(
        cockpit_module,
        "broker_status_context",
        fake_broker_status_context,
    )
    monkeypatch.setattr(
        cockpit_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )

    context = await cockpit_module._cockpit_execution_preview_context()

    assert context["preview_rows"] == [{"ticker": "T00"}]
    assert captured["limit"] == cockpit_module.MAX_COCKPIT_CANDIDATES
    assert captured["broker_kwargs"] == {"use_cache": True, "allow_live_read": False}
    assert captured["execution_kwargs"] == {
        "raw_reports": reports[: cockpit_module.MAX_COCKPIT_CANDIDATES],
        "data_sources": data_sources,
        "broker": broker,
    }


async def test_cockpit_source_context_runs_builder_on_current_event_loop() -> None:
    current_loop = id(cockpit_module.asyncio.get_running_loop())

    async def builder() -> dict[str, object]:
        return {"loop_id": id(cockpit_module.asyncio.get_running_loop())}

    context = await cockpit_module._source_context(
        "execution",
        builder,
        timeout_seconds=1.0,
    )

    assert context["loop_id"] == current_loop


async def test_cockpit_source_context_cancels_timed_out_builder() -> None:
    cancelled = cockpit_module.asyncio.Event()

    async def builder() -> dict[str, object]:
        try:
            await cockpit_module.asyncio.sleep(5)
        except cockpit_module.asyncio.CancelledError:
            cancelled.set()
            raise
        return {"status": "finished"}

    context = await cockpit_module._source_context(
        "execution",
        builder,
        timeout_seconds=0.01,
    )

    assert context["context_status"]["status"] == "delayed"  # type: ignore[index]
    await cockpit_module.asyncio.wait_for(cancelled.wait(), timeout=0.5)


def test_cockpit_optional_context_timeout_defaults_to_fast_first_screen(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENCY_COCKPIT_OPTIONAL_CONTEXT_TIMEOUT_SECONDS", raising=False)

    assert cockpit_module._optional_context_timeout_seconds() == 1.0


def test_cockpit_required_context_timeout_defaults_below_route_budget(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENCY_COCKPIT_REQUIRED_CONTEXT_TIMEOUT_SECONDS", raising=False)

    assert cockpit_module._required_context_timeout_seconds() <= 8.0


async def test_cached_cockpit_context_coalesces_concurrent_requests(monkeypatch) -> None:
    calls = {"count": 0}
    cockpit_module._cockpit_context_cache.clear()
    cockpit_module._cockpit_context_inflight.clear()

    async def fake_cockpit_context(**_kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        await cockpit_module.asyncio.sleep(0.01)
        return {
            "build": calls["count"],
            "data_state": {"lane_rows": [{"lane_id": "massive_live_trade_slices"}]},
        }

    monkeypatch.setattr(cockpit_module, "cockpit_context", fake_cockpit_context)

    first, second = await cockpit_module.asyncio.gather(
        cockpit_module.cached_cockpit_context(),
        cockpit_module.cached_cockpit_context(),
    )

    assert first["build"] == second["build"] == 1
    assert first["data_state"] == second["data_state"]
    assert first["cockpit_context_freshness"]["status_label"] == "Cockpit data loaded"
    assert second["cockpit_context_freshness"]["status_label"] == "Cockpit data loaded"
    assert calls["count"] == 1


async def test_warm_cockpit_context_cache_primes_first_runtime_request(monkeypatch) -> None:
    calls = {"count": 0}
    cockpit_module._cockpit_context_cache.clear()
    cockpit_module._cockpit_context_inflight.clear()

    async def fake_cockpit_context(**_kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        return {
            "build": calls["count"],
            "data_state": {"lane_rows": [{"lane_id": "massive_live_trade_slices"}]},
        }

    monkeypatch.setattr(cockpit_module, "cockpit_context", fake_cockpit_context)

    warmed = await cockpit_module.warm_cockpit_context_cache()
    context = await cockpit_module.cached_cockpit_context()

    assert warmed is True
    assert context["build"] == 1
    assert context["data_state"] == {"lane_rows": [{"lane_id": "massive_live_trade_slices"}]}
    assert context["cockpit_context_freshness"]["status_label"] == "Cockpit data loaded"
    assert calls["count"] == 1


async def test_cockpit_context_cache_covers_one_runtime_smoke_sequence(monkeypatch) -> None:
    calls = {"count": 0}
    now = {"value": 1000.0}
    cockpit_module._cockpit_context_cache.clear()
    cockpit_module._cockpit_context_inflight.clear()

    async def fake_cockpit_context(**_kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        return {
            "build": calls["count"],
            "data_state": {"lane_rows": [{"lane_id": "massive_live_trade_slices"}]},
        }

    monkeypatch.setattr(cockpit_module, "monotonic", lambda: now["value"])
    monkeypatch.setattr(cockpit_module, "cockpit_context", fake_cockpit_context)

    first = await cockpit_module.cached_cockpit_context()
    now["value"] += 10.0
    second = await cockpit_module.cached_cockpit_context()

    assert first["build"] == second["build"] == 1
    assert second["cockpit_context_freshness"]["source"] == "cache"
    assert calls["count"] == 1
    assert cockpit_module._cockpit_context_inflight == {}


async def test_cockpit_context_cache_invalidates_when_data_proof_changes(monkeypatch) -> None:
    calls = {"count": 0}
    proof = {"value": 1}
    cockpit_module._cockpit_context_cache.clear()
    cockpit_module._cockpit_context_inflight.clear()

    async def fake_cockpit_context(**_kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        return {"build": calls["count"]}

    monkeypatch.setattr(cockpit_module, "cockpit_context", fake_cockpit_context)
    monkeypatch.setattr(
        cockpit_module,
        "runtime_status_data_proof_version",
        lambda: proof["value"],
    )

    first = await cockpit_module.cached_cockpit_context()
    proof["value"] = 2
    second = await cockpit_module.cached_cockpit_context()

    assert first["build"] == 1
    assert second["build"] == 2
    assert calls["count"] == 2


async def test_expired_cockpit_cache_serves_last_context_while_refreshing(monkeypatch) -> None:
    calls = {"count": 0}
    now = {"value": 1000.0}
    cockpit_module._cockpit_context_cache.clear()
    cockpit_module._cockpit_context_inflight.clear()
    cache_key = (None, None, cockpit_module.runtime_status_data_proof_version())
    cockpit_module._cockpit_context_cache[cache_key] = (
        now["value"] - cockpit_module.COCKPIT_CONTEXT_CACHE_SECONDS - 1.0,
        {
            "build": "last-proven",
            "data_state": {"lane_rows": [{"lane_id": "massive_live_trade_slices"}]},
        },
    )

    async def fake_cockpit_context(**_kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        return {
            "build": "fresh",
            "data_state": {"lane_rows": [{"lane_id": "massive_live_trade_slices"}]},
        }

    monkeypatch.setattr(cockpit_module, "monotonic", lambda: now["value"])
    monkeypatch.setattr(cockpit_module, "cockpit_context", fake_cockpit_context)

    context = await cockpit_module.cached_cockpit_context()
    await cockpit_module.asyncio.sleep(0)
    await cockpit_module.asyncio.sleep(0)
    refreshed = await cockpit_module.cached_cockpit_context()

    assert context["build"] == "last-proven"
    assert refreshed["build"] == "fresh"
    assert calls["count"] == 1


def test_approved_watch_candidate_uses_ready_execution_preview_as_orderable() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Approve",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T00:00:00+00:00",
        }
    ]
    sources["execution"]["preview_rows"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "preview_state": "READY",
            "side": "BUY",
            "submit_enabled": True,
            "order_value_label": "$1000.00",
            "notional": 1000.0,
            "order_intent_hash": "a" * 64,
            "order_intent_hash_label": "aaaaaaaaaaaa",
            "llm_status_label": "LLM review available",
            "llm_rationale": "LLM agrees with the promoted paper BUY preview.",
        }
    ]
    sources["execution"]["orderable_rows"] = sources["execution"]["preview_rows"]  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]
    manifest = context["clearance"]["manifest"]

    assert row["ticker"] == "AMZN"
    assert row["actionable"] is True
    assert row["status"] == "approved"
    assert row["status_label"] == "Ready to submit paper order"
    assert row["action_label"] == "Submit paper order"
    assert row["order_preview"] == "$1000.00"
    assert row["order_notional"] == 1000.0
    assert row["llm_label"] == "LLM review available"
    assert manifest[0]["ticker"] == "AMZN"
    assert manifest[0]["kind"] == "buy"


def test_blocked_candidate_with_ready_preview_is_not_actionable() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "BLOCK",
            "risk_detail": "Portfolio concentration cap would be exceeded.",
            "review_state": "Ready",
            "human_review_decision": "Approve",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T00:00:00+00:00",
        }
    ]
    sources["execution"]["preview_rows"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "preview_state": "READY",
            "side": "BUY",
            "submit_enabled": True,
            "order_value_label": "$1000.00",
            "notional": 1000.0,
        }
    ]
    sources["execution"]["orderable_rows"] = sources["execution"]["preview_rows"]  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["actionable"] is False
    assert row["order_reviewable"] is False
    assert row["status"] == "blocked"
    assert row["status_label"] == "Audit only - policy gate blocks order"
    assert row["action_label"] == "Open audit"
    assert context["clearance"]["manifest"] == []


def test_ready_preview_without_submit_is_order_intent_review_not_paper_ready() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Approve",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T00:00:00+00:00",
        }
    ]
    sources["execution"]["preview_rows"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "preview_state": "READY",
            "side": "BUY",
            "submit_enabled": False,
            "order_value_label": "$1000.00",
            "notional": 1000.0,
        }
    ]
    sources["execution"]["orderable_rows"] = []  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    row = context["candidates"][0]

    assert row["actionable"] is False
    assert row["order_reviewable"] is True
    assert row["status"] == "pending"
    assert row["status_label"] == "Order details need approval"
    assert row["action_label"] == "Review order details"
    assert row["execution_focus_url"] == "/execution-preview?ticker=AMZN#focused-preview-AMZN"
    assert context["scenario"]["state"] == "review"


def test_llm_not_run_copy_is_explicit_for_non_top_ten() -> None:
    sources = _sample_sources()
    queue = sources["dashboard"]["review_queue"]  # type: ignore[index]
    for index in range(11):
        queue.append(  # type: ignore[union-attr]
            {
                "ticker": f"T{index:02d}",
                "company": f"Ticker {index:02d}",
                "sector": "Testing",
                "final_action": "BUY",
                "final_score": 0.1 + index / 100,
                "risk_status_label": "PASS",
                "top_reasons": [f"Volume {index + 1}.0x baseline."],
                "is_reviewable": True,
            }
        )

    context = cockpit_context_from_sources(sources)
    rows = {row["ticker"]: row for row in context["candidates"]}

    assert rows["T00"]["llm_label"] == (
        "LLM not run because this ticker is outside the top 10 automatic review set."
    )


def test_candidate_status_copy_is_operator_facing() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    rows = {row["ticker"]: row for row in context["candidates"]}

    assert rows["AAA"]["status_label"] == "Ready to submit paper order"
    assert rows["CCC"]["status_label"] == "Audit only - policy gate blocks order"


def test_cockpit_ticker_detail_payload_surfaces_rich_candidate_brief() -> None:
    payload = cockpit_ticker_detail_payload_from_context(
        {
            "ticker": "AMZN",
            "decision_brief": {
                "ticker": "AMZN",
                "headline": "AMZN is selected for human review.",
                "detail": "Selected because buy/sell pressure and abnormal volume are constructive.",
                "next_step": "Human review is recorded as Approve; monitor the next runtime cycle.",
                "action_label": "Watch",
                "state_label": "Selected For Review",
                "conviction_pct": 69,
                "source_count": 5,
                "confirmed_signal_count": 2,
                "support_cards": [
                    {
                        "label": "Buy Sell Pressure",
                        "detail": "Hard evidence: score +0.87 bullish, 55% confidence, source Massive Stock Trades.",
                        "meta": "Actionable / FRESH / Inferred",
                        "tone": "pass",
                    }
                ],
                "caution_cards": [
                    {
                        "label": "Market Flow Trend",
                        "detail": "Hard evidence: score -0.59 bearish, 55% confidence.",
                        "meta": "Context Only / FRESH / Inferred",
                        "tone": "block",
                    }
                ],
                "decision_points": [
                    {
                        "label": "Evidence breadth",
                        "detail": "5 independent source(s), 2 confirmed signal(s).",
                        "tone": "pass",
                    }
                ],
                "signal_mix_note": "3 actionable bullish, 0 actionable bearish.",
            },
            "latest_report": {
                "ticker": "AMZN",
                "cycle_id": "cycle-live",
                "as_of": "2026-05-22T00:00:00+00:00",
                "llm_status_label": "Included",
                "llm_status_detail": "LLM reviewed the top-10 candidate.",
                "llm_action": "AGREE",
                "llm_confidence_pct": 70,
                "llm_rationale": "LLM agrees with WATCH because bullish signals are confirmed but caution remains.",
                "actionable_signals": [
                    {
                        "lane": "Buy Sell Pressure",
                        "direction": "BULLISH",
                        "actionability_label": "Actionable",
                        "freshness": "FRESH",
                        "verification_label": "Inferred",
                        "score": "+0.87 bullish",
                        "confidence_pct": 55,
                        "source": "Massive Stock Trades",
                        "timestamp_label": "2026-05-22 13:16 UTC",
                        "trigger_headline": "AMZN Buy Sell Pressure signal was constructive.",
                        "trigger_cards": [
                            {"label": "Score", "value": "+0.87 bullish"},
                            {"label": "Confidence", "value": "55%"},
                        ],
                    }
                ],
                "context_signals": [],
                "suppressed_signals": [],
            },
            "data_health": {
                "status_label": "Usable With Gaps",
                "status_class": "warn",
                "headline": "AMZN candidate brief is usable, but Massive trade prints needs attention.",
                "recommended_action": "Review the caution for Massive trade prints.",
                "primary_blocker": "Massive trade prints - Attention",
                "primary_blocker_detail": "28/30 ticker(s) usable.",
                "overall_percent": 65,
                "last_verified_label": "2026-05-22 16:06 UTC",
            },
            "review": {"decision": "Approve", "reason": "paper review approved"},
        }
    )

    assert payload["ticker"] == "AMZN"
    assert payload["cycle_id"] == "cycle-live"
    assert payload["as_of"] == "2026-05-22T00:00:00+00:00"
    assert payload["headline"] == "AMZN is selected for human review."
    assert payload["llm"]["status_label"] == "Included"
    assert payload["llm"]["manual_review_available"] is True
    assert payload["llm"]["manual_review_action"] == "/candidates/AMZN/llm-review"
    assert payload["support_cards"][0]["detail"].startswith("Hard evidence: score +0.87")
    assert payload["signals"][0]["hard_evidence"] == (
        "Score +0.87 bullish; Confidence 55%"
    )
    assert payload["data_health"]["status_label"] == "Usable With Gaps"
