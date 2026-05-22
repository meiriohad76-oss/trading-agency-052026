from __future__ import annotations

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
