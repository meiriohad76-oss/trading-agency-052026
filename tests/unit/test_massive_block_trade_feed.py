from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from research.scripts.derive_massive_block_trade_feed import (
    _coverage_from_source,
    _source_manifest_problem,
    _validate_lane_invocation,
    main,
)


def test_derive_massive_block_trade_feed_writes_artifact_and_lane_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trade_root = tmp_path / "stock_trades"
    output_root = tmp_path / "block_feed"
    source_manifest = tmp_path / "massive_live_trade_slices.json"
    lane_manifest = tmp_path / "massive_block_trade_feed.json"
    progress_path = tmp_path / "progress.json"
    partition = trade_root / "ticker=AAPL" / "year=2026"
    partition.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "year": 2026,
                "trade_date": date(2026, 5, 11),
                "trade_ts": "2026-05-11T14:00:00+00:00",
                "sequence_number": 1,
                "trade_id": "a",
                "source_id": "a",
                "price": 100.0,
                "size": 20_000,
                "notional": 2_000_000.0,
                "is_block_trade": True,
                "is_off_exchange": False,
            },
            {
                "ticker": "AAPL",
                "year": 2026,
                "trade_date": date(2026, 5, 11),
                "trade_ts": "2026-05-11T14:01:00+00:00",
                "sequence_number": 2,
                "trade_id": "b",
                "source_id": "b",
                "price": 100.0,
                "size": 100,
                "notional": 10_000.0,
                "is_block_trade": False,
                "is_off_exchange": False,
            },
        ]
    ).to_parquet(partition / "trades.parquet", engine="pyarrow", index=False)
    source_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "status": "complete",
                "fetched_at": datetime(2026, 5, 11, 14, 5, tzinfo=UTC).isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "tickers": ["AAPL"],
                "coverage_pct": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-11",
                        "coverage_status": "complete",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "derive_massive_block_trade_feed.py",
            "--start",
            "2026-05-11",
            "--end",
            "2026-05-11",
            "--ticker",
            "AAPL",
            "--trade-root",
            str(trade_root),
            "--output-root",
            str(output_root),
            "--source-lane-manifest",
            str(source_manifest),
            "--lane-manifest-path",
            str(lane_manifest),
            "--progress-path",
            str(progress_path),
        ],
    )

    assert main() == 0

    derived = pd.read_parquet(
        output_root / "ticker=AAPL" / "year=2026" / "block_trades.parquet"
    )
    manifest = json.loads(lane_manifest.read_text(encoding="utf-8"))
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert len(derived) == 1
    assert manifest["lane_id"] == "massive_block_trade_feed"
    assert manifest["status"] == "complete"
    assert manifest["coverage_pct"] == 100
    assert progress["state"] == "complete"


def test_derive_massive_block_trade_feed_rejects_wrong_lane_id() -> None:
    class Args:
        lane_id = "massive_live_trade_slices"

    try:
        _validate_lane_invocation(Args())
    except SystemExit:
        pass
    else:
        raise AssertionError("block-trade derivation should not write other lane manifests")


def test_block_trade_derivation_requires_live_slice_source_manifest() -> None:
    class Args:
        start = date(2026, 5, 11)
        end = date(2026, 5, 11)

    problem = _source_manifest_problem(
        {
            "lane_id": "massive_daily_bars",
            "dataset": "prices_daily",
            "window": {"start": "2026-05-11", "end": "2026-05-11"},
        },
        Args(),
    )

    assert "massive_live_trade_slices" in problem


def test_block_trade_derivation_treats_missing_source_coverage_as_unusable() -> None:
    coverage = _coverage_from_source(
        {
            "lane_id": "massive_live_trade_slices",
            "dataset": "stock_trades",
            "raw_source_dataset": "stock_trades",
            "window": {"start": "2026-05-11", "end": "2026-05-11"},
            "coverage": [
                {
                    "ticker": "AAPL",
                    "trade_date": "2026-05-11",
                    "coverage_status": "missing",
                }
            ],
        },
        ("AAPL",),
        start=date(2026, 5, 11),
        end=date(2026, 5, 11),
    )

    assert coverage[0]["coverage_status"] == "failed"
    assert coverage[0]["complete"] is False
    assert coverage[0]["usable_for_live_pipeline"] is False


def test_block_trade_derivation_preserves_partial_usable_source_status() -> None:
    coverage = _coverage_from_source(
        {
            "lane_id": "massive_live_trade_slices",
            "dataset": "stock_trades",
            "raw_source_dataset": "stock_trades",
            "window": {"start": "2026-05-11", "end": "2026-05-11"},
            "coverage": [
                {
                    "ticker": "AAPL",
                    "trade_date": "2026-05-11",
                    "coverage_status": "partial",
                    "complete": False,
                    "downloaded_row_count": 1000,
                    "pages_downloaded": 1,
                    "order": "desc",
                }
            ],
        },
        ("AAPL",),
        start=date(2026, 5, 11),
        end=date(2026, 5, 11),
    )

    assert coverage[0]["coverage_status"] == "partial_usable"
    assert coverage[0]["complete"] is False
    assert coverage[0]["usable_for_live_pipeline"] is True
    assert coverage[0]["source_complete"] is False
