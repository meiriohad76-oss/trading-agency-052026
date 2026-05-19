from __future__ import annotations

from dataclasses import dataclass

from pit.manifest import DatasetName

from agency.provenance import FreshnessDomain


@dataclass(frozen=True)
class RuntimeLaneConfig:
    lane: str
    dataset: DatasetName
    source: str
    source_tier: str
    verification_level: str
    freshness_domain: FreshnessDomain
    confidence: float = 0.8


@dataclass(frozen=True)
class RuntimeDatasetConfig:
    dataset: DatasetName
    source: str
    source_tier: str
    freshness_domain: FreshnessDomain


LANE_CONFIGS: dict[str, RuntimeLaneConfig] = {
    "abnormal_volume": RuntimeLaneConfig(
        "abnormal_volume",
        DatasetName.PRICES_DAILY,
        "daily-market-bars",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.PRICING,
        0.7,
    ),
    "activity_alerts": RuntimeLaneConfig(
        "activity_alerts",
        DatasetName.UNUSUAL_ACTIVITY_ALERTS,
        "activity-alerts",
        "PAID_SUB_EMAIL",
        "CONFIRMED",
        FreshnessDomain.NEWS,
    ),
    "block_trade_pressure": RuntimeLaneConfig(
        "block_trade_pressure",
        DatasetName.STOCK_TRADES,
        "massive-stock-trades",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.TRADE_PRINTS,
        0.55,
    ),
    "buy_sell_pressure": RuntimeLaneConfig(
        "buy_sell_pressure",
        DatasetName.STOCK_TRADES,
        "massive-stock-trades",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.TRADE_PRINTS,
        0.55,
    ),
    "market_flow_trend": RuntimeLaneConfig(
        "market_flow_trend",
        DatasetName.STOCK_TRADES,
        "massive-stock-trades",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.TRADE_PRINTS,
        0.55,
    ),
    "fundamentals": RuntimeLaneConfig(
        "fundamentals",
        DatasetName.SEC_COMPANY_FACTS,
        "sec-company-facts",
        "OFFICIAL_FILING",
        "CONFIRMED",
        FreshnessDomain.SEC_FUNDAMENTALS,
    ),
    "insider": RuntimeLaneConfig(
        "insider",
        DatasetName.SEC_FORM4,
        "sec-form4",
        "OFFICIAL_FILING",
        "CONFIRMED",
        FreshnessDomain.SEC_FORM4,
    ),
    "institutional": RuntimeLaneConfig(
        "institutional",
        DatasetName.SEC_13F,
        "sec-13f",
        "OFFICIAL_FILING",
        "CONFIRMED",
        FreshnessDomain.SEC_13F,
    ),
    "news": RuntimeLaneConfig(
        "news",
        DatasetName.NEWS_RSS,
        "rss-news",
        "RSS_HEADLINE",
        "CONFIRMED",
        FreshnessDomain.NEWS,
        0.6,
    ),
    "subscription_thesis": RuntimeLaneConfig(
        "subscription_thesis",
        DatasetName.SUBSCRIPTION_EMAILS,
        "subscription-email-thesis",
        "PAID_SUB_EMAIL",
        "CONFIRMED",
        FreshnessDomain.NEWS,
        0.65,
    ),
    "options_anomaly": RuntimeLaneConfig(
        "options_anomaly",
        DatasetName.OPTIONS_CHAINS,
        "options-chain-anomaly",
        "MARKET_DATA",
        "INFERRED",
        FreshnessDomain.PRICING,
        0.55,
    ),
    "options_flow": RuntimeLaneConfig(
        "options_flow",
        DatasetName.OPTIONS_CHAINS,
        "options-chain-flow",
        "MARKET_DATA",
        "INFERRED",
        FreshnessDomain.PRICING,
        0.55,
    ),
    "pre_market_unusual_activity": RuntimeLaneConfig(
        "pre_market_unusual_activity",
        DatasetName.STOCK_TRADES,
        "massive-stock-trades",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.TRADE_PRINTS,
        0.55,
    ),
    "sector_momentum": RuntimeLaneConfig(
        "sector_momentum",
        DatasetName.PRICES_DAILY,
        "daily-market-bars",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.PRICING,
        0.7,
    ),
    "technical_analysis": RuntimeLaneConfig(
        "technical_analysis",
        DatasetName.PRICES_DAILY,
        "technical-analysis-worker",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.PRICING,
        0.65,
    ),
    "unusual_trade_activity": RuntimeLaneConfig(
        "unusual_trade_activity",
        DatasetName.STOCK_TRADES,
        "massive-stock-trades",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.TRADE_PRINTS,
        0.55,
    ),
}

DATASET_CONFIGS: dict[DatasetName, RuntimeDatasetConfig] = {
    DatasetName.PRICES_DAILY: RuntimeDatasetConfig(
        DatasetName.PRICES_DAILY,
        "daily-market-bars",
        "MARKET_DATA",
        FreshnessDomain.PRICING,
    ),
    DatasetName.SEC_COMPANY_FACTS: RuntimeDatasetConfig(
        DatasetName.SEC_COMPANY_FACTS,
        "sec-company-facts",
        "OFFICIAL_FILING",
        FreshnessDomain.SEC_FUNDAMENTALS,
    ),
    DatasetName.SEC_FORM4: RuntimeDatasetConfig(
        DatasetName.SEC_FORM4,
        "sec-form4",
        "OFFICIAL_FILING",
        FreshnessDomain.SEC_FORM4,
    ),
    DatasetName.SEC_13F: RuntimeDatasetConfig(
        DatasetName.SEC_13F,
        "sec-13f",
        "OFFICIAL_FILING",
        FreshnessDomain.SEC_13F,
    ),
    DatasetName.NEWS_RSS: RuntimeDatasetConfig(
        DatasetName.NEWS_RSS,
        "rss-news",
        "RSS_HEADLINE",
        FreshnessDomain.NEWS,
    ),
    DatasetName.SUBSCRIPTION_EMAILS: RuntimeDatasetConfig(
        DatasetName.SUBSCRIPTION_EMAILS,
        "subscription-email-thesis",
        "PAID_SUB_EMAIL",
        FreshnessDomain.NEWS,
    ),
    DatasetName.STOCK_TRADES: RuntimeDatasetConfig(
        DatasetName.STOCK_TRADES,
        "massive-stock-trades",
        "CONFIRMED_TRADE_PRINT",
        FreshnessDomain.TRADE_PRINTS,
    ),
    DatasetName.OPTIONS_CHAINS: RuntimeDatasetConfig(
        DatasetName.OPTIONS_CHAINS,
        "options-chains",
        "MARKET_DATA",
        FreshnessDomain.PRICING,
    ),
    DatasetName.UNUSUAL_ACTIVITY_ALERTS: RuntimeDatasetConfig(
        DatasetName.UNUSUAL_ACTIVITY_ALERTS,
        "activity-alerts",
        "PAID_SUB_EMAIL",
        FreshnessDomain.NEWS,
    ),
}

STOCKS_ONLY_RUNTIME_SIGNALS = (
    "fundamentals",
    "insider",
    "institutional",
    "abnormal_volume",
    "technical_analysis",
    "sector_momentum",
    "news",
)

OPTIONAL_RUNTIME_SIGNALS = (
    "activity_alerts",
    "block_trade_pressure",
    "buy_sell_pressure",
    "market_flow_trend",
    "options_anomaly",
    "options_flow",
    "pre_market_unusual_activity",
    "subscription_thesis",
    "unusual_trade_activity",
)

DEFAULT_RUNTIME_SIGNALS = STOCKS_ONLY_RUNTIME_SIGNALS
