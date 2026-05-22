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


def test_cockpit_template_has_bluf_before_diagnostics() -> None:
    html = _template()

    assert "cockpit-bluf" in html
    assert "cockpit-engine-strip" in html
    assert html.index("cockpit-bluf") < html.index("cockpit-engine-strip")
    assert "System diagnostics" not in html.split("cockpit-phase", 1)[0]


def test_cockpit_template_has_phase_rail() -> None:
    html = _template()

    assert "cockpit-phase-rail" in html
    assert "Candidates" in html
    assert "Portfolio" in html
    assert "Clearance" in html
    assert "Cleared" in html


def test_cockpit_template_has_four_phase_cells() -> None:
    html = _template()

    assert html.count("cockpit-phase-cell") >= 4


def test_cockpit_template_has_arc_gauge_primitives() -> None:
    html = _template()
    css = _styles()

    assert "cockpit-arc-gauge" in html
    assert "cockpit-arc-needle" in html
    assert ".cockpit-arc-gauge" in css
    assert ".cockpit-arc-needle" in css


def test_cockpit_template_has_segment_readouts() -> None:
    html = _template()
    css = _styles()

    assert "cockpit-segment-readout" in html
    assert ".cockpit-segment-readout" in css


def test_cockpit_template_has_whymark_threshold_tips() -> None:
    html = _template()

    assert "cockpit-whymark" in html
    assert "title=\"Gross exposure compares current exposure plus staged orders to the policy cap.\"" in html


def test_cockpit_template_has_engine_strip_with_data_hooks() -> None:
    html = _template()

    assert "cockpit-engine-strip" in html
    assert "data-cockpit-engine" in html
    assert "engine.state" in html


def test_cockpit_template_has_instrument_nav() -> None:
    html = _template()

    assert "cockpit-instrument-nav" in html
    assert "Universe" in html
    assert "Signals" in html
    assert "Audit" in html
    assert "Policy" in html
    assert "Monitor" in html


def test_cockpit_template_uses_mono_class_for_numeric_readouts() -> None:
    html = _template()
    css = _styles()

    assert "cockpit-mono" in html
    assert ".cockpit-mono" in css


def test_base_navigation_links_to_cockpit() -> None:
    base = Path("src/agency/templates/base.html").read_text(encoding="utf-8")

    assert "href=\"/cockpit\"" in base
    assert "Cockpit" in base


def test_cockpit_template_posts_research_review_actions() -> None:
    html = _template()

    assert "candidate.reviewable" in html
    assert "candidate.approve_review_action" in html
    assert "method=\"post\"" in html
    assert "Approve Research" in html


def test_cockpit_engine_strip_does_not_call_healthy_fresh_source_down() -> None:
    sources = _sample_sources()
    sources["dashboard"]["data_sources"] = [  # type: ignore[index]
        {
            "source": "daily-market-bars",
            "status": "HEALTHY",
            "freshness": "FRESH",
            "status_class": "block",
            "checked_at": "2026-05-22T13:19:42.098031+00:00",
        }
    ]

    context = cockpit_context_from_sources(sources)
    engine = context["engines"][0]

    assert engine["name"] == "daily-market-bars"
    assert engine["state"] == "needs_refresh"
    assert engine["age"] == "FRESH"
    assert "HEALTHY / FRESH" in engine["detail"]
