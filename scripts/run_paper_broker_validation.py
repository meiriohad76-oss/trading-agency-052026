from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from agency.api.reports import runtime_selection_reports  # noqa: E402
from agency.api.risk import runtime_risk_decisions  # noqa: E402
from agency.broker import (  # noqa: E402
    AlpacaBrokerClient,
    AlpacaBrokerError,
    AlpacaTradingConfig,
    broker_snapshot,
    build_market_order_payload,
)
from agency.dashboard import paper_review_queue  # type: ignore[attr-defined]  # noqa: E402
from agency.db import MissingDatabaseConfigurationError, get_session  # noqa: E402
from agency.services import (  # noqa: E402
    build_and_persist_human_review_event,
    persist_order_execution_state,
    persist_portfolio_snapshot,
)

DECISIONS = ("APPROVE", "DEFER", "REJECT")
TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}


@dataclass(frozen=True)
class CycleRecord:
    cycle_id: str
    queue_count: int
    decisions: list[dict[str, str]]


async def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = parse_args()
    if args.as_of is None:
        args.as_of = configured_as_of(args.config)
    configure_safe_broker_reads()
    started_at = datetime.now(UTC)
    broker = await verified_broker_summary()
    portfolio_snapshots = [await record_current_portfolio_snapshot()]
    records: list[CycleRecord] = []
    decision_cursor = 0
    for index in range(args.cycles):
        cycle_id = args.cycle_id_prefix + f"-{started_at:%Y%m%dT%H%M%SZ}-{index + 1}"
        cycle_output_root = run_cycle(args, cycle_id=cycle_id, index=index + 1)
        queue = await review_queue_for_cycle(cycle_id, output_root=cycle_output_root)
        if len(queue) < args.min_reviewable_per_cycle:
            raise RuntimeError(f"{cycle_id} produced only {len(queue)} reviewable rows")
        record, decision_cursor = await record_review_decisions(
            cycle_id=cycle_id,
            queue=queue,
            max_decisions=args.review_max_per_cycle,
            decision_cursor=decision_cursor,
        )
        records.append(record)
    trade_test = (
        await run_paper_trade_test(args, started_at=started_at)
        if args.trade_test
        else None
    )
    portfolio_snapshots.append(await record_current_portfolio_snapshot())
    summary = build_summary(
        broker=broker,
        records=records,
        trade_test=trade_test,
        portfolio_snapshots=portfolio_snapshots,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    require_decisions(summary, args.require_all_decisions)
    require_safe_trade_test(summary)
    write_report(summary, args.output_root)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["verdict"] == "paper_broker_validation_passed" else 1


def configure_safe_broker_reads() -> None:
    os.environ["AGENCY_ALPACA_BROKER_ENABLED"] = "true"
    os.environ.setdefault("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets")
    os.environ["AGENCY_BROKER_SUBMIT_ENABLED"] = "false"
    os.environ["AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS"] = "true"
    os.environ["ALPACA_ALLOW_LIVE_TRADING"] = "false"


async def verified_broker_summary() -> dict[str, object]:
    try:
        snapshot = await broker_snapshot()
    except AlpacaBrokerError as exc:
        raise RuntimeError(f"Alpaca paper broker read failed: {exc}") from exc
    account = mapping(snapshot.get("account"))
    if snapshot.get("mode") != "paper":
        raise RuntimeError("broker validation must use Alpaca paper mode")
    if account.get("status") != "ACTIVE":
        raise RuntimeError("Alpaca paper account is not ACTIVE")
    return {
        "provider": snapshot["provider"],
        "mode": snapshot["mode"],
        "connected": snapshot["connected"],
        "status_label": snapshot["status_label"],
        "account_status": account.get("status"),
        "currency": account.get("currency"),
        "equity": account.get("equity"),
        "buying_power": account.get("buying_power"),
        "cash": account.get("cash"),
        "positions": len(sequence(snapshot.get("positions"))),
        "open_orders": len(sequence(snapshot.get("orders"))),
        "gross_exposure_pct": snapshot["gross_exposure_pct"],
    }


async def run_paper_trade_test(
    args: argparse.Namespace,
    *,
    started_at: datetime,
) -> dict[str, object]:
    config = AlpacaTradingConfig.from_env()
    config.require_paper(purpose="paper trade validation")
    client = AlpacaBrokerClient(config)
    ticker = str(args.test_trade_ticker).upper()
    clock = await client.clock()
    cycle_id = f"{args.cycle_id_prefix}-trade-{started_at:%Y%m%dT%H%M%SZ}"
    before_positions = await client.positions()
    open_orders = await client.orders(status="open")
    ticker_open_orders = [
        safe_order(order)
        for order in open_orders
        if str(order.get("ticker", "")).upper() == ticker
    ]
    before_ticker_quantity = position_quantity(ticker, before_positions)
    if ticker_open_orders:
        return refused_existing_open_order_trade_test(
            ticker=ticker,
            notional=float(args.test_trade_notional),
            clock=clock,
            before_ticker_quantity=before_ticker_quantity,
            open_orders_for_ticker=ticker_open_orders,
        )
    if before_ticker_quantity > 0:
        return refused_existing_position_trade_test(
            ticker=ticker,
            notional=float(args.test_trade_notional),
            clock=clock,
            before_ticker_quantity=before_ticker_quantity,
            open_orders_for_ticker=ticker_open_orders,
        )
    buy_order = await client.submit_order(
        build_market_order_payload(
            cycle_id=cycle_id,
            ticker=ticker,
            side="BUY",
            quantity=None,
            notional=float(args.test_trade_notional),
        )
    )
    await persist_validation_order_state(cycle_id=cycle_id, order=buy_order)
    buy_terminal = await wait_for_order_terminal(
        client,
        buy_order,
        timeout_seconds=float(args.trade_timeout_seconds),
        poll_interval_seconds=float(args.trade_poll_interval_seconds),
    )
    await persist_validation_order_state(cycle_id=cycle_id, order=buy_terminal)
    buy_cancelled = False
    cleanup_terminal: dict[str, object] | None = None
    buy_filled_qty = optional_float(buy_terminal.get("filled_qty")) or 0.0
    if order_status(buy_terminal) == "FILLED" or buy_filled_qty > 0:
        cleanup_qty = position_quantity(ticker, await client.positions()) or buy_filled_qty
        if cleanup_qty > 0:
            cleanup_order = await client.submit_order(
                build_market_order_payload(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    side="SELL",
                    quantity=cleanup_qty,
                    notional=None,
                    order_intent_hash=stable_hash(f"{cycle_id}:{ticker}:cleanup"),
                )
            )
            await persist_validation_order_state(cycle_id=cycle_id, order=cleanup_order)
            cleanup_terminal = await wait_for_order_terminal(
                client,
                cleanup_order,
                timeout_seconds=float(args.trade_timeout_seconds),
                poll_interval_seconds=float(args.trade_poll_interval_seconds),
            )
            await persist_validation_order_state(cycle_id=cycle_id, order=cleanup_terminal)
    elif order_status(buy_terminal) not in TERMINAL_ORDER_STATUSES:
        await client.cancel_order(str(buy_order["order_id"]))
        buy_cancelled = True
        buy_terminal = await wait_for_order_terminal(
            client,
            buy_order,
            timeout_seconds=float(args.trade_timeout_seconds),
            poll_interval_seconds=float(args.trade_poll_interval_seconds),
        )
        await persist_validation_order_state(cycle_id=cycle_id, order=buy_terminal)
    after_positions = await client.positions()
    open_orders = await client.orders(status="open")
    ticker_open_orders = [
        safe_order(order)
        for order in open_orders
        if str(order.get("ticker", "")).upper() == ticker
    ]
    final_quantity = position_quantity(ticker, after_positions)
    return {
        "enabled": True,
        "verdict": paper_trade_verdict(
            market_open=bool(clock["is_open"]),
            buy_order=buy_terminal,
            buy_cancelled=buy_cancelled,
            cleanup_order=cleanup_terminal,
            final_ticker_quantity=final_quantity,
            open_order_count=len(ticker_open_orders),
        ),
        "ticker": ticker,
        "notional": float(args.test_trade_notional),
        "market_clock": dict(clock),
        "before_ticker_quantity": before_ticker_quantity,
        "buy_order": safe_order(buy_terminal),
        "buy_cancelled": buy_cancelled,
        "cleanup_order": safe_order(cleanup_terminal) if cleanup_terminal is not None else None,
        "final_ticker_quantity": final_quantity,
        "open_orders_for_ticker": ticker_open_orders,
    }


async def persist_validation_order_state(
    *,
    cycle_id: str,
    order: Mapping[str, object],
) -> None:
    async with get_session() as session:
        await persist_order_execution_state(
            session,
            cycle_id=cycle_id,
            order=order,
            reason="Alpaca paper validation order state",
        )
        await session.commit()


async def record_current_portfolio_snapshot() -> dict[str, object]:
    snapshot = await broker_snapshot()
    try:
        async with get_session() as session:
            payload = await persist_portfolio_snapshot(session, snapshot)
            await session.commit()
    except (
        MissingDatabaseConfigurationError,
        SQLAlchemyError,
        RuntimeError,
        TimeoutError,
        OSError,
    ):
        return {
            "snapshot_id": "not_persisted",
            "captured_at": str(snapshot.get("checked_at") or datetime.now(UTC).isoformat()),
            "position_count": len(sequence(snapshot.get("positions"))),
            "open_order_count": len(sequence(snapshot.get("orders"))),
            "gross_exposure_pct": float(str(snapshot.get("gross_exposure_pct") or 0.0)),
            "persistence_status": "unavailable",
        }
    return {
        "snapshot_id": str(payload["snapshot_id"]),
        "captured_at": str(payload["captured_at"]),
        "position_count": int(str(payload["position_count"])),
        "open_order_count": int(str(payload["open_order_count"])),
        "gross_exposure_pct": float(str(payload["gross_exposure_pct"])),
        "persistence_status": "persisted",
    }


async def wait_for_order_terminal(
    client: AlpacaBrokerClient,
    order: Mapping[str, object],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, object]:
    current = dict(order)
    order_id = str(current["order_id"])
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline and order_status(current) not in TERMINAL_ORDER_STATUSES:
        await asyncio.sleep(poll_interval_seconds)
        current = await client.order(order_id)
    return current


def run_cycle(args: argparse.Namespace, *, cycle_id: str, index: int) -> Path:
    output_root = Path(args.output_root) / f"cycle-{index}"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_live_runtime_cycle.py"),
        "--config",
        str(args.config),
        "--cycle-id",
        cycle_id,
        "--audit-trigger",
        "TEST",
        "--max-tickers",
        str(args.max_tickers),
        "--output-root",
        str(output_root),
        "--no-persist",
        "--no-broker-snapshot",
    ]
    if args.as_of is not None:
        command.extend(["--as-of", str(args.as_of)])
    if args.replay_freshness:
        command.append("--replay-freshness")
    if not args.enable_llm_review:
        command.append("--no-enable-llm-review")
    env = os.environ.copy()
    env["AGENCY_ALPACA_BROKER_ENABLED"] = "false"
    env["AGENCY_BROKER_SUBMIT_ENABLED"] = "false"
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{cycle_id} failed: {completed.stderr.strip()}")
    return output_root


async def review_queue_for_cycle(
    cycle_id: str,
    *,
    output_root: Path | None = None,
) -> Sequence[Mapping[str, object]]:
    if output_root is not None:
        reports = _json_rows(output_root / "selection-reports.json")
        risk_decisions = _json_rows(output_root / "risk-decisions.json")
        if reports and risk_decisions:
            return paper_review_queue(
                reports,
                risk_decisions,
                {"cycle_id": cycle_id},
                review_events=(),
            )
    reports, risk_decisions = await asyncio.gather(
        runtime_selection_reports(limit=200),
        runtime_risk_decisions(limit=200),
    )
    return paper_review_queue(
        reports,
        risk_decisions,
        {"cycle_id": cycle_id},
        review_events=(),
    )


def _json_rows(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, Mapping)]


async def record_review_decisions(
    *,
    cycle_id: str,
    queue: Sequence[Mapping[str, object]],
    max_decisions: int,
    decision_cursor: int,
) -> tuple[CycleRecord, int]:
    rows = queue[:max_decisions]
    decisions: list[dict[str, str]] = []
    async with get_session() as session:
        for row in rows:
            decision = DECISIONS[decision_cursor % len(DECISIONS)]
            await build_and_persist_human_review_event(
                session,
                cycle_id=cycle_id,
                ticker=str(row["ticker"]),
                as_of=str(row["as_of"]),
                decision=decision,
                reviewed_by="paper-broker-validation",
            )
            decisions.append(
                {
                    "ticker": str(row["ticker"]),
                    "as_of": str(row["as_of"]),
                    "decision": decision,
                    "risk_decision": str(row["risk_decision"]),
                }
            )
            decision_cursor += 1
        await session.commit()
    return (
        CycleRecord(cycle_id=cycle_id, queue_count=len(queue), decisions=decisions),
        decision_cursor,
    )


def build_summary(
    *,
    broker: Mapping[str, object],
    records: Sequence[CycleRecord],
    trade_test: Mapping[str, object] | None = None,
    portfolio_snapshots: Sequence[Mapping[str, object]] = (),
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, object]:
    decision_counts = Counter(
        decision["decision"]
        for record in records
        for decision in record.decisions
    )
    verdict = "paper_broker_validation_passed"
    trade_verdict = str((trade_test or {}).get("verdict", ""))
    if trade_test is not None and trade_verdict not in _safe_paper_trade_verdicts():
        verdict = "paper_broker_validation_attention_required"
    return {
        "verdict": verdict,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "broker": dict(broker),
        "paper_trade_test": dict(trade_test) if trade_test is not None else None,
        "portfolio_snapshots": [dict(snapshot) for snapshot in portfolio_snapshots],
        "cycle_count": len(records),
        "review_decision_counts": dict(sorted(decision_counts.items())),
        "cycles": [
            {
                "cycle_id": record.cycle_id,
                "queue_count": record.queue_count,
                "recorded_decisions": record.decisions,
            }
            for record in records
        ],
    }


def require_decisions(summary: Mapping[str, object], required: bool) -> None:
    if not required:
        return
    counts = mapping(summary["review_decision_counts"])
    missing = [decision for decision in DECISIONS if int(str(counts.get(decision, 0))) < 1]
    if missing:
        raise RuntimeError(f"missing required review decisions: {', '.join(missing)}")


def require_safe_trade_test(summary: Mapping[str, object]) -> None:
    trade_test = summary.get("paper_trade_test")
    if trade_test is None:
        return
    verdict = str(mapping(trade_test).get("verdict", ""))
    if verdict not in _safe_paper_trade_verdicts():
        raise RuntimeError(f"paper trade test did not finish safely: {verdict}")


def write_report(summary: Mapping[str, object], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    latest_json = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    latest_markdown = markdown_report(summary)
    (output_root / "paper-broker-validation.json").write_text(
        latest_json,
        encoding="utf-8",
    )
    (output_root / "paper-broker-validation.md").write_text(
        latest_markdown,
        encoding="utf-8",
    )
    run_root = output_root / "runs"
    run_root.mkdir(exist_ok=True)
    run_slug = report_run_slug(summary)
    (run_root / f"{run_slug}.json").write_text(latest_json, encoding="utf-8")
    (run_root / f"{run_slug}.md").write_text(latest_markdown, encoding="utf-8")


def report_run_slug(summary: Mapping[str, object]) -> str:
    started_at = str(summary["started_at"])
    safe_started_at = "".join(char for char in started_at if char.isalnum())
    return f"paper-broker-validation-{safe_started_at}"


def markdown_report(summary: Mapping[str, object]) -> str:
    broker = mapping(summary["broker"])
    lines = [
        "# Alpaca Paper Broker Validation",
        "",
        f"Verdict: `{summary['verdict']}`",
        f"Started: `{summary['started_at']}`",
        f"Finished: `{summary['finished_at']}`",
        "",
        "## Broker Read",
        "",
        f"- Mode: `{broker['mode']}`",
        f"- Account status: `{broker['account_status']}`",
        f"- Equity: `{broker['equity']}`",
        f"- Buying power: `{broker['buying_power']}`",
        f"- Positions: `{broker['positions']}`",
        f"- Open orders: `{broker['open_orders']}`",
        f"- Gross exposure: `{broker['gross_exposure_pct']}`",
    ]
    trade_test = summary.get("paper_trade_test")
    if trade_test is not None:
        trade = mapping(trade_test)
        buy = mapping(trade["buy_order"])
        lines.extend(
            [
                "",
                "## Paper Trade Test",
                "",
                f"- Verdict: `{trade['verdict']}`",
                f"- Ticker: `{trade['ticker']}`",
                f"- Notional: `{trade['notional']}`",
                f"- Market open: `{mapping(trade['market_clock'])['is_open']}`",
                f"- Buy order status: `{buy['status']}`",
                f"- Buy filled quantity: `{buy['filled_qty']}`",
                f"- Buy cancelled: `{trade['buy_cancelled']}`",
                f"- Final ticker quantity: `{trade['final_ticker_quantity']}`",
                f"- Open ticker orders: `{len(sequence(trade['open_orders_for_ticker']))}`",
            ]
        )
        cleanup = trade.get("cleanup_order")
        if cleanup is not None:
            cleanup_order = mapping(cleanup)
            lines.append(f"- Cleanup order status: `{cleanup_order['status']}`")
    snapshots = sequence(summary.get("portfolio_snapshots", []))
    lines.extend(
        [
            "",
            "## Portfolio Snapshots",
            "",
            "| Captured | Positions | Open Orders | Exposure |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for snapshot in snapshots:
        row = mapping(snapshot)
        lines.append(
            f"| `{row['captured_at']}` | {row['position_count']} | "
            f"{row['open_order_count']} | {row['gross_exposure_pct']} |"
        )
    lines.extend(
        [
            "",
            "## Recorded Paper Decisions",
            "",
            "| Cycle | Ticker | Risk | Review |",
            "| --- | --- | --- | --- |",
        ]
    )
    for cycle in sequence(summary["cycles"]):
        payload = mapping(cycle)
        for decision in sequence(payload["recorded_decisions"]):
            row = mapping(decision)
            lines.append(
                f"| `{payload['cycle_id']}` | {row['ticker']} | "
                f"{row['risk_decision']} | {row['decision']} |"
            )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Alpaca paper reads and review cycles.")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--max-tickers", type=int, default=10)
    parser.add_argument("--review-max-per-cycle", type=int, default=3)
    parser.add_argument("--min-reviewable-per-cycle", type=int, default=1)
    parser.add_argument("--cycle-id-prefix", default="paper-broker-validation")
    parser.add_argument("--as-of")
    parser.add_argument("--replay-freshness", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--trade-test", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--test-trade-ticker", default="AAPL")
    parser.add_argument("--test-trade-notional", type=positive_float, default=5.0)
    parser.add_argument("--trade-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--trade-poll-interval-seconds", type=float, default=2.0)
    parser.add_argument(
        "--require-all-decisions",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--enable-llm-review", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "live-refresh.local.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "alpaca-paper-validation",
    )
    return parser.parse_args()


def configured_as_of(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    end = payload.get("end")
    return str(end) if end else None


def paper_trade_verdict(
    *,
    market_open: bool,
    buy_order: Mapping[str, object],
    buy_cancelled: bool,
    cleanup_order: Mapping[str, object] | None,
    final_ticker_quantity: float,
    open_order_count: int,
) -> str:
    buy_status = order_status(buy_order)
    cleanup_status = order_status(cleanup_order or {})
    if buy_status == "FILLED" and cleanup_status == "FILLED" and open_order_count == 0:
        if final_ticker_quantity > 0:
            return "paper_trade_attention_required"
        return "paper_trade_round_trip_filled"
    if buy_status == "FILLED" and final_ticker_quantity > 0 and cleanup_order is not None:
        return "paper_trade_opened_cleanup_pending"
    if (
        buy_cancelled
        and not market_open
        and buy_status == "CANCELED"
        and final_ticker_quantity == 0
        and open_order_count == 0
    ):
        return "paper_order_submit_cancel_verified_market_closed"
    if buy_status == "REJECTED":
        return "paper_trade_rejected"
    return "paper_trade_attention_required"


def refused_existing_position_trade_test(
    *,
    ticker: str,
    notional: float,
    clock: Mapping[str, object],
    before_ticker_quantity: float,
    open_orders_for_ticker: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "enabled": True,
        "verdict": "paper_trade_refused_existing_position",
        "ticker": ticker,
        "notional": notional,
        "market_clock": dict(clock),
        "before_ticker_quantity": before_ticker_quantity,
        "buy_order": safe_order({"ticker": ticker, "status": "NOT_SUBMITTED"}),
        "buy_cancelled": False,
        "cleanup_order": None,
        "final_ticker_quantity": before_ticker_quantity,
        "open_orders_for_ticker": [dict(order) for order in open_orders_for_ticker],
        "detail": (
            "Validation trade was not submitted because this ticker already has a "
            "paper position; closing the test fill could close user-owned paper shares."
        ),
    }


def refused_existing_open_order_trade_test(
    *,
    ticker: str,
    notional: float,
    clock: Mapping[str, object],
    before_ticker_quantity: float,
    open_orders_for_ticker: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "enabled": True,
        "verdict": "paper_trade_refused_existing_open_order",
        "ticker": ticker,
        "notional": notional,
        "market_clock": dict(clock),
        "before_ticker_quantity": before_ticker_quantity,
        "buy_order": safe_order({"ticker": ticker, "status": "NOT_SUBMITTED"}),
        "buy_cancelled": False,
        "cleanup_order": None,
        "final_ticker_quantity": before_ticker_quantity,
        "open_orders_for_ticker": [dict(order) for order in open_orders_for_ticker],
        "detail": (
            "Validation trade was not submitted because this ticker already has an "
            "open paper order; adding another order could change user-owned paper exposure."
        ),
    }


def safe_order(order: Mapping[str, object]) -> dict[str, object]:
    return {
        "order_id_hash": stable_hash(str(order.get("order_id", ""))),
        "client_order_id": str(order.get("client_order_id", "")),
        "ticker": str(order.get("ticker", "")),
        "side": str(order.get("side", "")),
        "type": str(order.get("type", "")),
        "time_in_force": str(order.get("time_in_force", "")),
        "status": order_status(order),
        "qty": optional_float(order.get("qty")),
        "notional": optional_float(order.get("notional")),
        "filled_qty": optional_float(order.get("filled_qty")),
        "filled_avg_price": optional_float(order.get("filled_avg_price")),
        "submitted_at": str(order.get("submitted_at", "")),
        "filled_at": str(order.get("filled_at", "")),
    }


def position_quantity(ticker: str, positions: Sequence[Mapping[str, object]]) -> float:
    for position in positions:
        if str(position.get("ticker", "")).upper() == ticker.upper():
            quantity = optional_float(position.get("qty"))
            return abs(quantity) if quantity is not None else 0.0
    return 0.0


def order_status(order: Mapping[str, object]) -> str:
    return str(order.get("status", "")).upper()


def _safe_paper_trade_verdicts() -> set[str]:
    return {
        "paper_trade_round_trip_filled",
        "paper_order_submit_cancel_verified_market_closed",
        "paper_trade_refused_existing_position",
        "paper_trade_refused_existing_open_order",
    }


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive and finite")
    return parsed


def optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, int | float | str):
        raise TypeError("expected a numeric value")
    return float(value)


def stable_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected a mapping")
    return value


def sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError("expected a sequence")
    return value


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
