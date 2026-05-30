from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fundamentals.forward_state import (
    FileForwardFundamentalsLoader,
    forward_fundamentals_source_health,
    read_forward_fundamentals_state,
)
from signals.fundamentals import fundamental_factor_frame

AS_OF = date(2026, 5, 30)
NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


def test_reads_yfinance_and_fmp_state_for_ticker(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "yfinance" / "AAPL.json",
        {
            "ticker": "AAPL",
            "forward_pe": 24.3,
            "forward_eps": 7.28,
            "analyst_count": 43,
            "fetched_at": NOW.isoformat(),
        },
    )
    _write_json(
        tmp_path / "fmp" / "AAPL.json",
        {
            "ticker": "AAPL",
            "status": "ready",
            "eps_beat_rate": 0.75,
            "forward_eps": 7.31,
            "analyst_count": 47,
            "fetched_at": NOW.isoformat(),
        },
    )

    state = read_forward_fundamentals_state("aapl", state_root=tmp_path, now=NOW)

    assert state["forward_data_status"] == "ready"
    assert state["forward_pe"] == pytest.approx(24.3)
    assert state["forward_eps"] == pytest.approx(7.28)
    assert state["eps_beat_rate"] == pytest.approx(0.75)
    assert state["analyst_count"] == 47
    assert state["forward_data_as_of"] == NOW.isoformat()
    assert state["providers"] == ["yfinance", "fmp"]


def test_missing_state_returns_missing_status(tmp_path: Path) -> None:
    state = read_forward_fundamentals_state("AAPL", state_root=tmp_path, now=NOW)

    assert state["forward_data_status"] == "missing"
    assert state["forward_pe"] is None
    assert "No forward fundamentals state" in str(state["forward_data_detail"])


def test_old_state_returns_expired_status(tmp_path: Path) -> None:
    old = NOW - timedelta(days=10)
    _write_json(
        tmp_path / "yfinance" / "AAPL.json",
        {
            "ticker": "AAPL",
            "forward_pe": 24.3,
            "fetched_at": old.isoformat(),
        },
    )

    state = read_forward_fundamentals_state("AAPL", state_root=tmp_path, now=NOW)

    assert state["forward_data_status"] == "expired"
    assert state["forward_pe"] is None
    assert "needs refresh" in str(state["forward_data_detail"])


def test_forward_score_is_none_when_optional_state_missing() -> None:
    loader = _FakeFundamentalsLoader({"AAPL": _fundamentals()})
    forward_loader = _FakeForwardLoader({"AAPL": {"forward_data_status": "missing"}})

    frame = fundamental_factor_frame(AS_OF, {"AAPL"}, loader, forward_loader=forward_loader)

    assert pd.isna(frame.iloc[0]["forward_score"])
    assert frame.iloc[0]["forward_data_status"] == "missing"
    assert frame.iloc[0]["composite_score"] == pytest.approx(frame.iloc[0]["quality_score"])


def test_ready_forward_state_populates_score_inputs(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "yfinance" / "AAPL.json",
        {
            "ticker": "AAPL",
            "forward_pe": 24.3,
            "forward_eps": 7.28,
            "fetched_at": NOW.isoformat(),
        },
    )
    _write_json(
        tmp_path / "fmp" / "AAPL.json",
        {
            "ticker": "AAPL",
            "status": "ready",
            "eps_beat_rate": 0.75,
            "analyst_count": 47,
            "fetched_at": NOW.isoformat(),
        },
    )
    loader = _FakeFundamentalsLoader({"AAPL": _fundamentals()})
    forward_loader = FileForwardFundamentalsLoader(state_root=tmp_path, now=NOW)

    frame = fundamental_factor_frame(AS_OF, {"AAPL"}, loader, forward_loader=forward_loader)
    row = frame.iloc[0]

    assert row["forward_data_status"] == "ready"
    assert row["forward_pe"] == pytest.approx(24.3)
    assert row["eps_beat_rate"] == pytest.approx(0.75)
    assert row["analyst_count"] == 47
    assert row["forward_score"] == pytest.approx(0.0)


def test_forward_state_health_is_warning_not_blocker(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "fmp" / "AAPL.json",
        {
            "ticker": "AAPL",
            "status": "not_configured",
            "detail": "FMP_API_KEY is not configured.",
            "fetched_at": NOW.isoformat(),
        },
    )

    health = forward_fundamentals_source_health({"AAPL", "MSFT"}, state_root=tmp_path, now=NOW)

    assert health["source"] == "forward-fundamentals"
    assert health["status"] == "DEGRADED"
    assert health["freshness"] == "PARTIAL"
    assert health["critical"] is False
    assert health["ready_ticker_count"] == 0
    assert "Forward fundamentals not configured" in str(health["detail"])


class _FakeForwardLoader:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self._values = values

    def forward_fundamentals(self, ticker: str, as_of: date) -> dict[str, object]:
        return self._values[ticker.upper()]


class _FakeFundamentalsLoader:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self._values = values

    def fundamentals(self, ticker: str, as_of: date) -> object:
        return _ProvenancedValue(self._values[ticker.upper()])


class _ProvenancedValue:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value


def _fundamentals() -> dict[str, object]:
    return {
        "revenue": 100.0,
        "gross_profit": 44.0,
        "operating_income": 30.0,
        "net_income": 24.0,
        "free_cash_flow": 27.0,
        "total_assets": 200.0,
        "total_liabilities": 90.0,
        "total_equity": 110.0,
        "filing_period": "Q3",
        "filing_year": 2026,
        "filing_form": "10-Q",
        "filing_period_end": "2026-09-30",
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
