from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from data_refresh.live_config import RefreshConfigOverrides, load_refresh_config
from data_refresh.market_calendar import is_trading_day
from market_flow.storage import coverage_key, load_stock_trade_coverage_metadata

TRACKED_DATASETS = (
    "prices_daily",
    "sec_company_facts",
    "sec_form4",
    "stock_trades",
)
DEFAULT_BATCH_SIZE = 25
DEFAULT_OUTPUT_ROOT = Path("research/results/active-universe-refresh-plan")
PYTHON_COMMAND = r".\.venv\Scripts\python"
STOCK_TRADE_BACKTEST_LANE_ID = "massive_backtest_trade_tape"
MASSIVE_DAILY_BARS_LANE_ID = "massive_daily_bars"


@dataclass(frozen=True)
class ActiveUniversePlanRequest:
    repo_root: Path
    config_path: Path
    output_root: Path = DEFAULT_OUTPUT_ROOT
    as_of: date | None = None
    datasets: tuple[str, ...] | None = None
    batch_size: int = DEFAULT_BATCH_SIZE
    massive_requests_remaining: int | None = None


def build_active_universe_refresh_plan(request: ActiveUniversePlanRequest) -> dict[str, Any]:
    if request.batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    repo_root = request.repo_root
    config = load_refresh_config(request.config_path, repo_root=repo_root)
    as_of = request.as_of or config.end or date.today()
    active_tickers = _active_universe_tickers(repo_root, as_of)
    requested_datasets = _requested_datasets(request.datasets)
    stock_window = _stock_trade_window(config, as_of)
    remaining = request.massive_requests_remaining

    coverage: dict[str, Any] = {}
    batches: list[dict[str, Any]] = []
    for dataset in requested_datasets:
        covered = _covered_tickers(
            repo_root,
            dataset,
            as_of=as_of,
            stock_window=stock_window,
        )
        missing = [ticker for ticker in active_tickers if ticker not in covered]
        planned, deferred, remaining = _quota_split(
            dataset,
            missing,
            remaining,
            config=config,
            stock_window=stock_window,
        )
        coverage[dataset] = {
            "covered_count": len(covered.intersection(active_tickers)),
            "missing_count": len(missing),
            "planned_count": len(planned),
            "deferred_count": len(deferred),
            "estimated_massive_requests": _request_estimate(
                dataset,
                planned,
                config=config,
                stock_window=stock_window,
            ),
            "deferred_tickers": deferred,
        }
        batches.extend(
            _dataset_batches(
                dataset,
                planned,
                request.batch_size,
                config=config,
                config_path=request.config_path,
                repo_root=repo_root,
                stock_window=stock_window,
                as_of=as_of,
            )
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "config_path": _display_path(request.config_path, repo_root),
        "as_of": as_of.isoformat(),
        "active_universe_count": len(active_tickers),
        "active_universe_sample": active_tickers[:10],
        "massive_requests_remaining_before_plan": request.massive_requests_remaining,
        "massive_requests_remaining_after_plan": remaining,
        "stock_trades_window": {
            "start": stock_window[0].isoformat(),
            "end": stock_window[1].isoformat(),
            "trading_days": _trading_days(*stock_window),
        },
        "coverage": coverage,
        "batches": batches,
    }


def write_active_universe_refresh_plan(plan: dict[str, Any], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "active-universe-refresh-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "active-universe-refresh-plan.md").write_text(
        _plan_markdown(plan),
        encoding="utf-8",
    )


def _active_universe_tickers(repo_root: Path, as_of: date) -> list[str]:
    path = repo_root / "research" / "data" / "parquet" / "universe_membership.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"missing active universe file: {_display_path(path, repo_root)}")
    frame = pl.read_parquet(path)
    frame = frame.with_columns(
        pl.col("start_date").cast(pl.Date, strict=False).alias("__start"),
        pl.col("end_date").cast(pl.Date, strict=False).alias("__end"),
    )
    active = frame.filter(
        pl.col("__start") <= as_of,
        pl.col("__end").is_null() | (pl.col("__end") > as_of),
    )
    return sorted({str(ticker).upper() for ticker in active.get_column("ticker").to_list()})


def _requested_datasets(datasets: tuple[str, ...] | None) -> tuple[str, ...]:
    requested = tuple(datasets or TRACKED_DATASETS)
    unknown = sorted(set(requested).difference(TRACKED_DATASETS))
    if unknown:
        raise ValueError(f"unknown active-universe dataset(s): {', '.join(unknown)}")
    return requested


def _covered_tickers(
    repo_root: Path,
    dataset: str,
    *,
    as_of: date,
    stock_window: tuple[date, date],
) -> set[str]:
    manifest = _manifest_payload(repo_root, dataset)
    manifest_tickers = _manifest_tickers(manifest)
    if manifest_tickers:
        if not _manifest_current_for_dataset(
            dataset,
            manifest,
            as_of=as_of,
            stock_window=stock_window,
        ):
            return set()
        if dataset == "stock_trades":
            return _stock_trade_complete_tickers(repo_root, manifest_tickers, stock_window)
        return manifest_tickers
    dataset_path = repo_root / "research" / "data" / "parquet" / dataset
    if not dataset_path.exists():
        return set()
    files = [dataset_path] if dataset_path.is_file() else sorted(dataset_path.rglob("*.parquet"))
    tickers: set[str] = set()
    for path in files:
        try:
            frame = pl.read_parquet(path, columns=["ticker"])
        except Exception:
            continue
        tickers.update(str(ticker).upper() for ticker in frame.get_column("ticker").to_list())
    return tickers


def _manifest_payload(repo_root: Path, dataset: str) -> dict[str, Any]:
    path = repo_root / "research" / "data" / "manifests" / f"{dataset}.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _stock_trade_complete_tickers(
    repo_root: Path,
    tickers: set[str],
    stock_window: tuple[date, date],
) -> set[str]:
    root = repo_root / "research" / "data" / "parquet" / "stock_trades"
    coverage = load_stock_trade_coverage_metadata(root)
    if not coverage:
        return set()
    complete: set[str] = set()
    trading_days = _trading_dates(*stock_window)
    for ticker in tickers:
        if all(
            str(coverage.get(coverage_key(ticker, day), {}).get("coverage_status")) == "complete"
            for day in trading_days
        ):
            complete.add(ticker)
    return complete


def _manifest_tickers(payload: dict[str, Any]) -> set[str]:
    value = payload.get("tickers") if isinstance(payload, dict) else None
    if not isinstance(value, list):
        return set()
    return {str(ticker).upper() for ticker in value if str(ticker).strip()}


def _manifest_current_for_dataset(
    dataset: str,
    manifest: Mapping[str, Any],
    *,
    as_of: date,
    stock_window: tuple[date, date],
) -> bool:
    if dataset == "prices_daily":
        observed = _manifest_as_of_date(manifest)
        return observed is not None and observed >= as_of
    if dataset == "stock_trades":
        date_range = manifest.get("date_range")
        if not isinstance(date_range, Mapping):
            return False
        start = _parse_date(date_range.get("start"))
        end = _parse_date(date_range.get("end"))
        return (
            start is not None
            and end is not None
            and start <= stock_window[0]
            and end >= stock_window[1]
        )
    return True


def _manifest_as_of_date(manifest: Mapping[str, Any]) -> date | None:
    return _parse_date(manifest.get("max_timestamp_as_of") or manifest.get("fetched_at"))


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.removesuffix("Z")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _quota_split(
    dataset: str,
    tickers: list[str],
    remaining: int | None,
    *,
    config: RefreshConfigOverrides,
    stock_window: tuple[date, date],
) -> tuple[list[str], list[str], int | None]:
    if not _uses_massive(dataset, config):
        return tickers, [], remaining
    if remaining is None:
        return tickers, [], None
    if dataset == "prices_daily":
        estimate = _request_estimate(
            dataset,
            tickers,
            config=config,
            stock_window=stock_window,
        )
        if estimate <= remaining:
            return tickers, [], remaining - estimate
        return [], tickers, remaining
    planned: list[str] = []
    deferred: list[str] = []
    for ticker in tickers:
        estimate = _request_estimate(dataset, [ticker], config=config, stock_window=stock_window)
        if estimate <= remaining:
            planned.append(ticker)
            remaining -= estimate
        else:
            deferred.append(ticker)
    return planned, deferred, remaining


def _uses_massive(dataset: str, config: RefreshConfigOverrides) -> bool:
    if dataset == "stock_trades":
        return True
    return dataset == "prices_daily" and (config.market_data_provider or "").lower() == "massive"


def _request_estimate(
    dataset: str,
    tickers: list[str],
    *,
    config: RefreshConfigOverrides,
    stock_window: tuple[date, date],
) -> int:
    if not tickers or not _uses_massive(dataset, config):
        return 0
    if dataset == "prices_daily":
        return 1
    max_pages = config.stock_trades_max_pages_per_day or 1
    return len(tickers) * _trading_days(*stock_window) * max_pages


def _dataset_batches(
    dataset: str,
    tickers: list[str],
    batch_size: int,
    *,
    config: RefreshConfigOverrides,
    config_path: Path,
    repo_root: Path,
    stock_window: tuple[date, date],
    as_of: date,
) -> list[dict[str, Any]]:
    if dataset == "stock_trades":
        return _stock_trade_lane_batches(
            tickers,
            batch_size,
            stock_window=stock_window,
        )
    if dataset == "prices_daily" and (config.market_data_provider or "").lower() == "massive":
        return _massive_daily_bar_lane_batches(
            tickers,
            as_of=as_of,
        )
    batches: list[dict[str, Any]] = []
    for index, batch in enumerate(_chunks(tickers, batch_size), start=1):
        command = [
            PYTHON_COMMAND,
            "research\\scripts\\run_data_refresh_batch.py",
            "--config",
            _display_path(config_path, repo_root),
            "--dataset",
            dataset,
            "--no-market-aware",
        ]
        if dataset == "stock_trades":
            command.extend(
                [
                    "--stock-trades-start",
                    stock_window[0].isoformat(),
                    "--stock-trades-end",
                    stock_window[1].isoformat(),
                ]
            )
        for ticker in batch:
            command.extend(["--ticker", ticker])
        command.extend(
            [
                "--output-root",
                f"research\\results\\active-universe-refresh\\{dataset}-batch-{index:03d}",
            ]
        )
        batches.append(
            {
                "dataset": dataset,
                "batch_id": index,
                "ticker_count": len(batch),
                "tickers": batch,
                "command": command,
                "command_text": " ".join(command),
            }
        )
    return batches


def _massive_daily_bar_lane_batches(
    tickers: list[str],
    *,
    as_of: date,
) -> list[dict[str, Any]]:
    if not tickers:
        return []
    command = [
        PYTHON_COMMAND,
        "research\\scripts\\pull_massive_grouped_daily.py",
        "--date",
        as_of.isoformat(),
        "--lane-id",
        MASSIVE_DAILY_BARS_LANE_ID,
        "--lane-manifest-path",
        "research\\data\\manifests\\massive_lanes\\massive_daily_bars.json",
    ]
    command.append("--tickers")
    command.extend(tickers)
    return [
        {
            "dataset": "prices_daily",
            "lane_id": MASSIVE_DAILY_BARS_LANE_ID,
            "batch_id": 1,
            "ticker_count": len(tickers),
            "tickers": tickers,
            "command": command,
            "command_text": " ".join(command),
            "detail": (
                "Massive daily bars are lane-owned; this command updates the "
                f"{MASSIVE_DAILY_BARS_LANE_ID} manifest instead of running a "
                "generic data-refresh batch."
            ),
        }
    ]


def _stock_trade_lane_batches(
    tickers: list[str],
    batch_size: int,
    *,
    stock_window: tuple[date, date],
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    trading_day_count = max(_trading_days(*stock_window), 1)
    for index, batch in enumerate(_chunks(tickers, batch_size), start=1):
        command = [
            PYTHON_COMMAND,
            "research\\scripts\\backfill_massive_stock_trades.py",
            "--start",
            stock_window[0].isoformat(),
            "--end",
            stock_window[1].isoformat(),
            "--batch-size",
            "1",
            "--recent-first",
            "--max-batches",
            str(max(len(batch) * trading_day_count, 1)),
            "--lane-id",
            STOCK_TRADE_BACKTEST_LANE_ID,
            "--lane-manifest-path",
            "research\\data\\manifests\\massive_lanes\\massive_backtest_trade_tape.json",
        ]
        for ticker in batch:
            command.extend(["--ticker", ticker])
        command.extend(
            [
                "--output-root",
                f"research\\results\\active-universe-refresh\\stock-trades-lane-batch-{index:03d}",
            ]
        )
        batches.append(
            {
                "dataset": "stock_trades",
                "lane_id": STOCK_TRADE_BACKTEST_LANE_ID,
                "batch_id": index,
                "ticker_count": len(batch),
                "tickers": batch,
                "command": command,
                "command_text": " ".join(command),
                "detail": (
                    "Stock-trade repair is lane-owned; this command updates the "
                    f"{STOCK_TRADE_BACKTEST_LANE_ID} manifest instead of running "
                    "a generic data-refresh batch."
                ),
            }
        )
    return batches


def _stock_trade_window(config: RefreshConfigOverrides, as_of: date) -> tuple[date, date]:
    start = config.stock_trades_start or config.stock_trades_end or as_of
    end = config.stock_trades_end or config.stock_trades_start or as_of
    if end < as_of:
        return as_of, as_of
    if end < start:
        raise ValueError("stock_trades_end must be on or after stock_trades_start")
    return start, end


def _inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1


def _trading_days(start: date, end: date) -> int:
    return len(_trading_dates(start, end))


def _trading_dates(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def _chunks(tickers: list[str], size: int) -> list[list[str]]:
    return [tickers[index : index + size] for index in range(0, len(tickers), size)]


def _display_path(path: Path, repo_root: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


def _plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Active Universe Refresh Plan",
        "",
        f"As-of: `{plan['as_of']}`",
        f"Active universe tickers: `{plan['active_universe_count']}`",
        (
            "Massive requests remaining after planned batches: "
            f"`{_remaining_label(plan['massive_requests_remaining_after_plan'])}`"
        ),
        "",
        "| Dataset | Covered | Missing | Planned | Deferred | Massive requests |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    coverage = plan["coverage"]
    for dataset in TRACKED_DATASETS:
        if dataset not in coverage:
            continue
        item = coverage[dataset]
        lines.append(
            "| "
            f"{dataset} | {item['covered_count']} | {item['missing_count']} | "
            f"{item['planned_count']} | {item['deferred_count']} | "
            f"{item['estimated_massive_requests']} |"
        )
    lines.extend(["", "## Runnable Batches", ""])
    if not plan["batches"]:
        lines.append("No batches are needed for the selected datasets.")
    for batch in plan["batches"]:
        lines.extend(
            [
                f"### {batch['dataset']} batch {batch['batch_id']:03d}",
                "",
                f"Tickers: `{batch['ticker_count']}`",
                "",
                f"`{batch['command_text']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _remaining_label(value: object) -> str:
    return "unlimited" if value is None else str(value)
