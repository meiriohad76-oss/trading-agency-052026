from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN_PATH = (
    ROOT
    / "research"
    / "results"
    / "active-universe-refresh-plan-current"
    / "active-universe-refresh-plan.json"
)
STATUS_FILENAME = "active-universe-refresh-run-status.json"


def main() -> int:
    args = _parse_args()
    plan_path = args.plan
    plan = _read_plan(plan_path)
    batches = _selected_batches(
        plan,
        start_batch=args.start_batch,
        end_batch=args.end_batch,
    )
    status_path = args.status_path or plan_path.parent / STATUS_FILENAME
    if not batches:
        _write_status(status_path, state="complete", batches=[], current=None)
        print("No active-universe refresh batches selected.")
        return 0

    results: list[dict[str, Any]] = []
    for batch in batches:
        batch_result = _run_batch(batch, status_path=status_path, completed=results)
        results.append(batch_result)
        if batch_result["returncode"] != 0:
            _write_status(status_path, state="failed", batches=results, current=None)
            return int(batch_result["returncode"])
    _write_status(status_path, state="complete", batches=results, current=None)
    print(f"Active-universe refresh batches complete; wrote {status_path}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run selected batches from an active-universe refresh plan."
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--start-batch", type=int, default=1)
    parser.add_argument("--end-batch", type=int)
    parser.add_argument("--status-path", type=Path)
    return parser.parse_args()


def _read_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("active-universe refresh plan must be a JSON object")
    return payload


def _selected_batches(
    plan: dict[str, Any],
    *,
    start_batch: int,
    end_batch: int | None,
) -> list[dict[str, Any]]:
    raw_batches = plan.get("batches", [])
    if not isinstance(raw_batches, list):
        return []
    selected: list[dict[str, Any]] = []
    for value in raw_batches:
        if not isinstance(value, dict):
            continue
        batch_id = _int_value(value.get("batch_id"))
        if batch_id < start_batch:
            continue
        if end_batch is not None and batch_id > end_batch:
            continue
        selected.append(value)
    return selected


def _run_batch(
    batch: dict[str, Any],
    *,
    status_path: Path,
    completed: list[dict[str, Any]],
) -> dict[str, Any]:
    command = [str(item) for item in batch.get("command", [])]
    if not command:
        raise ValueError(f"batch {batch.get('batch_id')} has no command")
    _validate_command_scope(command, batch_id=batch.get("batch_id"))
    started_at = datetime.now(UTC)
    current = {
        "batch_id": batch.get("batch_id"),
        "dataset": batch.get("dataset"),
        "ticker_count": batch.get("ticker_count"),
        "started_at": started_at.isoformat(),
        "command": command,
    }
    _write_status(status_path, state="running", batches=completed, current=current)
    print(
        "Running batch "
        f"{batch.get('batch_id')} ({batch.get('dataset')}, {batch.get('ticker_count')} tickers)"
    )
    completed_process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    finished_at = datetime.now(UTC)
    result = {
        **current,
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "returncode": completed_process.returncode,
        "stdout_tail": completed_process.stdout[-2000:],
        "stderr_tail": completed_process.stderr[-2000:],
    }
    print(result["stdout_tail"])
    if result["stderr_tail"]:
        print(result["stderr_tail"], file=sys.stderr)
    _write_status(status_path, state="running", batches=[*completed, result], current=None)
    return result


def _validate_command_scope(command: list[str], *, batch_id: object) -> None:
    command_text = " ".join(command).lower()
    if (
        "run_data_refresh_batch.py" in command_text
        and _command_has_option_value(command, "--dataset", "stock_trades")
    ):
        raise ValueError(
            f"batch {batch_id} contains a stale direct stock_trades batch; "
            "regenerate a lane-owned plan with plan_active_universe_refresh.py "
            "and run stock-trade data through the Massive Lane Orchestrator"
        )
    if (
        "backfill_massive_stock_trades.py" in command_text
        and "--ticker" not in command
        and "--allow-active-universe" not in command
    ):
        raise ValueError(
            f"batch {batch_id} backtest trade-tape command has no explicit ticker scope"
        )
    if "pull_massive_stock_trades.py" in command_text and "--lane-id" not in command:
        raise ValueError(
            f"batch {batch_id} Massive stock-trade command is missing --lane-id"
        )


def _command_has_option_value(command: list[str], option: str, expected: str) -> bool:
    expected_normalized = expected.lower()
    option_prefix = f"{option}="
    for index, item in enumerate(command):
        normalized = item.lower()
        if normalized == option and index + 1 < len(command):
            return command[index + 1].lower() == expected_normalized
        if normalized.startswith(option_prefix):
            return normalized[len(option_prefix) :] == expected_normalized
    return False


def _write_status(
    path: Path,
    *,
    state: str,
    batches: list[dict[str, Any]],
    current: dict[str, Any] | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.1.0",
        "state": state,
        "updated_at": datetime.now(UTC).isoformat(),
        "completed_batch_count": len(batches),
        "current": current,
        "batches": batches,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
