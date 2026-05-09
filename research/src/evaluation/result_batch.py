from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from evaluation.h1_ic import H1ICConfig, evaluate_signal_ic
from evaluation.result_batch_status import result_to_json, result_to_markdown
from evaluation.signal_registry import SIGNALS
from evaluation.verdicts import (
    summarize_signal_verdicts,
    synthesize_horizon_verdicts,
    verdicts_to_markdown,
)
from pit.exceptions import DataNotAvailableAt
from pit.loader import PITLoader
from pit.manifest import DatasetName, ManifestRegistry

SIGNAL_DATASETS: Mapping[str, tuple[DatasetName, ...]] = {
    "abnormal_volume": (DatasetName.PRICES_DAILY,),
    "activity_alerts": (DatasetName.UNUSUAL_ACTIVITY_ALERTS,),
    "block_trade_pressure": (DatasetName.STOCK_TRADES,),
    "buy_sell_pressure": (DatasetName.STOCK_TRADES,),
    "fundamentals": (DatasetName.SEC_COMPANY_FACTS,),
    "insider": (DatasetName.SEC_FORM4,),
    "institutional": (DatasetName.SEC_13F,),
    "news": (DatasetName.NEWS_RSS,),
    "options_anomaly": (DatasetName.OPTIONS_CHAINS,),
    "options_flow": (DatasetName.OPTIONS_CHAINS,),
    "sector_momentum": (DatasetName.PRICES_DAILY,),
    "subscription_thesis": (DatasetName.SUBSCRIPTION_EMAILS,),
}


@dataclass(frozen=True)
class ResearchBatchConfig:
    start: date
    end: date
    signals: tuple[str, ...]
    horizons: tuple[int, ...] = (5, 20)
    step_size_days: int = 21
    static_universe: frozenset[str] | None = None


@dataclass(frozen=True)
class DatasetCheck:
    dataset: str
    available: bool
    reason: str


@dataclass(frozen=True)
class ResearchBatchResult:
    config: ResearchBatchConfig
    dataset_checks: tuple[DatasetCheck, ...]
    h1_ran: bool
    written_paths: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return any(not check.available for check in self.dataset_checks)


def required_datasets(
    signals: Sequence[str],
    *,
    uses_static_universe: bool = False,
) -> dict[DatasetName, str]:
    """Return the manifest requirements needed for the requested research batch."""
    _validate_signals(signals)
    requirements = {
        DatasetName.PRICES_DAILY: "forward returns, H4 profile, and H5 sweep",
    }
    if not uses_static_universe:
        requirements[DatasetName.UNIVERSE_MEMBERSHIP] = "dynamic H1 evaluation universe"
    for signal in signals:
        for dataset in SIGNAL_DATASETS[signal]:
            requirements.setdefault(dataset, f"{signal} signal inputs")
    return dict(sorted(requirements.items(), key=lambda item: item[0].value))


def inspect_datasets(
    requirements: Mapping[DatasetName, str],
    *,
    manifest_root: Path,
    parquet_root: Path,
    as_of: date,
) -> tuple[DatasetCheck, ...]:
    """Inspect required manifests without reading research data directly."""
    registry = ManifestRegistry(
        manifest_root,
        parquet_root,
        clock=lambda: datetime.now(UTC),
    )
    checks: list[DatasetCheck] = []
    for dataset, reason in sorted(requirements.items(), key=lambda item: item[0].value):
        try:
            manifest = registry.require(dataset, as_of=as_of)
        except DataNotAvailableAt as exc:
            checks.append(
                DatasetCheck(
                    dataset.value,
                    False,
                    _portable_reason(exc.reason, manifest_root, parquet_root),
                )
            )
        else:
            checks.append(
                DatasetCheck(
                    dataset.value,
                    True,
                    f"{reason}; {manifest.row_count} row(s)",
                )
            )
    return tuple(checks)


def run_research_batch(
    config: ResearchBatchConfig,
    *,
    output_root: Path,
    manifest_root: Path,
    parquet_root: Path,
) -> ResearchBatchResult:
    """Run available H1 research artifacts, or write readiness status if blocked."""
    requirements = required_datasets(
        config.signals,
        uses_static_universe=config.static_universe is not None,
    )
    dataset_checks = inspect_datasets(
        requirements,
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        as_of=config.end,
    )
    written_paths: list[str] = []
    result = ResearchBatchResult(config, dataset_checks, False, ())
    if not result.blocked:
        written_paths.extend(
            _run_h1(
                config,
                output_root=output_root,
                manifest_root=manifest_root,
                parquet_root=parquet_root,
            )
        )
        result = ResearchBatchResult(config, dataset_checks, True, tuple(written_paths))
    final_result = ResearchBatchResult(
        config,
        dataset_checks,
        result.h1_ran,
        (*written_paths, "batch-status.json", "batch-status.md"),
    )
    _write_status_files(final_result, output_root)
    return final_result


def _run_h1(
    config: ResearchBatchConfig,
    *,
    output_root: Path,
    manifest_root: Path,
    parquet_root: Path,
) -> list[str]:
    loader = PITLoader(parquet_root=parquet_root, manifest_root=manifest_root)
    h1_config = H1ICConfig(
        start=config.start,
        end=config.end,
        horizons=config.horizons,
        step_size_days=config.step_size_days,
        static_universe=None if config.static_universe is None else set(config.static_universe),
    )
    frames = [
        evaluate_signal_ic(
            signal_name=signal,
            signal_fn=SIGNALS[signal],
            loader=loader,
            config=h1_config,
        ).results
        for signal in config.signals
    ]
    ic_results = pd.concat(frames, ignore_index=True)
    horizon_verdicts = synthesize_horizon_verdicts(ic_results)
    signal_verdicts = summarize_signal_verdicts(horizon_verdicts)
    _write_frame(output_root / "h1-ic.csv", horizon_verdicts)
    _write_frame(output_root / "h1-verdicts.csv", signal_verdicts)
    (output_root / "h1-verdicts.md").write_text(
        verdicts_to_markdown(signal_verdicts),
        encoding="utf-8",
    )
    return ["h1-ic.csv", "h1-verdicts.csv", "h1-verdicts.md"]


def _write_status_files(result: ResearchBatchResult, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "batch-status.json").write_text(result_to_json(result), encoding="utf-8")
    (output_root / "batch-status.md").write_text(result_to_markdown(result), encoding="utf-8")


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _portable_reason(reason: str, manifest_root: Path, parquet_root: Path) -> str:
    output = reason
    for root in (manifest_root, parquet_root):
        output = output.replace(str(root), _display_path(root))
        output = output.replace(root.as_posix(), _display_path(root))
    return output.replace("\\", "/")


def _display_path(path: Path) -> str:
    parts = path.parts
    if "research" not in parts:
        return path.as_posix()
    return "/".join(parts[parts.index("research"):])


def _validate_signals(signals: Iterable[str]) -> None:
    missing = sorted(set(signals).difference(SIGNALS))
    if missing:
        raise ValueError(f"unknown signal(s): {missing}")
