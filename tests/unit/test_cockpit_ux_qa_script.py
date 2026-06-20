from __future__ import annotations

import inspect

import pytest

import scripts.check_cockpit_ux_qa as qa


def test_qa_script_parses_allow_paper_submit_default_false() -> None:
    args = qa._parse_args(["--url", "http://127.0.0.1:8000/cockpit"])

    assert args.allow_paper_submit is False


def test_qa_script_has_required_viewports() -> None:
    viewport_names = {name for name, _viewport in qa.VIEWPORTS}

    assert viewport_names >= {
        "desktop-1920",
        "desktop-1366",
        "kiosk-1280",
        "mobile-390",
    }


def test_qa_script_preflights_required_status_endpoints() -> None:
    assert qa.PREFLIGHT_ENDPOINTS == (
        "/api/cockpit",
        "/status/data-load",
        "/status/full-live-readiness",
        "/status/data-sources",
        "/status/execution-preview",
    )


def test_qa_script_refuses_paper_submit_without_ready_preflight() -> None:
    preflight = {
        "/status/full-live-readiness": {"ready": True, "tradable_ready": True},
        "/status/execution-preview": {"orderable_count": 0, "submit_ready_count": 0},
    }

    with pytest.raises(RuntimeError, match="orderable execution preview"):
        qa._validate_paper_submit_preflight(preflight, allow_paper_submit=True)


def test_qa_script_allows_no_submit_mode_without_broker_evidence() -> None:
    qa._validate_paper_submit_preflight({}, allow_paper_submit=False)


def test_qa_script_records_preflight_json_name() -> None:
    assert qa.PREFLIGHT_REPORT_NAME == "cockpit-preflight.json"


def test_qa_script_writes_semantic_contract_artifact() -> None:
    source = inspect.getsource(qa.main)

    assert "cockpit-first-screen-semantic-contract.json" in source
    assert "_semantic_contract_case_results" in source


def test_qa_script_semantic_contract_cases_cover_required_states() -> None:
    cases = {str(case["name"]): case for case in qa._semantic_contract_cases()}

    assert set(cases) >= {
        "review_ready_paper_gated_noncritical_engine_unavailable",
        "review_not_ready_live_trade_slices_need_refresh",
        "missing_source_proof",
        "email_login_required_market_data_review_usable",
        "paper_execution_ready_broker_env_available",
    }
    assert cases["review_ready_paper_gated_noncritical_engine_unavailable"]["expected_state"] == "review"
    assert (
        cases["review_not_ready_live_trade_slices_need_refresh"]["expected_state"]
        == "status-delayed"
    )
    assert cases["missing_source_proof"]["expected_state"] == "outage"
    assert cases["email_login_required_market_data_review_usable"]["expected_state"] == "review"
    assert cases["paper_execution_ready_broker_env_available"]["expected_state"] == "normal"


def test_qa_script_semantic_contract_cases_require_operator_proof_text() -> None:
    cases = {str(case["name"]): case for case in qa._semantic_contract_cases()}

    live_gap_text = " ".join(cases["review_not_ready_live_trade_slices_need_refresh"]["required_texts"])
    missing_proof_text = " ".join(cases["missing_source_proof"]["required_texts"])
    paper_ready_text = " ".join(cases["paper_execution_ready_broker_env_available"]["required_texts"])

    assert "What remains usable" in live_gap_text
    assert "Refresh live trade slices" in live_gap_text
    assert "confirm proof timestamp changed" in live_gap_text
    assert "Open Diagnostics for Source proof" in missing_proof_text
    assert "not checked" in missing_proof_text
    assert "Broker paper API connected" in paper_ready_text
    assert "API keys loaded" in paper_ready_text


def test_qa_script_captures_first_load_screenshot_before_clicking_clearance() -> None:
    source = inspect.getsource(qa.main)

    assert "first_viewport_screenshot" in source
    assert source.index("first_viewport_screenshot") < source.index("_submit_gate_is_safe")


def test_qa_script_collects_external_requests_and_small_touch_targets() -> None:
    source = inspect.getsource(qa.main)
    failed_source = inspect.getsource(qa._failed)
    touch_source = inspect.getsource(qa._small_touch_targets)

    assert "external_requests" in source
    assert "_external_request_collector" in source
    assert "small_touch_targets" in source
    assert "external_requests" in failed_source
    assert "small_touch_targets" in failed_source
    assert "rect.width < 44 || rect.height < 44" in touch_source


def test_qa_script_fails_hidden_inner_horizontal_overflow() -> None:
    source = inspect.getsource(qa.main)
    failed_source = inspect.getsource(qa._failed)
    overflow_source = inspect.getsource(qa._inner_horizontal_overflow_errors)

    assert "inner_overflow_errors" in source
    assert "inner_overflow_errors" in failed_source
    assert "scrollWidth" in overflow_source
    assert "extends outside viewport" in overflow_source


def test_qa_script_applies_scenario_query_param() -> None:
    url = qa._scenario_url("http://127.0.0.1:8000/cockpit?foo=bar", "outage")

    assert url == "http://127.0.0.1:8000/cockpit?foo=bar&scenario=outage"


def test_qa_script_can_expand_all_required_scenarios() -> None:
    assert qa.SCENARIOS == ("normal", "no-actionable", "outage", "status-delayed", "submitted")
    assert qa._scenario_names("all") == [
        "normal",
        "no-actionable",
        "outage",
        "status-delayed",
        "submitted",
    ]
    assert qa._scenario_names("outage") == ["outage"]


def test_qa_script_waits_on_real_first_screen_selectors_not_ready_marker() -> None:
    source = inspect.getsource(qa.main)

    assert 'data-cockpit-ready="true"' not in source
    assert ".cockpit-data-state-strip" in source
    assert ".cockpit-phase:not([hidden])" in source


def test_qa_script_treats_locked_submit_as_safe_in_safety_scenarios() -> None:
    source = inspect.getsource(qa._submit_gate_is_safe)

    assert '{"outage", "status-delayed", "no-actionable", "submitted"}' in source
    assert "not ack.is_visible()" in source
    assert "return initially_disabled and wrong_phrase_disabled and not armed_enabled" in source


def test_qa_script_returns_to_candidates_before_ticker_detail_focus() -> None:
    source = inspect.getsource(qa._exercise_focus)
    panels_branch = source.split('elif focus == "panels":', 1)[1]
    candidates_phase = '[data-cockpit-phase-target="candidates"]'
    row_toggle = "[data-cockpit-row-toggle]"

    assert candidates_phase in panels_branch
    assert panels_branch.index(candidates_phase) < panels_branch.index(row_toggle)


def test_qa_script_candidates_focus_opens_candidate_phase_before_row_toggle() -> None:
    source = inspect.getsource(qa._exercise_focus)
    candidates_branch = source.split('if focus == "candidates":', 1)[1].split(
        'elif focus == "portfolio":',
        1,
    )[0]
    candidates_phase = '[data-cockpit-phase-target="candidates"]'
    row_toggle = "[data-cockpit-row-toggle]"

    assert candidates_phase in candidates_branch
    assert '[data-cockpit-phase="candidates"]' in candidates_branch
    assert '[data-cockpit-phase="candidates"]:not([hidden]) [data-cockpit-row-toggle]' in (
        candidates_branch
    )
    assert '[data-cockpit-phase="candidates"]:not([hidden]) .cockpit-row-detail' in (
        candidates_branch
    )
    assert "candidate phase did not open" in candidates_branch
    assert candidates_branch.index(candidates_phase) < candidates_branch.index(row_toggle)


def test_qa_script_panel_focus_uses_first_matching_panel_trigger() -> None:
    source = inspect.getsource(qa._exercise_focus)
    panels_branch = source.split('elif focus == "panels":', 1)[1]

    assert "trigger = page.locator" in panels_branch
    assert "_try_click(trigger)" in panels_branch


def test_qa_script_first_screen_semantics_use_operator_copy() -> None:
    source = inspect.getsource(qa._first_screen_semantic_errors)

    assert '"System Status"' in source
    assert "First viewport is missing the proof strip." in source
    assert "First viewport is missing primary dashboard navigation." in source
    assert "First viewport is missing the workflow phase rail or operator path." in source
    assert '"Fix Data"' in source
    assert '"SA Login"' in source
    assert "First viewport is missing cockpit instruments or proof chips." in source
    assert "First viewport is missing operator proof text" in source
    assert "Review-ready API state rendered as a {rendered_state} cockpit." in source
    assert "plain-English state is not visible" in source
    assert "detail is not visible" not in source


def test_qa_script_detects_cross_endpoint_readiness_drift() -> None:
    errors = qa._cross_endpoint_truth_errors(
        {
            "/api/cockpit": {
                "data_state": {
                    "review": {"ready": True},
                    "paper": {"ready": True},
                },
                "clearance": {"orderable_count": 1, "ready_count": 1},
            },
            "/status/data-load": {
                "review_operational_ready": False,
                "tradable_ready": False,
            },
            "/status/execution-preview": {
                "orderable_count": 0,
                "submit_ready_count": 0,
            },
        }
    )

    assert any("review.ready" in error for error in errors)
    assert any("paper.ready" in error for error in errors)
    assert any("orderable_count" in error for error in errors)
    assert any("ready_count" in error for error in errors)


def test_qa_script_submit_gate_requires_real_manifest_order_intent() -> None:
    source = inspect.getsource(qa._submit_gate_is_safe)
    manifest_source = inspect.getsource(qa._paper_manifest_has_order_intent)

    assert "manifest_ready = _paper_manifest_has_order_intent(page)" in source
    assert "not manifest_ready" in source
    assert "cycle_id" in manifest_source
    assert "order_intent_hash" in manifest_source


def test_qa_script_checks_candidate_dom_api_drift() -> None:
    source = inspect.getsource(qa._candidate_dom_api_errors)

    assert "data-cockpit-candidate" in source
    assert "ticker mismatch" in source
    assert "evidence line" in source
    assert "risk line" in source


def test_qa_script_preferences_focus_verifies_reload_persistence() -> None:
    source = inspect.getsource(qa._exercise_focus)
    preferences_branch = source.split('elif focus == "preferences":', 1)[1].split(
        'elif focus == "panels":',
        1,
    )[0]

    assert '[data-cockpit-preferences-open]' in preferences_branch
    assert 'value="duotone"' in preferences_branch
    assert 'value="light"' in preferences_branch
    assert 'value="calm"' in preferences_branch
    assert "page.reload" in preferences_branch
    assert "did not persist after reload" in preferences_branch


def test_qa_script_portfolio_focus_uses_first_matching_phase_controls() -> None:
    source = inspect.getsource(qa._exercise_focus)
    portfolio_branch = source.split('elif focus == "portfolio":', 1)[1].split(
        'elif focus == "panels":',
        1,
    )[0]

    assert "phase_button = page.locator" in portfolio_branch
    assert "phase_button.count() == 0" in portfolio_branch
    assert "_try_click(phase_button.first)" in portfolio_branch
    assert "portfolio_phase.first.is_visible()" in portfolio_branch
