from __future__ import annotations

from types import ModuleType

import pandas as pd
import pytest
from technical_analysis import indicator_engine
from technical_analysis.indicator_engine import (
    ExternalIndicatorSnapshot,
    external_indicator_snapshot,
)

ROWS = 45
FAKE_SCORE = 0.25


def test_external_indicator_snapshot_uses_factory() -> None:
    snapshot = external_indicator_snapshot(
        close=_series(),
        high=_series(offset=1.0),
        low=_series(offset=-1.0),
        volume=_series(start=1_000_000.0, step=1000.0),
        factory=_fake_factory,
    )

    assert snapshot.status == "ta_available"
    assert snapshot.score == FAKE_SCORE
    assert "technical_indicator_pack_bullish" in snapshot.reason_codes


def test_external_indicator_snapshot_is_neutral_when_ta_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_module(name: str) -> ModuleType:
        del name
        raise ModuleNotFoundError("ta")

    monkeypatch.setattr(indicator_engine, "import_module", missing_module)

    snapshot = external_indicator_snapshot(
        close=_series(),
        high=_series(offset=1.0),
        low=_series(offset=-1.0),
        volume=_series(start=1_000_000.0, step=1000.0),
    )

    assert snapshot.status == "ta_not_installed"
    assert snapshot.score == 0.0
    assert snapshot.values["adx14"] is None


def _fake_factory(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> ExternalIndicatorSnapshot:
    del close, high, low, volume
    return ExternalIndicatorSnapshot(
        provider="fake",
        status="ta_available",
        score=FAKE_SCORE,
        trend_score=0.3,
        momentum_score=0.2,
        channel_score=0.1,
        volume_score=0.4,
        reason_codes=["technical_indicator_pack_bullish"],
        values={"adx14": 30.0},
    )


def _series(*, start: float = 100.0, step: float = 1.0, offset: float = 0.0) -> pd.Series:
    return pd.Series([start + offset + step * index for index in range(ROWS)])
