from __future__ import annotations

from pathlib import Path

from agency.views._shared import operator_status_label

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "src" / "agency" / "templates"
STATIC_ROOT = REPO_ROOT / "src" / "agency" / "static"


def _template(name: str) -> str:
    return (TEMPLATE_ROOT / name).read_text(encoding="utf-8")


def test_command_dashboard_starts_with_act_zone_and_review_queue() -> None:
    html = _template("dashboard.html")

    assert "operator-checklist-card" in html
    assert 'class="command-act-zone"' in html
    assert 'class="command-diagnose-zone"' in html
    assert html.index('class="command-act-zone"') < html.index('id="review-queue-heading"')
    assert html.index('id="review-queue-heading"') < html.index('class="command-diagnose-zone"')
    assert "System diagnostics" in html
    assert "advanced-detail" in html


def test_command_dashboard_uses_four_prioritized_kpis() -> None:
    html = _template("dashboard.html")
    kpi_grid = html.split('class="kpi-grid"', 1)[1].split("</section>", 1)[0]

    assert kpi_grid.count("<article") == 4
    assert "Needs Review" in kpi_grid
    assert "System Status" in kpi_grid
    assert "Data Coverage" in kpi_grid
    assert "Trade Gate" in kpi_grid
    assert "Contracts" not in kpi_grid
    assert "Provider Connections" not in kpi_grid
    assert "Lane Refresh" not in kpi_grid


def test_command_email_progress_is_conditional_not_idle_prime_real_estate() -> None:
    html = _template("dashboard.html")

    assert "email_alert_active" in html
    assert "email_progress_active" in html
    assert "subscription-pipeline" in html
    assert "No email article run recorded" not in html
    assert "No current subscription email article-analysis progress file was found." not in html


def test_command_dashboard_shows_visible_cache_and_data_freshness() -> None:
    html = _template("dashboard.html")

    assert "data-freshness" in html
    assert "command_freshness_label" in html
    assert "Data as of" in html or "Updated" in html


def test_operator_status_label_maps_domain_statuses_to_four_display_states() -> None:
    assert operator_status_label("PASS") == ("Ready", "ready")
    assert operator_status_label("ALLOW") == ("Ready", "ready")
    assert operator_status_label("WARN") == ("Attention", "attention")
    assert operator_status_label("BLOCK") == ("Blocked", "blocked")
    assert operator_status_label("NO_TRADE") == ("Inactive", "inactive")
    assert operator_status_label("DISABLED") == ("Inactive", "inactive")
    assert operator_status_label("") == ("Inactive", "inactive")


def test_operator_templates_avoid_sprint_one_jargon() -> None:
    combined = "\n".join(
        [
            _template("dashboard.html"),
            _template("base.html"),
            _template("execution_preview.html"),
            _template("cockpit.html"),
        ]
    )

    forbidden = [
        "Paper Promotion",
        "Execution Freshness Gate",
        "Operationability",
        "operationability",
        "BLUF",
        "client order",
        "Lane Refresh",
        "Massive data lanes",
        "Massive Lanes",
        "Live-Critical Due",
        "Repair Due",
        "Support Due",
    ]
    for phrase in forbidden:
        assert phrase not in combined


def test_styles_define_act_diagnose_and_status_vocabulary() -> None:
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".command-act-zone" in css
    assert ".command-diagnose-zone" in css
    assert ".operator-checklist-card" in css
    assert ".operator-state-ready" in css
    assert ".operator-state-attention" in css
    assert ".operator-state-blocked" in css
    assert ".operator-state-inactive" in css


def test_mobile_shell_keeps_cockpit_briefing_above_fold() -> None:
    css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    mobile_rules = css.split("@media (max-width: 640px)", 2)[-1]
    assert ".nav-list" in mobile_rules
    assert "overflow-x: auto" in mobile_rules
    assert ".workflow-breadcrumb" in mobile_rules
    assert ".workflow-breadcrumb-segment" in mobile_rules


def test_sidebar_uses_operator_workflow_labels_and_breadcrumb() -> None:
    html = _template("base.html")

    assert "Today's Cockpit" in html
    assert "System Status" in html
    assert "Review Candidates" in html
    assert "Submit Orders" in html
    assert "Today's cycle" in html
    assert "workflow-breadcrumb" in html
    assert html.index("Research") < html.index("Core workflow")
    assert "V3 Cockpit" not in html
    assert "Ops status" not in html
    assert ">Execute<" not in html


def test_cockpit_uses_dynamic_readiness_title_and_non_numeric_phases() -> None:
    html = _template("cockpit.html")

    assert "scenario.browser_title" in html
    assert "scenario.page_title" in html
    assert "Session readiness" in html
    assert "Action required" in html
    assert "data-phase-state" in html
    assert "phase_states" in html
    assert "cockpit-mono\">01" not in html
    assert "Phase 1 - Candidates" not in html


def test_candidate_detail_title_sticky_context_and_timestamps_are_decision_focused() -> None:
    html = _template("candidate_detail.html")

    assert "decision_brief.action_label" in html
    assert "decision_brief.top_reason_brief" in html
    assert "decision_brief.conviction_pct" in html
    assert "evidence_delta_since_review" in html
    assert "Data as of {{ signal.timestamp_label }}" in html
    assert "is ready for evidence review" not in html


def test_execution_preview_hides_hash_and_shows_traceable_operator_language() -> None:
    html = _template("execution_preview.html")

    assert "Eligibility" in html
    assert "order_integrity_label" in html
    assert "pipeline_chain" in html
    assert "Paper Promotion" not in html
    assert "Paper promotion checks" not in html
    assert "Intent hash" not in html


def test_shared_evidence_legend_and_conviction_tooltips_are_present() -> None:
    assert (TEMPLATE_ROOT / "_evidence_legend.html").exists()
    legend = _template("_evidence_legend.html")
    combined = "\n".join(
        [
            _template("cockpit.html"),
            _template("candidate_detail.html"),
            _template("final_selection.html"),
        ]
    )

    assert "confirmed direct data" in legend
    assert "evidence_legend" in combined
    assert combined.count("conviction-help") >= 3
    assert "Conviction combines" in combined


def test_cockpit_clearance_phrase_gives_live_feedback() -> None:
    html = _template("cockpit.html")
    script = (STATIC_ROOT / "cockpit.js").read_text(encoding="utf-8")

    assert 'placeholder="submit paper orders"' in html
    assert "data-cockpit-submit-feedback" in html
    assert "Confirm &amp; Submit Paper Orders" in html
    assert "Phrase matches" in script
    assert "Type the exact phrase" in script


def test_scheduler_impact_and_tooltip_registry_are_documented() -> None:
    html = _template("dashboard.html")
    registry = REPO_ROOT / "docs" / "TOOLTIP_REGISTRY.md"

    assert registry.exists()
    assert "scheduler_candidate_impact" in html
    assert "Candidate impact" in html
    assert "Trade Eligibility" in registry.read_text(encoding="utf-8")
