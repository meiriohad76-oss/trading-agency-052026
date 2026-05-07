from __future__ import annotations

import json
from datetime import date

import polars as pl
import pytest
from evaluation.result_batch import (
    ResearchBatchConfig,
    inspect_datasets,
    required_datasets,
    result_to_markdown,
    run_research_batch,
)
from pit.manifest import DatasetName
from pit_fixtures import TODAY, write_manifest


def test_required_datasets_include_prices_and_signal_inputs() -> None:
    requirements = required_datasets(["fundamentals", "insider", "sector_momentum"])

    assert set(requirements) == {
        DatasetName.PRICES_DAILY,
        DatasetName.SEC_COMPANY_FACTS,
        DatasetName.SEC_FORM4,
        DatasetName.UNIVERSE_MEMBERSHIP,
    }


def test_required_datasets_skip_universe_when_static_universe_is_used() -> None:
    requirements = required_datasets(["fundamentals"], uses_static_universe=True)

    assert DatasetName.UNIVERSE_MEMBERSHIP not in requirements


def test_inspect_datasets_reports_missing_and_ready_manifests(tmp_path) -> None:
    manifest_root = tmp_path / "manifests"
    parquet_root = tmp_path / "parquet"
    manifest_root.mkdir()
    parquet_root.mkdir()
    prices = pl.DataFrame([{"ticker": "A", "date": date(2023, 1, 1), "close": 100.0}])
    prices.write_parquet(parquet_root / "prices.parquet")
    write_manifest(manifest_root, DatasetName.PRICES_DAILY, "prices.parquet", 1)

    checks = inspect_datasets(
        {
            DatasetName.PRICES_DAILY: "prices",
            DatasetName.SEC_COMPANY_FACTS: "fundamentals",
        },
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        as_of=TODAY,
    )

    assert checks[0].dataset == "prices_daily"
    assert checks[0].available is True
    assert checks[1].dataset == "sec_company_facts"
    assert checks[1].available is False


def test_run_research_batch_writes_blocked_status(tmp_path) -> None:
    output_root = tmp_path / "results"
    manifest_root = tmp_path / "manifests"
    parquet_root = tmp_path / "parquet"
    manifest_root.mkdir()
    parquet_root.mkdir()

    result = run_research_batch(
        ResearchBatchConfig(
            start=date(2023, 1, 1),
            end=date(2023, 1, 5),
            signals=("fundamentals",),
        ),
        output_root=output_root,
        manifest_root=manifest_root,
        parquet_root=parquet_root,
    )

    status = json.loads((output_root / "batch-status.json").read_text(encoding="utf-8"))
    markdown = result_to_markdown(result)

    assert result.h1_ran is False
    assert status["h1_ran"] is False
    assert "missing required datasets" in markdown


def test_required_datasets_reject_unknown_signal() -> None:
    with pytest.raises(ValueError, match="unknown signal"):
        required_datasets(["not-a-signal"])
