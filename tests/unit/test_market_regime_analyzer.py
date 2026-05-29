from __future__ import annotations

import json

from agency.market_regime.analyzer import (
    analyze_intraday_drift,
    classify_macro_tilt,
    classify_market_backdrop,
    classify_sector_state,
    classify_vol_regime,
    detect_regime_change,
    per_stock_context,
)
from agency.market_regime.policy import RegimePolicy


def test_policy_defaults_match_spec() -> None:
    policy = RegimePolicy()

    assert policy.risk_off_spy_5d_pct == -1.5
    assert policy.risk_off_breadth_pct == 35.0
    assert policy.risk_off_tlt_5d_pct == 1.5
    assert policy.risk_on_spy_5d_pct == 1.0
    assert policy.risk_on_qqq_5d_pct == 0.0
    assert policy.risk_on_breadth_pct == 55.0
    assert policy.risk_on_vol_cap == 20.0
    assert policy.volatile_vol_threshold == 25.0
    assert policy.volatile_abs_move_pct == 2.0
    assert policy.rotating_sector_spread == 1.5
    assert policy.vix_calm == 20.0
    assert policy.vix_high == 35.0
    assert policy.cmf_period == 14
    assert policy.risk_on_modifier == 0.03
    assert policy.risk_off_modifier == -0.08
    assert policy.elevated_vol_size_multiplier == 0.75
    assert policy.high_vol_size_multiplier == 0.50


def test_policy_loads_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("AGENCY_RISK_OFF_SPY_5D_PCT", "-2.25")
    monkeypatch.setenv("AGENCY_INTRADAY_REFRESH_INTERVAL_MINUTES", "30")

    policy = RegimePolicy.from_env()

    assert policy.risk_off_spy_5d_pct == -2.25
    assert policy.intraday_refresh_interval_minutes == 30


def test_policy_env_overrides_local_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "portfolio-policy.local.json"
    path.write_text(
        json.dumps({"market_regime": {"risk_off_spy_5d_pct": -2.0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENCY_RISK_OFF_SPY_5D_PCT", "-3.0")

    policy = RegimePolicy.from_env(config_path=path)

    assert policy.risk_off_spy_5d_pct == -3.0


def test_risk_off_on_negative_spy() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=-1.6,
        qqq_5d_pct=0.2,
        breadth_pct=70.0,
        spy_vol_10d=15.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.2,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_OFF"
    assert result["conviction_modifier"] == -0.08


def test_risk_off_on_low_breadth() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=0.1,
        qqq_5d_pct=0.1,
        breadth_pct=34.0,
        spy_vol_10d=12.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_OFF"


def test_risk_off_on_bond_flight() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=0.0,
        qqq_5d_pct=0.0,
        breadth_pct=60.0,
        spy_vol_10d=12.0,
        tlt_5d_pct=1.6,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_OFF"


def test_volatile_regime() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=2.1,
        qqq_5d_pct=2.0,
        breadth_pct=50.0,
        spy_vol_10d=26.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "VOLATILE"
    assert result["conviction_modifier"] == -0.05


def test_risk_on_all_conditions() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=1.2,
        qqq_5d_pct=0.1,
        breadth_pct=56.0,
        spy_vol_10d=19.0,
        tlt_5d_pct=-0.2,
        sector_zscore_spread=0.1,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "RISK_ON"


def test_neutral_fallthrough() -> None:
    result = classify_market_backdrop(
        spy_5d_pct=0.2,
        qqq_5d_pct=-0.1,
        breadth_pct=50.0,
        spy_vol_10d=18.0,
        tlt_5d_pct=0.0,
        sector_zscore_spread=0.2,
        policy=RegimePolicy(),
    )
    assert result["regime"] == "NEUTRAL"


def test_vol_regime_calm_and_high() -> None:
    assert classify_vol_regime(19.9, RegimePolicy())["vol_regime"] == "CALM"
    assert classify_vol_regime(35.1, RegimePolicy())["vol_regime"] == "HIGH"


def test_macro_tilt_defensive_and_risk_appetite() -> None:
    policy = RegimePolicy()
    assert classify_macro_tilt(-0.1, 10.0, -0.5, policy)["macro_tilt"] == "DEFENSIVE"
    assert classify_macro_tilt(1.2, -11.0, -0.5, policy)["macro_tilt"] == "RISK_APPETITE"


def test_sector_quadrants_and_boosts() -> None:
    policy = RegimePolicy()
    assert classify_sector_state(1.0, 0.2, 0.1, "UP", policy)["state"] == "ADVANCING"
    assert classify_sector_state(1.0, -0.2, 0.1, "DOWN", policy)["state"] == "TOPPING"
    assert classify_sector_state(-1.0, -0.2, -0.1, "DOWN", policy)["state"] == "DECLINING"
    assert classify_sector_state(-1.0, 0.2, 0.1, "UP", policy)["state"] == "BASING"
    assert classify_sector_state(1.0, 0.2, 0.1, "UP", policy)["conviction_boost"] == 0.03
    assert classify_sector_state(-1.0, -0.2, -0.1, "DOWN", policy)["conviction_boost"] == -0.05


def test_per_stock_context_lookup() -> None:
    sector_map = {
        "XLK": {"state": "ADVANCING", "bias": "TAILWIND", "conviction_boost": 0.03}
    }
    result = per_stock_context(["AAPL", "MSFT"], {"AAPL": "XLK"}, sector_map)
    assert result["AAPL"]["sector"] == "XLK"
    assert result["AAPL"]["conviction_boost"] == 0.03
    assert result["MSFT"]["sector"] == "UNKNOWN"


def test_regime_change_detected() -> None:
    result = detect_regime_change(
        {"market_backdrop": {"regime": "NEUTRAL"}, "sector_map": {"XLK": {"state": "TOPPING"}}},
        {
            "market_backdrop": {"regime": "RISK_OFF"},
            "sector_map": {"XLK": {"state": "DECLINING"}},
        },
    )
    assert result["regime_changed"] is True
    assert result["prior_regime"] == "NEUTRAL"
    assert result["sector_transitions"] == [
        {"sector": "XLK", "from_state": "TOPPING", "to_state": "DECLINING"}
    ]


def test_no_regime_change() -> None:
    result = detect_regime_change(
        {
            "market_backdrop": {"regime": "RISK_ON"},
            "sector_map": {"XLK": {"state": "ADVANCING"}},
        },
        {
            "market_backdrop": {"regime": "RISK_ON"},
            "sector_map": {"XLK": {"state": "ADVANCING"}},
        },
    )
    assert result["regime_changed"] is False


def test_intraday_drift_computed() -> None:
    result = analyze_intraday_drift(
        {
            "SPY": {"price": 101.0, "prior_close": 100.0},
            "XLK": {"price": 103.0, "prior_close": 100.0},
        },
        morning_rank=["XLK", "SPY"],
    )
    assert result["spy_session_return_pct"] == 1.0
    assert result["sectors"]["XLK"]["vs_spy_pct"] == 2.0
