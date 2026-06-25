from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from live_runtime.config import LANE_CONFIGS

DISABLED = "disabled"
CONTEXT_ONLY = "context_only"
CORROBORATING = "corroborating"
ACTION_WEIGHTED = "action_weighted"


@dataclass(frozen=True)
class LanePromotionPolicy:
    lane: str
    state: str
    runtime_effect: str
    evidence_required: str
    rationale: str


LANE_PROMOTION_POLICIES: dict[str, LanePromotionPolicy] = {
    "fundamentals": LanePromotionPolicy(
        "fundamentals",
        ACTION_WEIGHTED,
        "Can contribute to WATCH when evidence breadth and freshness pass.",
        "SEC company-facts manifest available and no source-health blocker.",
        (
            "Official filing data is confirmed, slowly changing, and already part of the "
            "conservative gate."
        ),
    ),
    "insider": LanePromotionPolicy(
        "insider",
        ACTION_WEIGHTED,
        "Can contribute to WATCH when corroborated by another usable source.",
        "SEC Form 4 manifest available for the ticker window.",
        (
            "Official insider filings are confirmed, but coverage is still partial for the "
            "full universe."
        ),
    ),
    "institutional": LanePromotionPolicy(
        "institutional",
        CONTEXT_ONLY,
        "Context only: 13F filings are delayed by up to 45 days after quarter end.",
        "SEC 13F manifest available and mapped through the local CUSIP map.",
        (
            "Official lagged 13F data confirms historical institutional positioning, but the "
            "filing delay makes it unsuitable as a current action-weighted signal."
        ),
    ),
    "abnormal_volume": LanePromotionPolicy(
        "abnormal_volume",
        CORROBORATING,
        "Can corroborate confirmed evidence, but should not stand alone.",
        "Daily price/volume bars with PIT freshness.",
        "Volume spikes are inferred from bars and need confirmed source support.",
    ),
    "sector_momentum": LanePromotionPolicy(
        "sector_momentum",
        CORROBORATING,
        "Can corroborate stock-specific evidence.",
        "Daily sector/benchmark bars with PIT freshness.",
        "Sector strength is useful context but not a stock-specific thesis by itself.",
    ),
    "technical_analysis": LanePromotionPolicy(
        "technical_analysis",
        CORROBORATING,
        "Can explain and corroborate setups; promotion waits for holdout validation.",
        "Technical worker calibration with sufficient train/test coverage.",
        (
            "The worker is implemented, but chart features should earn more weight only after "
            "wider validation."
        ),
    ),
    "news": LanePromotionPolicy(
        "news",
        CONTEXT_ONLY,
        "Explains current context; does not independently push WATCH.",
        "Ticker-tagged coverage with forward validation.",
        "Generic RSS/news coverage is useful but still needs ticker-specific validation.",
    ),
    "subscription_thesis": LanePromotionPolicy(
        "subscription_thesis",
        CONTEXT_ONLY,
        "Provides paid-email/article thesis context only.",
        "Service-specific article extraction quality and forward validation.",
        "Mailbox evidence is valuable, but current article summaries are still being hardened.",
    ),
    "activity_alerts": LanePromotionPolicy(
        "activity_alerts",
        CONTEXT_ONLY,
        "Provider/export alerts can enrich evidence until validated.",
        "A confirmed paid provider/export feed and forward validation.",
        "The importer exists; a reliable live provider is not selected for this lane.",
    ),
    "buy_sell_pressure": LanePromotionPolicy(
        "buy_sell_pressure",
        CORROBORATING,
        "Can corroborate confirmed evidence from Massive stock prints.",
        "Massive stock-trade coverage plus market-flow holdout validation.",
        "Trade-sign inference is useful but should remain guarded until coverage expands.",
    ),
    "block_trade_pressure": LanePromotionPolicy(
        "block_trade_pressure",
        CORROBORATING,
        "Can corroborate confirmed evidence from large/off-exchange prints.",
        "Massive stock-trade coverage plus provider-backed dark-pool validation later.",
        "This is inferred block/off-exchange pressure, not a dedicated dark-pool feed.",
    ),
    "unusual_trade_activity": LanePromotionPolicy(
        "unusual_trade_activity",
        CORROBORATING,
        "Can corroborate confirmed evidence from Massive trade activity spikes.",
        "Massive stock-trade coverage and market-flow calibration.",
        "Activity spikes are inferred and need confirmed source support.",
    ),
    "pre_market_unusual_activity": LanePromotionPolicy(
        "pre_market_unusual_activity",
        CORROBORATING,
        "Can corroborate confirmed evidence when pre-market prints are present.",
        "Massive pre-market stock-trade coverage and calibration.",
        "Pre-market activity can matter, but it is noisy and must not stand alone.",
    ),
    "market_flow_trend": LanePromotionPolicy(
        "market_flow_trend",
        CORROBORATING,
        "Can corroborate confirmed evidence after market-flow calibration.",
        "Massive stock-trade coverage and holdout validation.",
        "Short flow trends are inferred from prints and should remain conservative.",
    ),
    "options_anomaly": LanePromotionPolicy(
        "options_anomaly",
        DISABLED,
        "Disabled until a real options provider is selected.",
        "Paid options provider/API or export with historical validation.",
        "The code path exists, but the provider-backed data source is intentionally backlog.",
    ),
    "options_flow": LanePromotionPolicy(
        "options_flow",
        DISABLED,
        "Disabled until a real options-flow provider is selected.",
        "Paid options-flow provider/API or export with historical validation.",
        "The code path exists, but the provider-backed data source is intentionally backlog.",
    ),
    "sec_filing_analysis": LanePromotionPolicy(
        "sec_filing_analysis",
        ACTION_WEIGHTED,
        "Can contribute to WATCH when a recent filing with clear sentiment is available.",
        "At least one SEC filing analyzed within the last 90 days.",
        (
            "Official SEC filings are the most reliable forward-looking signal available. "
            "LLM-extracted guidance and surprise data directly informs the trade decision."
        ),
    ),
}


def load_lane_promotion_status(runtime_signals: Iterable[str] | None = None) -> dict[str, object]:
    configured = set(runtime_signals or ())
    rows = [_lane_row(lane, configured) for lane in sorted(LANE_CONFIGS)]
    counts = {state: sum(1 for row in rows if row["state"] == state) for state in _states()}
    return {
        "schema_version": "0.1.0",
        "ready": True,
        "state": "ready",
        "lane_count": len(rows),
        "configured_count": sum(1 for row in rows if row["configured"] is True),
        "counts": counts,
        "lanes": rows,
    }


def _lane_row(lane: str, configured: set[str]) -> dict[str, object]:
    policy = LANE_PROMOTION_POLICIES.get(
        lane,
        LanePromotionPolicy(
            lane,
            CONTEXT_ONLY,
            "Unknown lanes are held to context-only until explicitly promoted.",
            "Add a lane-promotion policy and validation report.",
            "No explicit promotion policy exists for this lane.",
        ),
    )
    config = LANE_CONFIGS[lane]
    return {
        "lane": lane,
        "state": policy.state,
        "configured": lane in configured,
        "dataset": config.dataset.value,
        "source": config.source,
        "verification_level": config.verification_level,
        "runtime_effect": policy.runtime_effect,
        "evidence_required": policy.evidence_required,
        "rationale": policy.rationale,
    }


def _states() -> tuple[str, ...]:
    return DISABLED, CONTEXT_ONLY, CORROBORATING, ACTION_WEIGHTED
