from __future__ import annotations

from pathlib import Path

import scripts.check_cockpit_ux_qa as cockpit_qa

COCKPIT_ASSET_PATHS = (
    Path("src/agency/templates/base.html"),
    Path("src/agency/templates/cockpit.html"),
    Path("src/agency/templates/_cockpit_panels.html"),
    Path("src/agency/static/cockpit.js"),
    Path("src/agency/static/styles.css"),
)


def _asset_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in COCKPIT_ASSET_PATHS)


def test_cockpit_ui_has_no_cdn_dependencies() -> None:
    text = _asset_text().lower()

    forbidden = (
        "cdn.",
        "unpkg.com",
        "jsdelivr",
        "fonts.googleapis",
        "fonts.gstatic",
        "cdnjs",
    )
    assert not any(token in text for token in forbidden)


def test_cockpit_documents_local_font_fallback_until_woff2_bundled() -> None:
    readme = Path("src/agency/static/fonts/README.md")

    assert readme.exists()
    text = readme.read_text(encoding="utf-8").lower()
    assert "woff2" in text
    assert "local fallback" in text
    assert "no cdn" in text


def test_start_dev_binds_localhost_by_default_and_supports_kiosk_route() -> None:
    script = Path("scripts/start_dev.ps1").read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in script
    assert "[switch]$Kiosk" in script
    assert "$StartPath = \"/cockpit\"" in script


def test_pi_cockpit_docs_include_kiosk_resilience_and_measurement_checklist() -> None:
    doc = Path("docs/raspberry-pi-cockpit.md")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8").lower()
    for phrase in (
        "chromium",
        "systemd",
        "hide the cursor",
        "disable screen sleep",
        "cold load",
        "idle cpu",
        "8-hour memory",
        "local log",
    ):
        assert phrase in text


def test_cockpit_css_has_touch_targets_and_focus_tooltips() -> None:
    css = Path("src/agency/static/styles.css").read_text(encoding="utf-8")

    assert "--cockpit-touch-target: 44px" in css
    assert ".cockpit-shell button" in css
    assert "min-height: var(--cockpit-touch-target)" in css
    assert ".info-tip:focus-visible::after" in css
    assert '.info-tip[data-tooltip-open="true"]::after' in css


def test_cockpit_js_enables_tap_tooltips() -> None:
    script = Path("src/agency/static/cockpit.js").read_text(encoding="utf-8")

    assert "setupTouchTooltips" in script
    assert "data-tooltip-open" in script
    assert "tabIndex" in script


def test_cockpit_qa_has_touch_emulated_viewport() -> None:
    matrix = dict(cockpit_qa.VIEWPORTS)

    assert matrix["kiosk-1280"]["viewport"] == {"width": 1280, "height": 720}
    assert matrix["mobile-390"]["has_touch"] is True
    assert matrix["mobile-390"]["is_mobile"] is True
