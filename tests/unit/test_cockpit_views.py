from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "src/agency/templates/cockpit.html"
PANELS = REPO_ROOT / "src/agency/templates/_cockpit_panels.html"
BASE_TEMPLATE = REPO_ROOT / "src/agency/templates/base.html"
STYLES = REPO_ROOT / "src/agency/static/styles.css"
V3_STYLES = REPO_ROOT / "src/agency/static/v3-screens.css"
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


def test_cockpit_template_exposes_dashboard_navigation() -> None:
    html = _template()

    assert "cockpit-dashboard-nav" in html
    assert "Open dashboards" in html
    assert 'href="/signals"' in html
    assert 'href="/signals?lane=fundamentals#signal-rows-heading"' in html
    assert "Fundamentals &amp; SEC" in html
    assert 'href="/portfolio-monitor"' in html
    assert 'href="/market-regime"' in html
    assert 'href="/command"' in html


def test_cockpit_template_exposes_persistent_sa_email_agent_controls() -> None:
    html = _template()
    css = V3_STYLES.read_text(encoding="utf-8")

    assert "cockpit-email-agent-control" in html
    assert "Seeking Alpha login and article analysis" in html
    assert 'action="/scheduler/subscription-emails/login-refresh?return_to=cockpit"' in html
    assert "Open SA browser and verify login" in html
    assert (
        'action="/scheduler/subscription-emails/continue-after-login?return_to=cockpit"'
        in html
    )
    assert "I logged in - analyze unread SA emails" in html
    assert ".cockpit-email-agent-control" in css


def test_cockpit_mobile_primary_actions_keep_touch_target_height() -> None:
    css = V3_STYLES.read_text(encoding="utf-8")

    assert ".v3-screen-cockpit .cockpit-primary-action .button" in css
    assert ".v3-screen-cockpit .cockpit-top-actions .button" in css
    assert "min-height: 46px" not in css
    assert "min-height: 54px" in css


def test_cockpit_template_uses_mono_class_for_numeric_readouts() -> None:
    html = _template()
    css = _styles()

    assert "cockpit-mono" in html
    assert ".cockpit-mono" in css


def test_base_brand_links_to_cockpit_and_marks_legacy_routes_diagnostic() -> None:
    base = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert '<a class="brand" href="/cockpit">' in base
    assert "href=\"/cockpit\"" in base
    assert "Cockpit" in base
    assert "Diagnostics: System Status" in base
    assert "Legacy workflow diagnostics" in base
    assert "Diagnostic: Order Preview" in base
    assert "data-enable-heartbeat" in base


def test_cockpit_template_posts_research_review_actions() -> None:
    html = _template()

    assert "candidate.reviewable" in html
    assert "candidate.approve_review_action" in html
    assert "method=\"post\"" in html
    assert "Approve Research" in html


def test_cockpit_paused_data_proof_keeps_candidates_visible_for_inspection() -> None:
    html = _template()
    css = _styles()

    assert 'candidate_actions_paused = scenario.state in ["outage", "status-delayed"]' in html
    assert 'scenario.state != "no-actionable"' not in html
    assert 'scenario.state not in ["outage", "status-delayed", "no-actionable"]' not in html
    assert "cockpit-candidate-table-paused" in html
    assert "Inspect ticker" in html
    assert "before approving or sending this ticker forward" in html
    assert "Reason: {{ scenario.detail" in html
    assert "Proof: {{ scenario.last_good_cycle_label" in html
    assert "Existing candidates remain visible below for inspection." in html
    assert ".cockpit-candidate-table-paused" in css


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


def test_cockpit_script_allows_phase_navigation_in_safety_scenarios() -> None:
    script = COCKPIT_JS.read_text(encoding="utf-8")

    assert 'scenarioState === "submitted" ? "cleared"' in script
    assert (
        'scenarioState === "outage" || scenarioState === "status-delayed"'
        in script
    )
    assert 'scenarioState === "no-actionable"' in script
    assert "function scenarioSafePhase(phase)" in script
    assert "return phase || defaultPhase;" in script
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
