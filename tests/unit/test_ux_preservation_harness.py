from __future__ import annotations

from pathlib import Path

from scripts import check_ux_preservation


def test_preservation_harness_selects_expected_groups() -> None:
    signal_tests = check_ux_preservation.selected_tests("signals")
    cockpit_tests = check_ux_preservation.selected_tests("cockpit")
    all_tests = check_ux_preservation.selected_tests("all")

    assert "tests/unit/test_signal_evidence.py" in signal_tests
    assert "tests/unit/test_signal_evidence_fundamentals.py" in signal_tests
    assert "tests/unit/test_actionability_gate.py" in signal_tests
    assert "tests/unit/test_cockpit_candidates.py" in cockpit_tests
    assert "tests/unit/test_cockpit_lane_state.py" in cockpit_tests
    assert all_tests == (*signal_tests, *cockpit_tests)


def test_preservation_harness_uses_current_python_for_pytest() -> None:
    command = check_ux_preservation.build_pytest_command(
        ["tests/unit/test_signal_evidence.py"],
        extra_args=["--", "-q"],
    )

    assert command[1:3] == ["-m", "pytest"]
    assert command[-1] == "-q"


def test_preservation_required_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]

    assert check_ux_preservation.required_file_failures(root) == []


def test_preservation_plan_markers_exist() -> None:
    root = Path(__file__).resolve().parents[2]

    assert check_ux_preservation.required_marker_failures(root) == []
