from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

DATASETS = (
    "prices_daily",
    "sec_company_facts",
    "sec_form4",
    "sec_13f",
    "news_rss",
    "subscription_emails",
    "stock_trades",
    "options_chains",
    "unusual_activity_alerts",
)
ExtractionMode = Literal["auto", "baseline", "incremental", "force"]
ExtractionAction = Literal["baseline", "incremental", "skip", "force"]
JobStatus = Literal["pending", "running", "planned", "passed", "failed", "blocked", "skipped"]
StockTradesOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class RefreshBatchConfig:
    repo_root: Path
    output_root: Path
    start: date
    end: date
    datasets: tuple[str, ...] = DATASETS
    tickers: tuple[str, ...] = ()
    rss_feeds: tuple[str, ...] = ()
    filer_ciks: tuple[str, ...] = ()
    cusip_map: Path | None = None
    activity_alerts_csv: Path | None = None
    subscription_email_config: Path | None = None
    sec_user_agent: str | None = None
    python_executable: str = "python"
    workers: int = 1
    include_etfs: bool = True
    refresh: bool = False
    dry_run: bool = False
    market_data_provider: str = "yfinance"
    market_data_feed: str = "iex"
    market_data_adjustment: str = "all"
    market_data_base_url: str = "https://data.alpaca.markets"
    market_data_credentials_present: bool = False
    massive_base_url: str = "https://api.polygon.io"
    massive_credentials_present: bool = False
    stock_trades_start: date | None = None
    stock_trades_end: date | None = None
    stock_trades_limit: int = 50_000
    stock_trades_max_pages_per_day: int | None = None
    stock_trades_order: StockTradesOrder = "asc"
    extraction_mode: ExtractionMode = "auto"
    sec_company_facts_max_age_days: int = 7
    sec_form4_max_age_days: int = 1
    sec_13f_max_age_days: int = 45
    news_rss_max_age_minutes: int = 30
    subscription_email_max_age_minutes: int = 10


@dataclass(frozen=True)
class RefreshJob:
    dataset: str
    command: tuple[str, ...]
    display_command: tuple[str, ...]
    blocked_reasons: tuple[str, ...] = ()
    skip_reason: str | None = None
    extraction_action: ExtractionAction | None = None
    requires_console: bool = False


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class RefreshJobResult:
    dataset: str
    status: JobStatus
    reason: str
    command: tuple[str, ...]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    extraction_action: ExtractionAction | None = None


@dataclass(frozen=True)
class RefreshBatchResult:
    config: RefreshBatchConfig
    jobs: tuple[RefreshJobResult, ...]
    written_paths: tuple[str, ...]
    started_at: str | None = None
    updated_at: str | None = None

    @property
    def failed(self) -> bool:
        return any(job.status == "failed" for job in self.jobs)

    @property
    def blocked(self) -> bool:
        return any(job.status == "blocked" for job in self.jobs)

    @property
    def in_progress(self) -> bool:
        return any(job.status in {"pending", "running"} for job in self.jobs)


Runner = Callable[[Sequence[str], Path], CommandResult]
