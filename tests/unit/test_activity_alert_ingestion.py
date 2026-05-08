from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
from activity_alerts.local_csv import read_activity_alert_csv
from activity_alerts.storage import write_activity_alert_frame, write_manifest
from pit.manifest import DatasetName
from pit_fixtures import loader_with, provenance

from agency.provenance import SourceTier

FETCHED_AT = datetime(2026, 5, 8, 14, 0, tzinfo=UTC)
RAW_ALERT_ROWS = 2
UPDATED_NOTIONAL = 2_000_000.0


def test_read_activity_alert_csv_normalizes_local_provider_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "alerts.csv"
    csv_path.write_text(
        "\n".join(
            [
                "ticker,alert_type,direction,observed_at,notional,source_tier",
                "aapl,Block Trade,call,2026-05-08T13:00:00Z,1000000,paid_sub_email",
            ]
        ),
        encoding="utf-8",
    )

    frame = read_activity_alert_csv(csv_path, fetched_at=FETCHED_AT)

    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["alert_type"] == "block_trade"
    assert frame.iloc[0]["direction"] == "BULLISH"
    assert frame.iloc[0]["source_tier"] == SourceTier.PAID_SUB_EMAIL.value
    assert frame.iloc[0]["verification_level"] == "CONFIRMED"


def test_write_activity_alert_frame_dedupes_and_writes_manifest(tmp_path: Path) -> None:
    parquet_path = tmp_path / "unusual_activity_alerts.parquet"
    manifest_path = tmp_path / "unusual_activity_alerts.json"
    frame = pd.DataFrame(
        [
            _alert_row("AAPL", "same", notional=1_000_000.0),
            _alert_row("AAPL", "same", notional=UPDATED_NOTIONAL),
        ]
    )

    rows_written = write_activity_alert_frame(parquet_path, frame)
    write_manifest(manifest_path, parquet_path, fetched_at=FETCHED_AT)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stored = pd.read_parquet(parquet_path)

    assert rows_written == RAW_ALERT_ROWS
    assert len(stored) == 1
    assert stored.iloc[0]["notional"] == UPDATED_NOTIONAL
    assert manifest["dataset"] == "unusual_activity_alerts"
    assert manifest["row_count"] == 1
    assert manifest["issues"] == []


def test_pit_loader_filters_activity_alerts_by_ticker_and_observed_date(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            _alert_row("AAPL", "old", as_of=date(2026, 5, 1)),
            _alert_row("AAPL", "inside", as_of=date(2026, 5, 5)),
            _alert_row("AAPL", "future", as_of=date(2026, 5, 7)),
            _alert_row("MSFT", "other", as_of=date(2026, 5, 5)),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.UNUSUAL_ACTIVITY_ALERTS: frame})

    result = loader.activity_alerts(["AAPL"], date(2026, 5, 6), lookback_days=3)

    assert [item.provenance.source_id for item in result] == ["inside"]
    assert [item.value["ticker"] for item in result] == ["AAPL"]


def _alert_row(
    ticker: str,
    source_id: str,
    *,
    as_of: date = date(2026, 5, 8),
    notional: float = 1_000_000.0,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "alert_type": "block_trade",
        "direction": "BULLISH",
        "event_time": as_of,
        "summary": "fixture",
        "price": 100.0,
        "volume": 10_000.0,
        "notional": notional,
        "premium": None,
        **provenance(SourceTier.PAID_SUB_EMAIL, as_of, source_id=source_id),
    }
