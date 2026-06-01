from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "research" / "results" / "ux-preservation" / "latest"

SIGNAL_TESTS: tuple[str, ...] = (
    "tests/unit/test_signal_evidence.py",
    "tests/unit/test_signal_evidence_fundamentals.py",
    "tests/unit/test_subscription_thesis_signal.py",
    "tests/unit/test_sec_views_period_fix.py",
    "tests/unit/test_pit_loader.py",
    "tests/unit/test_actionability_gate.py",
)

COCKPIT_TESTS: tuple[str, ...] = (
    "tests/unit/test_cockpit_candidates.py",
    "tests/unit/test_cockpit_lane_state.py",
    "tests/unit/test_cockpit_routes.py",
    "tests/unit/test_fastapi_app.py",
)

REQUIRED_FILES: tuple[str, ...] = (
    "docs/superpowers/plans/2026-06-01-ux-upgrade-cockpit-implementation.md",
    "docs/superpowers/specs/2026-06-01-cockpit-variation-a-decision-lock.md",
    "docs/audits/cockpit-contract-audit-2026-06-01.md",
    "ux upgrade claude design 01062026/Variation A.html",
    "ux upgrade claude design 01062026/handoff/07-data-schema.md",
)

PLAN_MARKERS: tuple[str, ...] = (
    "Recent Work That Must Be Preserved",
    "Visual Fidelity Gate Against Expert HTML",
    "Preservation Regression Test Set",
    "UXC-014 - Preservation Regression Harness",
)


@dataclass(frozen=True)
class CommandResult:
    label: str
    command: list[str]
    returncode: int
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC).isoformat()
    file_failures = required_file_failures(PROJECT_ROOT)
    marker_failures = required_marker_failures(PROJECT_ROOT)
    test_paths = selected_tests(args.group)
    missing_tests = [path for path in test_paths if not (PROJECT_ROOT / path).exists()]
    commands: list[CommandResult] = []

    if args.list:
        for path in test_paths:
            print(path)
        return 0

    if not args.skip_pytest and not file_failures and not marker_failures and not missing_tests:
        commands.append(
            run_command(
                "pytest",
                build_pytest_command(test_paths, extra_args=args.pytest_args),
                cwd=PROJECT_ROOT,
            )
        )

    failed_commands = [result for result in commands if result.returncode != 0]
    passed = not file_failures and not marker_failures and not missing_tests and not failed_commands
    report = {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at,
        "status": "pass" if passed else "fail",
        "group": args.group,
        "required_files": list(REQUIRED_FILES),
        "file_failures": file_failures,
        "marker_failures": marker_failures,
        "missing_tests": missing_tests,
        "test_paths": list(test_paths),
        "commands": [asdict(result) for result in commands],
    }
    report_path = output_dir / "ux-preservation-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "group", "file_failures", "marker_failures", "missing_tests")}, indent=2))
    print(f"report={report_path}")
    return 0 if passed else 1


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the UX cockpit preservation regression gate.",
    )
    parser.add_argument(
        "--group",
        choices=("all", "signals", "cockpit"),
        default="all",
        help="Regression group to run.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Check files/markers only. Used by fast smoke tests.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print selected test paths without running them.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Optional arguments passed to pytest after '--'.",
    )
    return parser.parse_args(argv)


def selected_tests(group: str) -> tuple[str, ...]:
    if group == "signals":
        return SIGNAL_TESTS
    if group == "cockpit":
        return COCKPIT_TESTS
    return (*SIGNAL_TESTS, *COCKPIT_TESTS)


def build_pytest_command(
    test_paths: Sequence[str],
    *,
    extra_args: Sequence[str] = (),
) -> list[str]:
    cleaned_args = list(extra_args)
    if cleaned_args and cleaned_args[0] == "--":
        cleaned_args = cleaned_args[1:]
    return [sys.executable, "-m", "pytest", *test_paths, *cleaned_args]


def required_file_failures(root: Path) -> list[str]:
    return [path for path in REQUIRED_FILES if not (root / path).exists()]


def required_marker_failures(root: Path) -> list[str]:
    plan_path = root / "docs/superpowers/plans/2026-06-01-ux-upgrade-cockpit-implementation.md"
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{plan_path}: {exc}"]
    return [marker for marker in PLAN_MARKERS if marker not in text]


def run_command(label: str, command: Sequence[str], *, cwd: Path) -> CommandResult:
    started = monotonic()
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    return CommandResult(
        label=label,
        command=list(command),
        returncode=completed.returncode,
        duration_seconds=round(monotonic() - started, 3),
        stdout_tail=tail(completed.stdout),
        stderr_tail=tail(completed.stderr),
    )


def tail(text: str, *, max_chars: int = 12_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


if __name__ == "__main__":
    raise SystemExit(main())
