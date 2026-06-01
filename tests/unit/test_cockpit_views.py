from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "src/agency/templates/cockpit.html"
PANELS = REPO_ROOT / "src/agency/templates/_cockpit_panels.html"
BASE_TEMPLATE = REPO_ROOT / "src/agency/templates/base.html"
STYLES = REPO_ROOT / "src/agency/static/styles.css"
COCKPIT_JS = REPO_ROOT / "src/agency/static/cockpit.js"
DATA_REFRESH_PROGRESS_JS = REPO_ROOT / "src/agency/static/data-refresh-progress.js"


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


def test_cockpit_gauge_needles_are_data_driven_not_literal_angles() -> None:
    html = _template()
    context = cockpit_context_from_sources(_sample_sources())
    account = context["account"]
    market = context["market"]

    for literal in ('style="--needle: 52deg"', 'style="--needle: 36deg"', 'style="--needle: 44deg"', 'style="--needle: 18deg"'):
        assert literal not in html
    assert "market.needle_degrees" in html
    assert "account.gross_needle_degrees" in html
    assert "account.cash_needle_degrees" in html
    assert "account.concentration_needle_degrees" in html
    assert account["gross_needle_degrees"] == -24
    assert account["cash_needle_degrees"] == 90
    assert account["concentration_needle_degrees"] == -90
    assert market["needle_degrees"] == 0


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


def test_base_brand_links_to_command_without_demoting_cockpit_nav() -> None:
    base = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert '<a class="brand" href="/command">' in base
    assert "href=\"/cockpit\"" in base
    assert "Cockpit" in base
    assert "data-enable-heartbeat" in base


def test_cockpit_template_posts_research_review_actions() -> None:
    html = _template()

    assert "candidate.reviewable" in html
    assert "candidate.approve_review_action" in html
    assert "method=\"post\"" in html
    assert "Approve Research" in html


def test_cockpit_static_controls_are_truthful_and_filterable() -> None:
    html = _template()
    panels = PANELS.read_text(encoding="utf-8")
    script = COCKPIT_JS.read_text(encoding="utf-8")

    assert 'data-cockpit-ready="true"' not in html
    assert "data-cockpit-ticker-payload='{{ candidate|tojson }}'" in html
    assert 'data-cockpit-ticker-payload="{{ candidate|tojson|safe }}"' not in html
    assert 'class="cockpit-phase-cell active"' not in html
    assert "window.confirm(" not in script
    assert "showRestoreNotice(" in script
    assert "setupReviewActionForms()" in DATA_REFRESH_PROGRESS_JS.read_text(
        encoding="utf-8"
    )
    assert 'document.querySelector(".topbar")?.setAttribute("hidden", "")' in script
    assert 'document.querySelector(".v3-phase-rail")?.setAttribute("hidden", "")' in script
    assert "data-signal-filter" in script
    assert "data-monitor-filter" in script
    assert "cockpit-signal-item signal-{{ signal.tier|lower" in panels
    assert "cockpit-monitor-item monitor-{{ event.status_class|default('info', true)|lower" in panels


def test_cockpit_script_forces_safety_scenario_starting_phase() -> None:
    script = COCKPIT_JS.read_text(encoding="utf-8")

    assert 'scenarioState === "submitted" ? "cleared"' in script
    assert 'scenarioState === "outage" || scenarioState === "no-actionable"' in script
    assert "function scenarioSafePhase(phase)" in script
    assert "state.phase = scenarioSafePhase(pendingRestore.phase)" in script
    assert "submitGateInvalidated = true" in script


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
