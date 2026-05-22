from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
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


def test_candidate_evidence_thresholds_have_whymark_tips() -> None:
    html = _template()

    assert "Evidence tiers: confirmed uses direct source data" in html
    assert "data-cockpit-tip=\"evidence-tier-thresholds\"" in html


def test_blocked_candidate_has_audit_link_not_approve_button() -> None:
    context = cockpit_context_from_sources(_sample_sources())
    row = {row["ticker"]: row for row in context["candidates"]}["CCC"]

    assert row["actionable"] is False
    assert row["decision_controls"] == ["audit"]
    assert row["audit_url"] == "/api/audit/CCC"


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

    assert rows["AAA"]["status_label"] == "Ready for your decision"
    assert rows["CCC"]["status_label"] == "Audit only - policy gate blocks order"
