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
        "yfinance-daily",
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
    "sector_momentum": RuntimeLaneConfig(
        "sector_momentum",
        DatasetName.PRICES_DAILY,
        "yfinance-daily",
        "INFERRED_FROM_BARS",
        "INFERRED",
        FreshnessDomain.PRICING,
        0.7,
    ),
}

DATASET_CONFIGS: dict[DatasetName, RuntimeDatasetConfig] = {
    DatasetName.PRICES_DAILY: RuntimeDatasetConfig(
        DatasetName.PRICES_DAILY,
        "yfinance-daily",
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
    DatasetName.UNUSUAL_ACTIVITY_ALERTS: RuntimeDatasetConfig(
        DatasetName.UNUSUAL_ACTIVITY_ALERTS,
        "activity-alerts",
        "PAID_SUB_EMAIL",
        FreshnessDomain.NEWS,
    ),
}

DEFAULT_RUNTIME_SIGNALS = (
    "fundamentals",
    "insider",
    "institutional",
    "abnormal_volume",
    "sector_momentum",
    "news",
    "activity_alerts",
)
