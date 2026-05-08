from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pit.loader import PITLoader


def test_real_pit_loader_smoke_when_datasets_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        root / "research" / "data" / "manifests" / "prices_daily.json",
        root / "research" / "data" / "manifests" / "universe_membership.json",
    ]
    if not all(path.exists() for path in required):
        pytest.skip("real PIT datasets are populated by later data tickets")

    loader = PITLoader()
    as_of = _manifest_as_of(required[0])

    assert loader.prices(["AAPL"], as_of, lookback_days=10).height > 0
    assert "AAPL" in loader.universe_members(as_of)


def _manifest_as_of(path: Path) -> date:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return datetime.fromisoformat(str(payload["max_timestamp_as_of"])).date()
