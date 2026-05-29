from __future__ import annotations

from pathlib import Path

from service_fixtures import selection_report

from agency.services import PortfolioPolicy, build_execution_preview, build_portfolio_monitor
from agency.services.human_review import selection_report_hash
from agency.services.paper_trade_promotion import (
    PaperTradePromotionConfig,
    promote_paper_trade_reports,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "src/agency/templates"
STYLE_PATH = REPO_ROOT / "src/agency/static/styles.css"
V3_STYLE_PATH = REPO_ROOT / "src/agency/static/v3-screens.css"
DATA_REFRESH_PROGRESS_JS = REPO_ROOT / "src/agency/static/data-refresh-progress.js"
COCKPIT_JS = REPO_ROOT / "src/agency/static/cockpit.js"
COMMAND_VIEW = REPO_ROOT / "src/agency/views/command.py"


def _template(name: str) -> str:
    return (TEMPLATE_ROOT / name).read_text(encoding="utf-8")


def test_final_selection_surfaces_actionable_decision_before_details() -> None:
    html = _template("final_selection.html")

    assert "Selected" in html
    assert "No-Trade" in html
    assert "watch_rows" in html
    assert "no_trade_rows" in html
    assert "blocked_rows" in html
    assert "top-visible-reasons" in html
    assert "technical-provenance" in html


def test_final_selection_preserves_ticker_focus_and_action_labels() -> None:
    html = _template("final_selection.html")

    assert "focused_final_selection" in html
    assert "Show full candidate queue" in html
    assert "watch_rows[:12]" in html
    assert "no_trade_rows[:12]" in html
    assert "blocked_rows[:20]" in html
    assert 'id="candidate-{{ row.ticker }}"' in html
    assert 'href="/candidates/{{ row.ticker }}?from=final-selection#candidate-{{ row.ticker }}"' in html
    assert "Approve research for {{ row.ticker }}" in html
    assert "Defer {{ row.ticker }} review" in html
    assert "Reject {{ row.ticker }} candidate" in html


def test_final_selection_shows_readable_provenance_and_cycle_ids() -> None:
    html = _template("final_selection.html")
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "selection-provenance" in html
    assert "freshness_proof_label" in html
    assert "provenance_items" in html
    assert "cycle-id-chip" in html
    assert 'title="{{ summary.cycle_id }}"' in html
    assert ".selection-provenance" in css
    assert ".cycle-id-chip" in css

    provenance_block = css.split(".selection-provenance", 1)[1].split("}", 1)[0]
    cycle_chip_block = css.split(".cycle-id-chip", 1)[1].split("}", 1)[0]
    assert "grid-column: 1 / -1" in provenance_block
    assert "overflow-wrap: anywhere" in provenance_block
    assert "white-space: normal" in cycle_chip_block
    assert "overflow-wrap: anywhere" in cycle_chip_block


def test_command_dashboard_has_queue_cta_and_collapsed_diagnostics() -> None:
    html = _template("dashboard.html")

    assert "operator-checklist-card" in html
    assert "operator-checklist-grid" in html
    assert "command-act-zone" in html
    assert "Trade Gate" in html
    assert "Today&apos;s workflow" in html
    assert "Review {{ review_progress.pending_count }} candidates" in html
    assert "href=\"#review-queue-heading\"" in html
    assert "data-freshness" in html
    assert "scheduler-candidate-impact" in html
    assert "System diagnostics" in html
    assert "Data Sources" in html
    assert "review-state-icon" in html
    assert "Blocked by risk" not in html


def test_command_review_forms_are_labeled_for_progressive_enhancement() -> None:
    html = _template("dashboard.html")
    script = DATA_REFRESH_PROGRESS_JS.read_text(encoding="utf-8")

    assert 'class="review-action-form"' in html
    assert 'data-review-action="approve"' in html
    assert 'data-review-action="defer"' in html
    assert 'data-review-action="reject"' in html
    assert 'data-review-ticker="{{ item.ticker }}"' in html
    assert "setupReviewActionForms()" in script
    assert ".review-action-form" in script
    assert "event.preventDefault()" in script
    assert "fetch(form.action" in script
    assert "form.replaceChildren(output)" in script
    assert "[data-review-status]" in script


def test_command_uses_shared_duration_humanizer() -> None:
    source = COMMAND_VIEW.read_text(encoding="utf-8")

    assert "_humanize_seconds_in_text," in source
    assert "def _humanize_seconds_in_text" not in source
    assert "def _duration_label" not in source


def test_candidate_detail_prioritizes_decision_and_collapses_technical_detail() -> None:
    html = _template("candidate_detail.html")

    assert "candidate_return.label" in html
    assert "candidate_return.href" in html
    assert "decision-hero-recommendation" in html
    assert "llm-summary-panel" in html
    assert "LLM Recommendation" in html
    assert "latest_report.llm_rationale" in html
    assert "currently_holding" in html
    assert "Supporting detail" in html
    assert "technical-provenance" in html
    assert "Email/article evidence" in html
    assert "Score impact" in html
    assert "Approved - execution preview updated" in html
    assert "Blocked Signals" not in html
    assert "blocked signals" not in html
    assert "Excluded Signals" in html


def test_portfolio_monitor_contains_exit_recommendation_workflow() -> None:
    html = _template("portfolio_monitor.html")

    assert "Total exposure" in html
    assert "Max allowed" in html
    assert "Go to Candidates" in html
    assert "Exit Recommendations" in html
    assert "exposure_freed_label" in html
    assert "Review exit plan for {{ position.ticker }}" in html
    assert 'href="/execution-preview?ticker={{ position.ticker }}#focused-preview-{{ position.ticker }}"' in html
    assert "Portfolio within policy - no exits needed" in html
    assert "Execution Preview" in html
    assert "pnl-value" in html


def test_risk_and_execution_templates_show_llm_and_order_workflow_status() -> None:
    risk_html = _template("risk.html")
    execution_html = _template("execution_preview.html")

    assert "Ready to review" in risk_html
    assert "Blocked by policy" in risk_html
    assert "Needs data" in risk_html
    assert "Agent checked - OK" in risk_html
    assert "Risk matrix" in risk_html
    assert "llm_action" in risk_html
    assert "deterministic_score_label" in risk_html

    assert "paper-mode-card" in execution_html
    assert "LLM status" in execution_html
    assert "llm_conflict" in execution_html
    assert "Submit each ready order from its card" in execution_html
    assert "Submitted paper order" in execution_html
    focused_block = execution_html.split("focused-execution-gates", 1)[1].split("{% else %}", 1)[0]
    assert "LLM status" in focused_block
    assert "Data currency check" in focused_block
    assert "Submission Gate" in focused_block
    assert "Broker" in focused_block


def test_execution_preview_paper_cards_are_readable() -> None:
    execution_html = _template("execution_preview.html")
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "execution-preview-card paper-mode-card" in execution_html
    assert "review_only_rows[:8]" in execution_html
    assert "blocked_rows[:25]" in execution_html
    assert "Open ticker-specific review" in execution_html
    assert "execution-review-status" in execution_html
    assert "execution-metric-value" in execution_html
    assert "execution-blocker-list" in execution_html
    assert ".execution-preview-card.paper-mode-card" in css
    assert ".execution-preview-card .review-card-metrics" in css
    assert ".execution-preview-card .review-card-metrics strong" in css
    assert ".execution-review-status" in css
    assert ".execution-blocker-list" in css

    execution_metric_block = css.split(".execution-preview-card .review-card-metrics strong", 1)[1].split("}", 1)[0]
    assert "word-break: normal" in execution_metric_block
    assert "hyphens: none" in execution_metric_block


def test_data_refresh_meter_is_module_scoped_before_iifes() -> None:
    script = DATA_REFRESH_PROGRESS_JS.read_text(encoding="utf-8")
    assert "const meter = (percent)" in script
    assert script.index("const meter = (percent)") < script.index("(() => {")
    data_load_section = script.split('const panel = document.querySelector("[data-load-panel]");', 1)[1]
    assert "const meter = (percent)" not in data_load_section


def test_data_health_panel_uses_actionable_user_copy_not_internal_telemetry() -> None:
    html = _template("_data_health.html")

    assert "What this means" in html
    assert "Recommended action" in html
    assert "Blocking reason" in html
    assert "Show operational diagnostics" in html
    assert "row.blocking_reason" in html
    assert "row.recommended_action" in html
    assert "row.why_it_matters" in html
    assert "data_health.action_buttons" in html
    assert "button" in html
    assert "data_health.lane_state_rows" in html
    assert "Extraction lane states" in html


def test_operator_data_health_copy_does_not_use_stale_wording() -> None:
    dashboard_html = _template("dashboard.html")
    signals_html = _template("signals.html")
    progress_js = DATA_REFRESH_PROGRESS_JS.read_text(encoding="utf-8")

    forbidden_visible_copy = [
        "Refresh Status Stale",
        "Health check stale",
        "Stale Or Warning",
        "No stale scheduler",
        "treat the page as stale",
        "treat the dashboard as stale",
        "visible progress may be stale",
        "return \"Stale\"",
        "staleness",
    ]

    combined = "\n".join([dashboard_html, signals_html, progress_js])
    for phrase in forbidden_visible_copy:
        assert phrase not in combined


def test_command_lane_tables_show_eta_and_progress_meters() -> None:
    dashboard_html = _template("dashboard.html")
    progress_js = DATA_REFRESH_PROGRESS_JS.read_text(encoding="utf-8")

    assert "lane.progress_meter_label" in dashboard_html
    assert "lane.progress_style" in dashboard_html
    assert "row.progress_meter_label" in dashboard_html
    assert "row.eta_label" in dashboard_html
    assert "lane.progress_percent" in progress_js
    assert "item.progress_percent" in progress_js
    assert "lane.progress_detail_label" in progress_js


def test_cockpit_local_storage_cannot_restore_server_approval_markers() -> None:
    script = COCKPIT_JS.read_text(encoding="utf-8")
    decision_block = script.split(
        'document.querySelectorAll("[data-cockpit-decision]").forEach',
        1,
    )[1].split(
        'document.querySelectorAll("[data-cockpit-exit]").forEach',
        1,
    )[0]

    assert "isServerDecisionButton(button)" in decision_block
    assert "markServerDecisionPending(button, decision)" in decision_block
    assert (
        decision_block.index("isServerDecisionButton(button)")
        < decision_block.index("state.decisions[ticker] = decision")
    )
    assert "discardLegacyServerDecisionMarkers()" in script
    assert "server approval" in script


def test_candidate_email_readout_avoids_bad_word_breaks() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    readout_block = css.split(".readout-card strong", 1)[1].split("}", 1)[0]
    assert "overflow-wrap: break-word" in readout_block
    assert "word-break: normal" in readout_block
    assert "hyphens: none" in readout_block


def test_dark_disclosures_and_signal_evidence_keep_readable_contrast() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert ".details-panel.shared-disclosure" in css
    assert ".shared-disclosure > summary" in css
    assert "background: var(--surface-2)" in css
    assert ".llm-summary-panel" in css
    assert ".signal-evidence-panel .shared-disclosure" in css


def test_base_audit_and_styles_expose_shared_design_system_markers() -> None:
    base_html = _template("base.html")
    audit_html = _template("audit.html")
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "workflow-nav" in base_html
    assert "status-icon" in base_html
    assert "nav-secondary" in base_html
    assert "ux-v3-all-dashboards-20260523" in base_html
    assert "paper-mode-card" in audit_html
    assert "Show details: LLM rationale" in audit_html
    assert ".paper-mode-card" in css
    assert ".status-icon" in css
    assert ".tag-urgent" in css
    assert ".shared-disclosure" in css
    assert ".action-approve" in css


def test_review_queue_ready_badge_has_readable_contrast() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert ".tag-urgent" in css
    urgent_block = css.split(".tag-urgent {", 1)[1].split("}", 1)[0]
    assert "color: var(--text)" in urgent_block
    assert "#7a2500" not in urgent_block
    assert "font-weight: 800" in urgent_block
    assert ".review-state-icon" in css


def test_v3_status_tags_keep_readable_text_spacing() -> None:
    css = V3_STYLE_PATH.read_text(encoding="utf-8")

    tag_block = css.split(".v3-app .tag,", 1)[1].split("}", 1)[0]
    assert "letter-spacing: 0" in tag_block
    assert "text-transform: none" in tag_block
    assert "font-weight: 700" in tag_block


def test_review_queue_metric_values_do_not_break_words() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert ".review-card .review-card-metrics strong" in css
    metric_block = css.split(".review-card .review-card-metrics strong {", 1)[1].split("}", 1)[0]
    assert "word-break: normal" in metric_block
    assert "hyphens: none" in metric_block


def test_disabled_mini_buttons_are_visually_muted() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert ".mini-button:disabled" in css
    disabled_block = css.split(".mini-button:disabled", 1)[1].split("}", 1)[0]
    assert "cursor: not-allowed" in disabled_block
    assert "var(--text-muted)" in disabled_block
    assert "var(--surface-2)" in disabled_block


def test_operational_tooltips_are_keyboard_accessible() -> None:
    base_html = _template("base.html")
    data_health_html = _template("_data_health.html")
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "enhanceInfoTips" in base_html
    assert "tip.tabIndex = 0" in base_html
    assert "tip.dataset.tooltip" in base_html
    assert 'data-tooltip="{{ item.tooltip' in data_health_html
    assert ".info-tip:focus-visible::after" in css
    assert "content: attr(data-tooltip)" in css


def test_dark_muted_text_uses_readable_contrast_tokens() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "--text-muted: #aeb6c6" in css
    assert "--muted: var(--text-dim)" in css
    assert ".muted-line" in css


def test_portfolio_monitor_uses_operational_empty_states_not_none() -> None:
    html = _template("portfolio_monitor.html")

    assert "Broker offline" in html
    assert "No current thesis" in html
    assert "No position size" in html
    assert 'or "None"' not in html
    assert "else %}None" not in html


def test_hero_step_numbers_match_sidebar_navigation() -> None:
    for template_name in (
        "dashboard.html",
        "final_selection.html",
        "portfolio_monitor.html",
        "execution_preview.html",
        "market_regime.html",
        "signals.html",
        "risk.html",
        "policy.html",
        "learning.html",
        "audit.html",
    ):
        html = _template(template_name)
        assert "next-action" in html or "operator-checklist-card" in html


def test_portfolio_monitor_flags_trailing_stop_proximity_before_trigger() -> None:
    snapshot = build_portfolio_monitor(
        [selection_report(action="BUY")],
        broker_positions=[
            {
                "ticker": "AAPL",
                "qty": 1.0,
                "market_value": 1000.0,
                "unrealized_pl": 10.0,
                "unrealized_plpc": 0.01,
                "side": "LONG",
            }
        ],
        high_water_marks={"AAPL": 6.0},
        policy=PortfolioPolicy(trailing_stop_pct=8.0, stop_loss_pct=20.0),
        generated_at="2026-05-07T09:34:00Z",
    )

    row = snapshot["positions"][0]
    assert row["exit_signal"] == "NONE"
    assert row["trailing_stop_proximity_alert"] is True
    assert row["trailing_stop_distance_pct"] == 3.0


def test_execution_submit_requires_research_approval_record() -> None:
    risk_decision = _allowed_risk_decision()
    policy = PortfolioPolicy(broker_submit_enabled=True)
    account = {"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0}

    blocked = build_execution_preview(
        risk_decision,
        policy=policy,
        account=account,
        research_approval_required=True,
    ).preview
    approved = build_execution_preview(
        risk_decision,
        policy=policy,
        account=account,
        research_approval_required=True,
        research_approval_recorded=True,
    ).preview

    assert blocked["submit_enabled"] is False
    assert "current human approval required" in blocked["reasons"]
    assert approved["submit_enabled"] is True


def test_approved_watch_can_be_promoted_to_orderable_buy_report() -> None:
    report = selection_report(action="WATCH", score=0.92)
    review_key = (str(report["cycle_id"]), str(report["ticker"]), str(report["as_of"]))
    promoted = promote_paper_trade_reports(
        [report],
        review_states={
            review_key: {
                "payload": {
                    "review_decision": "APPROVE",
                    "selection_report_hash": selection_report_hash(report),
                }
            }
        },
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_conviction=0.9,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    risk_decision = _allowed_risk_decision(promoted[0])

    assert promoted[0]["final_action"] == "BUY"
    assert risk_decision["decision"] == "ALLOW"


def _allowed_risk_decision(report: dict[str, object] | None = None) -> dict[str, object]:
    from agency.services import build_risk_decision

    return build_risk_decision(
        report or selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision
