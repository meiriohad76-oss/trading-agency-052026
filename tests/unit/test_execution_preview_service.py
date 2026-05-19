from __future__ import annotations

from service_fixtures import selection_report, source_health

from agency.contracts import validate_contract
from agency.services import (
    PortfolioPolicy,
    PaperTradePromotionConfig,
    build_execution_preview,
    build_human_review_event,
    build_risk_decision,
    build_risk_decisions,
    build_order_approval_event,
    paper_trade_promotion_evaluations,
    selection_report_hash,
)
from agency.views.execution import execution_preview_rows

GENERATED_AT = "2026-05-07T09:33:00Z"
EXPECTED_BUY_NOTIONAL = 1000.0
EXPECTED_SELL_QUANTITY = 3.5
EXPECTED_ENTRY_PRICE = 101.0


def test_execution_preview_builds_ready_paper_preview_for_allowed_trade() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")

    result = build_execution_preview(risk_decision, generated_at=GENERATED_AT)

    validate_contract("execution-preview", result.preview)
    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    assert result.preview["preview_state"] == "READY"
    assert result.preview["side"] == "BUY"
    assert result.preview["submit_enabled"] is False
    assert result.lifecycle_event["status"] == "RECORDED"


def test_execution_preview_sizes_buy_order_from_broker_equity_when_submit_enabled() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
    )

    assert result.preview["notional"] == EXPECTED_BUY_NOTIONAL
    assert result.preview["quantity"] is None
    assert result.preview["submit_enabled"] is True
    assert isinstance(result.preview["order_intent_hash"], str)
    assert len(str(result.preview["order_intent_hash"])) == 64


def test_execution_preview_hash_is_stable_and_bound_to_order_intent() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")
    policy = PortfolioPolicy(broker_submit_enabled=True)
    account = {"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0}

    first = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=policy,
        account=account,
    ).preview
    second = build_execution_preview(
        risk_decision,
        generated_at="2026-05-07T09:34:00Z",
        policy=policy,
        account=dict(account),
    ).preview
    resized = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=policy,
        account={"status": "ACTIVE", "equity": 20000.0, "buying_power": 20000.0},
    ).preview

    assert first["order_intent_hash"] == second["order_intent_hash"]
    assert first["order_intent_hash"] != resized["order_intent_hash"]


def test_execution_preview_hash_is_bound_to_full_portfolio_policy() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")
    account = {"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0}

    base = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True, cash_reserve_pct=10.0),
        account=account,
    ).preview
    changed_policy = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True, cash_reserve_pct=20.0),
        account=account,
    ).preview

    assert base["order_intent_hash"] != changed_policy["order_intent_hash"]


def test_order_approval_event_is_hash_bound_to_ready_sized_preview() -> None:
    preview = build_execution_preview(
        _risk_decision(action="BUY", decision_source="ALLOW"),
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
    ).preview

    event = build_order_approval_event(
        preview,
        reviewed_by="tester",
        event_time="2026-05-07T09:35:00Z",
    )

    validate_contract("candidate-lifecycle-event", event)
    assert event["event_type"] == "ORDER_APPROVAL"
    assert event["payload"]["order_intent_hash"] == preview["order_intent_hash"]
    assert event["payload"]["order_intent"]["ticker"] == "AAPL"


def test_execution_preview_blocks_submit_for_blocked_account_or_no_buying_power() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={
            "status": "ACTIVE",
            "equity": 10000.0,
            "buying_power": 0.0,
            "trading_blocked": True,
            "account_blocked": False,
        },
    )

    assert result.preview["notional"] == EXPECTED_BUY_NOTIONAL
    assert result.preview["submit_enabled"] is False


def test_execution_preview_blocks_sell_submit_for_blocked_account() -> None:
    risk_decision = _risk_decision(action="SELL", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={
            "status": "ACCOUNT_BLOCKED",
            "equity": 10000.0,
            "buying_power": 10000.0,
            "trading_blocked": True,
            "account_blocked": True,
        },
        positions=[
            {
                "ticker": "AAPL",
                "qty": EXPECTED_SELL_QUANTITY,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
    )

    assert result.preview["quantity"] == EXPECTED_SELL_QUANTITY
    assert result.preview["submit_enabled"] is False


def test_execution_preview_blocks_opening_order_when_position_or_order_exists() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="ALLOW")

    with_position = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[{"ticker": "AAPL", "qty": 1.0}],
    ).preview
    with_order = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        open_orders=[{"symbol": "AAPL", "status": "accepted"}],
    ).preview

    assert with_position["submit_enabled"] is False
    assert with_order["submit_enabled"] is False


def test_execution_preview_blocks_duplicate_close_order_for_same_ticker() -> None:
    risk_decision = _risk_decision(action="SELL", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[
            {
                "ticker": "AAPL",
                "qty": EXPECTED_SELL_QUANTITY,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
        open_orders=[{"symbol": "AAPL", "side": "sell", "status": "accepted"}],
    )

    assert result.preview["quantity"] == EXPECTED_SELL_QUANTITY
    assert result.preview["submit_enabled"] is False
    assert result.preview["reasons"] == ["active broker order already exists for this ticker"]


def test_execution_preview_sizes_sell_order_from_existing_position() -> None:
    risk_decision = _risk_decision(action="SELL", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[
            {
                "ticker": "AAPL",
                "qty": EXPECTED_SELL_QUANTITY,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
    )

    assert result.preview["quantity"] == EXPECTED_SELL_QUANTITY
    assert result.preview["entry"] == EXPECTED_ENTRY_PRICE
    assert result.preview["submit_enabled"] is True


def test_execution_preview_does_not_sell_a_short_position() -> None:
    risk_decision = _risk_decision(action="SELL", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        positions=[
            {
                "ticker": "AAPL",
                "side": "short",
                "qty": -2.0,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
    )

    assert result.preview["quantity"] is None
    assert result.preview["submit_enabled"] is False


def test_execution_preview_treats_explicit_short_side_as_authoritative() -> None:
    sell_decision = _risk_decision(action="SELL", decision_source="ALLOW")
    cover_decision = _risk_decision(
        action="COVER",
        decision_source="ALLOW",
        policy=PortfolioPolicy(allow_short_trades=True),
    )
    short_position = {
        "ticker": "AAPL",
        "side": "short",
        "qty": 2.0,
        "current_price": EXPECTED_ENTRY_PRICE,
    }

    sell = build_execution_preview(
        sell_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[short_position],
    ).preview
    cover = build_execution_preview(
        cover_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True, allow_short_trades=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[short_position],
    ).preview

    assert sell["quantity"] is None
    assert sell["submit_enabled"] is False
    assert cover["quantity"] == 2.0
    assert cover["submit_enabled"] is True


def test_execution_preview_sizes_cover_order_from_short_position() -> None:
    risk_decision = _risk_decision(
        action="COVER",
        decision_source="ALLOW",
        policy=PortfolioPolicy(allow_short_trades=True),
    )

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True, allow_short_trades=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[
            {
                "ticker": "AAPL",
                "side": "short",
                "qty": -2.0,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
    )

    assert result.preview["quantity"] == 2.0
    assert result.preview["submit_enabled"] is True


def test_execution_preview_allows_cover_submit_when_new_short_policy_disabled() -> None:
    risk_decision = _risk_decision(
        action="COVER",
        decision_source="ALLOW",
        policy=PortfolioPolicy(allow_short_trades=True),
    )

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True, allow_short_trades=False),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[
            {
                "ticker": "AAPL",
                "side": "short",
                "qty": -2.0,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
    )

    assert result.preview["quantity"] == 2.0
    assert result.preview["submit_enabled"] is True


def test_execution_preview_matches_raw_alpaca_symbol_positions() -> None:
    risk_decision = _risk_decision(action="SELL", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[
            {
                "symbol": "AAPL",
                "qty": EXPECTED_SELL_QUANTITY,
                "current_price": EXPECTED_ENTRY_PRICE,
            }
        ],
    )

    assert result.preview["quantity"] == EXPECTED_SELL_QUANTITY
    assert result.preview["submit_enabled"] is True


def test_execution_preview_blocks_sell_without_existing_long_position() -> None:
    risk_decision = _risk_decision(action="SELL", decision_source="ALLOW")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[],
    )

    assert result.preview["preview_state"] == "BLOCKED"
    assert result.preview["quantity"] is None
    assert result.preview["submit_enabled"] is False
    assert result.preview["reasons"] == ["no existing long position is available to sell"]


def test_execution_preview_blocks_cover_without_existing_short_position() -> None:
    risk_decision = _risk_decision(
        action="COVER",
        decision_source="ALLOW",
        policy=PortfolioPolicy(allow_short_trades=True),
    )

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True, allow_short_trades=False),
        account={"status": "ACTIVE", "equity": 10000.0, "buying_power": 10000.0},
        positions=[],
    )

    assert result.preview["preview_state"] == "BLOCKED"
    assert result.preview["quantity"] is None
    assert result.preview["submit_enabled"] is False
    assert result.preview["reasons"] == ["no existing short position is available to cover"]


def test_execution_preview_stays_closed_even_when_policy_allows_submit() -> None:
    risk_decision = _risk_decision(action="WATCH", decision_source="WARN")

    result = build_execution_preview(
        risk_decision,
        generated_at=GENERATED_AT,
        policy=PortfolioPolicy(broker_submit_enabled=True),
    )

    assert result.preview["preview_state"] == "DISABLED"
    assert result.preview["side"] == "NONE"
    assert result.preview["submit_enabled"] is False


def test_execution_preview_row_exposes_watch_promotion_check_diagnostics() -> None:
    report = selection_report(action="WATCH", score=0.95)
    key = _report_key(report)
    review = build_human_review_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        decision="APPROVE",
        selection_report_hash=selection_report_hash(report),
    )
    config = PaperTradePromotionConfig(
        enabled=True,
        min_source_count=1,
        min_confirmed_signals=2,
    )
    evaluations = paper_trade_promotion_evaluations(
        [report],
        review_states={key: review},
        broker_ready=True,
        config=config,
    )
    risk = build_risk_decisions(
        [report],
        [source_health()],
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
    )[0].risk_decision
    preview = build_execution_preview(
        risk,
        policy=PortfolioPolicy(default_position_pct=1.0, broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview

    rows = execution_preview_rows(
        [preview],
        approval_keys={key},
        review_states={key: review},
        promotion_evaluations=evaluations,
    )

    row = rows[0]
    checks = {str(check["name"]): check for check in row["paper_promotion_checks"]}
    assert row["paper_promotion_primary_blocker"] == (
        "confirmed signal count 1 is below required 2."
    )
    assert checks["confirmed_signal_count"]["label"] == "Confirmed signals"
    assert checks["confirmed_signal_count"]["status"] == "BLOCK"
    assert checks["confirmed_signal_count"]["value_detail"] == "1 / required >= 2"
    assert row["paper_promotion_check_summary"] == "11 passed, 1 blocked"
    assert "confirmed signal count 1 is below required 2" in row["reason"]
    assert "research approval is recorded" in row["next_step"].lower()


def test_execution_preview_blocks_when_risk_blocks() -> None:
    risk_decision = _risk_decision(action="BUY", decision_source="BLOCK")

    result = build_execution_preview(risk_decision, generated_at=GENERATED_AT)

    assert result.preview["preview_state"] == "BLOCKED"
    assert result.lifecycle_event["status"] == "BLOCKED"


def test_risk_exits_do_not_consume_new_position_capacity_or_add_exposure() -> None:
    reports = [selection_report(action="SELL"), selection_report(action="COVER")]

    results = build_risk_decisions(
        reports,
        [source_health()],
        policy=PortfolioPolicy(
            max_new_positions_per_cycle=0,
            max_gross_exposure_pct=100.0,
            allow_short_trades=True,
        ),
        current_gross_exposure_pct=95.0,
    )

    decisions = [result.risk_decision for result in results]
    assert [decision["decision"] for decision in decisions] == ["ALLOW", "ALLOW"]
    assert all(decision["projected_gross_exposure_pct"] == 95.0 for decision in decisions)
    assert all(
        _check_status(decision, "cycle_capacity") == "PASS" for decision in decisions
    )
    assert all(
        _check_status(decision, "gross_exposure") == "PASS" for decision in decisions
    )


def test_blocked_opening_trade_does_not_consume_capacity_for_later_clean_buy() -> None:
    blocked = selection_report(action="BUY", policy_status="BLOCK", policy_reason="blocked")
    clean = selection_report(action="BUY")

    results = build_risk_decisions(
        [blocked, clean],
        [source_health()],
        policy=PortfolioPolicy(max_new_positions_per_cycle=1, default_position_pct=10.0),
    )

    decisions = [result.risk_decision for result in results]
    assert decisions[0]["decision"] == "BLOCK"
    assert decisions[1]["decision"] == "ALLOW"
    assert decisions[1]["projected_gross_exposure_pct"] == 10.0


def _risk_decision(
    *,
    action: str,
    decision_source: str,
    policy: PortfolioPolicy | None = None,
) -> dict[str, object]:
    if decision_source == "BLOCK":
        report = selection_report(action=action, policy_status="BLOCK")
    elif decision_source == "WARN":
        report = selection_report(action=action, risk_flags=["source_warning"])
    else:
        report = selection_report(action=action)
    return build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
        policy=policy,
    ).risk_decision


def _check_status(decision: dict[str, object], name: str) -> str:
    checks = decision["checks"]
    if not isinstance(checks, list):
        raise TypeError("checks must be a list")
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return str(check["status"])
    raise AssertionError(f"missing check {name}")


def _report_key(report: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(report["cycle_id"]),
        str(report["ticker"]),
        str(report["as_of"]),
    )
