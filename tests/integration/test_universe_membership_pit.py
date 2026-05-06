from __future__ import annotations

from datetime import date

from pit.loader import PITLoader

MIN_UNION_MEMBERS = 120


def test_pit_loader_reads_committed_universe_membership() -> None:
    members = PITLoader(today=lambda: date(2026, 5, 6)).universe_members(date(2022, 6, 15))

    assert len(members) >= MIN_UNION_MEMBERS
    assert "AAPL" in members
    assert "SLB" not in members
