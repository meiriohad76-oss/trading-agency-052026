from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
from live_runtime.config import DEFAULT_RUNTIME_SIGNALS
from live_runtime.cycle import build_live_pit_runtime_cycle, required_runtime_datasets
from live_runtime.summary import build_live_runtime_summary, summary_to_markdown
from pit.manifest import DatasetName
from pit_fixtures import loader_with, price

GENERATED_AT = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)  # 22:00 UTC = after bar publication window
EXPECTED_PRICE_SIGNAL_COUNT = 2
EXPECTED_MARKET_FLOW_SIGNAL_COUNT = 8
MIDDAY_GENERATED_AT = datetime(2026, 5, 6, 14, 30, tzinfo=UTC)
WEEKEND_GENERATED_AT = datetime(2026, 5, 9, 10, 30, tzinfo=UTC)
TECHNICAL_PRICE_ROWS = 60
TECHNICAL_PRICE_STEP = 0.8


def test_build_live_pit_runtime_cycle_from_price_manifest(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 5), 100.0, date(2026, 5, 5), "a1"),
                    price("AAPL", date(2026, 5, 6), 110.0, date(2026, 5, 6), "a2"),
                    price("MSFT", date(2026, 5, 5), 100.0, date(2026, 5, 5), "m1"),
                    price("MSFT", date(2026, 5, 6), 90.0, date(2026, 5, 6), "m2"),
                ]
            )
        },
    )
    # Set manifest timestamp to today's date (same as generated_at date) so that
    # effective_freshness_timestamp returns checked_at (after bar publication window).
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-06T22:00:00+00:00",
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )

    assert [report["ticker"] for report in cycle.selection_reports] == ["AAPL", "MSFT"]
    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert (
        build_live_runtime_summary(cycle, persisted=False)["signal_count"]
        == EXPECTED_PRICE_SIGNAL_COUNT
    )


def test_current_date_daily_price_manifest_becomes_healthy_after_bar_publication(
    tmp_path: Path,
) -> None:
    """After 21:15 UTC, today's bars are published and source health becomes HEALTHY."""
    after_close = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)  # 22:00 UTC, after bar publication
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 5), 100.0, date(2026, 5, 5), "a1"),
                    price("AAPL", date(2026, 5, 6), 110.0, date(2026, 5, 6), "a2"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=after_close,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert signals
    assert {signal["freshness"] for signal in signals} == {"FRESH"}


def test_recent_daily_price_manifest_stays_fresh_across_weekend(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 7), 100.0, date(2026, 5, 7), "a1"),
                    price("AAPL", date(2026, 5, 8), 110.0, date(2026, 5, 8), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-08T00:00:00+00:00",
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-weekend",
        as_of=date(2026, 5, 8),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=WEEKEND_GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert signals
    assert {signal["freshness"] for signal in signals} == {"FRESH"}


def test_old_daily_price_manifest_still_goes_stale(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 1), 100.0, date(2026, 5, 1), "a1"),
                    price("AAPL", date(2026, 5, 2), 110.0, date(2026, 5, 2), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-02T00:00:00+00:00",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-old-prices",
        as_of=date(2026, 5, 2),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=WEEKEND_GENERATED_AT,
    )

    assert cycle.source_health[0]["status"] == "STALE"


def test_weekday_stale_daily_price_manifest_does_not_get_intraday_freshness(
    tmp_path: Path,
) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 8), 100.0, date(2026, 5, 8), "a1"),
                    price("AAPL", date(2026, 5, 11), 110.0, date(2026, 5, 11), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-11T00:00:00+00:00",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-weekday-stale-prices",
        as_of=date(2026, 5, 11),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=datetime(2026, 5, 13, 14, 30, tzinfo=UTC),
    )

    assert cycle.source_health[0]["status"] == "STALE"


def test_live_pit_runtime_cycle_does_not_add_sector_etfs_as_candidates(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("SPY", date(2026, 5, 5), 100.0, date(2026, 5, 5), "s1"),
                    price("SPY", date(2026, 5, 6), 101.0, date(2026, 5, 6), "s2"),
                    price("XLK", date(2026, 5, 5), 100.0, date(2026, 5, 5), "x1"),
                    price("XLK", date(2026, 5, 6), 102.0, date(2026, 5, 6), "x2"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("sector_momentum",),
        generated_at=GENERATED_AT,
    )

    assert [report["ticker"] for report in cycle.selection_reports] == ["AAPL"]
    assert build_live_runtime_summary(cycle, persisted=False)["signal_count"] == 0


def test_live_runtime_summary_marks_unhealthy_sources_blocked() -> None:
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=Path("missing-manifests"),
        parquet_root=Path("missing-parquet"),
        lanes=("fundamentals",),
        generated_at=GENERATED_AT,
    )

    summary = build_live_runtime_summary(cycle, persisted=False)
    markdown = summary_to_markdown(summary)

    assert summary["verdict"] == "blocked_or_context_only_due_to_source_health"
    assert summary["source_status_counts"] == {"UNAVAILABLE": 1}
    assert "| UNAVAILABLE | 1 |" in markdown


def test_live_runtime_summary_source_health_masks_watch_verdict(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-stale-watch",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        source_health=[{**cycle.source_health[0], "status": "STALE"}],
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "final_action": "WATCH",
                "llm_review": {"action": "WATCH"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["verdict"] == "blocked_or_context_only_due_to_source_health"


def test_live_runtime_summary_blocks_any_non_healthy_source_status(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-degraded-watch",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        source_health=[{**cycle.source_health[0], "status": "DEGRADED"}],
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "final_action": "WATCH",
                "llm_review": {"action": "WATCH"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["verdict"] == "blocked_or_context_only_due_to_source_health"


def test_live_runtime_summary_counts_missing_llm_action_as_unknown(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-llm-missing-action",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "llm_review": {"reason": "stubbed or failed review"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["llm_review_counts"] == {"UNKNOWN": 1}


def test_live_runtime_summary_counts_prompt_audit_payloads(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-llm-audit",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        prompt_audits=[
            {
                "payload": {
                    "response_status": "succeeded",
                    "llm_action": "AGREE",
                }
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)
    markdown = summary_to_markdown(summary)

    assert summary["llm_prompt_status_counts"] == {"succeeded": 1}
    assert summary["llm_prompt_action_counts"] == {"AGREE": 1}
    assert "| succeeded | 1 |" in markdown
    assert "| AGREE | 1 |" in markdown


def test_default_runtime_signals_are_stocks_only() -> None:
    datasets = required_runtime_datasets(DEFAULT_RUNTIME_SIGNALS)

    assert DatasetName.UNUSUAL_ACTIVITY_ALERTS not in datasets
    assert DatasetName.OPTIONS_CHAINS not in datasets


def test_optional_options_lanes_require_options_chain_dataset() -> None:
    datasets = required_runtime_datasets(("options_anomaly", "options_flow"))

    assert datasets == {DatasetName.OPTIONS_CHAINS}


def test_options_signal_freshness_uses_ticker_snapshot_timestamp(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.OPTIONS_CHAINS: pl.DataFrame(
                [
                    option_chain("AAPL", "call", 100, "2026-05-06T13:31:00+00:00"),
                    option_chain("AAPL", "put", 20, "2026-05-06T13:31:00+00:00"),
                    option_chain("MSFT", "call", 20, "2026-05-06T13:45:00+00:00"),
                    option_chain("MSFT", "put", 100, "2026-05-06T13:45:00+00:00"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-options",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("options_flow",),
        generated_at=MIDDAY_GENERATED_AT,
    )
    signals = {
        signal["ticker"]: signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    }

    assert signals["AAPL"]["provenance"]["timestamp_as_of"] == "2026-05-06T13:31:00+00:00"
    assert signals["MSFT"]["provenance"]["timestamp_as_of"] == "2026-05-06T13:45:00+00:00"


def test_optional_market_flow_lanes_require_stock_trades_dataset() -> None:
    datasets = required_runtime_datasets(
        (
            "buy_sell_pressure",
            "block_trade_pressure",
            "unusual_trade_activity",
            "pre_market_unusual_activity",
            "market_flow_trend",
        )
    )

    assert datasets == {DatasetName.STOCK_TRADES}


def test_optional_subscription_thesis_lane_requires_subscription_email_dataset() -> None:
    datasets = required_runtime_datasets(("subscription_thesis",))

    assert datasets == {DatasetName.SUBSCRIPTION_EMAILS}


def test_live_pit_runtime_cycle_can_emit_technical_analysis_signals(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price(
                        "AAPL",
                        date(2026, 5, 6) - timedelta(days=TECHNICAL_PRICE_ROWS - offset),
                        100.0 + TECHNICAL_PRICE_STEP * offset,
                        date(2026, 5, 6),
                        f"aapl-technical-{offset}",
                    )
                    for offset in range(TECHNICAL_PRICE_ROWS)
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-technical",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("technical_analysis",),
        generated_at=GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert signals[0]["lane"] == "technical_analysis"
    assert "Technical analysis: AAPL" in str(signals[0]["summary"])
    assert "technical_analysis_bullish" in signals[0]["reason_codes"]


def test_live_pit_runtime_cycle_can_emit_market_flow_signals(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.STOCK_TRADES: pl.DataFrame(
                [
                    stock_trade("AAPL", 100_000.0, 1, True),
                    stock_trade("MSFT", 100_000.0, -1, True),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-flow",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=(
            "buy_sell_pressure",
            "unusual_trade_activity",
            "pre_market_unusual_activity",
            "market_flow_trend",
        ),
        generated_at=GENERATED_AT,
    )
    summary = build_live_runtime_summary(cycle, persisted=False)

    assert cycle.source_health[0]["source"] == "massive-stock-trades"
    assert summary["signal_count"] == EXPECTED_MARKET_FLOW_SIGNAL_COUNT


def test_live_pit_runtime_cycle_keeps_subscription_thesis_context_only(
    tmp_path: Path,
) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.SUBSCRIPTION_EMAILS: pl.DataFrame(
                [
                    subscription_email(
                        "AAPL",
                        "BULLISH",
                        "Linked content thesis: constructive context for AAPL.",
                    )
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-thesis",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("subscription_thesis",),
        generated_at=GENERATED_AT,
    )
    pack = cycle.evidence_packs[0]
    report = cycle.selection_reports[0]

    assert len(pack["context_signals"]) == 1
    assert pack["actionable_signals"] == []
    assert pack["data_quality"]["source_count"] == 0
    assert report["final_action"] == "NO_TRADE"
    assert "Subscription article thesis" in str(pack["context_signals"][0]["summary"])


def test_replay_freshness_caps_future_manifest_timestamps(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.SEC_FORM4: pl.DataFrame(
                [
                    {
                        "ticker": "AAPL",
                        "transaction_date": date(2026, 1, 1),
                        "security_title": "Common Stock",
                        "transaction_code": "P",
                        "shares": 10.0,
                        "price": 100.0,
                        "filing_url": "https://sec.test/form4",
                        "source": "sec",
                        "source_tier": "OFFICIAL_FILING",
                        "source_id": "form4-a",
                        "source_url": "https://sec.test",
                        "timestamp_observed": GENERATED_AT,
                        "timestamp_as_of": date(2026, 1, 1),
                        "freshness": "FRESH",
                        "confidence": 1.0,
                        "verification_level": "CONFIRMED",
                    }
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-replay",
        as_of=date(2025, 12, 31),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("insider",),
        generated_at=GENERATED_AT,
        freshness_checked_at=datetime(2025, 12, 31, tzinfo=UTC),
    )

    assert cycle.source_health[0]["status"] == "HEALTHY"


def stock_trade(
    ticker: str,
    notional: float,
    direction: int,
    block: bool,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": date(2026, 5, 6),
        "trade_ts": "2026-05-06T13:30:00Z",
        "price": 100.0,
        "size": notional / 100.0,
        "notional": notional,
        "direction": direction,
        "signed_volume": direction * notional / 100.0,
        "signed_notional": direction * notional,
        "session": "REGULAR",
        "is_block_trade": block,
        "is_off_exchange": block,
        "sequence_number": 1,
        "source_id": f"{ticker}-flow",
        "timestamp_as_of": date(2026, 5, 6),
    }


def option_chain(
    ticker: str,
    option_type: str,
    volume: int,
    timestamp_as_of: str,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "snapshot_date": date(2026, 5, 6),
        "expiration": date(2026, 6, 19),
        "option_type": option_type,
        "strike": 100.0,
        "volume": volume,
        "open_interest": volume * 2,
        "implied_volatility": 0.30,
        "source": "fixture",
        "source_tier": "MARKET_DATA",
        "source_id": f"{ticker}-{option_type}",
        "source_url": None,
        "timestamp_observed": GENERATED_AT,
        "timestamp_as_of": timestamp_as_of,
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "INFERRED",
    }


def subscription_email(ticker: str, direction: str, summary: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "service": "seeking_alpha",
        "services": ["seeking_alpha"],
        "event_type": "sa_analyst_article",
        "event_types": ["sa_analyst_article"],
        "direction": direction,
        "title": "Safe hashed title only",
        "source_refs": [],
        "source": "seeking_alpha-email",
        "source_tier": "PAID_SUB_EMAIL",
        "source_id": f"{ticker}-subscription-thesis",
        "source_url": "https://seekingalpha.com/article/fixture",
        "message_id_hash": f"{ticker}-message",
        "sender_domain": "email.seekingalpha.com",
        "received_at": date(2026, 5, 6),
        "linked_content_status": "article_analyzed",
        "linked_content_url": "https://seekingalpha.com/article/fixture",
        "linked_content_title_hash": "titlehash",
        "linked_content_summary": summary,
        "timestamp_observed": GENERATED_AT,
        "timestamp_as_of": date(2026, 5, 6),
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }


def _set_manifest_max_as_of(
    manifest_root: Path,
    dataset: DatasetName,
    timestamp: str,
) -> None:
    manifest_path = manifest_root / f"{dataset.value}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["max_timestamp_as_of"] = timestamp
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
