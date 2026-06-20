from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agency.dashboard as dashboard_module
from agency.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "src" / "agency" / "templates"


def _template(name: str) -> str:
    return (TEMPLATE_ROOT / name).read_text(encoding="utf-8")


def test_root_and_brand_make_cockpit_the_primary_operator_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_command_context() -> dict[str, object]:
        raise AssertionError("root should not build the legacy command diagnostic page")

    monkeypatch.setattr(dashboard_module, "_command_dashboard_route_context", fail_command_context)
    client = TestClient(create_app())

    response = client.get("/", follow_redirects=False)
    base = _template("base.html")

    assert response.status_code == 303
    assert response.headers["location"] == "/cockpit"
    assert '<a class="brand" href="/cockpit">' in base
    assert 'href="/command"' in base
    assert base.index('href="/cockpit"') < base.index('href="/command"')


def test_legacy_routes_are_labeled_as_diagnostics_not_primary_workflow() -> None:
    base = _template("base.html")

    # Secondary routes are accessible with clear operator labels; the
    # "Diagnostics:" prefix was dropped in favour of shorter functional names.
    required = (
        "System Health",       # /command — system status page
        "Candidate Review",    # /final-selection — workflow nav
        "Order Clearance",     # /execution-preview — workflow nav
        "Audit Trail",         # /audit — secondary nav
        "Runtime checks",      # topbar meta block default
    )
    # These phrases belonged to an earlier naming pass; they must not return.
    forbidden = (
        ">Review Candidates<",
        ">Submit Orders<",
        ">Command<",
        "Pre-Flight Dashboards",
        "Runtime dashboard",
    )

    for phrase in required:
        assert phrase in base
    for phrase in forbidden:
        assert phrase not in base


def test_operator_templates_do_not_reintroduce_legacy_dashboard_copy() -> None:
    combined = "\n".join(
        _template(name)
        for name in (
            "base.html",
            "cockpit.html",
            "candidate_detail.html",
            "execution_preview.html",
            "dashboard.html",
        )
    )

    forbidden = (
        "Command dashboard",
        "Open signal dashboard",
        "No concrete evidence line",
        "Selection blocked",
        "Pre-Flight Dashboards",
        "Runtime dashboard",
    )
    for phrase in forbidden:
        assert phrase not in combined


def test_shared_data_health_copy_says_page_not_dashboard() -> None:
    source = (REPO_ROOT / "src" / "agency" / "views" / "_shared.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "This dashboard is",
        "this dashboard",
        "reload this dashboard",
        "using this dashboard",
        "dashboard monitor check",
    )
    for phrase in forbidden:
        assert phrase not in source
