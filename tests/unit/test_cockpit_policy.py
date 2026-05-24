from __future__ import annotations

from pathlib import Path

from agency.app import create_app
from agency.views.cockpit import cockpit_context_from_sources

PANELS = Path("src/agency/templates/_cockpit_panels.html")
SCRIPT = Path("src/agency/static/cockpit.js")


def _sources() -> dict[str, object]:
    return {
        "dashboard": {
            "data_load_status": {"cycle_id": "cycle-policy-test"},
            "policy_summary": {
                "min_final_conviction": 0.62,
                "default_position_pct": 5,
                "max_gross_exposure_pct": 100,
                "live_trading_enabled": False,
                "broker_submit_enabled": True,
            },
            "review_queue": [],
        },
        "execution": {},
        "portfolio": {},
        "market": {},
        "signals": {},
    }


def test_policy_panel_shows_deployed_and_staged_values() -> None:
    context = cockpit_context_from_sources(_sources())
    panels = PANELS.read_text(encoding="utf-8")

    assert "deployed_values" in context["policy"]
    assert "staged_values" in context["policy"]
    assert "data-policy-deployed" in panels
    assert "data-policy-staged" in panels
    assert "data-policy-diff" in panels


def test_policy_apply_requires_confirmation() -> None:
    panels = PANELS.read_text(encoding="utf-8")

    assert 'type="checkbox"' in panels
    assert "data-policy-confirm-apply" in panels
    assert "Apply next cycle" in panels


def test_policy_changes_apply_next_cycle_copy() -> None:
    panels = PANELS.read_text(encoding="utf-8")

    assert "apply to the next cycle" in panels.lower()
    assert "current deployed rules" in panels.lower()


def test_cockpit_policy_uses_existing_policy_write_route() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'fetch("/api/policy"' in script
    assert 'method: "POST"' in script


def test_cockpit_policy_does_not_introduce_conflicting_put_route() -> None:
    app = create_app()
    policy_routes = [
        route
        for route in app.routes
        if getattr(route, "path", "") == "/api/policy"
    ]

    assert any("POST" in getattr(route, "methods", set()) for route in policy_routes)
    assert not any("PUT" in getattr(route, "methods", set()) for route in policy_routes)


def test_live_trading_flag_is_locked_off() -> None:
    context = cockpit_context_from_sources(_sources())

    assert context["policy"]["dangerous_flags"]["live_trading"]["locked"] is True
    assert context["policy"]["dangerous_flags"]["live_trading"]["value"] == "locked off"


def test_policy_change_invalidates_staged_submit_until_revalidated() -> None:
    panels = PANELS.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    assert "data-policy-change-invalidates-submit" in panels
    assert "invalidateSubmitGate" in script
    assert "Refresh cockpit after policy apply before submitting paper orders." in script


def test_policy_field_typing_updates_diff_without_invalidating_submit_gate() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    input_handler = script.split('field.addEventListener("input", () => {', 1)[1].split("});", 1)[0]

    assert "refreshPolicyDiff();" in input_handler
    assert "invalidateSubmitGate" not in input_handler


def test_policy_diff_uses_dom_text_nodes_for_staged_values() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    policy_block = script.split("function setupPolicyPanel()", 1)[1].split(
        "function invalidateSubmitGate()",
        1,
    )[0]

    assert "diffTarget.innerHTML" not in policy_block
    assert ".textContent" in policy_block
