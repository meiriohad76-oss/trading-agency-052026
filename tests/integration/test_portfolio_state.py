from __future__ import annotations

from pathlib import Path

import pytest

from agency.portfolio.state import (
    ensure_daily_baseline,
    ensure_weekly_baseline,
    load_daily_baseline,
    load_high_water_marks,
    load_weekly_baseline,
    save_daily_baseline,
    save_high_water_marks,
    save_weekly_baseline,
    update_high_water_marks,
)


def test_high_water_marks_persist_and_load(tmp_path: Path) -> None:
    marks = {"AAPL": 3.45, "MSFT": 1.20, "NVDA": 0.0}

    save_high_water_marks(tmp_path, marks)
    loaded = load_high_water_marks(tmp_path)

    assert loaded["AAPL"] == pytest.approx(3.45)
    assert loaded["MSFT"] == pytest.approx(1.20)
    assert loaded["NVDA"] == pytest.approx(0.0)


def test_update_high_water_marks_only_goes_up() -> None:
    current = {"AAPL": 3.45}

    updated = update_high_water_marks(
        current,
        [{"symbol": "AAPL", "unrealized_plpc": "0.020"}],
    )
    updated2 = update_high_water_marks(
        updated,
        [{"symbol": "AAPL", "unrealized_plpc": "0.040"}],
    )

    assert updated["AAPL"] == pytest.approx(3.45)
    assert updated2["AAPL"] == pytest.approx(4.0)


def test_weekly_baseline_roundtrip(tmp_path: Path) -> None:
    baseline = {"week_start": "2026-05-26", "equity": 98500.00}

    save_weekly_baseline(tmp_path, baseline)
    loaded = load_weekly_baseline(tmp_path)

    assert loaded is not None
    assert loaded["week_start"] == "2026-05-26"
    assert loaded["equity"] == pytest.approx(98500.00)


def test_weekly_baseline_resets_on_new_week(tmp_path: Path) -> None:
    save_weekly_baseline(tmp_path, {"week_start": "2026-05-18", "equity": 97000.00})

    baseline = ensure_weekly_baseline(
        tmp_path,
        account={"equity": 100000.00},
        week_start="2026-05-26",
    )

    assert baseline["week_start"] == "2026-05-26"
    assert baseline["equity"] == pytest.approx(100000.00)
    assert load_weekly_baseline(tmp_path) == baseline


def test_daily_baseline_resets_on_new_date(tmp_path: Path) -> None:
    save_daily_baseline(tmp_path, {"date": "2026-05-28", "equity": 99000.00})

    baseline = ensure_daily_baseline(
        tmp_path,
        account={"portfolio_value": 100500.00},
        date="2026-05-29",
    )

    assert baseline["date"] == "2026-05-29"
    assert baseline["equity"] == pytest.approx(100500.00)
    assert load_daily_baseline(tmp_path) == baseline


def test_state_dir_missing_returns_empty_defaults(tmp_path: Path) -> None:
    empty_dir = tmp_path / "nonexistent"

    assert load_high_water_marks(empty_dir) == {}
    assert load_weekly_baseline(empty_dir) is None
    assert load_daily_baseline(empty_dir) is None
