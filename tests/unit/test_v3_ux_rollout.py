from __future__ import annotations

from pathlib import Path

TEMPLATE_ROOT = Path("src/agency/templates")
BASE = TEMPLATE_ROOT / "base.html"
STATIC_ROOT = Path("src/agency/static")

V3_SCREEN_TEMPLATES = [
    "audit.html",
    "candidate_detail.html",
    "cockpit.html",
    "dashboard.html",
    "execution_preview.html",
    "final_selection.html",
    "learning.html",
    "market_regime.html",
    "policy.html",
    "portfolio_monitor.html",
    "risk.html",
    "signals.html",
]

V3_NON_COCKPIT_TEMPLATES = [
    name for name in V3_SCREEN_TEMPLATES if name != "cockpit.html"
]

FORBIDDEN_V3_COPY = (
    "ux-v3-visible-20260523",
    "ux-v3-all-screens-20260522",
    "ux-v3-review-readable-2-20260522",
    "ux-v3-rich-ticker-detail-20260522",
    "first-version",
)

DEFAULT_BRIEFING_SNIPPETS = (
    "Start with the first action card",
    "This screen must show current source proof",
    "Pre-flight review",
)


def _template(name: str) -> str:
    return (TEMPLATE_ROOT / name).read_text(encoding="utf-8")


def _css_block(css: str, selector: str) -> str:
    return css.split(selector, 1)[1].split("}", 1)[0]


def test_shared_base_declares_v3_operating_shell() -> None:
    html = BASE.read_text(encoding="utf-8")

    assert 'data-ux-version="v3"' in html
    assert 'data-ux-build="ux-v3-all-dashboards-20260523"' in html
    assert "Trading Agency v3" in html
    assert "UX V3" in html
    assert "Pre-Flight" in html
    assert "Today's Cockpit" in html
    assert "System Status" in html
    assert "PAPER" in html
    assert "v3-phase-rail" in html
    assert "/static/v3-screens.css" in html
    assert "ux-v3-visible-20260523" not in html
    assert "ux-v3-all-screens-20260522" not in html
    assert "ux-v3-review-readable-2-20260522" not in html
    assert "Candidates" in html
    assert "Portfolio" in html
    assert "Clearance" in html
    assert "Cleared" in html
    assert "active_nav in ['audit', 'cleared']" in html


def test_all_primary_screens_have_bottom_line_page_titles() -> None:
    generic_titles = {
        "Command",
        "Signals",
        "Risk",
        "Policy",
        "Learning",
        "Runtime Audit",
        "Final Selection",
        "Execution Preview",
        "Portfolio Monitor",
        "Universe &amp; Market Regime",
        "{{ ticker }}",
    }

    for name in V3_SCREEN_TEMPLATES:
        html = _template(name)
        assert "Trading Agency v2" not in html, name
        page_title_line = next(
            line.strip()
            for line in html.splitlines()
            if line.strip().startswith("{% block page_title %}")
        )
        title = (
            page_title_line.removeprefix("{% block page_title %}")
            .removesuffix("{% endblock %}")
            .strip()
        )
        assert title not in generic_titles, name
        assert any(token in title.lower() for token in ("ready", "review", "shows", "tracks", "guards", "proves", "clears", "briefs", "today")), name


def test_every_non_cockpit_dashboard_keeps_data_health_visible() -> None:
    for name in V3_SCREEN_TEMPLATES:
        if name == "cockpit.html":
            continue
        html = _template(name)
        assert '{% from "_data_health.html" import data_health_panel %}' in html, name
        assert "{{ data_health_panel(data_health) }}" in html, name


def test_shared_base_renders_visible_v3_briefing_contract() -> None:
    html = BASE.read_text(encoding="utf-8")

    assert "v3-screen-{{ v3_screen" in html
    assert 'data-v3-screen="{{ v3_screen' in html
    assert 'data-v3-universal-briefing' in html
    assert "v3-briefing-strip" in html
    assert "{% block workflow_phase %}" in html
    assert "{% block operator_focus %}" in html
    assert "{% block evidence_contract %}" in html
    assert "Bottom line" in html
    assert "Evidence" in html
    assert "Operator move" in html


def test_every_non_cockpit_dashboard_declares_v3_identity_and_brief() -> None:
    for name in V3_NON_COCKPIT_TEMPLATES:
        html = _template(name)
        assert "{% set v3_screen =" in html, name
        assert "{% block workflow_phase %}" in html, name
        assert "{% block operator_focus %}" in html, name
        assert "{% block evidence_contract %}" in html, name


def test_v3_templates_do_not_ship_stale_tokens_or_legacy_copy() -> None:
    for name in V3_SCREEN_TEMPLATES:
        html = _template(name)
        for token in FORBIDDEN_V3_COPY:
            assert token not in html, f"{name}: {token}"


def test_every_non_cockpit_dashboard_briefing_is_route_specific() -> None:
    for name in V3_NON_COCKPIT_TEMPLATES:
        html = _template(name)
        for snippet in DEFAULT_BRIEFING_SNIPPETS:
            assert snippet not in html, f"{name}: {snippet}"


def test_v3_css_defines_shared_briefing_and_data_health_treatment() -> None:
    css = (STATIC_ROOT / "v3-screens.css").read_text(encoding="utf-8")

    assert ".v3-phase-rail" in css
    assert ".v3-briefing-strip" in css
    assert ".v3-briefing-card" in css
    assert ".v3-bluf-panel" in css
    assert ".data-health-panel" in css
    assert "font-variant-numeric: tabular-nums" in css
    assert "grid-template-columns: repeat(4" in css


def test_v3_css_owns_primary_body_components() -> None:
    css = (STATIC_ROOT / "v3-screens.css").read_text(encoding="utf-8")

    required_selectors = [
        ".v3-app .selection-row",
        ".v3-app .reason-code-row",
        ".v3-app .rationale-card",
        ".v3-app .llm-summary-panel",
        ".v3-app .execution-preview-card",
        ".v3-app .guidance-card",
        ".v3-app .gate-row",
        ".v3-app .details-panel summary",
        ".v3-app input",
        ".v3-app textarea",
        ".v3-app select",
        ".v3-app .disabled-button",
        ".v3-app .table-wrap",
    ]

    for selector in required_selectors:
        assert selector in css, selector


def test_v3_shared_buttons_are_centered_readable_and_link_safe() -> None:
    css = (STATIC_ROOT / "v3-screens.css").read_text(encoding="utf-8")

    button_block = _css_block(css, ".v3-app .primary-action,\n.v3-app .secondary-action,\n.v3-app .mini-button,\n.v3-app .button")
    secondary_block = _css_block(css, ".v3-app .secondary-action,\n.v3-app .button-secondary")

    assert "display: inline-flex" in button_block
    assert "align-items: center" in button_block
    assert "justify-content: center" in button_block
    assert "text-align: center" in button_block
    assert "text-decoration: none" in button_block
    assert "color: var(--v3-text)" in secondary_block
    assert "background: var(--v3-surface-2)" in secondary_block


def test_v3_templates_do_not_ship_inline_form_styles() -> None:
    for name in V3_SCREEN_TEMPLATES:
        html = _template(name)
        for line in html.splitlines():
            assert not (("<input" in line or "<textarea" in line or "<select" in line) and 'style="' in line), name


def test_v3_tables_keep_mobile_labels_on_all_non_cockpit_screens() -> None:
    for name in V3_NON_COCKPIT_TEMPLATES:
        html = _template(name)
        table_body = "\n".join(
            line.strip()
            for line in html.splitlines()
            if line.strip().startswith("<td") and "empty-row" not in line
        )
        if not table_body:
            continue
        assert "data-label=" in table_body, name
        for line in table_body.splitlines():
            if "colspan=" in line:
                continue
            assert "data-label=" in line, f"{name}: {line}"


def test_v3_final_selection_rows_expose_decisions_and_visible_provenance() -> None:
    html = _template("final_selection.html")

    assert "selection-provenance-visible" in html
    assert "selection-decision-actions" in html
    assert "approve_review_action" in html
    assert "defer_review_action" in html
    assert "reject_review_action" in html
    assert "LLM status" in html
    assert "Evidence Proof" in html


def test_v3_execution_submit_uses_human_clearance_gate() -> None:
    html = _template("execution_preview.html")

    assert "submit-gate-form" in html
    assert "submit_gate_armed" in html
    assert "submit paper orders" in html
    assert "execution-proof-strip" in html
