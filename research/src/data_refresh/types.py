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
    "options_chains",
)
JobStatus = Literal["planned", "passed", "failed", "blocked"]


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
    sec_user_agent: str | None = None
    python_executable: str = "python"
    workers: int = 1
    include_etfs: bool = True
    refresh: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class RefreshJob:
    dataset: str
    command: tuple[str, ...]
    display_command: tuple[str, ...]
    blocked_reasons: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class RefreshBatchResult:
    config: RefreshBatchConfig
    jobs: tuple[RefreshJobResult, ...]
    written_paths: tuple[str, ...]

    @property
    def failed(self) -> bool:
        return any(job.status == "failed" for job in self.jobs)

    @property
    def blocked(self) -> bool:
        return any(job.status == "blocked" for job in self.jobs)


Runner = Callable[[Sequence[str], Path], CommandResult]
