from __future__ import annotations

from service_fixtures import selection_report, source_health

from agency.services import (
    PaperTradePromotionConfig,
    PortfolioPolicy,
    TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG,
    build_execution_preview,
    build_human_review_event,
    build_operator_manual_advance_event,
    build_risk_decisions,
    promote_paper_trade_reports,
    selection_report_hash,
)
from agency.services.paper_trade_promotion import (
    TRADE_PROMOTION_APPROVAL_NOTE,
    paper_trade_promotion_evaluations,
)

EXPECTED_NOTIONAL = 1000.0


def test_approved_high_conviction_watch_can_be_promoted_to_paper_buy_preview() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )
    risk = build_risk_decisions(
        promoted,
        [source_health()],
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
    )[0].risk_decision
    preview = build_execution_preview(
        risk,
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
        account={"equity": 100000.0},
    ).preview

    assert promoted[0]["final_action"] == "BUY"
    assert TRADE_PROMOTION_REQUIRES_ORDER_APPROVAL_FLAG in promoted[0]["trade_plan"]["notes"]
    assert TRADE_PROMOTION_APPROVAL_NOTE in promoted[0]["trade_plan"]["notes"]
    assert risk["decision"] == "ALLOW"
    assert preview["preview_state"] == "READY"
    assert preview["side"] == "BUY"
    assert preview["notional"] == EXPECTED_NOTIONAL
    assert "order-intent preview" in str(preview["reasons"][0])


def test_paper_trade_promotion_requires_human_approval_and_no_policy_blocks() -> None:
    approved = selection_report(action="WATCH", score=0.95)
    blocked = selection_report(
        action="WATCH",
        score=0.99,
        policy_status="BLOCK",
        policy_reason="missing required evidence",
    )
    review = build_human_review_event(
        cycle_id=str(approved["cycle_id"]),
        ticker=str(approved["ticker"]),
        as_of=str(approved["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(approved),
    )

    promoted = promote_paper_trade_reports(
        [approved, blocked],
        review_states={_key(approved): review},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert promoted[0]["final_action"] == "BUY"
    assert promoted[1]["final_action"] == "WATCH"


def test_operator_manual_advance_promotes_hash_bound_policy_block_with_caution() -> None:
    report = selection_report(
        action="WATCH",
        score=0.95,
        policy_status="BLOCK",
        policy_reason="only one confirmed signal is available",
    )
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )
    advance = build_operator_manual_advance_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        selection_report_hash=selection_report_hash(report),
        override_reason="Paper rehearsal after reviewing the one-signal warning.",
        blocked_reason="selection policy gate blocked: evidence_breadth",
        acknowledged=True,
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        operator_advance_states={_key(report): advance},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )
    risk = build_risk_decisions(
        promoted,
        [source_health()],
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
    )[0].risk_decision
    preview = build_execution_preview(
        risk,
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview

    assert promoted[0]["final_action"] == "BUY"
    assert promoted[0]["policy_gates"][0]["status"] == "WARN"
    assert "Operator manual advance acknowledged" in str(promoted[0]["policy_gates"][0]["reason"])
    assert any("operator manual advance" in note for note in promoted[0]["trade_plan"]["notes"])
    assert risk["decision"] == "ALLOW"
    assert preview["preview_state"] == "READY"
    assert preview["notional"] == EXPECTED_NOTIONAL


def test_operator_manual_advance_requires_current_report_hash() -> None:
    report = selection_report(
        action="WATCH",
        score=0.95,
        policy_status="BLOCK",
        policy_reason="only one confirmed signal is available",
    )
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )
    stale_advance = build_operator_manual_advance_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        selection_report_hash="a" * 64,
        override_reason="This belongs to an older report.",
        acknowledged=True,
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        operator_advance_states={_key(report): stale_advance},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert promoted[0]["final_action"] == "WATCH"


def test_operator_manual_advance_does_not_bypass_broker_or_position_conflicts() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )
    advance = build_operator_manual_advance_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        selection_report_hash=selection_report_hash(report),
        override_reason="Try to advance despite a safety conflict.",
        acknowledged=True,
    )
    config = PaperTradePromotionConfig(
        enabled=True,
        min_source_count=1,
        min_confirmed_signals=1,
    )

    broker_blocked = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        operator_advance_states={_key(report): advance},
        broker_ready=False,
        config=config,
    )
    position_blocked = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        operator_advance_states={_key(report): advance},
        positions=[{"ticker": report["ticker"], "qty": 1.0}],
        broker_ready=True,
        config=config,
    )

    assert broker_blocked[0]["final_action"] == "WATCH"
    assert position_blocked[0]["final_action"] == "WATCH"


def test_approved_watch_with_policy_warning_promotes_to_ready_paper_buy_preview() -> None:
    report = selection_report(
        action="WATCH",
        score=0.95,
        policy_status="WARN",
        policy_reason="one source; user acknowledged caution",
    )
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )
    risk = build_risk_decisions(
        promoted,
        [source_health()],
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
    )[0].risk_decision
    preview = build_execution_preview(
        risk,
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview

    assert promoted[0]["final_action"] == "BUY"
    assert risk["decision"] == "ALLOW"
    assert preview["preview_state"] == "READY"
    assert preview["side"] == "BUY"
    assert preview["notional"] == EXPECTED_NOTIONAL


def test_paper_trade_promotion_default_config_leaves_approved_watch_research_only() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        broker_ready=True,
    )

    assert promoted[0]["final_action"] == "WATCH"
    assert promoted[0]["trade_plan"] is None


def test_paper_trade_promotion_evaluation_explains_approval_ready_watch() -> None:
    report = selection_report(action="WATCH", score=0.95)

    evaluations = paper_trade_promotion_evaluations(
        [report],
        review_states={},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    evaluation = evaluations[_key(report)]
    assert evaluation["state"] == "awaiting_research_approval"
    assert evaluation["can_promote_after_approval"] is True
    assert evaluation["eligible"] is False
    assert "Approve the current research report" in str(evaluation["next_step"])


def test_paper_trade_promotion_evaluation_explains_data_threshold_blocker() -> None:
    report = selection_report(action="WATCH", score=0.95)

    evaluations = paper_trade_promotion_evaluations(
        [report],
        review_states={},
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=99,
        ),
    )

    evaluation = evaluations[_key(report)]
    assert evaluation["state"] == "not_eligible"
    assert evaluation["can_promote_after_approval"] is False
    assert any("confirmed signal" in reason for reason in evaluation["reasons"])


def test_paper_trade_promotion_evaluation_includes_operator_check_diagnostics() -> None:
    report = selection_report(
        action="WATCH",
        score=0.7,
        policy_status="BLOCK",
        policy_reason="source breadth missing",
    )

    evaluations = paper_trade_promotion_evaluations(
        [report],
        review_states={},
        positions=[{"ticker": report["ticker"], "qty": 1.0}],
        open_orders=[{"ticker": report["ticker"], "status": "accepted"}],
        broker_ready=False,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_conviction=0.75,
            min_source_count=2,
            min_confirmed_signals=2,
        ),
    )

    checks = {
        str(check["name"]): check
        for check in evaluations[_key(report)]["checks"]
    }

    assert checks["conviction"]["label"] == "Conviction threshold"
    assert checks["conviction"]["observed"] == "0.70"
    assert checks["conviction"]["required"] == ">= 0.75"
    assert checks["source_count"]["label"] == "Source count"
    assert checks["source_count"]["observed"] == "1"
    assert checks["source_count"]["required"] == ">= 2"
    assert checks["confirmed_signal_count"]["label"] == "Confirmed signals"
    assert checks["confirmed_signal_count"]["observed"] == "1"
    assert checks["confirmed_signal_count"]["required"] == ">= 2"
    assert checks["freshness"]["label"] == "Evidence freshness"
    assert checks["policy_gates"]["label"] == "Selection policy gates"
    assert "evidence_breadth" in str(checks["policy_gates"]["detail"])
    assert checks["human_approval"]["label"] == "Human research approval"
    assert checks["position_conflict"]["label"] == "Position conflict"
    assert checks["open_order_conflict"]["label"] == "Open order conflict"


def test_paper_trade_promotion_skips_existing_positions() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        positions=[{"ticker": report["ticker"], "qty": 1.0}],
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert promoted[0]["final_action"] == "WATCH"


def test_paper_trade_promotion_skips_existing_short_positions() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        positions=[{"ticker": report["ticker"], "qty": -2.0, "side": "short"}],
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert promoted[0]["final_action"] == "WATCH"


def test_paper_trade_promotion_skips_existing_open_orders() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        open_orders=[{"ticker": report["ticker"], "status": "accepted"}],
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert promoted[0]["final_action"] == "WATCH"


def test_paper_trade_promotion_skips_raw_alpaca_symbol_open_orders() -> None:
    report = selection_report(action="WATCH", score=0.95)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )

    promoted = promote_paper_trade_reports(
        [report],
        review_states={_key(report): review},
        open_orders=[{"symbol": report["ticker"], "status": "accepted"}],
        broker_ready=True,
        config=PaperTradePromotionConfig(
            enabled=True,
            min_source_count=1,
            min_confirmed_signals=1,
        ),
    )

    assert promoted[0]["final_action"] == "WATCH"


def _key(report: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(report["cycle_id"]),
        str(report["ticker"]),
        str(report["as_of"]),
    )
