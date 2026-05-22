from __future__ import annotations

import re
from pathlib import Path

PRODUCTION_COCKPIT_PATHS = (
    Path("src/agency/views/cockpit.py"),
    Path("src/agency/templates/cockpit.html"),
    Path("src/agency/templates/_cockpit_panels.html"),
    Path("src/agency/static/cockpit.js"),
    Path("scripts/check_cockpit_ux_qa.py"),
    Path("scripts/check_dashboard_live_data_qa.py"),
)


def _combined_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in PRODUCTION_COCKPIT_PATHS)


def test_cockpit_production_paths_do_not_reference_window_cockpit_data() -> None:
    assert "window.COCKPIT_DATA" not in _combined_text()


def test_cockpit_production_paths_do_not_reference_editmode() -> None:
    assert "EDITMODE" not in _combined_text()


def test_cockpit_no_prototype_cycle_or_time_constants() -> None:
    text = _combined_text()

    assert "C-14:32" not in text
    assert "14:30" not in text
    assert not re.search(r"grossPostTrade.*84", text)


def test_cockpit_no_random_demo_order_ids() -> None:
    text = _combined_text()

    assert "Math.random" not in text
    assert "ALP-" not in text


def test_cockpit_no_hidden_artifact_fallback_as_readiness_proof() -> None:
    text = _combined_text().lower()

    assert "hidden artifact fallback" not in text
    assert "artifact_fallback" not in text


def test_cockpit_no_primary_stale_label() -> None:
    text = _combined_text().lower()

    assert "{{ source.state }}" not in text
    assert 'return "fresh"' not in text
    assert 'return "stale"' not in text
