from __future__ import annotations

from agency.api.health import _latest_iso_datetime, _valid_iso_datetime


def test_valid_iso_datetime_rejects_sentinel_strings() -> None:
    assert _valid_iso_datetime("not checked") is None
    assert _valid_iso_datetime("not recorded") is None
    assert _valid_iso_datetime(None) is None
    assert _valid_iso_datetime("garbage-string") is None
    assert _valid_iso_datetime("2026-05-22T14:00:00+00:00") == (
        "2026-05-22T14:00:00+00:00"
    )


def test_latest_iso_datetime_returns_most_recent() -> None:
    assert _latest_iso_datetime(None, "2026-05-22T14:00:00+00:00") == (
        "2026-05-22T14:00:00+00:00"
    )
    assert _latest_iso_datetime(
        "2026-05-21T00:00:00+00:00",
        "2026-05-22T00:00:00+00:00",
    ) == "2026-05-22T00:00:00+00:00"
    assert _latest_iso_datetime(
        "2026-05-23T00:00:00+00:00",
        "2026-05-22T00:00:00+00:00",
    ) == "2026-05-23T00:00:00+00:00"
