from __future__ import annotations

from service_fixtures import provenance

from agency.services import (
    LeveragedAlternativePolicy,
    build_evidence_pack,
    build_final_selection,
    build_leveraged_alternative_review,
    build_risk_decision,
    build_signal_result,
    evaluate_option_write_request,
)

EXPECTED_LEVERAGED_CAP = 1.5
EXPECTED_CALL_SPREAD_MAX_LOSS = 460.0
EXPECTED_CALL_SPREAD_BREAKEVEN = 199.6


def test_leveraged_alternatives_disabled_by_default() -> None:
    review = build_leveraged_alternative_review(_strong_report())

    assert review["enabled"] is False
    assert review["eligible"] is False
    assert review["status_label"] == "Disabled"
    assert review["alternatives"] == []


def test_low_conviction_candidate_never_gets_alternatives() -> None:
    review = build_leveraged_alternative_review(
        _strong_report(conviction=0.84),
        policy=_policy(),
        etf_catalog=[_etf("AAPL", "AAPU")],
    )

    assert review["eligible"] is False
    assert "conviction is below" in str(review["summary"])
    assert review["alternatives"] == []


def test_high_conviction_candidate_gets_advisory_etf_match() -> None:
    report = _strong_report(conviction=0.91)
    risk = _risk(report)

    review = build_leveraged_alternative_review(
        report,
        risk_decision=risk,
        policy=_policy(max_leveraged_position_pct=EXPECTED_LEVERAGED_CAP),
        etf_catalog=[_etf("AAPL", "AAPU", issuer="Direxion")],
    )

    assert review["eligible"] is True
    assert review["available_alternative_count"] == 1
    alternative = review["alternatives"][0]
    assert alternative["ticker"] == "AAPU"
    assert alternative["orderable"] is False
    assert alternative["estimated_position_pct"] == EXPECTED_LEVERAGED_CAP
    assert alternative["status_label"] == "Review Only"


def test_hard_risk_blocker_blocks_orderable_leverage() -> None:
    report = _strong_report(action="BUY", policy_status="BLOCK")
    risk = _risk(report)

    review = build_leveraged_alternative_review(
        report,
        risk_decision=risk,
        policy=_policy(),
        etf_catalog=[_etf("AAPL", "AAPU")],
    )

    assert review["eligible"] is False
    assert review["alternatives"] == []
    assert any(
        check["name"] == "hard_blockers" and check["status"] == "BLOCK"
        for check in review["trigger_checks"]
    )


def test_no_etf_available_is_explained() -> None:
    review = build_leveraged_alternative_review(
        _strong_report(ticker="WDC"),
        policy=_policy(),
        etf_catalog=[_etf("AAPL", "AAPU")],
    )

    assert review["eligible"] is True
    assert review["available_alternative_count"] == 0
    assert review["alternatives"][0]["blocker"] == "No curated ETF mapping."


def test_illiquid_etf_is_not_eligible() -> None:
    review = build_leveraged_alternative_review(
        _strong_report(),
        policy=_policy(min_etf_avg_dollar_volume=10_000_000.0),
        etf_catalog=[_etf("AAPL", "AAPU", avg_dollar_volume=100_000.0)],
    )

    alternative = review["alternatives"][0]
    assert alternative["eligible"] is False
    assert "liquidity floor" in str(alternative["blocker"])


def test_defined_risk_options_report_missing_chain() -> None:
    review = build_leveraged_alternative_review(
        _strong_report(),
        policy=_policy(allow_defined_risk_options=True),
        etf_catalog=[],
        option_chain=[],
    )

    assert any(item["type"] == "defined_risk_option" for item in review["alternatives"])
    assert "No option chain" in str(review["alternatives"][-1]["blocker"])


def test_defined_risk_option_candidate_uses_call_spread() -> None:
    review = build_leveraged_alternative_review(
        _strong_report(),
        policy=_policy(allow_defined_risk_options=True),
        etf_catalog=[],
        option_chain=[
            _call("AAPL260619C00195000", 195.0, bid=10.0, ask=10.4, delta=0.56),
            _call("AAPL260619C00205000", 205.0, bid=5.8, ask=6.2, delta=0.31),
        ],
    )

    option = review["alternatives"][-1]
    assert option["type"] == "defined_risk_call_spread"
    assert option["eligible"] is True
    assert option["max_loss"] == EXPECTED_CALL_SPREAD_MAX_LOSS
    assert option["breakeven"] == EXPECTED_CALL_SPREAD_BREAKEVEN
    assert option["orderable"] is False


def test_naked_option_write_is_blocked() -> None:
    blocked = evaluate_option_write_request(
        write_type="naked_call",
        contracts=1,
        policy=_policy(allow_covered_option_writes=True),
    )
    covered = evaluate_option_write_request(
        write_type="covered_call",
        contracts=1,
        policy=_policy(allow_covered_option_writes=True),
        covered_position_qty=100,
    )

    assert blocked["allowed"] is False
    assert blocked["status"] == "BLOCK"
    assert covered["allowed"] is True


def _policy(**overrides: object) -> LeveragedAlternativePolicy:
    values = {"enabled": True, **overrides}
    return LeveragedAlternativePolicy(**values)


def _strong_report(
    *,
    ticker: str = "AAPL",
    action: str = "BUY",
    conviction: float = 0.9,
    policy_status: str = "PASS",
) -> dict[str, object]:
    as_of = "2026-05-07T09:30:00Z"
    generated_at = "2026-05-07T09:31:00Z"
    pack = build_evidence_pack(
        cycle_id="cycle-1",
        ticker=ticker,
        as_of=as_of,
        generated_at=generated_at,
        signals=[
            build_signal_result(
                cycle_id="cycle-1",
                ticker=ticker,
                as_of=as_of,
                lane="fundamentals",
                score=0.8,
                provenance=provenance("source-1"),
                confidence=0.9,
            ),
            build_signal_result(
                cycle_id="cycle-1",
                ticker=ticker,
                as_of=as_of,
                lane="insider",
                score=0.7,
                provenance=provenance("source-2"),
                confidence=0.85,
            ),
        ],
    )
    report = build_final_selection(pack).selection_report
    report["final_action"] = action
    report["final_conviction"] = conviction
    report["policy_gates"] = [
        {
            "name": "evidence_breadth",
            "status": policy_status,
            "reason": "leveraged review fixture",
        }
    ]
    return report


def _risk(report: dict[str, object]) -> dict[str, object]:
    return build_risk_decision(
        report,
        {"source_count": 2, "degraded_source_count": 0},
    ).risk_decision


def _etf(
    underlying: str,
    ticker: str,
    *,
    issuer: str = "Test Issuer",
    avg_dollar_volume: float | None = None,
) -> dict[str, object]:
    return {
        "underlying": underlying,
        "ticker": ticker,
        "direction": "LONG",
        "leverage_factor": 2.0,
        "issuer": issuer,
        "enabled": True,
        "avg_dollar_volume": avg_dollar_volume,
    }


def _call(
    symbol: str,
    strike: float,
    *,
    bid: float,
    ask: float,
    delta: float,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "underlying": "AAPL",
        "option_type": "CALL",
        "expiration": "2026-06-19",
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "delta": delta,
    }
