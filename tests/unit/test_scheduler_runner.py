from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from datetime import UTC, datetime, timedelta

import agency.runtime.scheduler_runner as scheduler_runner
import agency.runtime.scheduler_status as scheduler_status
from agency.runtime.scheduler_runner import jobs_for_phase


def test_pre_market_jobs_include_stock_trades_and_email() -> None:
    jobs = jobs_for_phase("pre_market")
    names = {j["name"] for j in jobs}
    assert "stock_trades" in names
    assert "subscription_emails" in names
    assert "sec_company_facts" not in names


def test_regular_market_jobs_include_stock_trades_and_news() -> None:
    jobs = jobs_for_phase("regular_market")
    names = {j["name"] for j in jobs}
    assert "stock_trades" in names
    assert "news_rss" in names
    assert "prices_daily" not in names
    assert "sec_form4" not in names


def test_dataset_refresh_command_uses_singular_dataset_arg(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "research" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "live-refresh.local.json").write_text("{}", encoding="utf-8")
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(cmd))
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return Result()

    monkeypatch.setattr(scheduler_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(scheduler_runner, "PYTHON", "python")
    monkeypatch.setattr(scheduler_runner.subprocess, "run", fake_run)

    scheduler_runner._run_dataset_refresh("stock_trades")

    assert commands == []


def test_after_hours_jobs_include_prices_and_trades() -> None:
    jobs = jobs_for_phase("after_hours")
    names = {j["name"] for j in jobs}
    assert "prices_daily" in names
    assert "stock_trades" in names


def test_overnight_jobs_include_sec_baselines() -> None:
    jobs = jobs_for_phase("overnight_after_hours")
    names = {j["name"] for j in jobs}
    assert "sec_company_facts" in names
    assert "sec_form4" in names
    assert "sec_13f" in names


def test_scheduler_phase_aliases_and_real_closed_phases_have_jobs() -> None:
    assert jobs_for_phase("overnight") == jobs_for_phase("overnight_after_hours")
    assert jobs_for_phase("holiday") == jobs_for_phase("closed_holiday")
    assert jobs_for_phase("overnight_before_pre_market")
    assert jobs_for_phase("closed_weekend")
    assert jobs_for_phase("closed_holiday")


def test_work_queue_tick_prefers_massive_lanes_and_refreshes_runtime(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_context(**kwargs):  # type: ignore[no-untyped-def]
        assert "data_load_status" in kwargs
        return {
            "massive_orchestrator": {
                "lanes": [
                    {
                        "job_id": "massive:massive_live_trade_slices",
                        "kind": "massive_lane",
                        "name": "massive_live_trade_slices",
                        "lane_id": "massive_live_trade_slices",
                        "status": "DUE_NOW",
                        "command": ["python", "pull-lane.py"],
                    }
                ]
            },
            "jobs": [
                {
                    "job_id": "dataset:stock_trades",
                    "kind": "dataset",
                    "name": "stock_trades",
                    "status": "SKIPPED",
                    "command": [],
                },
                {
                    "job_id": "dataset:news_rss",
                    "kind": "dataset",
                    "name": "news_rss",
                    "status": "DUE_NOW",
                    "command": ["python", "pull-news.py"],
                },
            ],
        }

    def fake_run(command: list[str]) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("agency.runtime.data_load_status.load_data_load_status", lambda: {})
    monkeypatch.setattr("agency.runtime.data_refresh_progress.load_data_refresh_progress", lambda: {})
    monkeypatch.setattr(
        "agency.runtime.scheduler_work_queue.scheduler_work_queue_context",
        fake_context,
    )
    monkeypatch.setattr(scheduler_runner, "_load_live_scheduler_work_queue", lambda: None)
    monkeypatch.setattr(scheduler_runner, "_run_queue_command", fake_run)
    monkeypatch.setattr(
        scheduler_runner,
        "_runtime_cycle_command",
        lambda **_kwargs: ["python", "cycle.py"],
    )
    monkeypatch.setattr(scheduler_runner, "WORK_QUEUE_MAX_COMMANDS", 2)
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_AFTER_DATA_REFRESH", True)

    scheduler_runner._run_work_queue_tick()

    assert commands == [
        ["python", "pull-lane.py"],
        ["python", "pull-news.py"],
        ["python", "cycle.py"],
    ]


def test_manual_massive_lane_refresh_runs_only_requested_due_lane(monkeypatch) -> None:
    commands: list[list[str]] = []
    recorded: list[dict[str, object]] = []
    queue = {
        "massive_orchestrator": {
            "lanes": [
                {
                    "job_id": "massive:massive_live_trade_slices",
                    "kind": "massive_lane",
                    "name": "massive_live_trade_slices",
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "status": "DUE_NOW",
                    "command": ["python", "pull-live.py", "--ticker", "AAPL"],
                },
                {
                    "job_id": "massive:massive_daily_bars",
                    "kind": "massive_lane",
                    "name": "massive_daily_bars",
                    "lane_id": "massive_daily_bars",
                    "label": "Massive Daily Bars",
                    "status": "DUE_NOW",
                    "command": ["python", "pull-daily.py"],
                },
            ],
        },
        "jobs": [],
    }

    def fake_record(**kwargs):  # type: ignore[no-untyped-def]
        recorded.append(dict(kwargs))
        return dict(kwargs)

    def fake_run(command: list[str]) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(scheduler_status, "record_scheduler_runtime_status", fake_record)

    result = scheduler_runner.run_manual_massive_lane_refresh(
        "massive_live_trade_slices",
        queue_provider=lambda: queue,
        runner=fake_run,
    )

    assert result["state"] == "completed"
    assert commands == [["python", "pull-live.py", "--ticker", "AAPL"]]
    assert recorded[-1]["state"] == "idle"
    manual = recorded[-1]["extra"]["manual_lane_refresh"]  # type: ignore[index]
    assert manual["lane_id"] == "massive_live_trade_slices"
    assert manual["status"] == "completed"


def test_manual_massive_lane_refresh_refuses_policy_unavailable_lane(monkeypatch) -> None:
    commands: list[list[str]] = []
    recorded: list[dict[str, object]] = []
    queue = {
        "massive_orchestrator": {
            "lanes": [
                {
                    "job_id": "massive:massive_backtest_trade_tape",
                    "kind": "massive_lane",
                    "name": "massive_backtest_trade_tape",
                    "lane_id": "massive_backtest_trade_tape",
                    "label": "Massive Backtest Trade Tape",
                    "status": "DEFERRED",
                    "command": [],
                    "reason": "Full-depth backtest tape is deferred during market hours.",
                }
            ],
        },
        "jobs": [],
    }

    def fake_record(**kwargs):  # type: ignore[no-untyped-def]
        recorded.append(dict(kwargs))
        return dict(kwargs)

    def fake_run(command: list[str]) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, stdout="should not run", stderr="")

    monkeypatch.setattr(scheduler_status, "record_scheduler_runtime_status", fake_record)

    result = scheduler_runner.run_manual_massive_lane_refresh(
        "massive_backtest_trade_tape",
        queue_provider=lambda: queue,
        runner=fake_run,
    )

    assert result["state"] == "refused"
    assert commands == []
    assert "trade-aware policy" in str(result["detail"])
    manual = recorded[-1]["extra"]["manual_lane_refresh"]  # type: ignore[index]
    assert manual["status"] == "refused"


def test_work_queue_tick_marks_timed_out_dataset_refresh_status_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    status_path = (
        tmp_path
        / "research"
        / "results"
        / "latest-data-refresh"
        / "data-refresh-status.json"
    )
    status_path.parent.mkdir(parents=True)
    status_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "dataset": "sec_form4",
                        "status": "running",
                        "reason": "SEC Form 4 baseline is running",
                        "command": ["python", "pull-sec-form4.py"],
                    }
                ],
                "progress": {
                    "state": "running",
                    "total_jobs": 1,
                    "completed_jobs": 0,
                    "running_jobs": 1,
                    "pending_jobs": 0,
                    "percent_complete": 0,
                    "current_dataset": "sec_form4",
                },
                "failed": False,
                "has_failures": False,
                "failed_datasets": [],
                "in_progress": True,
            }
        ),
        encoding="utf-8",
    )

    def fake_context(**_kwargs):  # type: ignore[no-untyped-def]
        return {
            "massive_orchestrator": {"lanes": []},
            "jobs": [
                {
                    "job_id": "dataset:sec_form4",
                    "kind": "dataset",
                    "name": "sec_form4",
                    "dataset": "sec_form4",
                    "status": "DUE_NOW",
                    "command": ["python", "pull-sec-form4.py"],
                }
            ],
        }

    def fake_run(command: list[str]) -> CompletedProcess[str]:
        return CompletedProcess(
            command,
            124,
            stdout="",
            stderr="Command timed out after 240s.",
        )

    monkeypatch.setattr(scheduler_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("agency.runtime.data_load_status.load_data_load_status", lambda: {})
    monkeypatch.setattr("agency.runtime.data_refresh_progress.load_data_refresh_progress", lambda: {})
    monkeypatch.setattr(
        "agency.runtime.scheduler_work_queue.scheduler_work_queue_context",
        fake_context,
    )
    monkeypatch.setattr(scheduler_runner, "_load_live_scheduler_work_queue", lambda: None)
    monkeypatch.setattr(scheduler_runner, "_run_queue_command", fake_run)
    monkeypatch.setattr(scheduler_runner, "WORK_QUEUE_MAX_COMMANDS", 1)
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_AFTER_DATA_REFRESH", False)

    scheduler_runner._run_work_queue_tick()

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    job = payload["jobs"][0]
    assert job["status"] == "failed"
    assert job["returncode"] == 124
    assert "timed out" in job["stderr"]
    assert payload["progress"]["state"] == "failed"
    assert payload["progress"]["current_dataset"] is None
    assert payload["failed"] is True
    assert payload["has_failures"] is True
    assert payload["failed_datasets"] == ["sec_form4"]
    assert payload["in_progress"] is False


def test_work_queue_tick_records_job_success_cadence_memory(monkeypatch) -> None:
    command_started = datetime(2026, 5, 17, 14, 0, tzinfo=UTC)

    def fake_context(**_kwargs):  # type: ignore[no-untyped-def]
        return {
            "massive_orchestrator": {"lanes": []},
            "jobs": [
                {
                    "job_id": "dataset:sec_form4",
                    "kind": "dataset",
                    "name": "sec_form4",
                    "dataset": "sec_form4",
                    "status": "DUE_NOW",
                    "command": ["python", "pull-sec-form4.py"],
                }
            ],
        }

    monkeypatch.setattr("agency.runtime.data_load_status.load_data_load_status", lambda: {})
    monkeypatch.setattr("agency.runtime.data_refresh_progress.load_data_refresh_progress", lambda: {})
    monkeypatch.setattr(
        "agency.runtime.scheduler_work_queue.scheduler_work_queue_context",
        fake_context,
    )
    monkeypatch.setattr(scheduler_runner, "_load_live_scheduler_work_queue", lambda: None)
    monkeypatch.setattr(
        scheduler_runner,
        "_run_queue_command",
        lambda command: CompletedProcess(command, 0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(scheduler_runner, "WORK_QUEUE_MAX_COMMANDS", 1)
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_AFTER_DATA_REFRESH", False)

    scheduler_runner._run_work_queue_tick()

    status = scheduler_status.load_scheduler_runtime_status(now=command_started)
    success_at = status["job_last_success_at"]["dataset:sec_form4"]
    assert isinstance(success_at, str)
    assert status["last_tick_commands"][0]["exit_code"] == 0


def test_work_queue_command_extractor_ignores_signal_jobs() -> None:
    queue = {
        "massive_orchestrator": {"lanes": []},
        "jobs": [
            {"kind": "signal_lane", "status": "DUE_NOW", "command": ["python", "signal.py"]},
            {"kind": "dataset", "status": "DUE_NOW", "command": ["python", "data.py"]},
        ],
    }

    commands = scheduler_runner._commands_for_tick(queue)

    assert len(commands) == 1
    assert commands[0]["command"] == ["python", "data.py"]


def test_work_queue_command_extractor_does_not_rerun_running_lanes() -> None:
    queue = {
        "massive_orchestrator": {
            "lanes": [
                {
                    "kind": "massive_lane",
                    "status": "RUNNING",
                    "command": ["python", "pull-lane.py"],
                }
            ]
        },
        "jobs": [],
    }

    assert scheduler_runner._commands_for_tick(queue) == []


def test_runtime_cycle_command_scopes_to_refreshed_tickers(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_MAX_TICKERS", 2)
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_PERSIST", True)

    command = scheduler_runner._runtime_cycle_command(tickers=["msft", "AAPL", "MSFT"])

    assert "--runtime-universe" not in command
    assert "--max-tickers" not in command
    assert command.count("--ticker") == 2
    assert command[command.index("--ticker") + 1] == "MSFT"
    assert "AAPL" in command
    assert "--persist" not in command
    assert "--no-persist" in command
    assert command[command.index("--output-root") + 1] == "research\\results\\latest-mini-runtime-cycle"


def test_runtime_cycle_command_has_bounded_active_fallback(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_MAX_TICKERS", 12)
    monkeypatch.setattr(scheduler_runner, "RUNTIME_CYCLE_PERSIST", False)

    command = scheduler_runner._runtime_cycle_command(tickers=[])

    assert command[command.index("--runtime-universe") + 1] == "active"
    assert command[command.index("--max-tickers") + 1] == "12"
    assert command[command.index("--output-root") + 1] == "research\\results\\latest-live-runtime-cycle"
    assert "--no-persist" in command


def test_runtime_cycle_command_honors_scheduler_llm_toggle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(scheduler_runner, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("AGENCY_ENABLE_LLM_REVIEW", raising=False)
    monkeypatch.delenv("AGENCY_SCHEDULER_ENABLE_LLM_REVIEW", raising=False)
    monkeypatch.setattr(scheduler_runner, "SCHEDULER_ENABLE_LLM_REVIEW", True)

    enabled = scheduler_runner._runtime_cycle_command(tickers=["AAPL"])

    monkeypatch.setattr(scheduler_runner, "SCHEDULER_ENABLE_LLM_REVIEW", False)
    disabled = scheduler_runner._runtime_cycle_command(tickers=["AAPL"])

    assert "--enable-llm-review" in enabled
    assert "--no-enable-llm-review" not in enabled
    assert "--no-enable-llm-review" in disabled
    assert "--enable-llm-review" not in disabled


def test_runtime_cycle_command_loads_llm_toggle_from_env_file_after_import(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("AGENCY_ENABLE_LLM_REVIEW=true\n", encoding="utf-8")
    monkeypatch.setattr(scheduler_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(scheduler_runner, "SCHEDULER_ENABLE_LLM_REVIEW", False)
    monkeypatch.delenv("AGENCY_ENABLE_LLM_REVIEW", raising=False)
    monkeypatch.delenv("AGENCY_SCHEDULER_ENABLE_LLM_REVIEW", raising=False)

    command = scheduler_runner._runtime_cycle_command(tickers=["AAPL"])

    assert "--enable-llm-review" in command
    assert "--no-enable-llm-review" not in command


def test_scheduler_uses_memory_jobs_by_default_even_with_database_url() -> None:
    scheduler = scheduler_runner.build_scheduler("sqlite:///:memory:")

    assert "default" not in scheduler._jobstores  # noqa: SLF001


def test_work_queue_skip_preserves_stale_running_tick(monkeypatch) -> None:
    started_at = datetime.now(UTC) - timedelta(minutes=30)
    previous = {
        "schema_version": "0.1.0",
        "generated_at": started_at.isoformat(),
        "enabled": True,
        "database_configured": False,
        "state": "running",
        "status_label": "Running",
        "status_class": "pass",
        "job_count": 1,
        "detail": "Automatic lane refresh is running massive_live_trade_slices.",
        "tick_state": "running",
        "last_tick_started_at": started_at.isoformat(),
        "active_command": {
            "job_id": "massive:massive_live_trade_slices",
            "kind": "massive_lane",
            "name": "massive_live_trade_slices",
        },
    }
    monkeypatch.setattr(scheduler_status, "_RUNTIME_STATUS", dict(previous))
    monkeypatch.setattr(scheduler_status, "DEFAULT_TICK_STALE_SECONDS", 60)
    monkeypatch.setattr(scheduler_runner, "_WORK_QUEUE_TICK_RUNNING", True)
    monkeypatch.setattr(scheduler_runner, "_load_live_scheduler_work_queue", lambda: None)

    scheduler_runner._run_work_queue_tick()

    status = scheduler_status.load_scheduler_runtime_status(now=datetime.now(UTC))
    assert status["tick_state"] == "stale"
    assert status["status_class"] == "block"
    assert status["last_tick_started_at"] == started_at.isoformat()
    assert status["active_command"] == previous["active_command"]
    assert "has not finished" in str(status["detail"])
