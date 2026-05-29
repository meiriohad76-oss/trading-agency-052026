from __future__ import annotations

import json

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
