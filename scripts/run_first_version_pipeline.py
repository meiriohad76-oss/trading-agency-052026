from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PipelineStep:
    name: str
    command: list[str]
    requires_console: bool = False


@dataclass(frozen=True)
class StepResult:
    name: str
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    duration_seconds: float


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = _parse_args()
    results: list[StepResult] = []
    for step in build_pipeline_steps(args):
        result = run_step(step)
        results.append(result)
        print(json.dumps(asdict(result), sort_keys=True))
        if result.returncode != 0:
            summary = _summary(results, failed_step=step.name)
            write_pipeline_report(summary, results, args.report_root)
            print(json.dumps(summary, sort_keys=True))
            return result.returncode
    summary = _summary(results, failed_step=None)
    write_pipeline_report(summary, results, args.report_root)
    print(json.dumps(summary, sort_keys=True))
    return 0


def build_pipeline_steps(args: argparse.Namespace) -> list[PipelineStep]:
    steps: list[PipelineStep] = []
    if args.refresh_data:
        steps.append(PipelineStep("data_refresh", data_refresh_command(args)))
    if not args.skip_email:
        steps.append(
            PipelineStep(
                "subscription_email_ingest",
                email_ingest_command(args),
                requires_console=subscription_email_requires_console(args),
            )
        )
    steps.append(PipelineStep("live_runtime_cycle", runtime_cycle_command(args)))
    if args.check_dashboard:
        steps.append(PipelineStep("dashboard_readiness", dashboard_check_command(args)))
    return steps


def data_refresh_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "research" / "scripts" / "run_data_refresh_batch.py"),
        "--config",
        str(args.config),
    ]
    for dataset in args.refresh_dataset or ():
        command.extend(["--dataset", dataset])
    return command


def email_ingest_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "research" / "scripts" / "import_subscription_emails.py"),
        "--config",
        str(args.subscription_email_config),
        "--max-emails",
        str(args.email_max_emails),
        "--max-article-links",
        str(args.email_max_article_links),
    ]
    if args.email_include_seen:
        command.append("--include-seen")
    if args.email_unseen_only:
        command.append("--unseen-only")
    return command


def subscription_email_requires_console(args: argparse.Namespace) -> bool:
    config_path = Path(args.subscription_email_config)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("article_login_preflight_required") is True


def runtime_cycle_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_live_runtime_cycle.py"),
        "--config",
        str(args.config),
        "--output-root",
        str(args.output_root),
    ]
    if args.max_tickers is not None:
        command.extend(["--max-tickers", str(args.max_tickers)])
    if args.as_of is not None:
        command.extend(["--as-of", args.as_of])
    if args.replay_freshness:
        command.append("--replay-freshness")
    enable_llm_review = getattr(args, "enable_llm_review", None)
    if enable_llm_review is not None:
        llm_flag = "--enable-llm-review" if enable_llm_review else "--no-enable-llm-review"
        command.append(llm_flag)
    llm_review_max = getattr(args, "llm_review_max_candidates", None)
    if llm_review_max is not None:
        command.extend(["--llm-review-max-candidates", str(llm_review_max)])
    if getattr(args, "llm_review_include_no_trade", False):
        command.append("--llm-review-include-no-trade")
    if not args.persist:
        command.append("--no-persist")
    return command


def dashboard_check_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "check_operational_readiness.py"),
        "--base-url",
        args.base_url,
        "--min-queue",
        str(args.min_queue),
        "--min-reviewed",
        str(args.min_reviewed),
    ]
    if args.fail_on_warning:
        command.append("--fail-on-warning")
    return command


def run_step(step: PipelineStep) -> StepResult:
    started_at = _now_utc()
    started = datetime.now(UTC)
    if step.requires_console:
        returncode = subprocess.run(step.command, cwd=ROOT, check=False).returncode
        stdout = "interactive step attached to console"
        stderr = ""
    else:
        completed = subprocess.run(
            step.command,
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        returncode = completed.returncode
        stdout = _tail(completed.stdout)
        stderr = _tail(completed.stderr)
    finished = datetime.now(UTC)
    return StepResult(
        name=step.name,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        started_at=started_at,
        finished_at=finished.isoformat().replace("+00:00", "Z"),
        duration_seconds=round((finished - started).total_seconds(), 3),
    )


def _summary(results: Sequence[StepResult], *, failed_step: str | None) -> dict[str, object]:
    successful_steps = [result.name for result in results if result.returncode == 0]
    return {
        "ok": failed_step is None,
        "verdict": "agency_pipeline_passed" if failed_step is None else "agency_pipeline_failed",
        "failed_step": failed_step,
        "completed_steps": successful_steps,
        "step_count": len(results),
        "successful_step_count": len(successful_steps),
        "dashboard": "http://127.0.0.1:8000/",
    }


def write_pipeline_report(
    summary: Mapping[str, object],
    results: Sequence[StepResult],
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.1.0",
        "summary": dict(summary),
        "steps": [asdict(result) for result in results],
    }
    (output_root / "first-version-pipeline.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "first-version-pipeline.md").write_text(
        _pipeline_markdown(payload),
        encoding="utf-8",
    )


def _pipeline_markdown(payload: Mapping[str, object]) -> str:
    summary = _mapping(payload["summary"])
    lines = [
        "# First-Version Agency Pipeline",
        "",
        f"Verdict: `{summary['verdict']}`",
        f"Completed steps: `{summary['successful_step_count']}` / `{summary['step_count']}`",
        f"Failed step: `{summary['failed_step']}`",
        "",
        "| Step | Status | Duration |",
        "| --- | --- | ---: |",
    ]
    for item in _step_rows(payload):
        status = "passed" if item["returncode"] == 0 else "failed"
        lines.append(f"| {item['name']} | {status} | {item['duration_seconds']}s |")
    return "\n".join(lines).rstrip() + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the guarded first-version agency loop.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "live-refresh.local.json",
    )
    parser.add_argument(
        "--subscription-email-config",
        type=Path,
        default=ROOT / "research" / "config" / "subscription-email.local.json",
    )
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--refresh-dataset", action="append")
    parser.add_argument("--skip-email", action="store_true")
    parser.add_argument("--email-max-emails", type=int, default=1)
    parser.add_argument("--email-max-article-links", type=int, default=1)
    seen_group = parser.add_mutually_exclusive_group()
    seen_group.add_argument("--email-include-seen", action="store_true")
    seen_group.add_argument("--email-unseen-only", action="store_true")
    parser.add_argument("--as-of")
    parser.add_argument("--replay-freshness", action="store_true")
    parser.add_argument("--max-tickers", type=int)
    parser.add_argument("--enable-llm-review", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--llm-review-max-candidates", type=int, default=10)
    parser.add_argument("--llm-review-include-no-trade", action="store_true")
    parser.add_argument("--persist", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-live-runtime-cycle",
    )
    parser.add_argument("--check-dashboard", action="store_true")
    parser.add_argument(
        "--report-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-first-version-pipeline",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--min-queue", type=int, default=1)
    parser.add_argument("--min-reviewed", type=int, default=0)
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def _tail(value: str, limit: int = 1200) -> str:
    cleaned = value.strip()
    return cleaned if len(cleaned) <= limit else cleaned[-limit:]


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected mapping")
    return value


def _step_rows(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = payload["steps"]
    if not isinstance(value, list):
        raise TypeError("steps must be a list")
    return [item for item in value if isinstance(item, Mapping)]


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
