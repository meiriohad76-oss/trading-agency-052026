from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from pit.loader import PITLoader


def test_real_pit_loader_smoke_when_datasets_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        root / "research" / "data" / "manifests" / "prices.json",
        root / "research" / "data" / "manifests" / "universe_membership.json",
    ]
    if not all(path.exists() for path in required):
        pytest.skip("real PIT datasets are populated by later data tickets")

    loader = PITLoader()
    as_of = date.today() - timedelta(days=7)

    assert loader.prices(["AAPL"], as_of, lookback_days=10).height > 0
    assert "AAPL" in loader.universe_members(as_of)
