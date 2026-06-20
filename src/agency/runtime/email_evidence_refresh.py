from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

from agency.paths import REPO_ROOT
from agency.runtime.portfolio_news_agent_bridge import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_MINI_CYCLE_STATUS_PATH,
    DEFAULT_PARQUET_PATH,
    DEFAULT_SUMMARY_ROOT,
    export_portfolio_news_agent_events,
)

PYTHON = os.environ.get("AGENCY_PYTHON", str(REPO_ROOT / ".venv" / "Scripts" / "python"))
DEFAULT_CONFIG_PATH = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
DEFAULT_MINI_CYCLE_OUTPUT_ROOT = (
    REPO_ROOT / "research" / "results" / "latest-mini-runtime-cycle" / "subscription_email"
)
MINI_CYCLE_SIGNALS = ("subscription_thesis", "news")
Runner = Callable[..., CompletedProcess[str]]


def sync_email_evidence_and_run_mini_cycles(
    *,
    root: Path | None = None,
    parquet_path: Path = DEFAULT_PARQUET_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    summary_root: Path = DEFAULT_SUMMARY_ROOT,
    status_path: Path = DEFAULT_MINI_CYCLE_STATUS_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_root: Path = DEFAULT_MINI_CYCLE_OUTPUT_ROOT,
    run_mini_cycles: bool = True,
    runner: Runner = subprocess.run,
    mini_cycle_timeout_seconds: int = 300,
) -> dict[str, object]:
    """Sync Portfolio News Agent evidence and refresh only affected tickers."""

    started_at = _utc_now()
    _write_status(
        status_path,
        state="syncing_email_evidence",
        status_label="Email evidence syncing",
        affected_tickers=[],
        ticker_statuses=[],
        detail="Portfolio News Agent article summaries are being synced into agency evidence.",
        updated_at=started_at,
    )
    sync_result = export_portfolio_news_agent_events(
        root=root,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        summary_root=summary_root,
    )
    affected = _ticker_list(sync_result.get("affected_tickers"))
    ticker_statuses = [
        _ticker_status(ticker, state="queued", status_label="Mini analysis queued")
        for ticker in affected
    ]
    _write_status(
        status_path,
        state="email_evidence_synced",
        status_label="Email evidence synced",
        affected_tickers=affected,
        ticker_statuses=ticker_statuses,
        detail=_synced_detail(affected),
    )
    if not affected or not run_mini_cycles:
        return {
            **sync_result,
            "status": "email_evidence_synced",
            "mini_cycle_status_path": str(status_path),
            "mini_cycle_count": 0,
        }

    commands: list[dict[str, object]] = []
    for index, ticker in enumerate(affected):
        ticker_statuses[index] = _ticker_status(
            ticker,
            state="running",
            status_label="Mini analysis running",
        )
        _write_status(
            status_path,
            state="mini_analysis_running",
            status_label="Mini analysis running",
            affected_tickers=affected,
            ticker_statuses=ticker_statuses,
            detail=f"Mini analysis running for {ticker}.",
        )
        command = _mini_cycle_command(
            ticker,
            config_path=config_path,
            output_root=output_root,
            generated_at=started_at,
        )
        result = _run_command(
            command,
            runner=runner,
            timeout_seconds=mini_cycle_timeout_seconds,
        )
        commands.append(result)
        if int(result["exit_code"]) == 0:
            ticker_statuses[index] = _ticker_status(
                ticker,
                state="updated",
                status_label="Stock analysis updated",
                output_root=_ticker_output_root(output_root, ticker),
                exit_code=0,
            )
        else:
            ticker_statuses[index] = _ticker_status(
                ticker,
                state="failed",
                status_label="Mini analysis failed",
                output_root=_ticker_output_root(output_root, ticker),
                exit_code=int(result["exit_code"]),
                detail=str(result.get("stderr_tail") or result.get("stdout_tail") or "mini-cycle failed"),
            )

    failed = [row for row in ticker_statuses if row.get("state") == "failed"]
    final_state = "mini_analysis_failed" if failed else "stock_analysis_updated"
    final_label = "Mini analysis failed" if failed else "Stock analysis updated"
    _write_status(
        status_path,
        state=final_state,
        status_label=final_label,
        affected_tickers=affected,
        ticker_statuses=ticker_statuses,
        detail=_final_detail(affected, failed),
        commands=commands,
    )
    return {
        **sync_result,
        "status": final_state,
        "mini_cycle_status_path": str(status_path),
        "mini_cycle_count": len(commands),
        "mini_cycle_commands": commands,
    }


def _mini_cycle_command(
    ticker: str,
    *,
    config_path: Path,
    output_root: Path,
    generated_at: datetime,
) -> list[str]:
    cycle_id = f"email-{ticker.lower()}-{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
    command = [
        PYTHON,
        str(REPO_ROOT / "scripts" / "run_live_runtime_cycle.py"),
        "--config",
        str(config_path),
        "--ticker",
        ticker,
        "--cycle-id",
        cycle_id,
        "--audit-trigger",
        "SCHEDULED",
        "--no-persist",
        "--no-broker-snapshot",
        "--no-news-consumption",
        "--output-root",
        str(_ticker_output_root(output_root, ticker)),
    ]
    for signal in MINI_CYCLE_SIGNALS:
        command.extend(["--signal", signal])
    return command


def _run_command(
    command: list[str],
    *,
    runner: Runner,
    timeout_seconds: int,
) -> dict[str, object]:
    try:
        result = runner(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": 124,
            "stdout_tail": str(exc.stdout or "")[-500:],
            "stderr_tail": str(exc.stderr or "mini-cycle timed out")[-500:],
        }
    except Exception as exc:  # noqa: BLE001 - surfaced in dashboard status.
        return {
            "command": command,
            "exit_code": 1,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "command": command,
        "exit_code": int(result.returncode),
        "stdout_tail": str(result.stdout or "")[-500:],
        "stderr_tail": str(result.stderr or "")[-500:],
    }


def _write_status(
    path: Path,
    *,
    state: str,
    status_label: str,
    affected_tickers: Sequence[str],
    ticker_statuses: Sequence[Mapping[str, object]],
    detail: str,
    updated_at: datetime | None = None,
    commands: Sequence[Mapping[str, object]] = (),
) -> None:
    payload = {
        "schema_version": "0.1.0",
        "state": state,
        "status_label": status_label,
        "status_class": "block" if state == "mini_analysis_failed" else "pass",
        "affected_tickers": list(affected_tickers),
        "affected_tickers_label": _affected_label(affected_tickers),
        "ticker_statuses": [dict(row) for row in ticker_statuses],
        "detail": detail,
        "updated_at": (updated_at or _utc_now()).isoformat(),
        "commands": [dict(row) for row in commands],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ticker_status(
    ticker: str,
    *,
    state: str,
    status_label: str,
    output_root: Path | None = None,
    exit_code: int | None = None,
    detail: str = "",
) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": ticker,
        "state": state,
        "status_label": status_label,
        "status_class": "block" if state == "failed" else "warn" if state == "running" else "pass",
        "updated_at": _utc_now().isoformat(),
    }
    if output_root is not None:
        row["output_root"] = str(output_root)
    if exit_code is not None:
        row["exit_code"] = exit_code
    if detail:
        row["detail"] = detail
    return row


def _ticker_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return sorted(
        {
            str(item).strip().upper()
            for item in value
            if str(item).strip()
        }
    )


def _ticker_output_root(output_root: Path, ticker: str) -> Path:
    return output_root / ticker.lower()


def _synced_detail(affected: Sequence[str]) -> str:
    if affected:
        return f"Email evidence synced. {_affected_label(affected)}."
    return "Email evidence synced. No newly affected stock summaries were found."


def _final_detail(affected: Sequence[str], failed: Sequence[Mapping[str, object]]) -> str:
    if failed:
        failed_tickers = ", ".join(str(row.get("ticker")) for row in failed)
        return f"Email evidence synced, but mini analysis failed for {failed_tickers}."
    return f"Stock analysis updated. {_affected_label(affected)}."


def _affected_label(affected: Sequence[str]) -> str:
    if not affected:
        return "Affected tickers: none"
    shown = ", ".join(affected[:8])
    extra = len(affected) - 8
    if extra > 0:
        shown = f"{shown}, +{extra} more"
    return f"Affected tickers: {shown}"


def _utc_now() -> datetime:
    return datetime.now(UTC)
