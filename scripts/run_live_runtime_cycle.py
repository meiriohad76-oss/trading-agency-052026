from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.live_config import RefreshConfigOverrides, load_refresh_config  # noqa: E402
from live_runtime.config import DEFAULT_RUNTIME_SIGNALS, LANE_CONFIGS  # noqa: E402
from live_runtime.cycle import build_live_pit_runtime_cycle  # noqa: E402
from live_runtime.summary import (  # noqa: E402
    build_live_runtime_summary,
    write_live_runtime_summary,
)
from news.consumption import mark_news_consumed  # noqa: E402
from pit.exceptions import DataNotAvailableAt  # noqa: E402
from pit.loader import PITLoader  # noqa: E402
from pit.manifest import ManifestRegistry  # noqa: E402

from agency.broker import AlpacaBrokerError, broker_snapshot  # noqa: E402
from agency.db import MissingDatabaseConfigurationError, get_session  # noqa: E402
from agency.runtime import list_candidate_lifecycle_events  # noqa: E402
from agency.runtime.artifact_fallbacks import runtime_lifecycle_event_artifacts  # noqa: E402
from agency.services import (  # noqa: E402
    DEFAULT_AUTO_LLM_REVIEW_MAX_CANDIDATES,
    OpenAILlmReviewProvider,
    PaperTradePromotionConfig,
    RuntimeCycleResult,
    build_runtime_cycle_from_evidence_packs,
    persist_runtime_cycle,
    review_evidence_packs,
)

CANONICAL_RUNTIME_OUTPUT_ROOT = ROOT / "research" / "results" / "latest-live-runtime-cycle"
DEFAULT_NEWS_CONSUMPTION_LEDGER_PATH = ROOT / "research" / "data" / "state" / "news_rss_consumed.json"


async def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = _parse_args()
    config = load_refresh_config(args.config, repo_root=ROOT) if args.config else None
    lanes = _runtime_signals(args, config)
    as_of = _runtime_as_of(
        args=args,
        config=config,
        lanes=lanes,
    )
    tickers = _tickers(
        args,
        config,
        as_of=as_of,
        manifest_root=args.manifest_root,
        parquet_root=args.parquet_root,
    )
    max_tickers = _max_tickers(args, config)
    generated_at = datetime.now(UTC)
    freshness_checked_at = _freshness_checked_at(as_of, replay=args.replay_freshness)
    broker = await _broker_snapshot_if_enabled(enabled=args.broker_snapshot)
    base_cycle = cast(
        RuntimeCycleResult,
        build_live_pit_runtime_cycle(
            cycle_id=args.cycle_id or _cycle_id(as_of, generated_at),
            as_of=as_of,
            tickers=set(tickers[:max_tickers]),
            manifest_root=args.manifest_root,
            parquet_root=args.parquet_root,
            lanes=lanes,
            generated_at=generated_at,
            freshness_checked_at=freshness_checked_at,
            enable_llm_review=False,
            news_consumption_ledger_path=(
                args.news_consumption_ledger if args.news_consumption else None
            ),
        ),
    )
    llm_reviewed = 0
    llm_reviews: Mapping[str, Mapping[str, object]] | None = None
    llm_lifecycle_events: list[Mapping[str, object]] = []
    llm_prompt_audits: list[Mapping[str, object]] = []
    provider = OpenAILlmReviewProvider.from_env(enabled=args.enable_llm_review)
    if provider.enabled:
        llm_batch = await review_evidence_packs(
            cast(list[Mapping[str, object]], base_cycle.evidence_packs),
            provider=provider,
            max_reviews=args.llm_review_max_candidates,
            include_no_trade_with_evidence=args.llm_review_include_no_trade,
        )
        llm_reviewed = len(llm_batch.reviewed_tickers)
        llm_reviews = llm_batch.reviews_by_ticker
        llm_lifecycle_events = list(llm_batch.lifecycle_events)
        llm_prompt_audits = list(llm_batch.prompt_audits)
    promotion_config = PaperTradePromotionConfig.from_env()
    review_states = await _human_review_states_for_cycle(
        cycle_id=base_cycle.cycle_id,
        report_count=len(base_cycle.selection_reports),
    )
    cycle = build_runtime_cycle_from_evidence_packs(
        cycle_id=base_cycle.cycle_id,
        as_of=base_cycle.as_of,
        generated_at=base_cycle.generated_at,
        source_health=base_cycle.source_health,
        evidence_packs=base_cycle.evidence_packs,
        current_gross_exposure_pct=_broker_gross_exposure_pct(broker),
        account=_broker_account(broker),
        positions=_broker_positions(broker),
        open_orders=_broker_orders(broker),
        pending_opening_order_exposure_pct=_broker_pending_opening_order_exposure_pct(broker),
        llm_reviews=llm_reviews,
        llm_lifecycle_events=llm_lifecycle_events,
        llm_prompt_audits=llm_prompt_audits,
        paper_trade_review_states=review_states,
        paper_trade_broker_ready=_broker_ready_for_paper_promotion(broker),
        paper_trade_promotion_config=promotion_config,
    )
    if args.persist:
        try:
            async with get_session() as session:
                await persist_runtime_cycle(session, cycle, audit_trigger=args.audit_trigger)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            summary = build_live_runtime_summary(cycle, persisted=False)
            summary["persistence_error"] = f"{type(exc).__name__}: {exc}"
            if _should_write_persistence_failure_artifacts(args.output_root):
                write_live_runtime_summary(summary, args.output_root)
                write_runtime_cycle_artifacts(cycle, args.output_root)
            print(
                f"Live runtime cycle {summary['verdict']}; "
                f"llm_reviewed={llm_reviewed}; wrote {args.output_root}; "
                f"persistence_failed={summary['persistence_error']}"
            )
            return 1
        summary = build_live_runtime_summary(cycle, persisted=True)
    else:
        summary = build_live_runtime_summary(cycle, persisted=False)
    _finalize_successful_cycle_outputs(
        cycle=cycle,
        summary=summary,
        output_root=args.output_root,
        news_consumption_ledger_path=(
            args.news_consumption_ledger
            if args.persist and args.news_consumption
            else None
        ),
    )
    print(
        f"Live runtime cycle {summary['verdict']}; "
        f"llm_reviewed={llm_reviewed}; wrote {args.output_root}"
    )
    return 0


def write_runtime_cycle_artifacts(cycle: RuntimeCycleResult, output_root: Path) -> None:
    """Write inspectable no-secret runtime artifacts next to the compact summary."""
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "source-health.json": cycle.source_health,
        "evidence-packs.json": cycle.evidence_packs,
        "selection-reports.json": cycle.selection_reports,
        "risk-decisions.json": cycle.risk_decisions,
        "execution-previews.json": cycle.execution_previews,
        "prompt-audits.json": cycle.prompt_audits,
    }
    for filename, payload in artifacts.items():
        (output_root / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _finalize_successful_cycle_outputs(
    *,
    cycle: RuntimeCycleResult,
    summary: Mapping[str, object],
    output_root: Path,
    news_consumption_ledger_path: Path | None,
) -> None:
    write_live_runtime_summary(dict(summary), output_root)
    write_runtime_cycle_artifacts(cycle, output_root)
    if news_consumption_ledger_path is None:
        return
    mark_news_consumed(
        news_consumption_ledger_path,
        cycle_id=cycle.cycle_id,
        as_of=cycle.as_of,
        used_at=cycle.generated_at,
        items=cycle.news_consumption_items,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a PIT-backed local paper runtime cycle.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research/config/live-refresh.local.json",
    )
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--signal", choices=sorted(LANE_CONFIGS), action="append")
    parser.add_argument(
        "--runtime-universe",
        choices=("configured", "active"),
        help="Use configured tickers or active PIT universe membership.",
    )
    parser.add_argument("--as-of", type=_date)
    parser.add_argument(
        "--replay-freshness",
        action="store_true",
        help="Evaluate source freshness at the as-of date for PIT replay testing.",
    )
    parser.add_argument("--cycle-id")
    parser.add_argument(
        "--audit-trigger",
        choices=("MANUAL", "SCHEDULED", "API", "SYSTEM", "TEST"),
        default="MANUAL",
    )
    parser.add_argument("--max-tickers", type=int)
    parser.add_argument("--enable-llm-review", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--broker-snapshot",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Include a broker snapshot in the runtime cycle when broker env is enabled. "
            "Use --no-broker-snapshot for no-persist validation cycles that must not "
            "reload .env broker settings."
        ),
    )
    parser.add_argument(
        "--llm-review-max-candidates",
        type=int,
        default=_env_int(
            "AGENCY_LLM_REVIEW_MAX_CANDIDATES",
            default=DEFAULT_AUTO_LLM_REVIEW_MAX_CANDIDATES,
        ),
    )
    parser.add_argument("--llm-review-include-no-trade", action="store_true")
    parser.add_argument("--persist", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--news-consumption",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Filter RSS/news rows already used by previous live cycles and mark "
            "newly used rows after a persisted cycle succeeds."
        ),
    )
    parser.add_argument(
        "--news-consumption-ledger",
        type=Path,
        default=DEFAULT_NEWS_CONSUMPTION_LEDGER_PATH,
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=ROOT / "research" / "data" / "manifests",
    )
    parser.add_argument(
        "--parquet-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=CANONICAL_RUNTIME_OUTPUT_ROOT,
    )
    return parser.parse_args()


def _tickers(
    args: argparse.Namespace,
    config: RefreshConfigOverrides | None,
    *,
    as_of: date,
    manifest_root: Path,
    parquet_root: Path,
) -> list[str]:
    values = list(args.ticker)
    if values:
        return _normalized_tickers(values)
    mode = _runtime_universe_mode(args, config)
    if mode == "active":
        return _active_universe_tickers(
            as_of,
            manifest_root=manifest_root,
            parquet_root=parquet_root,
        )
    if config is not None:
        values = list(config.tickers)
    if values:
        return _normalized_tickers(values)
    return _active_universe_tickers(
        as_of,
        manifest_root=manifest_root,
        parquet_root=parquet_root,
    )


def _normalized_tickers(values: list[str]) -> list[str]:
    return sorted({ticker.upper() for ticker in values})


def _runtime_universe_mode(
    args: argparse.Namespace,
    config: RefreshConfigOverrides | None,
) -> str:
    value = getattr(args, "runtime_universe", None)
    if value is None and config is not None:
        value = config.runtime_universe
    if value is None:
        return "configured"
    normalized = str(value).strip().lower()
    if normalized not in {"configured", "active"}:
        raise ValueError("runtime_universe must be 'configured' or 'active'")
    return normalized


def _active_universe_tickers(
    as_of: date,
    *,
    manifest_root: Path,
    parquet_root: Path,
) -> list[str]:
    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=date.today,
    )
    try:
        return sorted(loader.universe_members(as_of))
    except DataNotAvailableAt as exc:
        raise ValueError(
            "provide --ticker, configured tickers, or a readable universe_membership dataset"
        ) from exc


def _max_tickers(args: argparse.Namespace, config: RefreshConfigOverrides | None) -> int:
    value = getattr(args, "max_tickers", None)
    if value is None and config is not None:
        value = config.runtime_max_tickers
    if value is None:
        value = _env_int("AGENCY_RUNTIME_MAX_TICKERS", default=250)
    if not isinstance(value, int):
        raise TypeError("max_tickers must be an integer")
    if value < 1:
        raise ValueError("max_tickers must be >= 1")
    return value


def _runtime_signals(
    args: argparse.Namespace,
    config: RefreshConfigOverrides | None,
) -> tuple[str, ...]:
    if args.signal:
        return tuple(args.signal)
    if config is not None and config.runtime_signals:
        return tuple(config.runtime_signals)
    return DEFAULT_RUNTIME_SIGNALS


def _runtime_as_of(
    *,
    args: argparse.Namespace,
    config: RefreshConfigOverrides | None,
    lanes: tuple[str, ...],
) -> date:
    as_of = getattr(args, "as_of", None)
    if isinstance(as_of, date):
        return as_of
    # Keep the default runtime date aligned with the UTC clock passed into
    # PITLoader below. On machines east of UTC, local midnight can otherwise
    # choose tomorrow while the PIT loader still rejects that date as lookahead.
    today = datetime.now(UTC).date()
    if (
        config is not None
        and config.end is not None
        and getattr(args, "replay_freshness", False)
    ):
        return min(config.end, today)
    manifest_dates: list[date] = []
    registry = ManifestRegistry(args.manifest_root, args.parquet_root)
    for lane in lanes:
        try:
            manifest = registry.require(LANE_CONFIGS[lane].dataset)
        except DataNotAvailableAt:
            continue
        manifest_dates.append(min(manifest.max_timestamp_as_of.date(), today))
    if manifest_dates:
        return max(manifest_dates)
    return today


def _should_write_persistence_failure_artifacts(output_root: Path) -> bool:
    """Keep the canonical latest runtime summary on the last persisted cycle."""
    try:
        return output_root.resolve(strict=False) != CANONICAL_RUNTIME_OUTPUT_ROOT.resolve(
            strict=False
        )
    except OSError:
        return True


def _cycle_id(as_of: date, generated_at: datetime) -> str:
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return f"live-pit-{as_of.isoformat()}-{stamp}"


def _freshness_checked_at(as_of: date, *, replay: bool) -> datetime | None:
    if not replay:
        return None
    return datetime.combine(as_of, time.min, tzinfo=UTC)


def _date(value: str) -> date:
    return date.fromisoformat(value)


async def _broker_snapshot_if_enabled(*, enabled: bool = True) -> Mapping[str, object] | None:
    if not enabled:
        return None
    if not _env_bool("AGENCY_ALPACA_BROKER_ENABLED"):
        return None
    try:
        return await broker_snapshot()
    except AlpacaBrokerError as exc:
        raise RuntimeError(f"Alpaca paper broker snapshot failed: {exc}") from exc


async def _human_review_states_for_cycle(
    *,
    cycle_id: str,
    report_count: int,
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    limit = max(report_count * 20, 100)
    try:
        async with get_session() as session:
            events = await list_candidate_lifecycle_events(
                session,
                cycle_id=cycle_id,
                limit=limit,
            )
    except (
        MissingDatabaseConfigurationError,
        OSError,
        RuntimeError,
        SQLAlchemyError,
        TypeError,
    ):
        events = runtime_lifecycle_event_artifacts(cycle_id=cycle_id, limit=limit)
    return _human_review_state_index(events)


def _human_review_state_index(
    events: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    indexed: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for event in sorted(events, key=lambda item: str(item.get("event_time", "")), reverse=True):
        if str(event.get("event_type")) != "HUMAN_REVIEW":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        key = (
            str(event.get("cycle_id", "")),
            str(event.get("ticker", "")).upper(),
            str(payload.get("as_of", "")),
        )
        if all(key) and key not in indexed:
            indexed[key] = event
    return indexed


def _broker_ready_for_paper_promotion(broker: Mapping[str, object] | None) -> bool:
    if broker is None:
        return False
    if broker.get("connected") is not True or str(broker.get("mode")) != "paper":
        return False
    account = _broker_account(broker)
    if account is None:
        return False
    return not (
        account.get("trading_blocked") is True
        or account.get("account_blocked") is True
    )


def _broker_account(broker: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if broker is None:
        return None
    account = broker.get("account")
    return cast(Mapping[str, object], account) if isinstance(account, Mapping) else None


def _broker_positions(broker: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    if broker is None:
        return []
    positions = broker.get("positions", [])
    if not isinstance(positions, list):
        return []
    return [cast(Mapping[str, object], item) for item in positions if isinstance(item, Mapping)]


def _broker_orders(broker: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    if broker is None:
        return []
    orders = broker.get("orders", [])
    if not isinstance(orders, list):
        return []
    return [cast(Mapping[str, object], item) for item in orders if isinstance(item, Mapping)]


def _broker_gross_exposure_pct(broker: Mapping[str, object] | None) -> float:
    if broker is None:
        return 0.0
    value = broker.get("gross_exposure_pct", 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def _broker_pending_opening_order_exposure_pct(broker: Mapping[str, object] | None) -> float:
    if broker is None:
        return 0.0
    account = _broker_account(broker)
    if account is None:
        return 0.0
    equity_value = account.get("equity", 0.0)
    equity = float(equity_value) if isinstance(equity_value, int | float) else 0.0
    if equity <= 0:
        return 0.0
    positions = _broker_positions(broker)
    pending_notional = sum(
        _broker_order_notional(order)
        for order in _broker_orders(broker)
        if _broker_order_is_opening(order, positions=positions)
    )
    return round(pending_notional / equity * 100.0, 6)


def _broker_order_is_opening(
    order: Mapping[str, object],
    *,
    positions: Sequence[Mapping[str, object]],
) -> bool:
    side = str(order.get("side", "")).upper()
    status = str(order.get("status", "")).upper()
    if status in {"CANCELED", "EXPIRED", "FILLED", "REJECTED"}:
        return False
    position = _broker_position_for_order(order, positions)
    if side == "BUY":
        return not _broker_position_is_short(position)
    if side == "SELL":
        return not _broker_position_is_long(position)
    return side == "SHORT"


def _broker_order_notional(order: Mapping[str, object]) -> float:
    notional = order.get("notional")
    if isinstance(notional, int | float):
        return abs(float(notional))
    quantity = order.get("qty")
    price = order.get("limit_price") or order.get("stop_price") or order.get("filled_avg_price")
    if isinstance(quantity, int | float) and isinstance(price, int | float):
        return abs(float(quantity) * float(price))
    return 0.0


def _broker_position_for_order(
    order: Mapping[str, object],
    positions: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    ticker = str(order.get("ticker") or order.get("symbol") or "").upper()
    if not ticker:
        return None
    return next(
        (
            position
            for position in positions
            if str(position.get("ticker") or position.get("symbol") or "").upper() == ticker
        ),
        None,
    )


def _broker_position_is_long(position: Mapping[str, object] | None) -> bool:
    if position is None:
        return False
    side = str(position.get("side", "")).upper()
    if side:
        return side == "LONG"
    quantity = position.get("qty", 0.0)
    return isinstance(quantity, int | float) and float(quantity) > 0


def _broker_position_is_short(position: Mapping[str, object] | None) -> bool:
    if position is None:
        return False
    side = str(position.get("side", "")).upper()
    if side:
        return side == "SHORT"
    quantity = position.get("qty", 0.0)
    return isinstance(quantity, int | float) and float(quantity) < 0


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
