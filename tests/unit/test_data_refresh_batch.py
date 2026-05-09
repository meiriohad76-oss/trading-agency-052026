from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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

    assert blocked_job.blocked_reasons == ("missing Massive market-flow credentials",)
    assert ready_job.blocked_reasons == ()
    assert "--massive-base-url" in ready_job.display_command
    assert ready_job.display_command[-2:] == ("--ticker", "AAPL")


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


def test_build_refresh_jobs_rejects_unknown_dataset(tmp_path: Path) -> None:
    config = _config(tmp_path, datasets=("not_a_dataset",))

    with pytest.raises(ValueError, match="unknown dataset"):
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
    )


def _clock() -> Callable[[], datetime]:
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    ticks = {"count": 0}

    def now() -> datetime:
        value = base + timedelta(seconds=ticks["count"])
        ticks["count"] += 1
        return value

    return now
