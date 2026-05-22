from __future__ import annotations

from pathlib import Path

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
