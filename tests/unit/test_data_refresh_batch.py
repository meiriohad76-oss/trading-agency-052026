from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import data_refresh.batch as batch
import pandas as pd
import pytest
from data_refresh.batch import build_refresh_jobs, run_refresh_batch
from data_refresh.status import result_progress
from data_refresh.types import (
    CommandResult,
    RefreshBatchConfig,
    RefreshBatchResult,
    RefreshJobResult,
)

FAILURE_CODE = 7
COMPLETE_PERCENT = 100
EXPECTED_COMMAND_DURATION_SECONDS = 3.0
EXPECTED_FORM4_ETA_SECONDS = 570
SMOKE_STOCK_TRADES_LIMIT = 1000
SMOKE_STOCK_TRADES_MAX_PAGES = 2


def test_build_refresh_jobs_blocks_missing_optional_source_config(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("sec_13f", "news_rss"))

    jobs = build_refresh_jobs(config)

    assert jobs[0].dataset == "sec_13f"
    assert "missing SEC_USER_AGENT" in jobs[0].blocked_reasons
    assert "missing 13F filer CIKs" in jobs[0].blocked_reasons
    assert "missing 13F CUSIP map" in jobs[0].blocked_reasons
    assert jobs[1].dataset == "news_rss"
    assert jobs[1].blocked_reasons == ("missing RSS feed specs",)


def test_build_refresh_jobs_uses_static_tickers_without_universe_file(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("prices_daily", "options_chains"),
        tickers=("aapl", "MSFT"),
    )

    jobs = build_refresh_jobs(config)

    assert all(job.blocked_reasons == () for job in jobs)
    assert jobs[0].display_command[-2:] == ("AAPL", "MSFT")
    assert jobs[1].display_command[-4:] == ("--ticker", "AAPL", "--ticker", "MSFT")


def test_build_refresh_jobs_blocks_alpaca_without_credentials(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("prices_daily",),
        tickers=("AAPL",),
        market_data_provider="alpaca",
    )

    job = build_refresh_jobs(config)[0]

    assert job.blocked_reasons == ("missing Alpaca market data credentials",)
    assert "--provider" in job.display_command
    assert "alpaca" in job.display_command


def test_build_refresh_jobs_passes_alpaca_market_data_options(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("prices_daily",),
        tickers=("AAPL",),
        market_data_provider="alpaca",
        market_data_credentials_present=True,
    )

    job = build_refresh_jobs(config)[0]

    assert job.blocked_reasons == ()
    assert "--alpaca-feed" in job.display_command
    assert "iex" in job.display_command


def test_build_refresh_jobs_blocks_massive_prices_without_credentials(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("prices_daily",),
        tickers=("AAPL",),
        market_data_provider="massive",
    )

    job = build_refresh_jobs(config)[0]

    assert "prices_daily is lane-owned by massive_daily_bars when provider=massive" in job.blocked_reasons
    assert "missing Massive market data credentials" in job.blocked_reasons
    assert job.display_command == ()


def test_build_refresh_jobs_passes_massive_market_data_options(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("prices_daily",),
        tickers=("AAPL",),
        market_data_provider="massive",
        massive_credentials_present=True,
    )

    job = build_refresh_jobs(config)[0]

    assert "prices_daily is lane-owned by massive_daily_bars when provider=massive" in job.blocked_reasons
    assert "use the scheduler work queue / Massive Lane Orchestrator instead of run_data_refresh_batch" in job.blocked_reasons
    assert job.display_command == ()


def test_build_refresh_jobs_accepts_local_activity_alert_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "alerts.csv"
    csv_path.write_text("ticker,alert_type,direction,observed_at\nAAPL,block,buy,2026-05-08\n")
    missing = _config(tmp_path, datasets=("unusual_activity_alerts",))
    ready = _config(tmp_path, datasets=("unusual_activity_alerts",), activity_alerts_csv=csv_path)

    blocked_job = build_refresh_jobs(missing)[0]
    ready_job = build_refresh_jobs(ready)[0]

    assert blocked_job.blocked_reasons == ("missing unusual activity alerts CSV",)
    assert ready_job.blocked_reasons == ()
    assert ready_job.display_command[-2:] == ("--input", "alerts.csv")


def test_build_refresh_jobs_accepts_subscription_email_config(tmp_path: Path) -> None:
    mailbox = tmp_path / "mail"
    mailbox.mkdir()
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        json.dumps({"mode": "local_eml", "input_path": str(mailbox)}),
        encoding="utf-8",
    )
    missing = _config(tmp_path, datasets=("subscription_emails",))
    ready = _config(
        tmp_path,
        datasets=("subscription_emails",),
        subscription_email_config=config_path,
    )

    blocked_job = build_refresh_jobs(missing)[0]
    ready_job = build_refresh_jobs(ready)[0]

    assert blocked_job.blocked_reasons == ("missing subscription email config",)
    assert ready_job.blocked_reasons == ()
    assert ready_job.display_command[-2:] == ("--config", "subscription-email.json")


def test_build_refresh_jobs_blocks_missing_subscription_email_input(tmp_path: Path) -> None:
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        json.dumps({"mode": "local_eml", "input_path": "missing-mail"}),
        encoding="utf-8",
    )
    config = _config(
        tmp_path,
        datasets=("subscription_emails",),
        subscription_email_config=config_path,
    )

    job = build_refresh_jobs(config)[0]

    assert job.blocked_reasons == ("missing subscription email input: missing-mail",)


def test_build_refresh_jobs_accepts_gmail_app_password_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_USERNAME", "user@example.test")
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_PASSWORD", "app-password")
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "gmail",
                "input_path": str(tmp_path / "mail"),
                "mailbox_username_env": "SUBSCRIPTION_EMAIL_USERNAME",
                "mailbox_password_env": "SUBSCRIPTION_EMAIL_PASSWORD",
            }
        ),
        encoding="utf-8",
    )
    config = _config(
        tmp_path,
        datasets=("subscription_emails",),
        subscription_email_config=config_path,
    )

    job = build_refresh_jobs(config)[0]

    assert job.blocked_reasons == ()


def test_build_refresh_jobs_blocks_gmail_token_without_env_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUBSCRIPTION_EMAIL_USERNAME", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_EMAIL_PASSWORD", raising=False)
    token_path = tmp_path / "subscription-token.json"
    token_path.write_text("{}", encoding="utf-8")
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "gmail",
                "input_path": str(tmp_path / "mail"),
                "token_path": str(token_path),
                "mailbox_username_env": "SUBSCRIPTION_EMAIL_USERNAME",
                "mailbox_password_env": "SUBSCRIPTION_EMAIL_PASSWORD",
            }
        ),
        encoding="utf-8",
    )
    config = _config(
        tmp_path,
        datasets=("subscription_emails",),
        subscription_email_config=config_path,
    )

    job = build_refresh_jobs(config)[0]

    assert job.blocked_reasons == (
        "missing subscription mailbox credentials: SUBSCRIPTION_EMAIL_USERNAME, SUBSCRIPTION_EMAIL_PASSWORD",
    )


def test_build_refresh_jobs_keeps_email_login_interactive_for_scheduled_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_USERNAME", "user@example.test")
    monkeypatch.setenv("SUBSCRIPTION_EMAIL_PASSWORD", "app-password")
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "gmail",
                "input_path": str(tmp_path / "mail"),
                "mailbox_username_env": "SUBSCRIPTION_EMAIL_USERNAME",
                "mailbox_password_env": "SUBSCRIPTION_EMAIL_PASSWORD",
                "article_login_preflight_required": True,
            }
        ),
        encoding="utf-8",
    )
    config = _config(
        tmp_path,
        datasets=("subscription_emails",),
        subscription_email_config=config_path,
    )

    job = build_refresh_jobs(config)[0]

    assert job.blocked_reasons == ()
    assert job.requires_console is True
    assert "--no-require-article-login" not in job.command
    assert "--max-article-links" not in job.command


def test_build_refresh_jobs_blocks_stock_trades_without_massive_credentials(
    tmp_path: Path,
) -> None:
    missing = _config(tmp_path, datasets=("stock_trades",), tickers=("aapl",))
    ready = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("aapl",),
        massive_credentials_present=True,
    )

    blocked_job = build_refresh_jobs(missing)[0]
    ready_job = build_refresh_jobs(ready)[0]

    assert "stock_trades is lane-owned" in blocked_job.blocked_reasons[0]
    assert "stock_trades is lane-owned" in ready_job.blocked_reasons[0]
    assert blocked_job.display_command == ()
    assert ready_job.display_command == ()


def test_build_refresh_jobs_passes_stock_trade_refresh_guardrails(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("aapl",),
        massive_credentials_present=True,
        stock_trades_limit=1000,
        stock_trades_max_pages_per_day=2,
    )

    job = build_refresh_jobs(config)[0]

    assert job.display_command == ()
    assert "Massive Lane Orchestrator" in job.blocked_reasons[1]


def test_build_refresh_jobs_defaults_stock_trades_to_end_date(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("aapl",),
        massive_credentials_present=True,
    )

    job = build_refresh_jobs(config)[0]

    assert job.display_command == ()
    assert "stock_trades is lane-owned" in job.blocked_reasons[0]


def test_build_refresh_jobs_uses_stock_trade_end_when_start_is_absent(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("aapl",),
        massive_credentials_present=True,
        stock_trades_end=date(2021, 1, 29),
    )

    job = build_refresh_jobs(config)[0]

    assert job.display_command == ()
    assert "stock_trades is lane-owned" in job.blocked_reasons[0]


def test_build_refresh_jobs_accepts_explicit_stock_trade_window(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("aapl",),
        massive_credentials_present=True,
        stock_trades_start=date(2021, 1, 28),
        stock_trades_end=date(2021, 1, 29),
    )

    job = build_refresh_jobs(config)[0]

    assert job.display_command == ()
    assert "stock_trades is lane-owned" in job.blocked_reasons[0]


def test_build_refresh_jobs_blocks_unsafe_stock_trade_history_window(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("aapl", "msft"),
        massive_credentials_present=True,
        stock_trades_start=date(2021, 1, 1),
        stock_trades_end=date(2021, 2, 28),
    )

    job = build_refresh_jobs(config)[0]

    assert job.display_command == ()
    assert "stock_trades is lane-owned" in job.blocked_reasons[0]


def test_run_refresh_batch_dry_run_writes_status(tmp_path: Path) -> None:
    cusip_map = tmp_path / "cusips.json"
    cusip_map.write_text('{"037833100": "AAPL"}', encoding="utf-8")
    config = _config(
        tmp_path,
        datasets=("sec_13f", "news_rss"),
        rss_feeds=("Yahoo,AAPL,https://example.test/rss",),
        filer_ciks=("0001067983",),
        cusip_map=cusip_map,
        sec_user_agent="Trading Agency admin@example.com",
        dry_run=True,
    )

    result = run_refresh_batch(config)

    status = json.loads(
        (config.output_root / "data-refresh-status.json").read_text(encoding="utf-8")
    )
    assert [job.status for job in result.jobs] == ["planned", "planned"]
    assert result.jobs[1].command[-1] == "Yahoo,AAPL,https://example.test/rss"
    assert status["blocked"] is False
    assert status["failed"] is False
    assert (config.output_root / "data-refresh-status.md").is_file()


def test_run_refresh_batch_status_includes_stock_trade_guardrails(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("AAPL",),
        dry_run=True,
        massive_credentials_present=True,
        stock_trades_limit=SMOKE_STOCK_TRADES_LIMIT,
        stock_trades_max_pages_per_day=SMOKE_STOCK_TRADES_MAX_PAGES,
    )

    run_refresh_batch(config)

    status = json.loads(
        (config.output_root / "data-refresh-status.json").read_text(encoding="utf-8")
    )
    markdown = (config.output_root / "data-refresh-status.md").read_text(encoding="utf-8")
    assert status["config"]["stock_trades_limit"] == SMOKE_STOCK_TRADES_LIMIT
    assert (
        status["config"]["stock_trades_max_pages_per_day"] == SMOKE_STOCK_TRADES_MAX_PAGES
    )
    assert f"max pages/day {SMOKE_STOCK_TRADES_MAX_PAGES}" in markdown


def test_run_refresh_batch_status_marks_unbounded_stock_trade_pages(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("AAPL",),
        dry_run=True,
        massive_credentials_present=True,
    )

    run_refresh_batch(config)

    status = json.loads(
        (config.output_root / "data-refresh-status.json").read_text(encoding="utf-8")
    )
    markdown = (config.output_root / "data-refresh-status.md").read_text(encoding="utf-8")
    assert status["config"]["stock_trades_max_pages_per_day"] is None
    assert "max pages/day unbounded" in markdown


def test_run_refresh_batch_skips_fresh_company_facts_baseline(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "sec_company_facts",
        fetched_at=datetime(2026, 5, 8, 12, tzinfo=UTC),
    )
    _write_ticker_frame(tmp_path, "sec_company_facts", "AAPL", "period_end")
    config = _config(
        tmp_path,
        datasets=("sec_company_facts",),
        tickers=("AAPL",),
        sec_user_agent="Trading Agency admin@example.com",
    )
    clock = _fixed_clock(datetime(2026, 5, 9, 12, tzinfo=UTC))

    result = run_refresh_batch(config, runner=_unexpected_runner, clock=clock)

    assert result.jobs[0].status == "skipped"
    assert result.jobs[0].extraction_action == "skip"
    assert "freshness window" in result.jobs[0].reason


def test_build_refresh_jobs_narrows_price_command_to_incremental_window(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "prices_daily")
    _write_ticker_frame(
        tmp_path,
        "prices_daily",
        "AAPL",
        "date",
        values=(date(2021, 1, 1), date(2021, 1, 15)),
    )
    config = _config(tmp_path, datasets=("prices_daily",), tickers=("AAPL",))

    job = build_refresh_jobs(config)[0]

    assert job.extraction_action == "incremental"
    assert job.display_command[job.display_command.index("--start") + 1] == "2021-01-16"
    assert job.display_command[job.display_command.index("--end") + 1] == "2021-01-31"


def test_build_refresh_jobs_baselines_missing_stock_trade_tickers(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "stock_trades")
    _write_ticker_frame(tmp_path, "stock_trades", "AAPL", "trade_date")
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("AAPL", "MSFT"),
        massive_credentials_present=True,
        stock_trades_start=date(2021, 1, 29),
        stock_trades_end=date(2021, 1, 31),
    )

    job = build_refresh_jobs(config)[0]

    assert job.extraction_action == "baseline"
    assert job.display_command == ()
    assert "stock_trades is lane-owned" in job.blocked_reasons[0]


def test_run_refresh_batch_records_failed_datasets(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("prices_daily", "news_rss"), tickers=("AAPL",))

    def runner(command: Sequence[str], cwd: Path) -> CommandResult:
        del cwd
        if "pull_yfinance_daily.py" in str(command):
            return CommandResult(1, stdout="", stderr="network failed")
        return CommandResult(0)

    result = run_refresh_batch(config, runner=runner)

    status_json = json.loads(
        (config.output_root / "data-refresh-status.json").read_text(encoding="utf-8")
    )
    assert result.failed is True
    assert status_json["has_failures"] is True
    assert status_json["failed_datasets"] == ["prices_daily"]


def test_run_refresh_batch_records_fake_command_failure(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("prices_daily",), tickers=("AAPL",))

    def runner(command: Sequence[str], cwd: Path) -> CommandResult:
        assert cwd == tmp_path
        assert "pull_yfinance_daily.py" in command[1]
        return CommandResult(FAILURE_CODE, stdout="partial output", stderr="network failed")

    result = run_refresh_batch(config, runner=runner)

    assert result.failed is True
    assert result.jobs[0].status == "failed"
    assert result.jobs[0].returncode == FAILURE_CODE
    assert result.jobs[0].stderr == "network failed"


def test_subprocess_console_runner_captures_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    class FakePipe:
        def __init__(self, chunks: list[str]) -> None:
            self.chunks = chunks
            self.closed = False

        def __iter__(self):
            return iter(self.chunks)

        def close(self) -> None:
            self.closed = True

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = FakePipe(["console stdout\n"])
            self.stderr = FakePipe(["console stderr\n"])

        def wait(self) -> int:
            return FAILURE_CODE

    def fake_popen(
        command: list[str],
        *,
        cwd: Path,
        stdout: object,
        stderr: object,
        stdin: object,
        text: bool,
        bufsize: int,
    ) -> FakeProcess:
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "stdout": stdout,
                "stderr": stderr,
                "stdin": stdin,
                "text": text,
                "bufsize": bufsize,
            }
        )
        return FakeProcess()

    monkeypatch.setattr(batch.subprocess, "Popen", fake_popen)

    result = batch._subprocess_console_runner(("tool", "--flag"), tmp_path)

    captured = capsys.readouterr()
    assert result == CommandResult(FAILURE_CODE, "console stdout\n", "console stderr\n")
    assert captured.out == "console stdout\n"
    assert captured.err == "console stderr\n"
    assert calls == [
        {
            "command": ["tool", "--flag"],
            "cwd": tmp_path,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": None,
            "text": True,
            "bufsize": 1,
        }
    ]


def test_run_refresh_batch_writes_running_progress_before_job_finishes(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("prices_daily",), tickers=("AAPL",))
    clock = _clock()

    def runner(command: Sequence[str], cwd: Path) -> CommandResult:
        del command, cwd
        status = json.loads(
            (config.output_root / "data-refresh-status.json").read_text(encoding="utf-8")
        )
        assert status["progress"]["state"] == "running"
        assert status["jobs"][0]["status"] == "running"
        assert status["progress"]["current_dataset"] == "prices_daily"
        assert status["progress"]["eta_seconds"] > 0
        return CommandResult(0)

    result = run_refresh_batch(config, runner=runner, clock=clock)
    status = json.loads(
        (config.output_root / "data-refresh-status.json").read_text(encoding="utf-8")
    )

    assert result.in_progress is False
    assert status["progress"]["state"] == "complete"
    assert status["progress"]["percent_complete"] == COMPLETE_PERCENT
    assert status["jobs"][0]["duration_seconds"] is not None


def test_run_refresh_batch_records_elapsed_command_duration(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("prices_daily",), tickers=("AAPL",))
    clock = _clock()

    def runner(command: Sequence[str], cwd: Path) -> CommandResult:
        del command, cwd
        clock()
        clock()
        return CommandResult(0)

    result = run_refresh_batch(config, runner=runner, clock=clock)

    assert result.jobs[0].duration_seconds == EXPECTED_COMMAND_DURATION_SECONDS


def test_result_progress_keeps_slow_dataset_eta_baseline(tmp_path: Path) -> None:
    started_at = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    result = RefreshBatchResult(
        config=_config(tmp_path, datasets=("prices_daily", "sec_form4")),
        jobs=(
            RefreshJobResult(
                dataset="prices_daily",
                status="passed",
                reason="done",
                command=("$PYTHON",),
                duration_seconds=3.0,
            ),
            RefreshJobResult(
                dataset="sec_form4",
                status="running",
                reason="running",
                command=("$PYTHON",),
                started_at=started_at.isoformat(),
            ),
        ),
        written_paths=(),
        updated_at=(started_at + timedelta(seconds=30)).isoformat(),
    )

    progress = result_progress(result)

    assert progress["eta_seconds"] == EXPECTED_FORM4_ETA_SECONDS


def test_result_progress_prioritizes_failed_job_over_running_job(tmp_path: Path) -> None:
    result = RefreshBatchResult(
        config=_config(tmp_path, datasets=("prices_daily", "sec_form4")),
        jobs=(
            RefreshJobResult(
                dataset="prices_daily",
                status="failed",
                reason="network failed",
                command=("$PYTHON",),
            ),
            RefreshJobResult(
                dataset="sec_form4",
                status="running",
                reason="running",
                command=("$PYTHON",),
            ),
        ),
        written_paths=(),
    )

    progress = result_progress(result)

    assert progress["state"] == "failed"


def test_build_refresh_jobs_rejects_unknown_dataset(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("not_a_dataset",))

    with pytest.raises(ValueError, match="unknown dataset"):
        build_refresh_jobs(config)


def test_build_refresh_jobs_rejects_invalid_stock_trade_guardrails(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        datasets=("stock_trades",),
        tickers=("AAPL",),
        stock_trades_limit=0,
    )

    with pytest.raises(ValueError, match="stock_trades_limit"):
        build_refresh_jobs(config)


def _config(
    tmp_path: Path,
    *,
    datasets: tuple[str, ...],
    tickers: tuple[str, ...] = (),
    rss_feeds: tuple[str, ...] = (),
    filer_ciks: tuple[str, ...] = (),
    cusip_map: Path | None = None,
    sec_user_agent: str | None = None,
    activity_alerts_csv: Path | None = None,
    subscription_email_config: Path | None = None,
    dry_run: bool = False,
    market_data_provider: str = "yfinance",
    market_data_credentials_present: bool = False,
    massive_credentials_present: bool = False,
    stock_trades_limit: int = 50_000,
    stock_trades_max_pages_per_day: int | None = None,
    stock_trades_start: date | None = None,
    stock_trades_end: date | None = None,
) -> RefreshBatchConfig:
    return RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2021, 1, 31),
        datasets=datasets,
        tickers=tickers,
        rss_feeds=rss_feeds,
        filer_ciks=filer_ciks,
        cusip_map=cusip_map,
        activity_alerts_csv=activity_alerts_csv,
        subscription_email_config=subscription_email_config,
        sec_user_agent=sec_user_agent,
        dry_run=dry_run,
        market_data_provider=market_data_provider,
        market_data_credentials_present=market_data_credentials_present,
        massive_credentials_present=massive_credentials_present,
        stock_trades_start=stock_trades_start,
        stock_trades_end=stock_trades_end,
        stock_trades_limit=stock_trades_limit,
        stock_trades_max_pages_per_day=stock_trades_max_pages_per_day,
    )


def _clock() -> Callable[[], datetime]:
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    ticks = {"count": 0}

    def now() -> datetime:
        value = base + timedelta(seconds=ticks["count"])
        ticks["count"] += 1
        return value

    return now


def _fixed_clock(value: datetime) -> Callable[[], datetime]:
    return lambda: value


def _unexpected_runner(command: Sequence[str], cwd: Path) -> CommandResult:
    raise AssertionError(f"unexpected command: {command} in {cwd}")


def _write_manifest(
    tmp_path: Path,
    dataset: str,
    *,
    fetched_at: datetime | None = None,
) -> None:
    manifest_path = tmp_path / "research" / "data" / "manifests" / f"{dataset}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fetched = fetched_at or datetime(2026, 5, 8, 12, tzinfo=UTC)
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": dataset,
                "row_count": 1,
                "fetched_at": fetched.isoformat(),
                "max_timestamp_as_of": fetched.isoformat(),
                "issues": [],
            }
        ),
        encoding="utf-8",
    )


def _write_ticker_frame(
    tmp_path: Path,
    dataset: str,
    ticker: str,
    date_column: str,
    *,
    values: tuple[date, ...] = (date(2021, 1, 1),),
) -> None:
    root = tmp_path / "research" / "data" / "parquet" / dataset / f"ticker={ticker}"
    root.mkdir(parents=True, exist_ok=True)
    rows = [{"ticker": ticker, date_column: value} for value in values]
    pd.DataFrame(rows).to_parquet(root / "rows.parquet", index=False)
