from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from data_refresh.types import DATASETS, RefreshBatchConfig, RefreshJob

JobBuilder = Callable[[RefreshBatchConfig], RefreshJob]


def build_refresh_jobs(config: RefreshBatchConfig) -> tuple[RefreshJob, ...]:
    _validate_config(config)
    builders: dict[str, JobBuilder] = {
        "prices_daily": _prices_job,
        "sec_company_facts": _company_facts_job,
        "sec_form4": _form4_job,
        "sec_13f": _form13f_job,
        "news_rss": _news_job,
        "options_chains": _options_job,
    }
    return tuple(builders[dataset](config) for dataset in config.datasets)


def _prices_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_yfinance_daily.py")
    command.extend(["--start", config.start.isoformat(), "--end", config.end.isoformat()])
    command.extend(["--workers", str(config.workers)])
    if config.include_etfs:
        command.append("--include-etfs")
    if config.refresh:
        command.append("--refresh")
    _extend_tickers(command, config.tickers, "--tickers")
    return _job(config, "prices_daily", command, _universe_reasons(config))


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
    reasons = () if config.rss_feeds else ("missing RSS feed specs",)
    return _job(config, "news_rss", command, reasons)


def _options_job(config: RefreshBatchConfig) -> RefreshJob:
    command = _base_command(config, "pull_yfinance_options.py")
    for ticker in config.tickers:
        command.extend(["--ticker", ticker.upper()])
    return _job(config, "options_chains", command, _universe_reasons(config))


def _base_command(config: RefreshBatchConfig, script_name: str) -> list[str]:
    return [config.python_executable, str(config.repo_root / "research" / "scripts" / script_name)]


def _job(
    config: RefreshBatchConfig,
    dataset: str,
    command: Sequence[str],
    reasons: Sequence[str],
) -> RefreshJob:
    return RefreshJob(
        dataset=dataset,
        command=tuple(command),
        display_command=_display_command(command, config.repo_root, config.python_executable),
        blocked_reasons=tuple(reasons),
    )


def _extend_tickers(command: list[str], tickers: Sequence[str], flag: str) -> None:
    if tickers:
        command.append(flag)
        command.extend(ticker.upper() for ticker in tickers)


def _universe_reasons(config: RefreshBatchConfig) -> tuple[str, ...]:
    universe_path = (
        config.repo_root
        / "research"
        / "data"
        / "parquet"
        / "universe_membership.parquet"
    )
    if config.tickers or universe_path.is_file():
        return ()
    return (f"missing universe file: {_display_path(universe_path, config.repo_root)}",)


def _sec_reasons(config: RefreshBatchConfig) -> tuple[str, ...]:
    if config.sec_user_agent is not None and config.sec_user_agent.strip() != "":
        return ()
    return ("missing SEC_USER_AGENT",)


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
