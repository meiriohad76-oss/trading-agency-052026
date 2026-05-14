#!/usr/bin/env python
"""Daily operations entry point for Trading Agency v2.

Runs the full daily paper-trading loop:
  1. Operational readiness check
  2. Market-aware data refresh (or skip with --skip-refresh)
  3. PIT runtime cycle
  4. Review queue check

Each step prints a timestamped status line. Any failure prints a recovery
hint and exits with a non-zero code.

Usage:
    python scripts/run_daily_ops.py [--dry-run] [--skip-refresh]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _step(label: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"\n[{ts}] -- {label} --", flush=True)


def _run(cmd: list[str], *, hint: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] would run: {' '.join(cmd)}")
        return
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"\nFAILED. Recovery hint: {hint}")
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print steps without running them")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip data refresh step")
    args = parser.parse_args()

    _step("1 / 4  Operational readiness check (~10s)")
    _run(
        [PYTHON, str(REPO_ROOT / "scripts" / "check_operational_readiness.py")],
        hint="Fix the failing readiness check before running the cycle.",
        dry_run=args.dry_run,
    )

    if not args.skip_refresh:
        _step("2 / 4  Market-aware data refresh (~2-10 min depending on phase)")
        config = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
        _run(
            [PYTHON, str(REPO_ROOT / "research" / "scripts" / "run_data_refresh_batch.py"),
             "--config", str(config)],
            hint="Check data-refresh-status.json in research/results/latest-data-refresh/ for failed datasets.",
            dry_run=args.dry_run,
        )
    else:
        _step("2 / 4  Data refresh skipped (--skip-refresh)")

    _step("3 / 4  PIT runtime cycle (~30s)")
    _run(
        [PYTHON, str(REPO_ROOT / "scripts" / "run_first_version_pipeline.py"),
         "--email-max-emails", "5",
         "--email-max-article-links", "2"],
        hint="Check the dashboard at http://127.0.0.1:8000/command for cycle errors.",
        dry_run=args.dry_run,
    )

    _step("4 / 4  Review queue check (~5s)")
    _run(
        [PYTHON, str(REPO_ROOT / "scripts" / "check_paper_review_status.py")],
        hint="Open http://127.0.0.1:8000/command and review the WATCH candidates.",
        dry_run=args.dry_run,
    )

    _step("Done")
    print("All steps completed. Open http://127.0.0.1:8000/command to review candidates.")


if __name__ == "__main__":
    main()
