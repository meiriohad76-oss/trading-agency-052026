from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from data_refresh.extraction_plan import ExtractionDecision, extraction_decision_for_dataset
from data_refresh.types import DATASETS, RefreshBatchConfig, RefreshJob

JobBuilder = Callable[[RefreshBatchConfig], RefreshJob]


def build_refresh_jobs(
    config: RefreshBatchConfig,
    *,
    now: datetime | None = None,
) -> tuple[RefreshJob, ...]:
    _validate_config(config)
    builders: dict[str, JobBuilder] = {
        "prices_daily": _prices_job,
        "sec_company_facts": _company_facts_job,
        "sec_form4": _form4_job,
        "sec_13f": _form13f_job,
        "news_rss": _news_job,
        "subscription_emails": _subscription_email_job,
        "stock_trades": _stock_trades_job,
        "options_chains": _options_job,
        "unusual_activity_alerts": _activity_alerts_job,
    }
    jobs: list[RefreshJob] = []
    for dataset in config.datasets:
        decision = extraction_decision_for_dataset(config, dataset, now=now)
        job = builders[dataset](_effective_config(config, decision))
        if decision.action == "skip":
            job = replace(job, blocked_reasons=(), skip_reason=decision.reason)
        jobs.append(replace(job, extraction_action=decision.action))
    return tuple(jobs)


def _effective_config(
    config: RefreshBatchConfig,
    decision: ExtractionDecision,
) -> RefreshBatchConfig:
    tickers = decision.tickers or config.tickers
    if decision.dataset == "stock_trades":
        return replace(
            config,
            tickers=tickers,
            refresh=config.refresh or decision.refresh,
            stock_trades_start=decision.start or config.stock_trades_start,
            stock_trades_end=decision.end or config.stock_trades_end,
        )
    return replace(
        config,
        tickers=tickers,
        refresh=config.refresh or decision.refresh,
        start=decision.start or config.start,
        end=decision.end or config.end,
    )


def _prices_job(config: RefreshBatchConfig) -> RefreshJob:
    if config.market_data_provider == "massive":
        lane_reasons = ["prices_daily is lane-owned by massive_daily_bars when provider=massive"]
        if not config.massive_credentials_present:
            lane_reasons.append("missing Massive market data credentials")
        lane_reasons.append(
            "use the scheduler work queue / Massive Lane Orchestrator instead of run_data_refresh_batch"
        )
        return _job(config, "prices_daily", (), tuple(lane_reasons))
    command = _base_command(config, "pull_yfinance_daily.py")
    command.extend(["--provider", config.market_data_provider])
    if config.market_data_provider == "alpaca":
        command.extend(
            [
                "--alpaca-feed",
                config.market_data_feed,
                "--alpaca-adjustment",
                config.market_data_adjustment,
                "--alpaca-data-base-url",
                config.market_data_base_url,
            ]
        )
    if config.market_data_provider == "massive":
        command.extend(["--massive-base-url", config.massive_base_url])
    command.extend(["--start", config.start.isoformat(), "--end", config.end.isoformat()])
    command.extend(["--workers", str(config.workers)])
    if config.include_etfs:
        command.append("--include-etfs")
    if config.refresh:
        command.append("--refresh")
    _extend_tickers(command, config.tickers, "--tickers")
    reasons = _universe_reasons(config) + _market_data_reasons(config)
    return _job(config, "prices_daily", command, reasons)


def _company_facts_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_sec_company_facts.py")
    if config.refresh:
        command.append("--refresh")
    _extend_tickers(command, config.tickers, "--tickers")
    reasons = _sec_reasons(config) + _universe_reasons(config)
    return _job(config, "sec_company_facts", command, reasons)


def _form4_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_sec_form4.py")
    command.extend(["--start", config.start.isoformat(), "--end", config.end.isoformat()])
    _extend_tickers(command, config.tickers, "--tickers")
    reasons = _sec_reasons(config) + _universe_reasons(config)
    return _job(config, "sec_form4", command, reasons)


def _form13f_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_sec_13f.py")
    command.extend(["--start", config.start.isoformat(), "--end", config.end.isoformat()])
    if config.filer_ciks:
        command.append("--filer-ciks")
        command.extend(config.filer_ciks)
    if config.cusip_map is not None:
        command.extend(["--cusip-map", str(config.cusip_map)])
    reasons = list(_sec_reasons(config))
    if not config.filer_ciks:
        reasons.append("missing 13F filer CIKs")
    if config.cusip_map is None:
        reasons.append("missing 13F CUSIP map")
    elif not config.cusip_map.is_file():
        display_path = _display_path(config.cusip_map, config.repo_root)
        reasons.append(f"missing CUSIP map file: {display_path}")
    return _job(config, "sec_13f", command, tuple(reasons))


def _news_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_news_rss.py")
    for feed in config.rss_feeds:
        command.extend(["--feed", feed])
    if config.sec_user_agent is not None and config.sec_user_agent.strip() != "":
        command.extend(["--sec-user-agent", config.sec_user_agent])
    reasons: list[str] = []
    if not config.rss_feeds:
        reasons.append("missing RSS feed specs")
    elif config.news_resolve_generic_tickers:
        command.append("--resolve-generic-tickers")
        if config.news_ticker_aliases_path is None:
            reasons.append("missing news ticker aliases config")
        else:
            command.extend(["--ticker-aliases", str(config.news_ticker_aliases_path)])
            if not config.news_ticker_aliases_path.is_file():
                display_path = _display_path(config.news_ticker_aliases_path, config.repo_root)
                reasons.append(f"missing news ticker aliases config: {display_path}")
        _extend_news_resolution_tickers(command, config)
        if not config.tickers and not _universe_path(config).is_file():
            reasons.append(
                f"missing universe file: {_display_path(_universe_path(config), config.repo_root)}"
            )
        command.extend(
            [
                "--news-resolution-min-confidence",
                str(config.news_resolution_min_confidence),
            ]
        )
        command.append(
            "--keep-unresolved-generic-news"
            if config.news_keep_unresolved_generic
            else "--no-keep-unresolved-generic-news"
        )
    return _job(config, "news_rss", command, reasons)


def _subscription_email_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "import_subscription_emails.py")
    reasons = []
    requires_console = False
    if config.subscription_email_config is None:
        reasons.append("missing subscription email config")
    else:
        command.extend(["--config", str(config.subscription_email_config)])
        if not config.subscription_email_config.is_file():
            display_path = _display_path(config.subscription_email_config, config.repo_root)
            reasons.append(f"missing subscription email config: {display_path}")
        else:
            reasons.extend(_subscription_email_config_reasons(config))
            if _subscription_email_requires_console(config):
                requires_console = True
    return _job(config, "subscription_emails", command, reasons, requires_console=requires_console)


def _subscription_email_config_reasons(config: RefreshBatchConfig) -> list[str]:
    if config.subscription_email_config is None:
        return []
    payload = _json_object(config.subscription_email_config)
    mode = str(payload.get("mode") or "local_eml")
    if mode == "local_eml":
        return _missing_local_email_input(payload, config.repo_root)
    if mode in {"gmail", "outlook", "imap"}:
        missing = _missing_mailbox_env(payload)
        if not missing:
            return []
        return [f"missing subscription mailbox credentials: {', '.join(missing)}"]
    return [f"unsupported subscription email mode: {mode}"]


def _subscription_email_requires_console(config: RefreshBatchConfig) -> bool:
    if config.subscription_email_config is None:
        return False
    payload = _json_object(config.subscription_email_config)
    return payload.get("article_login_preflight_required") is True


def _missing_mailbox_env(payload: dict[str, Any]) -> list[str]:
    names = (
        str(payload.get("mailbox_username_env") or "SUBSCRIPTION_EMAIL_USERNAME"),
        str(payload.get("mailbox_password_env") or "SUBSCRIPTION_EMAIL_PASSWORD"),
    )
    return [name for name in names if os.environ.get(name, "").strip() == ""]


def _missing_local_email_input(payload: dict[str, Any], repo_root: Path) -> list[str]:
    input_path = _payload_path(payload, "input_path", repo_root)
    if input_path is None:
        return ["missing subscription email input_path"]
    if input_path.exists():
        return []
    return [f"missing subscription email input: {_display_path(input_path, repo_root)}"]


def _payload_path(payload: dict[str, Any], key: str, repo_root: Path) -> Path | None:
    value = payload.get(key)
    if not isinstance(value, str) or value.strip() == "":
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _stock_trades_job(config: RefreshBatchConfig) -> RefreshJob:
    del config
    return RefreshJob(
        dataset="stock_trades",
        command=(),
        display_command=(),
        blocked_reasons=(
            "stock_trades is lane-owned by massive_live_trade_slices, "
            "massive_premarket_trade_slices, and massive_backtest_trade_tape",
            "use the scheduler work queue / Massive Lane Orchestrator instead of run_data_refresh_batch",
        ),
    )


def _options_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_yfinance_options.py")
    for ticker in config.tickers:
        command.extend(["--ticker", ticker.upper()])
    return _job(config, "options_chains", command, _universe_reasons(config))


def _activity_alerts_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "import_activity_alerts.py")
    reasons = []
    if config.activity_alerts_csv is None:
        reasons.append("missing unusual activity alerts CSV")
    else:
        command.extend(["--input", str(config.activity_alerts_csv)])
        if not config.activity_alerts_csv.is_file():
            display_path = _display_path(config.activity_alerts_csv, config.repo_root)
            reasons.append(f"missing unusual activity alerts CSV: {display_path}")
    return _job(config, "unusual_activity_alerts", command, reasons)


def _sec_filing_job(config: RefreshBatchConfig) -> RefreshJob:
    """Build a job to run the SEC filing monitor."""
    command = _base_command(config, "run_sec_filing_monitor.py")
    reasons = list(_sec_reasons(config))
    return _job(config, "sec_filing_analysis", command, reasons)


def _base_command(config: RefreshBatchConfig, script_name: str) -> list[str]:
    return [config.python_executable, str(config.repo_root / "research" / "scripts" / script_name)]


def _job(
    config: RefreshBatchConfig,
    dataset: str,
    command: Sequence[str],
    reasons: Sequence[str],
    *,
    requires_console: bool = False,
) -> RefreshJob:
    return RefreshJob(
        dataset=dataset,
        command=tuple(command),
        display_command=_display_command(command, config.repo_root, config.python_executable),
        blocked_reasons=tuple(reasons),
        requires_console=requires_console,
    )


def _extend_tickers(command: list[str], tickers: Sequence[str], flag: str) -> None:
    if tickers:
        command.append(flag)
        command.extend(ticker.upper() for ticker in tickers)


def _extend_news_resolution_tickers(
    command: list[str],
    config: RefreshBatchConfig,
) -> None:
    if config.tickers:
        for ticker in config.tickers:
            command.extend(["--ticker", ticker.upper()])
        return
    universe_path = _universe_path(config)
    command.extend(["--universe-path", str(universe_path)])


def _universe_reasons(config: RefreshBatchConfig) -> tuple[str, ...]:
    universe_path = _universe_path(config)
    if config.tickers or universe_path.is_file():
        return ()
    return (f"missing universe file: {_display_path(universe_path, config.repo_root)}",)


def _universe_path(config: RefreshBatchConfig) -> Path:
    return (
        config.repo_root
        / "research"
        / "data"
        / "parquet"
        / "universe_membership.parquet"
    )


def _sec_reasons(config: RefreshBatchConfig) -> tuple[str, ...]:
    if config.sec_user_agent is not None and config.sec_user_agent.strip() != "":
        return ()
    return ("missing SEC_USER_AGENT",)


def _market_data_reasons(config: RefreshBatchConfig) -> tuple[str, ...]:
    if config.market_data_provider == "alpaca":
        if config.market_data_credentials_present:
            return ()
        return ("missing Alpaca market data credentials",)
    if config.market_data_provider == "massive":
        if config.massive_credentials_present:
            return ()
        return ("missing Massive market data credentials",)
    if config.market_data_provider == "yfinance":
        return ()
    return (f"unknown market data provider: {config.market_data_provider}",)


def _display_command(
    command: Sequence[str],
    repo_root: Path,
    python_executable: str,
) -> tuple[str, ...]:
    display: list[str] = []
    for item in command:
        path = Path(item)
        if item == python_executable:
            display.append("$PYTHON")
        elif path.is_absolute():
            display.append(_display_path(path, repo_root))
        else:
            display.append(item)
    return tuple(display)


def _display_path(path: Path, repo_root: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


def _validate_config(config: RefreshBatchConfig) -> None:
    unknown = sorted(set(config.datasets).difference(DATASETS))
    if unknown:
        raise ValueError(f"unknown dataset(s): {unknown}")
    if config.end < config.start:
        raise ValueError("end must be on or after start")
    if config.workers < 1:
        raise ValueError("workers must be >= 1")
    if config.market_data_provider not in {"yfinance", "alpaca", "massive"}:
        raise ValueError(f"unknown market data provider: {config.market_data_provider}")
    if config.extraction_mode not in {"auto", "baseline", "incremental", "force"}:
        raise ValueError(f"unknown extraction mode: {config.extraction_mode}")
    for label, value in (
        ("market_data_feed", config.market_data_feed),
        ("market_data_adjustment", config.market_data_adjustment),
        ("market_data_base_url", config.market_data_base_url),
        ("massive_base_url", config.massive_base_url),
    ):
        if value.strip() == "":
            raise ValueError(f"{label} must not be blank")
    if config.stock_trades_limit < 1:
        raise ValueError("stock_trades_limit must be >= 1")
    if (
        config.stock_trades_max_pages_per_day is not None
        and config.stock_trades_max_pages_per_day < 1
    ):
        raise ValueError("stock_trades_max_pages_per_day must be >= 1")
    numeric_settings: tuple[tuple[str, int], ...] = (
        ("sec_company_facts_max_age_days", config.sec_company_facts_max_age_days),
        ("sec_form4_max_age_days", config.sec_form4_max_age_days),
        ("sec_13f_max_age_days", config.sec_13f_max_age_days),
        ("news_rss_max_age_minutes", config.news_rss_max_age_minutes),
        ("subscription_email_max_age_minutes", config.subscription_email_max_age_minutes),
    )
    for numeric_label, numeric_value in numeric_settings:
        if numeric_value < 1:
            raise ValueError(f"{numeric_label} must be >= 1")
    if not (0.0 <= config.news_resolution_min_confidence <= 1.0):
        raise ValueError("news_resolution_min_confidence must be between 0.0 and 1.0")
