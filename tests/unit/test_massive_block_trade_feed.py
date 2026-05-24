from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from research.scripts.derive_massive_block_trade_feed import (
    _coverage_from_source,
    _read_trade_frame,
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


def test_derive_massive_block_trade_feed_skips_unusable_source_ticker_parquet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trade_root = tmp_path / "stock_trades"
    output_root = tmp_path / "block_feed"
    source_manifest = tmp_path / "massive_live_trade_slices.json"
    lane_manifest = tmp_path / "massive_block_trade_feed.json"
    progress_path = tmp_path / "progress.json"
    aapl_partition = trade_root / "ticker=AAPL" / "year=2026"
    hon_partition = trade_root / "ticker=HON" / "year=2026"
    aapl_partition.mkdir(parents=True)
    hon_partition.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "year": 2026,
                "trade_date": date(2026, 5, 22),
                "trade_ts": "2026-05-22T19:00:00+00:00",
                "sequence_number": 1,
                "trade_id": "a",
                "source_id": "a",
                "price": 100.0,
                "size": 20_000,
                "notional": 2_000_000.0,
                "is_block_trade": True,
                "is_off_exchange": False,
            }
        ]
    ).to_parquet(aapl_partition / "trades.parquet", engine="pyarrow", index=False)
    (hon_partition / "trades.parquet").write_text("not parquet", encoding="utf-8")
    source_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "status": "partial",
                "fetched_at": datetime(2026, 5, 22, 19, 5, tzinfo=UTC).isoformat(),
                "window": {"start": "2026-05-22", "end": "2026-05-22"},
                "tickers": ["AAPL", "HON"],
                "coverage_pct": 50,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-22",
                        "coverage_status": "complete",
                    },
                    {
                        "ticker": "HON",
                        "trade_date": "2026-05-22",
                        "coverage_status": "failed",
                    },
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
            "2026-05-22",
            "--end",
            "2026-05-22",
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

    assert main() == 1

    derived = pd.read_parquet(
        output_root / "ticker=AAPL" / "year=2026" / "block_trades.parquet"
    )
    manifest = json.loads(lane_manifest.read_text(encoding="utf-8"))
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert len(derived) == 1
    assert manifest["status"] == "partial"
    assert manifest["issues"] == [
        {
            "reason": "source live-trade slice was not usable",
            "ticker": "HON",
            "trade_date": "2026-05-22",
        }
    ]
    assert progress["state"] == "partial"


def test_derive_massive_block_trade_feed_replaces_corrupt_existing_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trade_root = tmp_path / "stock_trades"
    output_root = tmp_path / "block_feed"
    source_manifest = tmp_path / "massive_live_trade_slices.json"
    lane_manifest = tmp_path / "massive_block_trade_feed.json"
    progress_path = tmp_path / "progress.json"
    trade_partition = trade_root / "ticker=AAPL" / "year=2026"
    output_partition = output_root / "ticker=AAPL" / "year=2026"
    trade_partition.mkdir(parents=True)
    output_partition.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "year": 2026,
                "trade_date": date(2026, 5, 22),
                "trade_ts": "2026-05-22T19:00:00+00:00",
                "sequence_number": 1,
                "trade_id": "a",
                "source_id": "a",
                "price": 100.0,
                "size": 20_000,
                "notional": 2_000_000.0,
                "is_block_trade": True,
                "is_off_exchange": False,
            }
        ]
    ).to_parquet(trade_partition / "trades.parquet", engine="pyarrow", index=False)
    (output_partition / "block_trades.parquet").write_text(
        "not parquet", encoding="utf-8"
    )
    source_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "status": "complete",
                "fetched_at": datetime(2026, 5, 22, 19, 5, tzinfo=UTC).isoformat(),
                "window": {"start": "2026-05-22", "end": "2026-05-22"},
                "tickers": ["AAPL"],
                "coverage_pct": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-22",
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
            "2026-05-22",
            "--end",
            "2026-05-22",
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

    derived = pd.read_parquet(output_partition / "block_trades.parquet")
    assert len(derived) == 1


def test_read_trade_frame_filters_partition_before_concat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    partition = tmp_path / "ticker=AAPL" / "year=2026"
    partition.mkdir(parents=True)
    (partition / "trades.parquet").write_text("placeholder", encoding="utf-8")

    def fake_read_parquet(_path: Path) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "trade_date": date(2026, 5, 21),
                    "is_block_trade": True,
                },
                {
                    "ticker": "AAPL",
                    "trade_date": date(2026, 5, 22),
                    "is_block_trade": True,
                },
            ]
        )

    real_concat = pd.concat

    def guarded_concat(frames, *args, **kwargs):  # type: ignore[no-untyped-def]
        materialized = list(frames)
        assert materialized
        assert all(
            set(frame["trade_date"]) == {date(2026, 5, 22)}
            for frame in materialized
        )
        return real_concat(materialized, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)
    monkeypatch.setattr(pd, "concat", guarded_concat)

    frame, issues = _read_trade_frame(
        tmp_path,
        tickers=("AAPL",),
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
    )

    assert issues == []
    assert len(frame) == 1
    assert frame["trade_date"].iat[0] == date(2026, 5, 22)


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
