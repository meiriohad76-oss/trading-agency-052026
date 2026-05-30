from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from agency.market_regime.fetcher import (
    FetchSummary,
    grouped_daily_breadth,
    load_state_json,
    refresh_etf_bars,
    refresh_fred_series,
    refresh_grouped_daily,
    refresh_intraday_bars,
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


def test_refresh_etf_bars_writes_state_file(tmp_path) -> None:
    fake_bars = {
        "SPY": [{"date": "2026-05-28", "open": 100.0, "high": 102.0,
                 "low": 99.0, "close": 101.0, "volume": 1_000_000.0}],
    }

    def fake_client(tickers, start, end):
        return {t: fake_bars[t] for t in tickers if t in fake_bars}

    result = refresh_etf_bars(
        tmp_path / "etf_bars.json",
        policy=RegimePolicy(),
        now=datetime.now(UTC),
        etf_client=fake_client,
    )

    assert result.ok is True
    assert load_state_json(tmp_path / "etf_bars.json") == fake_bars


def test_refresh_etf_bars_client_failure_non_blocking(tmp_path) -> None:
    def broken_client(tickers, start, end):
        raise RuntimeError("network error")

    result = refresh_etf_bars(
        tmp_path / "etf_bars.json",
        policy=RegimePolicy(),
        now=datetime.now(UTC),
        etf_client=broken_client,
    )

    assert result.ok is False
    assert any("failed" in issue.lower() for issue in result.issues)
    assert not (tmp_path / "etf_bars.json").exists()


def test_refresh_intraday_bars_writes_state_file(tmp_path) -> None:
    fake = {"SPY": {"price": 456.0, "prior_close": 450.0}}

    result = refresh_intraday_bars(
        tmp_path / "intraday_bars.json",
        snapshot_client=lambda tickers: fake,
    )

    assert result.ok is True
    assert load_state_json(tmp_path / "intraday_bars.json") == fake


def test_refresh_intraday_bars_failure_non_blocking(tmp_path) -> None:
    def broken(_):
        raise RuntimeError("down")

    result = refresh_intraday_bars(
        tmp_path / "intraday_bars.json",
        snapshot_client=broken,
    )

    assert result.ok is False


def test_refresh_grouped_daily_writes_breadth(tmp_path) -> None:
    fake_rows = [
        {"open": 10.0, "close": 11.0},
        {"open": 10.0, "close": 9.0},
        {"open": 10.0, "close": 11.5},
    ]

    result = refresh_grouped_daily(
        tmp_path / "grouped_daily.json",
        now=datetime.now(UTC),
        grouped_client=lambda day: fake_rows,
    )

    assert result.ok is True
    breadth = load_state_json(tmp_path / "grouped_daily.json")
    assert breadth["total"] == 3
    assert breadth["advancers"] == 2
    assert breadth["decliners"] == 1
    assert breadth["advancers_pct"] == pytest.approx(66.67, rel=0.01)


def test_refresh_grouped_daily_failure_non_blocking(tmp_path) -> None:
    def broken(day):
        raise RuntimeError("down")

    result = refresh_grouped_daily(
        tmp_path / "grouped_daily.json",
        now=datetime.now(UTC),
        grouped_client=broken,
    )

    assert result.ok is False
