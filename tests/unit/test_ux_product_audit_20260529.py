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
            _template("_cockpit_panels.html"),
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
        " blocker(s)",
        "Blockers",
        "blocker checks",
        "Cycle-level blockers",
        "No readiness blockers",
        "exact blocker",
        "promotion blockers",
        "promotion status and blocker",
        "Blocker:",
        "Trading Freshness Gate",
        "hash-bound",
        "Evidence hash",
        "evidence pack hash",
        "raw large-dataset",
        " due / {{ scheduler.massive_orchestrator.blocked_count }} blocked",
    ]
    for phrase in forbidden:
        assert phrase not in combined


def test_operator_view_models_avoid_visible_blocker_copy() -> None:
    combined = "\n".join(
        [
            (REPO_ROOT / "src" / "agency" / "views" / "command.py").read_text(
                encoding="utf-8"
            ),
            (REPO_ROOT / "src" / "agency" / "views" / "execution.py").read_text(
                encoding="utf-8"
            ),
            (REPO_ROOT / "src" / "agency" / "views" / "risk.py").read_text(
                encoding="utf-8"
            ),
            (REPO_ROOT / "src" / "agency" / "services" / "paper_trade_promotion.py").read_text(
                encoding="utf-8"
            ),
            (REPO_ROOT / "src" / "agency" / "static" / "data-refresh-progress.js").read_text(
                encoding="utf-8"
            ),
        ]
    )

    forbidden = [
        "No blockers detected.",
        "blocker(s) need attention",
        "blocker_count', 0)} blocker(s)",
        "Hard blockers stop",
        "Blockers are missing",
        "blocker prevents",
        "Current blocker:",
        "Blocker: {reason}",
        "No active load blocker",
        "Risk did not find a blocker",
        "Main blocker:",
        "No blocker or warning gate",
        "Blocked by risk policy",
        "Blocked after warnings",
        "operationability gaps",
        "live-critical due",
        "support due",
        "repair due",
        "Next live-critical ETA",
        "live-critical evidence",
        "hash-bound",
        "blocking gate",
        "blocking policy",
        "Blocked by selection policy",
        "Blocked by the active universe policy",
        "non-blocking evidence",
        "paper-promotion checks",
        "paper promotion threshold",
        "Review the order hash",
        "accepted this paper-promotion block",
        "Lane Refresh",
        "blocking until inspected",
    ]
    for phrase in forbidden:
        assert phrase not in combined


def test_signal_surfaces_use_friendly_process_labels() -> None:
    candidate_html = _template("candidate_detail.html")
    signals_html = _template("signals.html")
    cockpit_js = (STATIC_ROOT / "cockpit.js").read_text(encoding="utf-8")

    assert "{{ signal.display_name }}" in candidate_html
    assert "{{ row.display_name }}" in signals_html
    assert "{{ signal.lane }}" not in candidate_html
    assert "signal.lane ||" not in cockpit_js


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
    nav_html = html.split('<nav class="workflow-breadcrumb"', 1)[0]

    assert "Today's Cockpit" in html
    assert "System Status" in html
    assert "Review Candidates" in html
    assert "Submit Orders" in html
    assert "Market &amp; Universe" in html
    assert "Signal Analysis" in html
    assert "Risk Rules" in html
    assert "Trading Policy" in html
    assert "Audit Trail" in html
    assert "Today's cycle" in html
    assert "workflow-breadcrumb" in html
    assert html.index("Research") < html.index("Core workflow")
    assert "V3 Cockpit" not in html
    assert "Ops status" not in html
    assert "Universe &amp; market" not in nav_html
    assert ">Signals<" not in nav_html
    assert ">Risk<" not in nav_html
    assert ">Policy<" not in nav_html
    assert ">Execute<" not in nav_html


def test_global_phase_rail_uses_plain_workflow_not_numeric_steps() -> None:
    html = _template("base.html")

    assert "v3-phase-index" not in html
    assert "Review Candidates" in html
    assert "Portfolio Check" in html
    assert "Order Clearance" in html
    assert "Order Audit" in html
    assert ">01<" not in html
    assert ">02<" not in html
    assert ">03<" not in html
    assert ">04<" not in html


def test_cockpit_uses_dynamic_readiness_title_and_non_numeric_phases() -> None:
    html = _template("cockpit.html")

    assert "scenario.browser_title" in html
    assert "scenario.page_title" in html
    assert "Session readiness" in html
    assert "Action required" in html
    assert "data-phase-state" in html
    assert "phase_states" in html
    assert "candidate-action-legend" in html
    assert "Why buttons change" in html
    assert "Review order details" in html
    assert "cockpit-mono\">01" not in html
    assert "Phase 1 - Candidates" not in html


def test_candidate_detail_title_sticky_context_and_timestamps_are_decision_focused() -> None:
    html = _template("candidate_detail.html")

    assert "Agent recommends" in html
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
    assert "Policy-stopped / context-only" in html
    assert "Preview archive" in html
    assert "No transaction / stopped by policy" in html
    assert "Paper Promotion" not in html
    assert "Paper promotion checks" not in html
    assert "Intent hash" not in html
    assert "NO_TRADE / BLOCKED" not in html
    assert "blocked/no-order" not in html


def test_final_selection_archive_labels_are_plain_language() -> None:
    html = _template("final_selection.html")

    assert "Context-Only Archive" in html
    assert "Policy-Gated Archive" in html
    assert "No-trade context rows" in html
    assert "Policy-gated rows" in html
    assert "NO_TRADE - Context Only" not in html
    assert "BLOCKED - Policy Traceability" not in html


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

    assert 'placeholder="type: submit paper orders"' in html
    assert "Confirmation phrase" in html
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


def test_lane_state_copy_uses_operator_language() -> None:
    combined = "\n".join(
        [
            (REPO_ROOT / "src" / "agency" / "views" / "command.py").read_text(encoding="utf-8"),
            (REPO_ROOT / "src" / "agency" / "views" / "_shared.py").read_text(encoding="utf-8"),
            (REPO_ROOT / "src" / "agency" / "views" / "cockpit.py").read_text(encoding="utf-8"),
            _template("dashboard.html"),
            _template("_cockpit_panels.html"),
            _template("_data_health.html"),
            (STATIC_ROOT / "data-refresh-progress.js").read_text(encoding="utf-8"),
        ]
    )
    forbidden = [
        "Massive multi-lane",
        "Massive lane",
        "Massive lanes",
        "Massive-backed",
        "Raw lane",
        "raw lane",
        "lane-level scope only",
        "No lane reason recorded",
        "Fix lane blocker",
        "Waiting For Raw Lane",
        "Ready From Live Slices",
        "No data-load blockers",
        "No lane-state registry rows",
        "No lane-state explanation",
        "No lane action",
        "Data Pipeline State Board",
        "Blocks paper?",
        "Extraction lane states",
        "Blocking reason",
        "Live Health Monitor",
        "Health Monitor Status",
        "No Massive stock-trades",
        "Execution-Critical",
        "Execution-critical",
        "Run lane refresh",
        "Refresh lane",
        "Lane-level refresh",
        "lane refresh",
        "data lane",
        "this lane",
        "No lane detail recorded",
        "No direct lane refresh",
        "Signal lane",
        "signal lane rows",
        "narrative lanes",
    ]
    for phrase in forbidden:
        assert phrase not in combined
