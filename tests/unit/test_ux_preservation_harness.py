from __future__ import annotations

import json
from pathlib import Path

import scripts.check_ux_preservation as preservation


def test_semantic_preservation_checks_pass() -> None:
    results = preservation.run_semantic_checks()

    assert results
    assert all(result.passed for result in results)


def test_semantic_preservation_flags_generic_candidate_evidence() -> None:
    sources = preservation.rich_cockpit_sources()
    queue = sources["dashboard"]["review_queue"]  # type: ignore[index]
    queue[0]["top_reasons"] = ["Bullish signal detected."]  # type: ignore[index]

    results = preservation.run_semantic_checks(cockpit_sources=sources)

    failure = [
        result
        for result in results
        if result.name == "candidate evidence keeps concrete hard values"
    ][0]
    assert failure.passed is False
    assert "Bullish signal detected" in failure.detail


def test_semantic_preservation_flags_missing_trf_hard_evidence() -> None:
    detail = preservation.rich_candidate_detail_context()
    signal = detail["latest_report"]["actionable_signals"][0]  # type: ignore[index]
    signal["trigger_cards"] = [{"label": "Directional read", "value": "+72.0% buy-side"}]

    results = preservation.run_semantic_checks(detail_context=detail)

    failure = [
        result
        for result in results
        if result.name == "detail drawer preserves TRF/off-exchange hard evidence"
    ][0]
    assert failure.passed is False


def test_pytest_group_runner_reports_command_failure() -> None:
    def failing_runner(group: str, paths: object) -> preservation.CommandResult:
        return preservation.CommandResult(
            group=group,
            command=["python", "-m", "pytest", *list(paths)],  # type: ignore[arg-type]
            returncode=1,
            stdout_tail="assert protected behavior changed",
            stderr_tail="",
        )

    results = preservation.run_pytest_groups(["signals"], runner=failing_runner)
    summary = preservation._summary_payload(
        started_at=preservation.datetime.now(preservation.UTC),
        selected_groups=["signals"],
        semantic_results=[],
        command_results=results,
    )

    assert summary["status"] == "FAIL"
    assert summary["failures"][0]["group"] == "signals"  # type: ignore[index]
    assert "pytest exited 1" in summary["failures"][0]["detail"]  # type: ignore[index]


def test_main_writes_clear_artifacts(tmp_path: Path) -> None:
    output_root = tmp_path / "ux-preservation"
    audit_path = tmp_path / "audit.md"

    exit_code = preservation.main(
        [
            "--group",
            "cockpit",
            "--skip-pytest",
            "--output-root",
            str(output_root),
            "--audit-path",
            str(audit_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads((output_root / "ux-preservation-summary.json").read_text())
    assert payload["status"] == "PASS"
    assert payload["ticket"] == "UXC-014"
    assert "candidate evidence keeps concrete hard values" in audit_path.read_text()
