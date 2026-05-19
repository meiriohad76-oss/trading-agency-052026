from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LaneCadence = Literal["continuous", "event_driven", "daily", "scheduled", "backlog"]


@dataclass(frozen=True)
class SignalLanePolicy:
    lane: str
    dataset: str
    cadence: LaneCadence
    update_window: str
    extraction_rule: str
    operational_note: str


SIGNAL_LANE_POLICIES: dict[str, SignalLanePolicy] = {
    "activity_alerts": SignalLanePolicy(
        "activity_alerts",
        "unusual_activity_alerts",
        "continuous",
        "5-15m when provider/email source is enabled",
        "append only new provider/email alerts",
        "Paid alert feeds can move judgement quickly, but remain source-dependent.",
    ),
    "block_trade_pressure": SignalLanePolicy(
        "block_trade_pressure",
        "stock_trades",
        "continuous",
        "5-15m during pre-market and regular market",
        "fetch only missing Massive trade-date partitions",
        "Uses off-exchange and large-print trade pressure; no historical re-pull after baseline.",
    ),
    "buy_sell_pressure": SignalLanePolicy(
        "buy_sell_pressure",
        "stock_trades",
        "continuous",
        "5-15m during pre-market and regular market",
        "fetch only missing Massive trade-date partitions",
        "Uses signed trade pressure and pre-market contribution from Massive trades.",
    ),
    "market_flow_trend": SignalLanePolicy(
        "market_flow_trend",
        "stock_trades",
        "continuous",
        "15-30m during market hours; daily after close",
        "fetch only missing Massive trade-date partitions",
        "Looks for improving or deteriorating pressure across recent trade days.",
    ),
    "pre_market_unusual_activity": SignalLanePolicy(
        "pre_market_unusual_activity",
        "stock_trades",
        "continuous",
        "5-10m during pre-market",
        "fetch only current pre-market trade updates",
        "This is one of the highest-priority live monitoring lanes.",
    ),
    "subscription_thesis": SignalLanePolicy(
        "subscription_thesis",
        "subscription_emails",
        "continuous",
        "5-10m mailbox polling",
        "process only new matching emails and unprocessed article links",
        "Seeking Alpha, Zacks, and TradeVision emails become context-only thesis evidence.",
    ),
    "unusual_trade_activity": SignalLanePolicy(
        "unusual_trade_activity",
        "stock_trades",
        "continuous",
        "5-15m during market hours",
        "fetch only missing Massive trade-date partitions",
        "Detects unusual prints relative to recent baseline activity.",
    ),
    "news": SignalLanePolicy(
        "news",
        "news_rss",
        "event_driven",
        "15-30m RSS polling",
        "dedupe by source URL/title and append new headlines",
        "Headline evidence should not drive action alone without corroboration.",
    ),
    "insider": SignalLanePolicy(
        "insider",
        "sec_form4",
        "event_driven",
        "30-60m SEC current-filings check; daily fallback",
        "baseline once, then fetch filings after the latest local filing date",
        "Form 4 updates can matter quickly, but the job must be small-batch and incremental.",
    ),
    "abnormal_volume": SignalLanePolicy(
        "abnormal_volume",
        "prices_daily",
        "daily",
        "after market close; optional pre-open previous-day check",
        "append only missing daily OHLCV bars",
        "Uses daily volume relative to history, so intraday polling is not needed.",
    ),
    "sector_momentum": SignalLanePolicy(
        "sector_momentum",
        "prices_daily",
        "daily",
        "after market close",
        "append missing equity and sector ETF daily bars",
        "Feeds market/sector context and candidate prioritization.",
    ),
    "technical_analysis": SignalLanePolicy(
        "technical_analysis",
        "prices_daily",
        "daily",
        "after market close; pre-open uses last completed bar",
        "append missing daily bars, then recompute technical features",
        "Chart/candle signals are recomputed from the local baseline plus latest bars.",
    ),
    "fundamentals": SignalLanePolicy(
        "fundamentals",
        "sec_company_facts",
        "scheduled",
        "weekly freshness check; force after earnings/10-Q/10-K alerts if needed",
        "baseline once, then re-check only stale or forced tickers",
        "Quarterly facts rarely change intraday, so this lane should not poll constantly.",
    ),
    "institutional": SignalLanePolicy(
        "institutional",
        "sec_13f",
        "scheduled",
        "quarterly plus 13F filing-window checks",
        "baseline once, then check after new quarterly filing windows",
        "13F is delayed and low-frequency; use as context, not live pressure.",
    ),
    "options_anomaly": SignalLanePolicy(
        "options_anomaly",
        "options_chains",
        "backlog",
        "provider-dependent when enabled",
        "not active until paid options provider is wired",
        "Keep disabled until options data and limits are defined.",
    ),
    "options_flow": SignalLanePolicy(
        "options_flow",
        "options_chains",
        "backlog",
        "provider-dependent when enabled",
        "not active until paid options provider is wired",
        "Keep disabled until options flow provider is selected.",
    ),
}


def policies_for_lanes(lanes: tuple[str, ...]) -> tuple[SignalLanePolicy, ...]:
    return tuple(SIGNAL_LANE_POLICIES[lane] for lane in lanes if lane in SIGNAL_LANE_POLICIES)


def lanes_by_cadence(lanes: tuple[str, ...]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {
        "continuous": [],
        "event_driven": [],
        "daily": [],
        "scheduled": [],
        "backlog": [],
    }
    for policy in policies_for_lanes(lanes):
        grouped[policy.cadence].append(policy.lane)
    return grouped
