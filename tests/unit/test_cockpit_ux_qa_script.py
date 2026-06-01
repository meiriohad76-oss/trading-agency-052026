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


def test_qa_script_applies_scenario_query_param() -> None:
    url = qa._scenario_url("http://127.0.0.1:8000/cockpit?foo=bar", "outage")

    assert url == "http://127.0.0.1:8000/cockpit?foo=bar&scenario=outage"


def test_qa_script_can_expand_all_required_scenarios() -> None:
    assert qa.SCENARIOS == ("normal", "no-actionable", "outage", "submitted")
    assert qa._scenario_names("all") == ["normal", "no-actionable", "outage", "submitted"]
    assert qa._scenario_names("outage") == ["outage"]


def test_qa_script_treats_locked_submit_as_safe_in_safety_scenarios() -> None:
    source = inspect.getsource(qa._submit_gate_is_safe)

    assert '{"outage", "no-actionable", "submitted"}' in source
    assert "return initially_disabled and wrong_phrase_disabled and not armed_enabled" in source


def test_qa_script_returns_to_candidates_before_ticker_detail_focus() -> None:
    source = inspect.getsource(qa._exercise_focus)
    panels_branch = source.split('elif focus == "panels":', 1)[1]
    candidates_phase = '[data-cockpit-phase-target="candidates"]'
    row_toggle = "[data-cockpit-row-toggle]"

    assert candidates_phase in panels_branch
    assert panels_branch.index(candidates_phase) < panels_branch.index(row_toggle)


def test_qa_script_panel_focus_uses_first_matching_panel_trigger() -> None:
    source = inspect.getsource(qa._exercise_focus)
    panels_branch = source.split('elif focus == "panels":', 1)[1]

    assert ".first.click()" in panels_branch


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
    assert "phase_button.first.click()" in portfolio_branch
    assert "portfolio_phase.first.is_visible()" in portfolio_branch
