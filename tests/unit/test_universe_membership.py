from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from universe.checks import active_members
from universe.membership import build_universe_membership

SP100_MIN_ACTIVE = 98
NASDAQ100_MIN_ACTIVE = 95


def _membership_path() -> Path:
    return Path("research") / "data" / "parquet" / "universe_membership.parquet"


def _membership() -> pd.DataFrame:
    return pd.read_parquet(_membership_path())


def test_committed_universe_membership_spot_checks() -> None:
    frame = _membership()

    sp100_2022 = active_members(frame, date(2022, 6, 15), "SP100")
    nasdaq_2022 = active_members(frame, date(2022, 6, 15), "NASDAQ100")
    sp100_2022_after_removal = active_members(frame, date(2022, 1, 1), "SP100")
    nasdaq_before_pltr = active_members(frame, date(2023, 12, 1), "NASDAQ100")
    nasdaq_after_pltr = active_members(frame, date(2024, 12, 24), "NASDAQ100")

    assert "AAPL" in sp100_2022
    assert "AAPL" in nasdaq_2022
    assert "SLB" not in sp100_2022_after_removal
    assert "PLTR" not in nasdaq_before_pltr
    assert "PLTR" in nasdaq_after_pltr


def test_active_counts_are_inside_ticket_floor() -> None:
    frame = _membership()
    for as_of in (date(2019, 1, 1), date(2022, 6, 15), date(2026, 5, 6)):
        assert len(active_members(frame, as_of, "SP100")) >= SP100_MIN_ACTIVE
        assert len(active_members(frame, as_of, "NASDAQ100")) >= NASDAQ100_MIN_ACTIVE


def test_closed_rows_and_membership_intervals_do_not_overlap() -> None:
    frame = _membership()
    closed = frame[frame["end_date"].notna()]
    assert (closed["start_date"] < closed["end_date"]).all()

    for keys, group in frame.groupby(["ticker", "index_name"]):
        ordered = group.sort_values("start_date")
        previous_end: date | None = None
        for row in ordered.to_dict("records"):
            if previous_end is not None:
                assert row["start_date"] >= previous_end, keys
            previous_end = row["end_date"]


def test_builder_is_byte_deterministic(tmp_path: Path) -> None:
    source_dir = Path("research") / "scripts" / "data" / "universe_membership"
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    build_universe_membership(
        source_dir=source_dir,
        parquet_path=first,
        manifest_path=tmp_path / "first.json",
    )
    build_universe_membership(
        source_dir=source_dir,
        parquet_path=second,
        manifest_path=tmp_path / "second.json",
    )

    assert first.read_bytes() == second.read_bytes()
