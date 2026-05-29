from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agency.market_regime.fetcher import (
    FetchSummary,
    grouped_daily_breadth,
    load_state_json,
    refresh_fred_series,
    write_state_json,
)
from agency.market_regime.policy import RegimePolicy


def test_etf_bars_roundtrip(tmp_path) -> None:
    path = tmp_path / "etf_bars.json"
    payload = {"SPY": [{"date": "2026-05-28", "close": 100.0}]}

    write_state_json(path, payload)

    assert load_state_json(path) == payload


def test_fred_cache_hit(tmp_path) -> None:
    cache = tmp_path / "macro_fred.json"
    now = datetime.now(UTC)
    write_state_json(
        cache,
        {"generated_at": now.isoformat(), "series": {"VIXCLS": [{"value": 18.0}]}},
    )

    result = refresh_fred_series(cache, policy=RegimePolicy(), now=now + timedelta(hours=1))

    assert result.used_cache is True
    assert result.issues == []


def test_fred_failure_non_blocking(tmp_path) -> None:
    def broken_client(_: str):
        raise RuntimeError("fred down")

    result = refresh_fred_series(
        tmp_path / "macro_fred.json",
        policy=RegimePolicy(),
        now=datetime.now(UTC),
        series_client=broken_client,
    )

    assert isinstance(result, FetchSummary)
    assert result.ok is False
    assert result.issues


def test_grouped_daily_breadth_coverage() -> None:
    result = grouped_daily_breadth(
        [
            {"ticker": "AAA", "open": 10.0, "close": 11.0},
            {"ticker": "BBB", "open": 10.0, "close": 9.0},
            {"ticker": "CCC", "open": 10.0, "close": 12.0},
        ]
    )

    assert result["total"] == 3
    assert result["advancers"] == 2
    assert result["decliners"] == 1
    assert result["advancers_pct"] == 66.67
