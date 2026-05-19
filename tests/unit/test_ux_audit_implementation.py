from __future__ import annotations

from pathlib import Path

from service_fixtures import selection_report

from agency.services import PortfolioPolicy, build_execution_preview, build_portfolio_monitor
from agency.services.paper_trade_promotion import (
    PaperTradePromotionConfig,
    promote_paper_trade_reports,
)
from agency.services.human_review import selection_report_hash


TEMPLATE_ROOT = Path("src/agency/templates")
STYLE_PATH = Path("src/agency/static/styles.css")


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


def test_command_dashboard_has_queue_cta_and_collapsed_diagnostics() -> None:
    html = _template("dashboard.html")

    assert "operator-briefing" in html
    assert "operator-briefing-grid" in html
    assert "operator-queue-preview" in html
    assert "Trade eligibility" in html
    assert "What to do now" in html
    assert "Review {{ review_progress.pending_count }} candidates" in html
    assert "href=\"#review-queue-heading\"" in html
    assert "LLM review unavailable" in html
    assert "Portfolio exposure" in html
    assert "System diagnostics" in html
    assert "Data Sources" in html
    assert "review-state-icon" in html
    assert "Blocked by risk" not in html


def test_candidate_detail_prioritizes_decision_and_collapses_technical_detail() -> None:
    html = _template("candidate_detail.html")

    assert "Back to candidates" in html
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


def test_portfolio_monitor_contains_exit_recommendation_workflow() -> None:
    html = _template("portfolio_monitor.html")

    assert "Total exposure" in html
    assert "Max allowed" in html
    assert "Go to Candidates" in html
    assert "Exit Recommendations" in html
    assert "exposure_freed_label" in html
    assert "Confirm exit" in html
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
    assert "Submit all ready orders" in execution_html
    assert "Submitted paper order" in execution_html


def test_execution_preview_paper_cards_are_readable() -> None:
    execution_html = _template("execution_preview.html")
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "execution-preview-card paper-mode-card" in execution_html
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


def test_data_health_panel_uses_actionable_user_copy_not_internal_telemetry() -> None:
    html = _template("_data_health.html")

    assert "What this means" in html
    assert "Recommended action" in html
    assert "Blocking reason" in html
    assert "Show operational diagnostics" in html
    assert "row.blocking_reason" in html
    assert "row.recommended_action" in html
    assert "row.why_it_matters" in html


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
    assert "ux-health-llm-20260519" in base_html
    assert "paper-mode-card" in audit_html
    assert "Show details: LLM rationale" in audit_html
    assert ".paper-mode-card" in css
    assert ".status-icon" in css
    assert ".tag-urgent" in css
    assert ".shared-disclosure" in css
    assert ".action-approve" in css


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
    expected = {
        "dashboard.html": "01",
        "final_selection.html": "02",
        "portfolio_monitor.html": "03",
        "execution_preview.html": "04",
        "market_regime.html": "05",
        "signals.html": "06",
        "risk.html": "07",
        "policy.html": "08",
        "learning.html": "09",
        "audit.html": "10",
    }

    for template_name, step in expected.items():
        html = _template(template_name)
        assert f'<div class="next-action-step" aria-hidden="true">{step}</div>' in html


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
