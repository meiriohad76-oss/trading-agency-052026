from __future__ import annotations

from pathlib import Path

from agency.views.cockpit import cockpit_context_from_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")
STYLES = Path("src/agency/static/styles.css")
SCRIPT = Path("src/agency/static/cockpit.js")


def _sources() -> dict[str, object]:
    return {
        "dashboard": {
            "data_load_status": {"cycle_id": "cycle-pref-test"},
            "data_sources": [
                {
                    "name": "Massive live trade slices",
                    "status_label": "Loaded",
                    "status_class": "pass",
                    "last_update": "2026-05-22T14:00:00+00:00",
                }
            ],
            "review_queue": [
                {
                    "ticker": "PREF",
                    "final_action": "BUY",
                    "final_score": 0.73,
                    "risk_status_label": "PASS",
                    "top_reasons": ["Daily bars show 2.1% strength versus the 20-day baseline."],
                    "is_reviewable": True,
                }
            ],
        },
        "execution": {
            "orderable_rows": [{"ticker": "PREF", "notional_label": "$1,000"}],
            "preview_rows": [
                {
                    "ticker": "PREF",
                    "preview_state": "READY",
                    "side": "BUY",
                    "submit_enabled": True,
                    "notional_label": "$1,000",
                }
            ],
        },
        "portfolio": {},
        "market": {},
        "signals": {},
    }


def test_cockpit_preferences_include_color_theme_density() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "data-cockpit-preferences" in html
    assert 'name="cockpit-color-preset"' in html
    assert 'value="amber"' in html
    assert 'value="duotone"' in html
    assert 'value="saturated"' in html
    assert 'name="cockpit-theme"' in html
    assert 'value="dark"' in html
    assert 'value="accent"' in html
    assert 'value="light"' in html
    assert 'name="cockpit-density"' in html
    assert 'value="full"' in html
    assert 'value="calm"' in html


def test_cockpit_preferences_default_to_amber_accent_full() -> None:
    context = cockpit_context_from_sources(_sources())
    html = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    assert context["preferences"] == {
        "color_preset": "amber",
        "theme": "accent",
        "density": "full",
    }
    assert 'data-cockpit-color-preset="{{ preferences.color_preset }}"' in html
    assert '"colorPreset":"amber"' in script
    assert '"theme":"accent"' in script
    assert '"density":"full"' in script


def test_cockpit_preferences_radio_checked_state_uses_server_preferences() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'value="amber" checked' not in html
    assert 'value="accent" checked' not in html
    assert 'value="full" checked' not in html
    assert "preferences.color_preset == 'amber'" in html
    assert "preferences.theme == 'accent'" in html
    assert "preferences.density == 'full'" in html


def test_live_trading_is_not_a_tweak() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    preference_region = html.split("data-cockpit-preferences", 1)[-1].split("</aside>", 1)[0]
    assert "live_trading" not in preference_region.lower()
    assert "liveTrading" not in script


def test_scenario_override_is_hidden_without_dev_flag() -> None:
    context = cockpit_context_from_sources(
        _sources(),
        qa_scenario="outage",
        qa_scenarios_enabled=False,
    )

    assert context["qa_scenarios_enabled"] is False
    assert context["scenario"]["state"] == "normal"


def test_qa_scenario_override_banner_marks_non_operational() -> None:
    context = cockpit_context_from_sources(
        _sources(),
        qa_scenario="outage",
        qa_scenarios_enabled=True,
    )
    html = TEMPLATE.read_text(encoding="utf-8")

    assert context["qa_scenarios_enabled"] is True
    assert context["scenario"]["state"] == "outage"
    assert context["scenario"]["qa_override"] is True
    assert "Training scenario only" in html
    assert "QA scenario only" not in html
    assert "not operational evidence" in html
    assert "data-cockpit-qa-scenario" in html


def test_calm_mode_hides_nonessential_chrome_but_keeps_actions() -> None:
    css = STYLES.read_text(encoding="utf-8")

    assert '[data-cockpit-density="calm"] .cockpit-instrument-cluster' in css
    assert '[data-cockpit-density="calm"] .cockpit-engine-strip' in css
    assert '[data-cockpit-density="calm"] [data-cockpit-decision]' not in css
    assert '[data-cockpit-density="calm"] [data-cockpit-submit-button]' not in css
