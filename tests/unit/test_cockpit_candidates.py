from __future__ import annotations

from pathlib import Path

import agency.views.cockpit as cockpit_module
from agency.views.cockpit import (
    cockpit_context_from_sources,
    cockpit_ticker_detail_payload_from_context,
)
from tests.unit.test_cockpit_contract import _sample_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")
STYLES = Path("src/agency/static/styles.css")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _styles() -> str:
    return STYLES.read_text(encoding="utf-8")


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
    assert row["evidence_line"] == "No concrete evidence line is available in the current pack."
    assert row["risk_line"] == "Risk check did not attach a specific finding."
    assert row["risk_status_label"] == "Risk proof not attached"


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

    assert "Evidence tiers: confirmed uses direct source data" in html
    assert "data-cockpit-tip=\"evidence-tier-thresholds\"" in html


def test_candidate_row_layout_keeps_decision_controls_from_compressing_evidence() -> None:
    css = _styles()
    row_rule = css.split(".cockpit-candidate-row {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: 1fr;" in row_rule


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
    monkeypatch.setattr("agency.views.execution.execution_preview_context", fake_execution_preview_context)
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
    monkeypatch.setattr("agency.views.execution.execution_preview_context", fake_execution_preview_context)
    monkeypatch.setattr("agency.views.portfolio.portfolio_monitor_context", fake_portfolio_monitor_context)

    context = await cockpit_module.cockpit_context()

    assert calls["count"] == 2
    assert len(context["candidates"]) == 20
    assert context["candidates"][0]["ticker"] == "T00"
    assert context["scenario"]["headline"] == "20 candidates are ready for research review."


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
    assert row["status_label"] == "Ready for paper order"
    assert row["action_label"] == "Review paper order"
    assert row["order_preview"] == "$1000.00"
    assert row["order_notional"] == 1000.0
    assert row["llm_label"] == "LLM review available"
    assert manifest[0]["ticker"] == "AMZN"
    assert manifest[0]["kind"] == "buy"


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

    assert rows["AAA"]["status_label"] == "Ready for paper order"
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
    assert payload["headline"] == "AMZN is selected for human review."
    assert payload["llm"]["status_label"] == "Included"
    assert payload["support_cards"][0]["detail"].startswith("Hard evidence: score +0.87")
    assert payload["signals"][0]["hard_evidence"] == (
        "Score +0.87 bullish; Confidence 55%"
    )
    assert payload["data_health"]["status_label"] == "Usable With Gaps"
